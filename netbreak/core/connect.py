from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from .models import PortResult, PortState


async def probe(ip: str, port: int, timeout: float) -> PortResult:
    start = time.perf_counter()
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
    except ConnectionRefusedError:
        return PortResult(port, "tcp", PortState.CLOSED.value, "conn-refused")
    except asyncio.TimeoutError:
        return PortResult(port, "tcp", PortState.FILTERED.value, "no-response")
    except OSError as exc:
        return PortResult(port, "tcp", PortState.FILTERED.value, exc.strerror or "net-unreachable")
    rtt = (time.perf_counter() - start) * 1000.0
    try:
        writer.close()
        await writer.wait_closed()
    except OSError:
        pass
    return PortResult(port, "tcp", PortState.OPEN.value, "syn-ack", round(rtt, 2))


async def probe_retry(ip: str, port: int, timeout: float, retries: int) -> PortResult:
    result = await probe(ip, port, timeout)
    attempt = 0
    while result.state == PortState.FILTERED.value and attempt < retries:
        attempt += 1
        result = await probe(ip, port, timeout)
    if attempt:
        result.reason = f"{result.reason} ({attempt + 1} attempts)"
    return result


async def ping(ip: str, ports: tuple[int, ...], timeout: float) -> tuple[bool, str, float | None]:
    async def attempt(port: int) -> tuple[bool, float]:
        start = time.perf_counter()
        try:
            _r, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
        except (asyncio.TimeoutError, OSError):
            return False, 0.0
        rtt = (time.perf_counter() - start) * 1000.0
        try:
            w.close()
            await w.wait_closed()
        except OSError:
            pass
        return True, rtt

    tasks = [asyncio.create_task(attempt(p)) for p in ports]
    try:
        for future in asyncio.as_completed(tasks):
            alive, rtt = await future
            if alive:
                for task in tasks:
                    task.cancel()
                return True, "tcp-connect", round(rtt, 2)
    finally:
        for task in tasks:
            task.cancel()
    return False, "no-response", None


async def scan(
    ip: str,
    ports: list[int],
    *,
    timeout: float = 1.0,
    concurrency: int = 900,
    retries: int = 0,
    delay_ms: float = 0.0,
    cancel: asyncio.Event | None = None,
) -> AsyncIterator[PortResult]:
    chunk = max(concurrency * 8, 256)
    for start in range(0, len(ports), chunk):
        if cancel is not None and cancel.is_set():
            return
        batch = ports[start : start + chunk]
        sem = asyncio.Semaphore(concurrency)

        async def worker(port: int) -> PortResult | None:
            if cancel is not None and cancel.is_set():
                return None
            async with sem:
                if cancel is not None and cancel.is_set():
                    return None
                if delay_ms:
                    await asyncio.sleep(delay_ms / 1000.0)
                return await probe_retry(ip, port, timeout, retries)

        tasks = [asyncio.create_task(worker(p)) for p in batch]
        try:
            for future in asyncio.as_completed(tasks):
                result = await future
                if result is not None:
                    yield result
        finally:
            for task in tasks:
                task.cancel()
