from __future__ import annotations

import asyncio
import json
import platform
import re
import subprocess

from . import connect

PING_PORTS = (80, 443, 22, 445, 3389, 8080, 53, 25)
_RE_TTL = re.compile(r"ttl[=:](\d+)", re.I)
_RE_TIME = re.compile(r"time[=<](\d+(?:\.\d+)?)\s*ms", re.I)


async def tcp_ping(ip: str, timeout: float) -> tuple[bool, str, float | None]:
    return await connect.ping(ip, PING_PORTS, timeout)


def _system_ping(host: str, timeout: float) -> tuple[bool, int | None, float | None]:
    windows = platform.system().lower().startswith("win")
    if windows:
        command = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
    else:
        command = ["ping", "-c", "1", "-W", str(max(int(timeout), 1)), host]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout + 3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, None, None
    output = completed.stdout or ""
    if completed.returncode != 0:
        return False, None, None
    ttl_match = _RE_TTL.search(output)
    time_match = _RE_TIME.search(output)
    ttl = int(ttl_match.group(1)) if ttl_match else None
    rtt = float(time_match.group(1)) if time_match else None
    return True, ttl, rtt


async def _native_ping(binary: str, host: str, timeout: float) -> tuple[bool, int | None, float | None]:
    def run() -> tuple[bool, int | None, float | None]:
        try:
            completed = subprocess.run(
                [binary, "icmp", host, str(int(timeout * 1000))],
                capture_output=True,
                text=True,
                timeout=timeout + 3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False, None, None
        line = (completed.stdout or "").strip().splitlines()
        if not line:
            return False, None, None
        try:
            payload = json.loads(line[-1])
        except ValueError:
            return False, None, None
        return (
            bool(payload.get("alive")),
            payload.get("ttl"),
            payload.get("rtt_ms"),
        )

    return await asyncio.to_thread(run)


async def discover(
    host: str,
    *,
    timeout: float = 1.0,
    native_binary: str | None = None,
    use_icmp: bool = True,
) -> tuple[str, str, float | None, int | None]:
    alive, reason, rtt = await tcp_ping(host, timeout)
    if alive:
        return "up", reason, rtt, None
    if not use_icmp:
        return "down", reason, None, None
    if native_binary:
        alive, ttl, rtt = await _native_ping(native_binary, host, max(timeout, 1.0))
        if alive:
            return "up", "icmp-echo", rtt, ttl
    alive, ttl, rtt = await asyncio.to_thread(_system_ping, host, max(timeout, 1.0))
    if alive:
        return "up", "icmp-echo", rtt, ttl
    return "down", "no-response", None, None
