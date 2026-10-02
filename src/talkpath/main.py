"""Config-aware entry point for the TalkPath server."""

import argparse
import ipaddress
import os
from pathlib import Path

import uvicorn

from talkpath.config import PROJECT_ROOT, get_settings
from talkpath.lan_tls import ensure_lan_certificate, local_ipv4_addresses

LAN_TLS_DIR = PROJECT_ROOT / "data" / "tls"


def run(*, lan: bool = False, lan_ips: list[str] | None = None) -> None:
    """Start the FastAPI application with TalkPath settings."""

    settings = get_settings()
    options = {"factory": True, "host": settings.app_host, "port": settings.app_port}
    if lan:
        addresses = sorted(set(local_ipv4_addresses()) | set(lan_ips or []))
        cert_path, key_path, ca_path = ensure_lan_certificate(LAN_TLS_DIR, addresses)
        options.update(
            host="0.0.0.0",
            ssl_certfile=str(cert_path),
            ssl_keyfile=str(key_path),
        )
        for address in addresses:
            print(f"TalkPath LAN: https://{address}:{settings.app_port}")
        print(f"CA certificate for phones: {ca_path}")
        if settings.agent_backend == "pi":
            node_ca_path = ca_path
            existing_ca = os.environ.get("NODE_EXTRA_CA_CERTS")
            if existing_ca and Path(existing_ca).resolve() != ca_path.resolve():
                node_ca_path = LAN_TLS_DIR / "talkpath-node-ca-bundle.crt"
                node_ca_path.write_bytes(Path(existing_ca).read_bytes().rstrip() + b"\n" + ca_path.read_bytes())
            os.environ["TALKPATH_API_BASE_URL"] = f"https://127.0.0.1:{settings.app_port}"
            os.environ["NODE_EXTRA_CA_CERTS"] = str(node_ca_path)
    uvicorn.run("talkpath.api.app:create_app", **options)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start TalkPath")
    parser.add_argument("--lan", action="store_true", help="Serve HTTPS on the local network")
    parser.add_argument(
        "--lan-ip",
        action="append",
        type=ipaddress.IPv4Address,
        default=[],
        help="Add a LAN IPv4 address when automatic detection misses it",
    )
    arguments = parser.parse_args()
    run(lan=arguments.lan, lan_ips=[str(address) for address in arguments.lan_ip])
