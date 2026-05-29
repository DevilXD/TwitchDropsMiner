import ipaddress
import os
import socket
import subprocess
from pathlib import Path


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
    san_entries = ["DNS:localhost", "IP:127.0.0.1"]
    hostname = socket.gethostname()
    if hostname not in ("localhost", "127.0.0.1"):
        san_entries.append(f"DNS:{hostname}")
        try:
            local_ip = ipaddress.ip_address(socket.gethostbyname(hostname))
            if local_ip != ipaddress.ip_address("127.0.0.1"):
                san_entries.append(f"IP:{local_ip}")
        except Exception:
            pass
    cmd = (
        f"openssl req -x509 -newkey rsa:2048 -nodes -days 3650"
        f" -keyout {keyfile} -out {certfile}"
        f' -subj "/CN=TwitchDropsMiner"'
        f' -addext "subjectAltName={",".join(san_entries)}"'
    )
    subprocess.run(cmd, shell=True, check=True)
