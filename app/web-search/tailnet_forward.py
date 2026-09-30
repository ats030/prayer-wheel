"""Forward the API (8527) and YaCy (8090) from the host's Tailnet IPv4 to loopback.

app-portal reaches both over Tailscale. They keep listening only on 127.0.0.1,
so local callers (exam-trainer, the API's YaCy route) never depend on Tailscale
timing. This process waits for the Tailnet IP at boot and exits non-zero when it
cannot bind, so systemd retries. 0.0.0.0 is avoided so nothing is on the LAN.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time

PORTS = (8527, 8090)
IP_WAIT_SECONDS = 600


def tailnet_ip() -> str:
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True,
                             timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.split()[0] if out.split() else ""


def wait_for_ip() -> str:
    deadline = time.monotonic() + IP_WAIT_SECONDS
    while True:
        ip = tailnet_ip()
        if ip or time.monotonic() >= deadline:
            return ip
        time.sleep(5)


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


def handler(port: int):
    async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        try:
            up_r, up_w = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            client_w.close()
            return
        await asyncio.gather(pipe(client_r, up_w), pipe(up_r, client_w))
    return handle


async def serve(ip: str) -> None:
    servers = [await asyncio.start_server(handler(p), ip, p) for p in PORTS]
    await asyncio.gather(*(s.serve_forever() for s in servers))


def main() -> None:
    ip = wait_for_ip()
    if not ip:
        sys.exit("web-search-tailnet: Tailnet IP unavailable")
    asyncio.run(serve(ip))


if __name__ == "__main__":
    main()
