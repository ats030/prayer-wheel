"""Read only the selected Cloudflare credential, without executing dotenv files."""
import os
from pathlib import Path
import shlex


def read_token(path=None):
    path = Path(path) if path is not None else Path.home() / ".env"
    if not path.exists():
        return None
    if path.stat().st_size > 1_048_576 or path.stat().st_mode & 0o077:
        raise ValueError("Cloudflare credential file must be private and at most 1 MiB")
    values = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line or line.startswith("#"):
            continue
        name, value = line.split("=", 1)
        if name.strip() != "CLOUDFLARE_API_TOKEN":
            continue
        try:
            parts = shlex.split(value, comments=True)
        except ValueError:
            raise ValueError("Invalid Cloudflare credential assignment") from None
        if len(parts) != 1 or not 20 <= len(parts[0]) <= 512 or not all(
                c.isascii() and (c.isalnum() or c in "_-") for c in parts[0]):
            raise ValueError("Invalid Cloudflare credential assignment")
        values.append(parts[0])
    if len(values) > 1:
        raise ValueError("Duplicate Cloudflare credential assignments")
    return values[0] if values else None


def deployment_environment(use_oauth=False):
    env = dict(os.environ, WRANGLER_SEND_METRICS="false")
    if use_oauth:
        env.pop("CLOUDFLARE_API_TOKEN", None)
    elif not env.get("CLOUDFLARE_API_TOKEN"):
        token = read_token()
        if token:
            env["CLOUDFLARE_API_TOKEN"] = token
    env.setdefault("CLOUDFLARE_ACCOUNT_ID", "559cfb7fb4d4ff05a7bbcfc75ec739a4")
    return env
