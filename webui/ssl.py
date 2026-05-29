import ipaddress
import os
import socket
from pathlib import Path

import trustme


def get_ssl_kwargs(cert_dir: Path) -> dict[str, str]:
    if os.environ.get("SECURE_CONNECTION", "0") != "1":
        return {}
    keyfile = cert_dir / "web-privkey.pem"
    certfile = cert_dir / "web-fullchain.pem"
    if not keyfile.is_file() or not certfile.is_file():
        _generate_self_signed(keyfile, certfile, cert_dir)
    return {"ssl_keyfile": str(keyfile), "ssl_certfile": str(certfile)}


def _generate_self_signed(keyfile: Path, certfile: Path, cert_dir: Path) -> None:
    cert_dir.mkdir(parents=True, exist_ok=True)
    san = ["localhost", "127.0.0.1"]
    hostname = socket.gethostname()
    if hostname not in san:
        san.append(hostname)
        try:
            local_ip = ipaddress.ip_address(socket.gethostbyname(hostname))
            if local_ip not in san:
                san.append(local_ip)
        except Exception:
            pass
    ca = trustme.CA()
    cert = ca.issue_cert(*san)
    cert.private_key_pem.write_to_path(keyfile)
    cert.cert_chain_pems[0].write_to_path(certfile)
