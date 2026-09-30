"""Serve the API on loopback and, when present, the host's Tailnet IPv4.

Local callers (exam-trainer) keep using 127.0.0.1; app-portal reaches the
same process over Tailscale. uvicorn's CLI binds one host, so sockets are
opened here. 0.0.0.0 is avoided so the API never listens on the LAN.
"""
from __future__ import annotations

import socket
import subprocess
import sys

import uvicorn

PORT = 8527


def tailnet_ip() -> str:
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True,
                             timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.split()[0] if out.split() else ""


def bind(host: str) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, PORT))
    return sock


def main() -> None:
    hosts = ["127.0.0.1"]
    ip = tailnet_ip()
    if ip:
        hosts.append(ip)
    else:
        print("web-search: Tailnet IP unavailable; serving loopback only", file=sys.stderr)
    config = uvicorn.Config("main:app", port=PORT)
    uvicorn.Server(config).run(sockets=[bind(h) for h in hosts])


if __name__ == "__main__":
    main()
