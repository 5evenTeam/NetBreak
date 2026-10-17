from __future__ import annotations

import asyncio
import socket
import time
from typing import AsyncIterator

from .models import PortResult, PortState

DNS_QUERY = bytes.fromhex("abcd0100000100000000000003777777076578616d706c6503636f6d0000010001")
NTP_QUERY = b"\x1b" + b"\x00" * 47
SNMP_QUERY = bytes.fromhex("302602010104067075626c6963a0190204") + b"\x00" * 8

PAYLOADS: dict[int, bytes] = {
    53: DNS_QUERY,
    123: NTP_QUERY,
    161: SNMP_QUERY,
}


def _payload(port: int) -> bytes:
    return PAYLOADS.get(port, b"")


async def probe(ip: str, port: int, timeout: float) -> PortResult:
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    start = time.perf_counter()
    try:
        await loop.sock_connect(sock, (ip, port))
        await loop.sock_sendall(sock, _payload(port))
        try:
            data = await asyncio.wait_for(loop.sock_recv(sock, 65535), timeout)
        except asyncio.TimeoutError:
            return PortResult(port, "udp", PortState.OPEN_FILTERED.value, "no-response")
        except ConnectionResetError:
            return PortResult(port, "udp", PortState.CLOSED.value, "icmp-port-unreachable")
        except OSError as exc:
            name = getattr(exc, "strerror", None) or str(exc)
            if "reset" in name.lower() or "refused" in name.lower():
                return PortResult(port, "udp", PortState.CLOSED.value, "icmp-port-unreachable")
            return PortResult(port, "udp", PortState.OPEN_FILTERED.value, name)
        rtt = (time.perf_counter() - start) * 1000.0
        result = PortResult(port, "udp", PortState.OPEN.value, "udp-response", round(rtt, 2))
        result.info["bytes"] = str(len(data))
        result.banner = data[:64].hex()
        return result
    except ConnectionResetError:
        return PortResult(port, "udp", PortState.CLOSED.value, "icmp-port-unreachable")
    except OSError as exc:
        return PortResult(port, "udp", PortState.OPEN_FILTERED.value, exc.strerror or "net-unreachable")
    finally:
        sock.close()


async def scan(
    ip: str,
    ports: list[int],
    *,
    timeout: float = 2.0,
    concurrency: int = 150,
    cancel: asyncio.Event | None = None,
) -> AsyncIterator[PortResult]:
    sem = asyncio.Semaphore(concurrency)

    async def worker(port: int) -> PortResult | None:
        if cancel is not None and cancel.is_set():
            return None
        async with sem:
            if cancel is not None and cancel.is_set():
                return None
            return await probe(ip, port, timeout)

    tasks = [asyncio.create_task(worker(p)) for p in ports]
    try:
        for future in asyncio.as_completed(tasks):
            result = await future
            if result is not None:
                yield result
    finally:
        for task in tasks:
            task.cancel()
