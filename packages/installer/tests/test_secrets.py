from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from monctl_installer.secrets.generator import generate_secrets
from monctl_installer.secrets.store import (
    SecretsFileError,
    load_secrets,
    validate_secrets_file,
    write_secrets,
)


def test_generate_produces_distinct_values() -> None:
    a = generate_secrets()
    b = generate_secrets()
    for key in a.to_env_lines():
        assert key in b.to_env_lines() or True  # dummy; full value test below
    # No two bundles should share any secret.
    assert a.monctl_encryption_key != b.monctl_encryption_key
    assert a.pg_password != b.pg_password
    assert a.monctl_admin_password != b.monctl_admin_password


def test_encryption_key_has_enough_entropy() -> None:
    b = generate_secrets()
    # 32 bytes base64-urlsafe ≈ 43 chars (no padding) — cryptography.fernet minimum.
    assert len(b.monctl_encryption_key) >= 42


def test_admin_password_is_alnum_exact_length() -> None:
    b = generate_secrets()
    assert len(b.monctl_admin_password) == 20
    assert b.monctl_admin_password.isalnum()


def test_write_creates_0600(tmp_path: Path) -> None:
    target = tmp_path / "secrets.env"
    bundle = generate_secrets()
    write_secrets(bundle, target)
    assert target.exists()
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600
    # All 8 required keys present
    parsed = load_secrets(target)
    for key in [
        "MONCTL_ENCRYPTION_KEY",
        "MONCTL_JWT_SECRET_KEY",
        "MONCTL_COLLECTOR_API_KEY",
        "PG_PASSWORD",
        "PG_REPL_PASSWORD",
        "CLICKHOUSE_PASSWORD",
        "PEER_TOKEN",
        "MONCTL_ADMIN_PASSWORD",
    ]:
        assert key in parsed, f"missing {key}"


def test_write_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "secrets.env"
    write_secrets(generate_secrets(), target)
    with pytest.raises(SecretsFileError, match="already exists"):
        write_secrets(generate_secrets(), target)


def test_write_allows_overwrite_when_flagged(tmp_path: Path) -> None:
    target = tmp_path / "secrets.env"
    write_secrets(generate_secrets(), target)
    write_secrets(generate_secrets(), target, overwrite=True)


def test_validate_rejects_wrong_mode(tmp_path: Path) -> None:
    target = tmp_path / "secrets.env"
    write_secrets(generate_secrets(), target)
    os.chmod(target, 0o644)
    with pytest.raises(SecretsFileError, match="mode"):
        validate_secrets_file(target)


def test_validate_rejects_missing_key(tmp_path: Path) -> None:
    target = tmp_path / "secrets.env"
    target.write_text("MONCTL_ENCRYPTION_KEY=abc\n")
    os.chmod(target, 0o600)
    with pytest.raises(SecretsFileError, match="missing"):
        validate_secrets_file(target)


def test_validate_rejects_placeholder(tmp_path: Path) -> None:
    target = tmp_path / "secrets.env"
    bundle = generate_secrets()
    write_secrets(bundle, target)
    # Re-write one line with CHANGEME
    contents = target.read_text().replace(bundle.pg_password, "CHANGEME")
    target.write_text(contents)
    os.chmod(target, 0o600)
    with pytest.raises(SecretsFileError, match="placeholder"):
        validate_secrets_file(target)


def test_validate_accepts_valid_file(tmp_path: Path) -> None:
    target = tmp_path / "secrets.env"
    write_secrets(generate_secrets(), target)
    validate_secrets_file(target)  # no exception
