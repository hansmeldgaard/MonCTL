"""`bundle create` / `bundle load` — air-gapped install support.

`create` builds a self-contained tarball on an internet-connected machine:

    monctl-airgap-<version>.tar.gz
    ├── README.txt                  (manifest + next steps)
    ├── VERSION                     (monctl version, plain text)
    ├── images/
    │   ├── monctl-central.tar
    │   ├── monctl-collector.tar
    │   └── monctl-docker-stats.tar
    ├── docs/
    │   ├── INSTALL.md
    │   ├── UPGRADE.md
    │   └── TROUBLESHOOTING.md
    └── inventory-examples/
        ├── inventory.example.micro.yaml
        ├── inventory.example.small.yaml
        └── inventory.example.large.yaml

`load` extracts + `docker load`s the images on the operator machine. To push
the images to target hosts, see the deploy-from-bundle path in INSTALL.md
(adds `--image-source bundle` to `monctl_ctl deploy`, side-loads via scp +
docker load per host). That mode is not yet implemented; create the bundle
now so the air-gapped story exists.
"""
from __future__ import annotations

import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

REPO_ROOT_HINT = "hansmeldgaard"  # GHCR namespace used in release.yml

COMPONENTS: tuple[str, ...] = ("central", "collector", "docker-stats")


@dataclass(frozen=True)
class BundleResult:
    path: Path
    size_bytes: int
    components: tuple[str, ...]


class BundleError(Exception):
    pass


def create_bundle(
    *,
    version: str,
    out_path: Path,
    namespace: str = REPO_ROOT_HINT,
    registry: str = "ghcr.io",
    extras: dict[Literal["docs", "inventory_examples"], Path] | None = None,
    docker: str = "docker",
) -> BundleResult:
    """Build the air-gap bundle at `out_path`.

    Parameters
    ----------
    version     : image tag to snapshot, e.g. "v1.2.3"
    out_path    : target tarball path, typically monctl-airgap-<version>.tar.gz
    namespace   : GHCR org/user that owns the images
    registry    : image registry host
    extras      : optional repo-relative paths to include for docs/examples
    docker      : path to the docker CLI (overridable for tests)
    """
    out_path = out_path.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    staging = out_path.parent / f".{out_path.stem}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "images").mkdir(parents=True)

    # Pull + save every image.
    images: list[str] = []
    for comp in COMPONENTS:
        full = f"{registry}/{namespace}/monctl-{comp}:{version}"
        images.append(full)
        _run(docker, "pull", full)
        tar_path = staging / "images" / f"monctl-{comp}.tar"
        _run(docker, "save", "-o", str(tar_path), full)

    # VERSION + README manifest
    (staging / "VERSION").write_text(version + "\n")
    (staging / "README.txt").write_text(_manifest_text(version, images))

    # Docs + examples (optional; caller can skip for minimal bundles)
    if extras is None:
        extras = {}
    if "docs" in extras:
        _copy_if_exists(extras["docs"] / "INSTALL.md", staging / "docs" / "INSTALL.md")
        _copy_if_exists(extras["docs"] / "UPGRADE.md", staging / "docs" / "UPGRADE.md")
        _copy_if_exists(
            extras["docs"] / "TROUBLESHOOTING.md", staging / "docs" / "TROUBLESHOOTING.md"
        )
    if "inventory_examples" in extras:
        inv_root = extras["inventory_examples"]
        for example in ("micro", "small", "large"):
            _copy_if_exists(
                inv_root / f"inventory.example.{example}.yaml",
                staging / "inventory-examples" / f"inventory.example.{example}.yaml",
            )

    # Pack it up.
    with tarfile.open(out_path, "w:gz") as tf:
        tf.add(staging, arcname=out_path.stem)
    shutil.rmtree(staging)

    return BundleResult(
        path=out_path,
        size_bytes=out_path.stat().st_size,
        components=COMPONENTS,
    )


def load_bundle(path: Path, *, docker: str = "docker") -> list[str]:
    """Extract `path` to a temp dir and `docker load` every image tar inside.

    Returns the list of image references loaded (as reported by `docker load`).
    """
    path = path.expanduser().resolve()
    if not path.exists():
        raise BundleError(f"bundle not found: {path}")

    work = path.parent / f".{path.stem}.extract"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        with tarfile.open(path, "r:gz") as tf:
            tf.extractall(work)
        loaded: list[str] = []
        for img_tar in sorted((work).rglob("images/*.tar")):
            out = _run(docker, "load", "-i", str(img_tar))
            # docker load prints "Loaded image: <ref>" per image
            for line in out.splitlines():
                if line.startswith("Loaded image:"):
                    loaded.append(line.split(":", 1)[1].strip())
        return loaded
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _manifest_text(version: str, images: list[str]) -> str:
    image_lines = "\n".join(f"  - {img}" for img in images)
    return (
        f"MonCTL air-gap bundle\n"
        f"Version: {version}\n\n"
        f"Contents\n"
        f"--------\n"
        f"  images/   Docker images (docker save format)\n"
        f"  docs/     INSTALL / UPGRADE / TROUBLESHOOTING\n"
        f"  inventory-examples/   Sample inventories\n\n"
        f"Images included\n"
        f"---------------\n"
        f"{image_lines}\n\n"
        f"Usage\n"
        f"-----\n"
        f"1. Copy this tarball to the operator machine (pipx-installed monctl_ctl).\n"
        f"2. Load images locally: `monctl_ctl bundle load <tarball>`\n"
        f"3. Continue with the normal install flow: `monctl_ctl init && monctl_ctl deploy`\n\n"
        f"See docs/INSTALL.md for full prerequisites + air-gap deploy notes.\n"
    )


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def _run(*args: str) -> str:
    try:
        r = subprocess.run(args, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise BundleError(f"docker CLI not found: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise BundleError(
            f"command failed: {' '.join(args)}\nstderr: {exc.stderr}"
        ) from exc
    return r.stdout
