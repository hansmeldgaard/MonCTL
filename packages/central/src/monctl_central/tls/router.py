"""TLS certificate management endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_permission
from monctl_central.storage.models import TlsCertificate
from monctl_central.credentials.crypto import encrypt_dict, decrypt_dict

router = APIRouter()
logger = structlog.get_logger()


def _cert_info(cert: TlsCertificate) -> dict:
    return {
        "id": str(cert.id),
        "name": cert.name,
        "is_self_signed": cert.is_self_signed,
        "subject_cn": cert.subject_cn,
        "valid_from": cert.valid_from.isoformat() if cert.valid_from else None,
        "valid_to": cert.valid_to.isoformat() if cert.valid_to else None,
        "is_active": cert.is_active,
        "created_at": cert.created_at.isoformat() if cert.created_at else None,
    }


@router.get("")
async def get_tls_cert(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("settings", "view")),
):
    """Get the active TLS certificate info (without private key)."""
    stmt = select(TlsCertificate).where(TlsCertificate.is_active == True)
    cert = (await db.execute(stmt)).scalar_one_or_none()
    return {"status": "success", "data": _cert_info(cert) if cert else None}


class GenerateCertRequest(BaseModel):
    cn: str = "monctl.local"


@router.post("/generate")
async def generate_self_signed(
    request: GenerateCertRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("settings", "manage")),
):
    """Generate a self-signed TLS certificate."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="cryptography library not installed",
        )

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, request.cn)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(request.cn), x509.DNSName("localhost")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

    # Encrypt the private key
    key_pem_encrypted = encrypt_dict({"key": key_pem})

    # Deactivate existing certs
    await db.execute(update(TlsCertificate).values(is_active=False))

    tls_cert = TlsCertificate(
        name=f"self-signed-{request.cn}",
        cert_pem=cert_pem,
        key_pem_encrypted=key_pem_encrypted,
        is_self_signed=True,
        subject_cn=request.cn,
        valid_from=now,
        valid_to=now + timedelta(days=365),
        is_active=True,
    )
    db.add(tls_cert)
    await db.flush()
    return {"status": "success", "data": _cert_info(tls_cert)}


class UploadCertRequest(BaseModel):
    name: str
    cert_pem: str
    key_pem: str


@router.post("/upload")
async def upload_cert(
    request: UploadCertRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("settings", "manage")),
):
    """Upload a TLS certificate and private key."""
    try:
        from cryptography import x509
    except ImportError:
        raise HTTPException(status_code=500, detail="cryptography library not installed")

    try:
        cert = x509.load_pem_x509_certificate(request.cert_pem.encode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid certificate PEM")

    cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    subject_cn = cn[0].value if cn else "unknown"

    key_pem_encrypted = encrypt_dict({"key": request.key_pem})

    await db.execute(update(TlsCertificate).values(is_active=False))

    tls_cert = TlsCertificate(
        name=request.name,
        cert_pem=request.cert_pem,
        key_pem_encrypted=key_pem_encrypted,
        is_self_signed=False,
        subject_cn=subject_cn,
        valid_from=cert.not_valid_before_utc,
        valid_to=cert.not_valid_after_utc,
        is_active=True,
    )
    db.add(tls_cert)
    await db.flush()
    return {"status": "success", "data": _cert_info(tls_cert)}


@router.post("/deploy")
async def deploy_cert(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("settings", "manage")),
):
    """Deploy the active certificate to HAProxy."""
    stmt = select(TlsCertificate).where(TlsCertificate.is_active == True)
    cert = (await db.execute(stmt)).scalar_one_or_none()
    if cert is None:
        raise HTTPException(status_code=404, detail="No active certificate")

    try:
        key_data = decrypt_dict(cert.key_pem_encrypted)
        key_pem = key_data.get("key", "")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt private key")

    # Write combined PEM for HAProxy
    tls_dir = Path("/etc/monctl/tls")
    tls_dir.mkdir(parents=True, exist_ok=True)
    haproxy_pem = tls_dir / "haproxy.pem"
    haproxy_pem.write_text(cert.cert_pem + key_pem)

    # Try to reload HAProxy
    import subprocess
    try:
        subprocess.run(["systemctl", "reload", "haproxy"], check=True, timeout=10)
        logger.info("haproxy_reloaded")
    except Exception as exc:
        logger.warning("haproxy_reload_failed", error=str(exc))

    return {"status": "success", "data": {"deployed": True}}
