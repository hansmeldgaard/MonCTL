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

import hashlib
import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

REPO_ROOT_HINT = "hansmeldgaard"  # GHCR namespace used in release.yml

COMPONENTS: tuple[str, ...] = ("central", "collector", "docker-stats")

# Files inside the bundle that the manifest covers (everything except the
# manifest itself). MANIFEST.sha256 lists `<sha256>  <relative-path>` per line.
MANIFEST_NAME = "MANIFEST.sha256"


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
    # Lock down staging perms so a shared work dir (e.g. /tmp) can't expose
    # half-built images while the bundle is assembled (S-INST-013).
    prev_umask = os.umask(0o077)
    try:
        (staging / "images").mkdir(parents=True)
    finally:
        os.umask(prev_umask)

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

    # Generate manifest of every staged file BEFORE packing so loaders can
    # detect tampering / corruption-in-transit (M-INST-014).
    manifest_path = staging / MANIFEST_NAME
    manifest_path.write_text(_compute_manifest(staging))

    # Pack it up.
    with tarfile.open(out_path, "w:gz") as tf:
        tf.add(staging, arcname=out_path.stem)
    shutil.rmtree(staging)

    return BundleResult(
        path=out_path,
        size_bytes=out_path.stat().st_size,
        components=COMPONENTS,
    )


def _compute_manifest(root: Path) -> str:
    """Return ``MANIFEST.sha256`` text covering every file under ``root``.

    Excludes the manifest itself so verification can recompute against the
    same set. Sorted lexicographically for deterministic output.
    """
    lines: list[str] = []
    for fpath in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = fpath.relative_to(root).as_posix()
        if rel == MANIFEST_NAME:
            continue
        h = hashlib.sha256()
        with fpath.open("rb") as fh:
            for chunk in iter(lambda: fh.read(64 * 1024), b""):
                h.update(chunk)
        lines.append(f"{h.hexdigest()}  {rel}")
    return "\n".join(lines) + "\n"


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
        # ``filter='data'`` blocks tar-slip / absolute-path / device-file
        # entries (PEP 706, default in Python 3.12+). Pre-3.12 systems get
        # the same protection because the named arg is supported back to
        # 3.11.4. On older 3.11 the call raises TypeError; we catch and
        # fall back to a manual safe-extract loop. (S-INST-001 / M-INST-015)
        with tarfile.open(path, "r:gz") as tf:
            try:
                tf.extractall(work, filter="data")
            except TypeError:
                _safe_extractall(tf, work)

        # Verify manifest BEFORE handing tar contents to docker (M-INST-014).
        # Find the bundle's top-level directory inside ``work``; bundles use
        # ``out_path.stem`` as the arcname so there's exactly one child.
        roots = [p for p in work.iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise BundleError(
                f"bundle layout invalid: expected 1 top-level dir, got {len(roots)}"
            )
        bundle_root = roots[0]
        _verify_manifest(bundle_root)

        loaded: list[str] = []
        for img_tar in sorted(bundle_root.rglob("images/*.tar")):
            out = _run(docker, "load", "-i", str(img_tar))
            # docker load prints "Loaded image: <ref>" per image
            for line in out.splitlines():
                if line.startswith("Loaded image:"):
                    loaded.append(line.split(":", 1)[1].strip())
        return loaded
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _safe_extractall(tf: tarfile.TarFile, dest: Path) -> None:
    """Manual tar-slip-safe extraction for Python builds without ``filter='data'``.

    Rejects absolute paths, ``..`` segments, symlinks pointing outside dest,
    and device / FIFO members.
    """
    dest = dest.resolve()
    for member in tf.getmembers():
        if member.isdev() or member.isfifo():
            raise BundleError(f"bundle contains unsafe member type: {member.name!r}")
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(dest) + os.sep) and target != dest:
            raise BundleError(f"bundle contains path-traversal entry: {member.name!r}")
        if member.issym() or member.islnk():
            link_target = (target.parent / member.linkname).resolve()
            if not str(link_target).startswith(str(dest) + os.sep):
                raise BundleError(
                    f"bundle contains link escaping dest: {member.name!r} -> {member.linkname!r}"
                )
        tf.extract(member, dest)


def _verify_manifest(root: Path) -> None:
    """Recompute SHA-256s for every file under ``root`` and match the manifest.

    Raises ``BundleError`` on any mismatch, missing file, or extra file.
    """
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        raise BundleError(
            f"bundle integrity check failed: {MANIFEST_NAME} missing — "
            "bundle is from a pre-manifest installer or has been tampered with"
        )

    expected: dict[str, str] = {}
    for line in manifest_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise BundleError(f"malformed manifest line: {line!r}")
        sha, rel = parts
        expected[rel] = sha

    seen: set[str] = set()
    for fpath in root.rglob("*"):
        if not fpath.is_file():
            continue
        rel = fpath.relative_to(root).as_posix()
        if rel == MANIFEST_NAME:
            continue
        seen.add(rel)
        if rel not in expected:
            raise BundleError(f"bundle has unexpected file not in manifest: {rel}")
        h = hashlib.sha256()
        with fpath.open("rb") as fh:
            for chunk in iter(lambda: fh.read(64 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != expected[rel]:
            raise BundleError(
                f"bundle integrity check failed: {rel} sha256 mismatch "
                f"(expected {expected[rel][:12]}…, got {h.hexdigest()[:12]}…)"
            )

    missing = set(expected) - seen
    if missing:
        raise BundleError(
            f"bundle missing files listed in manifest: {sorted(missing)}"
        )


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
