import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import serialization

from talkpath import lan_tls
from talkpath.lan_tls import ensure_lan_certificate


def test_creates_persistent_ca_and_ip_certificate(tmp_path):
    cert_path, key_path, ca_path = ensure_lan_certificate(tmp_path, ["192.168.1.50"])

    ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value

    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert cert.issuer == ca.subject
    ca.public_key().verify(
        cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm
    )
    assert isinstance(key, rsa.RSAPrivateKey)
    assert cert.public_key().public_numbers() == key.public_key().public_numbers()
    assert ipaddress.ip_address("192.168.1.50") in names.get_values_for_type(x509.IPAddress)
    assert ipaddress.ip_address("127.0.0.1") in names.get_values_for_type(x509.IPAddress)

    original = (ca_path.read_bytes(), cert_path.read_bytes(), key_path.read_bytes())
    assert ensure_lan_certificate(tmp_path, ["192.168.1.50"]) == (
        cert_path, key_path, ca_path
    )
    assert (ca_path.read_bytes(), cert_path.read_bytes(), key_path.read_bytes()) == original


def test_ip_change_renews_server_certificate_but_keeps_ca(tmp_path):
    cert_path, _, ca_path = ensure_lan_certificate(tmp_path, ["192.168.1.50"])
    original_ca = ca_path.read_bytes()
    original_cert = cert_path.read_bytes()

    ensure_lan_certificate(tmp_path, ["192.168.1.51"])

    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ca_path.read_bytes() == original_ca
    assert cert_path.read_bytes() != original_cert
    assert ipaddress.ip_address("192.168.1.51") in names.get_values_for_type(x509.IPAddress)


def test_new_ca_also_renews_server_certificate(tmp_path):
    cert_path, _, ca_path = ensure_lan_certificate(tmp_path, ["192.168.1.50"])
    old_cert = cert_path.read_bytes()
    ca_path.unlink()
    (tmp_path / "talkpath-ca.key").unlink()

    ensure_lan_certificate(tmp_path, ["192.168.1.50"])

    ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    assert cert_path.read_bytes() != old_cert
    ca.public_key().verify(
        cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm
    )


def test_replaced_ca_renews_existing_server_certificate(tmp_path):
    cert_path, _, ca_path = ensure_lan_certificate(tmp_path, ["192.168.1.50"])
    old_cert = cert_path.read_bytes()
    replacement = tmp_path / "replacement"
    _, _, replacement_ca = ensure_lan_certificate(replacement, ["192.168.1.50"])
    ca_path.write_bytes(replacement_ca.read_bytes())
    (tmp_path / "talkpath-ca.key").write_bytes((replacement / "talkpath-ca.key").read_bytes())

    ensure_lan_certificate(tmp_path, ["192.168.1.50"])

    assert cert_path.read_bytes() != old_cert
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
    ca.public_key().verify(
        cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm
    )


def test_mismatched_ca_key_fails_before_serving(tmp_path):
    ensure_lan_certificate(tmp_path, ["192.168.1.50"])
    replacement = tmp_path / "replacement"
    ensure_lan_certificate(replacement, ["192.168.1.50"])
    (tmp_path / "talkpath-ca.key").write_bytes((replacement / "talkpath-ca.key").read_bytes())

    try:
        ensure_lan_certificate(tmp_path, ["192.168.1.50"])
    except RuntimeError as exc:
        assert "CA" in str(exc)
    else:
        raise AssertionError("Mismatched CA key must stop HTTPS startup")


def test_partial_ca_files_do_not_silently_replace_trusted_ca(tmp_path):
    ensure_lan_certificate(tmp_path, ["192.168.1.50"])
    (tmp_path / "talkpath-ca.key").unlink()

    try:
        ensure_lan_certificate(tmp_path, ["192.168.1.50"])
    except RuntimeError as exc:
        assert "CA" in str(exc)
    else:
        raise AssertionError("Missing CA key must not generate a new trusted identity")


def test_local_addresses_exclude_unusable_interfaces(monkeypatch):
    class Probe:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def connect(self, _address):
            pass

        def getsockname(self):
            return ("192.168.1.50", 12345)

    monkeypatch.setattr(lan_tls.socket, "gethostname", lambda: "host")
    monkeypatch.setattr(
        lan_tls.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (None, None, None, None, (address, 0))
            for address in ["0.0.0.0", "127.0.0.1", "169.254.1.2", "10.0.0.2"]
        ],
    )
    monkeypatch.setattr(lan_tls.socket, "socket", lambda *_args: Probe())

    assert lan_tls.local_ipv4_addresses() == ["10.0.0.2", "192.168.1.50"]
