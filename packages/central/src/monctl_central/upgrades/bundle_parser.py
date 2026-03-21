"""Parse MonCTL upgrade bundles (.tar.gz).

Expected bundle structure:
  monctl-v2.1.0.tar.gz
    |- version.json          # {"version": "2.1.0", "changelog": "..."}
    |- monctl-central.tar    # (optional) docker image
    |- monctl-collector.tar  # (optional) docker image
    +- changelog.md          # (optional)
"""

import hashlib
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import structlog

logger = structlog.get_logger()


@dataclass
class BundleInfo:
    version: str
    min_version: str | None
    changelog: str | None
    contains_central: bool
    contains_collector: bool
    sha256_hash: str
    file_size: int


def parse_bundle(file: BinaryIO, dest_dir: Path) -> BundleInfo:
    sha256 = hashlib.sha256()
    file_size = 0
    file.seek(0)
    while chunk := file.read(8192):
        sha256.update(chunk)
        file_size += len(chunk)
    file.seek(0)

    dest_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(fileobj=file, mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in member.name:
                raise ValueError(f"Unsafe path in bundle: {member.name}")

        names = tar.getnames()

        version_json_name = None
        for n in names:
            if n.endswith("version.json") or n == "version.json":
                version_json_name = n
                break
        if not version_json_name:
            raise ValueError("Bundle must contain version.json")

        tar.extractall(path=dest_dir, filter="data")

    version_path = dest_dir / version_json_name
    with open(version_path) as f:
        meta = json.load(f)

    version = meta.get("version")
    if not version:
        raise ValueError("version.json must contain 'version' field")

    contains_central = any("monctl-central.tar" in n for n in names)
    contains_collector = any("monctl-collector.tar" in n for n in names)

    changelog = meta.get("changelog")
    changelog_path = dest_dir / "changelog.md"
    if changelog_path.exists():
        changelog = changelog_path.read_text()

    return BundleInfo(
        version=version,
        min_version=meta.get("min_version"),
        changelog=changelog,
        contains_central=contains_central,
        contains_collector=contains_collector,
        sha256_hash=sha256.hexdigest(),
        file_size=file_size,
    )
