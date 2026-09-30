"""Prepare private YaCy data without starting YaCy or joining a network."""
import hashlib
import os
import re
import secrets
import subprocess
from pathlib import Path

IMAGE = "yacy/yacy_search_server@sha256:55c5e5dd928f312cf47a57afa8d645df37366f15678e0983c8b7fdbe3b5f6475"
DATA = Path("/home/ats030/data/web-search-yacy/SETTINGS")
PRIVATE = Path("/home/ats030/.config/web-search-yacy")


def prepare() -> None:
    config = DATA / "yacy.conf"
    password_file = PRIVATE / "admin-password"
    if config.exists() or password_file.exists():
        raise SystemExit("YaCy state already exists; refusing to replace private settings")
    defaults = subprocess.check_output([
        "docker", "run", "--rm", "--entrypoint", "cat", IMAGE,
        "/opt/yacy_search_server/defaults/yacy.init",
    ], text=True)
    properties = {}
    for line in defaults.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            properties[key.strip()] = value.strip()
    realm = properties["adminRealm"]
    password = secrets.token_urlsafe(32)
    digest = hashlib.md5(f"admin:{realm}:{password}".encode()).hexdigest()
    updates = {
        "adminAccountUserName": "admin",
        "adminAccountBase64MD5": "MD5:" + digest,
        "adminAccountForLocalhost": "false",
        "network.unit.definition": "defaults/yacy.network.webportal.unit",
        "upnp.enabled": "false", "server.https": "false",
        "update.process": "manual", "javastart_Xmx": "Xmx768m",
    }
    lines = defaults.splitlines()
    for key, value in updates.items():
        pattern = re.compile(r"^" + re.escape(key) + r"\s*=")
        matching = [i for i, line in enumerate(lines) if pattern.match(line)]
        if matching:
            lines[matching[-1]] = f"{key}={value}"
        else:
            lines.append(f"{key}={value}")
    previous_mask = os.umask(0o077)
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        PRIVATE.mkdir(parents=True, exist_ok=True)
        password_file.write_text(password + "\n")
        config.write_text("\n".join(lines) + "\n")
    finally:
        os.umask(previous_mask)
    print(f"Prepared private settings: {config}")
    print(f"Admin password stored privately: {password_file}")
    print("YaCy has not been started; choose an approved network mode before compose up")


if __name__ == "__main__":
    prepare()
