"""Async TCP connect-scan engine backing both the TUI and the CLI.

NetBreak uses plain OS-level TCP connects ("connect scan"), the same kind of
connection a web browser makes. This needs no raw sockets and no elevated
privileges, which keeps the tool simple and portable.
"""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass
from typing import AsyncIterator

OPEN = "open"
CLOSED = "closed"
FILTERED = "filtered"


@dataclass(slots=True)
class ScanResult:
    host: str
    port: int
    state: str
    service: str | None = None
    latency_ms: float | None = None
    note: str | None = None

    @property
    def is_open(self) -> bool:
        return self.state == OPEN


def resolve(host: str) -> str:
    """Resolve *host* to an IP address, preferring IPv4."""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    if not infos:
        raise OSError(f"could not resolve {host!r}")
    for family, _type, _proto, _canon, sockaddr in infos:
        if family == socket.AF_INET:
            return sockaddr[0]
    return infos[0][4][0]


def service_name(port: int) -> str | None:
    """Best-effort service name for a TCP port, e.g. 443 -> 'https'."""
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return None


async def scan_port(ip: str, port: int, timeout: float, host: str = "") -> ScanResult:
    """Probe a single TCP port and classify it as open/closed/filtered."""
    service = service_name(port)
    start = time.perf_counter()
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
    except ConnectionRefusedError:
        # A reachable host actively refused us: the port is closed.
        return ScanResult(host, port, CLOSED, service)
    except asyncio.TimeoutError:
        return ScanResult(host, port, FILTERED, service, note="timeout")
    except OSError as exc:
        return ScanResult(host, port, FILTERED, service, note=exc.strerror or str(exc))

    latency = (time.perf_counter() - start) * 1000.0
    try:
        writer.close()
        await writer.wait_closed()
    except OSError:
        pass
    return ScanResult(host, port, OPEN, service, round(latency, 2))


class Scanner:
    """Scans a list of ports on one host with bounded concurrency."""

    def __init__(
        self,
        host: str,
        ports: list[int],
        *,
        timeout: float = 1.0,
        concurrency: int = 400,
    ) -> None:
        self.host = host
        self.ports = ports
        self.timeout = timeout
        self.concurrency = max(1, concurrency)
        # Resolve once so hostname lookups don't slow down every probe.
        self.ip = resolve(host)

    async def scan(
        self, cancel: asyncio.Event | None = None
    ) -> AsyncIterator[ScanResult]:
        """Yield a ScanResult per port, in completion order.

        Ports are processed in bounded chunks so a full 1-65535 sweep never
        queues tens of thousands of tasks at once. Pass an ``asyncio.Event``
        via *cancel* to stop gracefully between probes.
        """
        chunk_size = self.concurrency * 8
        for start in range(0, len(self.ports), chunk_size):
            if cancel is not None and cancel.is_set():
                break
            chunk = self.ports[start : start + chunk_size]
            sem = asyncio.Semaphore(self.concurrency)

            async def bounded(port: int) -> ScanResult | None:
                if cancel is not None and cancel.is_set():
                    return None
                async with sem:
                    if cancel is not None and cancel.is_set():
                        return None
                    return await scan_port(self.ip, port, self.timeout, self.host)

            tasks = [asyncio.create_task(bounded(p)) for p in chunk]
            try:
                for future in asyncio.as_completed(tasks):
                    result = await future
                    if result is not None:
                        yield result
            finally:
                for task in tasks:
                    task.cancel()
