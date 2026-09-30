"""Create private credentials once. Never print passwords."""
import secrets
import subprocess
from pathlib import Path

PRIVATE = Path.home() / ".config/web-search-opensearch"


def prepare():
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    for filename, key in [("server.env", "OPENSEARCH_INITIAL_ADMIN_PASSWORD"),
                          ("reader.env", "PASSWORD")]:
        target = PRIVATE / filename
        if target.exists():
            continue
        with target.open("x") as handle:
            target.chmod(0o600)
            handle.write(f"{key}=Aa1!{secrets.token_hex(24)}\n")
    tls = PRIVATE / "tls"
    tls.mkdir(mode=0o700, exist_ok=True)
    if not (tls / "server.pem").exists():
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes",
            "-sha256", "-days", "365", "-subj", "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
            "-keyout", str(tls / "server-key.pem"), "-out", str(tls / "server.pem")],
            check=True, capture_output=True)
        (tls / "server-key.pem").chmod(0o600)
    print("Private credential files prepared; existing credentials preserved")


if __name__ == "__main__":
    prepare()
