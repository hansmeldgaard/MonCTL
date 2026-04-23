"""bundle tests — docker CLI stubbed via a fake binary on PATH.

The real `docker pull` / `docker save` round-trip is network-dependent and
registry-dependent; we assert contract (which image tags are pulled, what the
on-disk layout looks like) not byte-for-byte equivalence with docker output.
"""
from __future__ import annotations

import os
import tarfile
from pathlib import Path

import pytest

from monctl_installer.commands.bundle import (
    BundleError,
    create_bundle,
    load_bundle,
)


REPO_ROOT = Path(__file__).parents[3]


@pytest.fixture()
def fake_docker(tmp_path: Path) -> Path:
    """Write a dummy `docker` shim that records invocations and emits fake tars.

    - `docker pull X` → exit 0, stdout "pulled X"
    - `docker save -o PATH X` → write an empty tar to PATH
    - `docker load -i PATH` → print "Loaded image: <tagname>" for the tar
    """
    shim = tmp_path / "docker"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "set -e\n"
        "case \"$1\" in\n"
        "  pull) echo \"pulled $2\" ;;\n"
        "  save)\n"
        "    out_path=\"$3\"\n"
        "    # $4 is the image ref\n"
        "    tar -cf \"$out_path\" --files-from /dev/null\n"
        "    ;;\n"
        "  load)\n"
        "    # $3 is the path\n"
        "    echo 'Loaded image: ghcr.io/hansmeldgaard/monctl-fake:test'\n"
        "    ;;\n"
        "  *) echo \"unknown subcommand $1\" >&2; exit 1 ;;\n"
        "esac\n"
    )
    shim.chmod(0o755)
    return shim


def test_create_bundle_produces_tarball(fake_docker: Path, tmp_path: Path) -> None:
    out = tmp_path / "monctl-airgap.tar.gz"
    result = create_bundle(
        version="v0.1.0-test",
        out_path=out,
        docker=str(fake_docker),
        extras={
            "docs": REPO_ROOT,
            "inventory_examples": REPO_ROOT,
        },
    )
    assert result.path == out
    assert result.size_bytes > 0
    with tarfile.open(out, "r:gz") as tf:
        names = tf.getnames()
    # Manifest + VERSION + image tars + docs + example inventories present
    assert any(n.endswith("README.txt") for n in names)
    assert any(n.endswith("VERSION") for n in names)
    assert any(n.endswith("images/monctl-central.tar") for n in names)
    assert any(n.endswith("images/monctl-collector.tar") for n in names)
    assert any(n.endswith("images/monctl-docker-stats.tar") for n in names)
    assert any(n.endswith("docs/INSTALL.md") for n in names)
    assert any(n.endswith("inventory-examples/inventory.example.large.yaml") for n in names)


def test_create_bundle_skips_missing_extras(fake_docker: Path, tmp_path: Path) -> None:
    out = tmp_path / "bundle.tar.gz"
    create_bundle(
        version="v0.1.0-test",
        out_path=out,
        docker=str(fake_docker),
        extras={"docs": tmp_path / "nope", "inventory_examples": tmp_path / "nope"},
    )
    # Tarball still builds; docs/examples sections just absent.
    with tarfile.open(out, "r:gz") as tf:
        names = tf.getnames()
    assert not any(n.endswith("docs/INSTALL.md") for n in names)
    # Images still present
    assert any(n.endswith("images/monctl-central.tar") for n in names)


def test_load_bundle_reads_images(fake_docker: Path, tmp_path: Path) -> None:
    out = tmp_path / "bundle.tar.gz"
    create_bundle(
        version="v0.1.0-test", out_path=out, docker=str(fake_docker), extras=None
    )
    loaded = load_bundle(out, docker=str(fake_docker))
    # Fake docker emits the same ref for every tar → we see it N times.
    assert "ghcr.io/hansmeldgaard/monctl-fake:test" in loaded
    assert len(loaded) == 3  # one per COMPONENTS entry


def test_load_bundle_missing_path() -> None:
    with pytest.raises(BundleError, match="bundle not found"):
        load_bundle(Path("/tmp/does-not-exist-xyzzy.tar.gz"))


def test_create_bundle_surfaces_docker_failure(tmp_path: Path) -> None:
    failing = tmp_path / "docker"
    failing.write_text("#!/usr/bin/env bash\nexit 1\n")
    failing.chmod(0o755)
    with pytest.raises(BundleError, match="command failed"):
        create_bundle(
            version="v0.1.0", out_path=tmp_path / "out.tar.gz", docker=str(failing)
        )


def test_create_bundle_missing_docker_binary(tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="docker CLI not found"):
        create_bundle(
            version="v0.1.0",
            out_path=tmp_path / "out.tar.gz",
            docker="/does/not/exist/docker-binary-xyzzy",
        )
