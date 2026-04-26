"""Cryptographically random secret generation for a fresh MonCTL install.

Every secret below is generated locally and never leaves the operator's machine
until `monctl_ctl deploy` scp's them into `/opt/monctl/<project>/.env` on each
host (mode 0600). No phone-home, no license server.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, fields

_PRONOUNCEABLE_CONSONANTS = "bcdfghjklmnprstvwxz"
_PRONOUNCEABLE_VOWELS = "aeiouy"


@dataclass(frozen=True)
class SecretBundle:
    """Every secret needed to stand up a MonCTL cluster.

    `admin_password` is pronounceable (operator reads it from a screen once).
    Everything else is urlsafe-base64 with sufficient entropy.
    """

    monctl_encryption_key: str  # 32 bytes urlsafe-base64 — encrypts credentials at rest
    monctl_jwt_secret_key: str  # 64 bytes urlsafe-base64 — signs login JWTs
    monctl_collector_api_key: str  # prefix + 32 bytes — shared with every collector
    pg_password: str
    pg_repl_password: str
    clickhouse_password: str
    peer_token: str  # shared gRPC secret between cache-node and poll-worker
    monctl_admin_password: str  # pronounceable; printed once
    # Superset (only used when the inventory has a host with role=superset, but
    # always generated so flipping the role on later doesn't require a re-init).
    superset_secret_key: str  # 64 bytes urlsafe-base64 — Flask session signing
    superset_db_pw: str  # Postgres metadata DB password (Superset's internal PG)
    superset_admin_pw: str  # initial Superset UI admin
    monctl_oauth_client_id: str  # OAuth2 client ID central seeds at startup
    monctl_oauth_client_secret: str  # OAuth2 client secret

    def to_env_lines(self) -> list[str]:
        """Emit in the order the compose `.env` files expect.

        Returns `KEY=VALUE` lines with no quoting — compose .env doesn't tolerate
        double quotes around values, and none of our generated secrets contain
        characters that would need escaping (urlsafe-base64 is safe; admin password
        is alnum).
        """
        return [
            f"MONCTL_ENCRYPTION_KEY={self.monctl_encryption_key}",
            f"MONCTL_JWT_SECRET_KEY={self.monctl_jwt_secret_key}",
            f"MONCTL_COLLECTOR_API_KEY={self.monctl_collector_api_key}",
            f"PG_PASSWORD={self.pg_password}",
            f"PG_REPL_PASSWORD={self.pg_repl_password}",
            f"CLICKHOUSE_PASSWORD={self.clickhouse_password}",
            f"PEER_TOKEN={self.peer_token}",
            f"MONCTL_ADMIN_PASSWORD={self.monctl_admin_password}",
            f"SUPERSET_SECRET_KEY={self.superset_secret_key}",
            f"SUPERSET_DB_PW={self.superset_db_pw}",
            f"SUPERSET_ADMIN_PW={self.superset_admin_pw}",
            f"MONCTL_OAUTH_CLIENT_ID={self.monctl_oauth_client_id}",
            f"MONCTL_OAUTH_CLIENT_SECRET={self.monctl_oauth_client_secret}",
        ]


def generate_secrets() -> SecretBundle:
    return SecretBundle(
        monctl_encryption_key=secrets.token_urlsafe(32),
        monctl_jwt_secret_key=secrets.token_urlsafe(64),
        monctl_collector_api_key=f"monctl_col_{secrets.token_urlsafe(32)}",
        pg_password=secrets.token_urlsafe(32),
        pg_repl_password=secrets.token_urlsafe(32),
        clickhouse_password=secrets.token_urlsafe(32),
        peer_token=secrets.token_urlsafe(32),
        monctl_admin_password=_pronounceable_password(length=20),
        superset_secret_key=secrets.token_urlsafe(64),
        superset_db_pw=secrets.token_urlsafe(32),
        superset_admin_pw=_pronounceable_password(length=20),
        monctl_oauth_client_id=f"superset_{secrets.token_urlsafe(16)}",
        monctl_oauth_client_secret=secrets.token_urlsafe(48),
    )


def _pronounceable_password(length: int = 20) -> str:
    """Alternating consonant/vowel syllables + random digits, e.g. "vilopazu kimobe 47".

    Length is approximate — final string trimmed/padded to exactly `length` chars.
    Alnum only, safe as an env value and easy to read from a screen.
    """
    if length < 8:
        raise ValueError("pronounceable password must be >= 8 chars")
    # Build syllables until we exceed target, then trim.
    buf: list[str] = []
    while sum(len(s) for s in buf) < length - 2:
        c = secrets.choice(_PRONOUNCEABLE_CONSONANTS)
        v = secrets.choice(_PRONOUNCEABLE_VOWELS)
        buf.append(c + v)
    word = "".join(buf)[: length - 2]
    digits = f"{secrets.randbelow(90) + 10:02d}"
    return word + digits


def bundle_fieldnames() -> list[str]:
    return [f.name for f in fields(SecretBundle)]
