"""Parse .whl file metadata from ZIP archives.

A wheel is a ZIP file with a .dist-info directory containing a METADATA file
(RFC 822-like format) and a WHEEL file with tags. The filename itself encodes
{distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from email.parser import BytesParser


@dataclass
class WheelMetadata:
    """Parsed metadata from a .whl file."""
    name: str = ""
    version: str = ""
    summary: str = ""
    homepage_url: str = ""
    python_requires: str = ""
    dependencies: list[str] = field(default_factory=list)
    python_tag: str = ""
    abi_tag: str = ""
    platform_tag: str = ""
    sha256_hash: str = ""
    file_size: int = 0


_FILENAME_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9]([A-Za-z0-9._]*[A-Za-z0-9])?)"
    r"-(?P<version>[A-Za-z0-9_.!+]+)"
    r"(-(?P<build>\d[A-Za-z0-9_.]*))?"
    r"-(?P<python>[A-Za-z0-9_.]+)"
    r"-(?P<abi>[A-Za-z0-9_.]+)"
    r"-(?P<platform>[A-Za-z0-9_.]+)"
    r"\.whl$"
)


def normalize_package_name(name: str) -> str:
    """Normalize a package name per PEP 503 (lowercase, hyphens to dashes)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_wheel_filename(filename: str) -> dict:
    """Parse a wheel filename into its component parts.

    Returns a dict with keys: name, version, python_tag, abi_tag, platform_tag.
    Raises ValueError if the filename does not match the wheel naming convention.
    """
    m = _FILENAME_RE.match(filename)
    if not m:
        raise ValueError(f"Invalid wheel filename: {filename!r}")
    return {
        "name": m.group("name"),
        "version": m.group("version"),
        "python_tag": m.group("python"),
        "abi_tag": m.group("abi"),
        "platform_tag": m.group("platform"),
    }


def parse_wheel(file_bytes: bytes) -> WheelMetadata:
    """Parse metadata from a .whl file (in-memory bytes).

    Reads the METADATA and WHEEL files from the .dist-info directory.
    """
    meta = WheelMetadata()
    meta.sha256_hash = hashlib.sha256(file_bytes).hexdigest()
    meta.file_size = len(file_bytes)

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        # Find the .dist-info directory
        dist_info = None
        for name in zf.namelist():
            if name.endswith(".dist-info/METADATA"):
                dist_info = name.rsplit("/", 1)[0]
                break

        if dist_info is None:
            raise ValueError("No .dist-info/METADATA found in wheel archive")

        # Parse METADATA (RFC 822 format)
        metadata_bytes = zf.read(f"{dist_info}/METADATA")
        parser = BytesParser()
        msg = parser.parsebytes(metadata_bytes)

        meta.name = msg.get("Name", "")
        meta.version = msg.get("Version", "")
        meta.summary = msg.get("Summary", "")
        meta.homepage_url = msg.get("Home-page", "") or msg.get("Home-Page", "")
        meta.python_requires = msg.get("Requires-Python", "")

        # Extract dependencies from Requires-Dist headers
        deps = msg.get_all("Requires-Dist", [])
        # Filter out extras-only deps (those with "; extra ==" conditions)
        meta.dependencies = [d for d in deps if "extra ==" not in d]

        # Parse WHEEL file for tags
        wheel_path = f"{dist_info}/WHEEL"
        if wheel_path in zf.namelist():
            wheel_bytes = zf.read(wheel_path)
            wheel_msg = parser.parsebytes(wheel_bytes)
            tag = wheel_msg.get("Tag", "")
            if tag:
                parts = tag.split("-")
                if len(parts) >= 3:
                    meta.python_tag = parts[0]
                    meta.abi_tag = parts[1]
                    meta.platform_tag = parts[2]

    return meta
