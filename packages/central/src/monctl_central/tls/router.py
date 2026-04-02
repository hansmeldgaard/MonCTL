"""TLS certificate management endpoints."""

from __future__ import annotations

import hashlib
import ipaddress
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.config import settings
from monctl_central.dependencies import get_db, require_permission
from monctl_central.storage.models import TlsCertificate
from monctl_central.credentials.crypto import encrypt_dict, decrypt_dict

router = APIRouter()
logger = structlog.get_logger()


def _parse_san_list(cert) -> list[str]:
    """Extract SAN entries from a certificate."""
    try:
        from cryptography import x509
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        sans = []
        for name in ext.value:
            if isinstance(name, x509.DNSName):
                sans.append(f"DNS:{name.value}")
            elif isinstance(name, x509.IPAddress):
                sans.append(f"IP:{name.value}")
        return sans
    except Exception:
        return []


def _cert_fingerprint(cert_pem: str) -> str:
    """Compute SHA-256 fingerprint of a PEM certificate."""
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        digest = cert.fingerprint(cert.signature_hash_algorithm or __import__('cryptography.hazmat.primitives.hashes', fromlist=['SHA256']).SHA256())
        return ":".join(f"{b:02X}" for b in digest)
    except Exception:
        raw = hashlib.sha256(cert_pem.encode()).digest()
        return ":".join(f"{b:02X}" for b in raw)


def _cert_info(cert: TlsCertificate) -> dict:
    san_list: list[str] = []
    fingerprint = ""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        parsed = x509.load_pem_x509_certificate(cert.cert_pem.encode())
        san_list = _parse_san_list(parsed)
        digest = parsed.fingerprint(hashes.SHA256())
        fingerprint = ":".join(f"{b:02X}" for b in digest)
    except Exception:
        pass

    return {
        "id": str(cert.id),
        "name": cert.name,
        "is_self_signed": cert.is_self_signed,
        "subject_cn": cert.subject_cn,
        "valid_from": cert.valid_from.isoformat() if cert.valid_from else None,
        "valid_to": cert.valid_to.isoformat() if cert.valid_to else None,
        "is_active": cert.is_active,
        "created_at": cert.created_at.isoformat() if cert.created_at else None,
        "san_list": san_list,
        "fingerprint": fingerprint,
    }


@router.get("")
async def get_tls_cert(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("settings", "view")),
):
    """Get the active TLS certificate info (without private key)."""
    stmt = select(TlsCertificate).where(TlsCertificate.is_active == True)  # noqa: E712
    cert = (await db.execute(stmt)).scalar_one_or_none()
    return {"status": "success", "data": _cert_info(cert) if cert else None}


class GenerateCertRequest(BaseModel):
    cn: str = "monctl.local"
    san_ips: list[str] | None = None  # If None, use MONCTL_TLS_SAN_IPS
    san_dns: list[str] | None = None  # If None, use [cn, "localhost"]
    validity_days: int = 3650


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

    # Build SAN list
    san_entries: list[x509.GeneralName] = []

    # DNS SANs
    dns_names = request.san_dns if request.san_dns is not None else [request.cn, "localhost"]
    for name in dns_names:
        if name.strip():
            san_entries.append(x509.DNSName(name.strip()))

    # IP SANs — from request or config
    ip_strings = request.san_ips
    if ip_strings is None and settings.tls_san_ips:
        ip_strings = [ip.strip() for ip in settings.tls_san_ips.split(",") if ip.strip()]
    if ip_strings:
        for ip_str in ip_strings:
            try:
                san_entries.append(x509.IPAddress(ipaddress.ip_address(ip_str.strip())))
            except ValueError:
                logger.warning("tls_invalid_san_ip", ip=ip_str)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, request.cn)])
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=request.validity_days))
    )
    if san_entries:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(san_entries), critical=False,
        )
    cert = builder.sign(key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

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
        valid_to=now + timedelta(days=request.validity_days),
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
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError:
        raise HTTPException(status_code=500, detail="cryptography library not installed")

    try:
        cert = x509.load_pem_x509_certificate(request.cert_pem.encode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid certificate PEM")

    # Validate private key
    try:
        load_pem_private_key(request.key_pem.encode(), password=None)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid private key PEM")

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
    """Deploy the active certificate to the local HAProxy (via shared volume).

    Other central nodes pick up the change automatically within 60 seconds.
    """
    stmt = select(TlsCertificate).where(TlsCertificate.is_active == True)  # noqa: E712
    cert = (await db.execute(stmt)).scalar_one_or_none()
    if cert is None:
        raise HTTPException(status_code=404, detail="No active certificate")

    from monctl_central.dependencies import get_session_factory
    from monctl_central.tls.sync import sync_cert_to_disk

    factory = get_session_factory()
    written = await sync_cert_to_disk(factory)

    return {
        "status": "success",
        "data": {
            "deployed": True,
            "written": written,
            "message": "Certificate deployed locally. Other nodes sync within 60 seconds.",
        },
    }


@router.get("/download")
async def download_cert(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("settings", "view")),
):
    """Download the active certificate PEM (public cert only, no private key)."""
    stmt = select(TlsCertificate).where(TlsCertificate.is_active == True)  # noqa: E712
    cert = (await db.execute(stmt)).scalar_one_or_none()
    if cert is None:
        raise HTTPException(status_code=404, detail="No active certificate")

    return PlainTextResponse(
        content=cert.cert_pem,
        media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="{cert.subject_cn}.crt"'},
    )
