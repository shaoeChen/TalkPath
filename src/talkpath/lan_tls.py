"""Per-installation certificates for opt-in LAN HTTPS."""

from __future__ import annotations

import ipaddress
import os
import socket
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def local_ipv4_addresses() -> list[str]:
    """Find usable IPv4 addresses for the host's LAN URL and certificate."""

    addresses: set[str] = set()
    try:
        for entry in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            addresses.add(entry[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 80))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(
        address
        for address in addresses
        if (ip := ipaddress.ip_address(address)).is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_unspecified
    )


def _save_private_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _create_ca(ca_path: Path, ca_key_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TalkPath local CA")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    _save_private_key(ca_key_path, key)
    ca_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _create_server_certificate(
    cert_path: Path,
    key_path: Path,
    ca_path: Path,
    ca_key_path: Path,
    addresses: set[ipaddress.IPv4Address],
) -> None:
    ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TalkPath LAN")]))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost")]
                + [x509.IPAddress(address) for address in sorted(addresses)]
            ),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _save_private_key(key_path, key)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def ensure_lan_certificate(directory: Path, ips: list[str]) -> tuple[Path, Path, Path]:
    """Return server cert, server key, and persistent CA cert for LAN HTTPS."""

    addresses = {ipaddress.IPv4Address(ip) for ip in ips}
    if not addresses:
        raise RuntimeError("No LAN IPv4 address found for HTTPS certificate")
    addresses.add(ipaddress.IPv4Address("127.0.0.1"))
    directory.mkdir(parents=True, exist_ok=True)
    ca_path = directory / "talkpath-ca.crt"
    ca_key_path = directory / "talkpath-ca.key"
    cert_path = directory / "talkpath-server.crt"
    key_path = directory / "talkpath-server.key"

    if ca_path.exists() != ca_key_path.exists():
        raise RuntimeError("CA certificate or private key is missing; restore both from backup")
    new_ca = not ca_path.exists()
    if new_ca:
        _create_ca(ca_path, ca_key_path)

    ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
    if ca.public_key().public_numbers() != ca_key.public_key().public_numbers():
        raise RuntimeError("CA certificate and private key do not match")

    renew = new_ca or not (cert_path.exists() and key_path.exists())
    if not renew:
        try:
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            actual_ips = set(names.get_values_for_type(x509.IPAddress))
            ca.public_key().verify(
                cert.signature,
                cert.tbs_certificate_bytes,
                padding.PKCS1v15(),
                cert.signature_hash_algorithm,
            )
            renew = (
                actual_ips != addresses
                or cert.not_valid_after_utc < datetime.now(timezone.utc) + timedelta(days=30)
                or cert.public_key().public_numbers() != key.public_key().public_numbers()
            )
        except (ValueError, TypeError, InvalidSignature, x509.ExtensionNotFound):
            renew = True
    if renew:
        _create_server_certificate(cert_path, key_path, ca_path, ca_key_path, addresses)
    return cert_path, key_path, ca_path
