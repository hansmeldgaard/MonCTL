from __future__ import annotations

import stat
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from monctl_installer.cli import main
from monctl_installer.commands.init import InitError, run_from_yaml


REPO_ROOT = Path(__file__).parents[3]
MICRO = REPO_ROOT / "inventory.example.micro.yaml"


def test_init_from_seed_writes_both_files(tmp_path: Path) -> None:
    inv = tmp_path / "inventory.yaml"
    sec = tmp_path / "secrets.env"
    result = run_from_yaml(
        seed_path=MICRO, inventory_path=inv, secrets_path=sec, overwrite=False
    )
    assert inv.exists()
    assert sec.exists()
    assert stat.S_IMODE(sec.stat().st_mode) == 0o600
    assert len(result.admin_password) == 20
    assert "127.0.0.1" in result.login_url


def test_init_from_seed_rewrites_secrets_path(tmp_path: Path) -> None:
    inv = tmp_path / "inventory.yaml"
    sec = tmp_path / "secrets.env"
    run_from_yaml(seed_path=MICRO, inventory_path=inv, secrets_path=sec, overwrite=False)
    doc = yaml.safe_load(inv.read_text())
    # init should normalise the secrets.file path to match where we actually wrote it
    assert doc["secrets"]["file"] == str(sec)


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    inv = tmp_path / "inventory.yaml"
    sec = tmp_path / "secrets.env"
    run_from_yaml(seed_path=MICRO, inventory_path=inv, secrets_path=sec, overwrite=False)
    with pytest.raises(InitError, match="already exists"):
        run_from_yaml(
            seed_path=MICRO, inventory_path=inv, secrets_path=sec, overwrite=False
        )


def test_init_force_preserves_existing_secrets(tmp_path: Path) -> None:
    """`--force` rewrites the inventory but MUST NOT rotate secrets.

    Post M-INST-010: re-running init to fix a typo in inventory must never
    silently invalidate every JWT, encrypted credential at rest, and
    collector key. Rotation requires the explicit `regenerate_secrets`
    flag (`--regenerate-secrets` on the CLI).
    """
    inv = tmp_path / "inventory.yaml"
    sec = tmp_path / "secrets.env"
    first = run_from_yaml(
        seed_path=MICRO, inventory_path=inv, secrets_path=sec, overwrite=False
    )
    second = run_from_yaml(
        seed_path=MICRO, inventory_path=inv, secrets_path=sec, overwrite=True
    )
    assert first.admin_password == second.admin_password


def test_init_regenerate_secrets_rotates_password(tmp_path: Path) -> None:
    """Opting in via `regenerate_secrets=True` rotates the password."""
    inv = tmp_path / "inventory.yaml"
    sec = tmp_path / "secrets.env"
    first = run_from_yaml(
        seed_path=MICRO, inventory_path=inv, secrets_path=sec, overwrite=False
    )
    second = run_from_yaml(
        seed_path=MICRO,
        inventory_path=inv,
        secrets_path=sec,
        overwrite=True,
        regenerate_secrets=True,
    )
    assert first.admin_password != second.admin_password


def test_init_rejects_broken_seed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nhosts: []\n")
    inv = tmp_path / "inventory.yaml"
    sec = tmp_path / "secrets.env"
    with pytest.raises(InitError, match="validation"):
        run_from_yaml(seed_path=bad, inventory_path=inv, secrets_path=sec, overwrite=False)
    assert not inv.exists()  # cleaned up
    assert not sec.exists()


def test_cli_init_from_seed(tmp_path: Path) -> None:
    runner = CliRunner()
    inv = tmp_path / "inventory.yaml"
    sec = tmp_path / "secrets.env"
    result = runner.invoke(
        main,
        [
            "init",
            "--inventory",
            str(inv),
            "--secrets",
            str(sec),
            "--from",
            str(MICRO),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "ADMIN CREDENTIALS" in result.output
    assert inv.exists() and sec.exists()


def test_cli_init_interactive_single_host(tmp_path: Path) -> None:
    runner = CliRunner()
    inv = tmp_path / "inventory.yaml"
    sec = tmp_path / "secrets.env"
    # Answers to the wizard prompts, in order:
    # name, domain, vip?, ssh user, host1 name, host1 addr, host1 roles,
    # host2 name (blank ends), shards, replicas, pg mode
    answers = "\n".join(
        [
            "demo",           # cluster name
            "",               # domain (blank)
            "n",              # use vip?
            "monctl",         # ssh user
            "box",            # host1 name
            "127.0.0.1",      # host1 address
            "postgres,redis,clickhouse,central,collector,docker_stats",  # roles
            "",               # end hosts list
            "1",              # shards
            "1",              # replicas
            "standalone",     # pg mode
        ]
    )
    result = runner.invoke(
        main,
        ["init", "--inventory", str(inv), "--secrets", str(sec)],
        input=answers + "\n",
    )
    assert result.exit_code == 0, result.output
    doc = yaml.safe_load(inv.read_text())
    assert doc["cluster"]["name"] == "demo"
    assert len(doc["hosts"]) == 1
    assert doc["hosts"][0]["name"] == "box"
