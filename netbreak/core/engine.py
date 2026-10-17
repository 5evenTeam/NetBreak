from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import AsyncIterator

from .. import targets as targetlib
from ..ports import service_for
from . import connect, discovery, osdetect, udp, versions
from .backends import Engines
from .backends import find as find_engines
from .events import (
    Event,
    HostFinished,
    HostUp,
    PortDiscovered,
    ScanFinished,
    ScanStarted,
    WarningRaised,
)
from .models import HostResult, HostState, PortResult, ScanOptions


@dataclass
class HostRef:
    target: str
    address: str
    hostname: str | None = None


def _spec_text(ports: list[int]) -> str:
    if not ports:
        return ""
    ordered = sorted(ports)
    chunks: list[str] = []
    start = previous = ordered[0]
    for port in ordered[1:]:
        if port == previous + 1:
            previous = port
            continue
        chunks.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = port
    chunks.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(chunks)


class ScanEngine:
    def __init__(self, options: ScanOptions, engines: Engines | None = None) -> None:
        self.options = options
        self.engines = engines or find_engines()
        self.hosts: list[HostResult] = []
        self.warnings: list[str] = []
        self.elapsed = 0.0
        self.engine_name = self._pick_engine()
        self.cancelled = False
        self._cancel = asyncio.Event()
        self._probed = 0
        self._total = 0

    def _pick_engine(self) -> str:
        requested = (self.options.engine or "auto").strip().lower()
        available = self.engines
        if requested in ("auto", ""):
            return available.best()
        if requested == "go":
            return "go" if available.go else "python"
        if requested in ("cpp", "c++", "native"):
            return "cpp" if available.native else "python"
        if requested == "python":
            return "python"
        return available.best()

    def cancel(self) -> None:
        self._cancel.set()
        self.cancelled = True

    @property
    def progress(self) -> tuple[int, int]:
        return self._probed, self._total

    async def _resolve_all(self) -> list[HostRef]:
        options = self.options
        names = targetlib.expand(options.targets, ipv6=options.ipv6)
        refs: list[HostRef] = []
        for name in names:
            try:
                address = await asyncio.to_thread(targetlib.resolve, name, ipv6=options.ipv6)
            except (OSError, ValueError) as exc:
                self.warnings.append(f"skipping {name}: {exc}")
                continue
            hostname = None
            if options.resolve:
                hostname = await asyncio.to_thread(targetlib.reverse_name, address)
            refs.append(HostRef(name, address, hostname))
        if not refs:
            raise ValueError("no targets could be resolved")
        return refs

    async def run(self) -> AsyncIterator[Event]:
        options = self.options
        started = time.perf_counter()
        try:
            refs = await self._resolve_all()
        except (ValueError, OSError) as exc:
            self.warnings.append(str(exc))
            yield WarningRaised(str(exc))
            self.elapsed = time.perf_counter() - started
            yield ScanFinished([], round(self.elapsed, 2), True)
            return

        self._total = len(refs) * max(options.port_count(), 1)
        yield ScanStarted([ref.address for ref in refs], self._total, self.engine_name)

        for warning in self.warnings:
            yield WarningRaised(warning)
        self.warnings.clear()

        for ref in refs:
            if self._cancel.is_set():
                break
            async for event in self._scan_host(ref):
                yield event
            for warning in self.warnings:
                yield WarningRaised(warning)
            self.warnings.clear()

        self.elapsed = time.perf_counter() - started
        yield ScanFinished(self.hosts, round(self.elapsed, 2), self._cancel.is_set())

    async def _scan_host(self, ref: HostRef) -> AsyncIterator[Event]:
        options = self.options
        host = HostResult(
            target=ref.target,
            address=ref.address,
            hostname=ref.hostname,
            engine=self.engine_name,
        )

        if options.ping:
            state, reason, rtt, ttl = await discovery.discover(
                ref.address,
                timeout=options.timeout,
                native_binary=self.engines.native,
            )
            host.state, host.reason, host.rtt_ms, host.ttl = state, reason, rtt, ttl
        else:
            host.state, host.reason = HostState.UP.value, "user-set"

        if host.state != HostState.UP.value:
            self.hosts.append(host)
            yield HostFinished(host)
            return

        yield HostUp(host)

        if options.tcp and options.ports.tcp:
            async for result in self._scan_tcp(ref.address):
                host.ports.append(result)
                yield PortDiscovered(ref.address, result)

        if options.udp and options.ports.udp:
            async for result in self._scan_udp(ref.address):
                host.ports.append(result)
                yield PortDiscovered(ref.address, result)

        if options.version_detect:
            async for event in self._detect_versions(host, ref.address):
                yield event

        if options.os_detect:
            if host.ttl is None:
                alive, ttl, _rtt = await asyncio.to_thread(
                    discovery._system_ping, ref.address, max(options.timeout, 1.0)
                )
                if alive:
                    host.ttl = ttl
            host.os_guess = osdetect.guess(host.ttl, host.ports)

        host.ports.sort(key=lambda p: (p.port, p.protocol))
        self.hosts.append(host)
        yield HostFinished(host)

    async def _scan_tcp(self, address: str) -> AsyncIterator[PortResult]:
        options = self.options
        if self.engine_name == "go" and self.engines.go:
            produced = 0
            async for result in self._external_scan(
                self.engines.go,
                ["scan", "-host", address, "-p", _spec_text(options.ports.tcp)],
                result_protocol="tcp",
            ):
                produced += 1
                yield result
            if produced:
                return
            self.warnings.append("go engine returned nothing, falling back to python engine")
            self.engine_name = "python"
        elif self.engine_name == "cpp" and self.engines.native:
            produced = 0
            async for result in self._external_scan(
                self.engines.native,
                ["connect", address, _spec_text(options.ports.tcp)],
                result_protocol="tcp",
            ):
                produced += 1
                yield result
            if produced:
                return
            self.warnings.append("native engine returned nothing, falling back to python engine")
            self.engine_name = "python"

        async for result in connect.scan(
            address,
            options.ports.tcp,
            timeout=options.timeout,
            concurrency=options.concurrency,
            retries=options.retries,
            delay_ms=options.delay_ms,
            cancel=self._cancel,
        ):
            result.service = result.service or service_for(result.port, "tcp")
            self._probed += 1
            yield result

    async def _external_scan(
        self,
        binary: str,
        arguments: list[str],
        result_protocol: str,
    ) -> AsyncIterator[PortResult]:
        options = self.options
        command = [
            binary,
            *arguments,
            "-timeout",
            str(options.timeout),
            "-concurrency",
            str(options.concurrency),
            "-retries",
            str(options.retries),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            self.warnings.append(f"cannot launch {binary}: {exc}")
            return
        try:
            assert process.stdout is not None
            while True:
                if self._cancel.is_set():
                    process.kill()
                    break
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace").strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except ValueError:
                    continue
                kind = payload.get("event", "port")
                if kind == "error":
                    self.warnings.append(str(payload.get("message", "engine error")))
                    continue
                if kind == "progress":
                    continue
                port = payload.get("port")
                if port is None:
                    continue
                result = PortResult(
                    int(port),
                    payload.get("proto", result_protocol),
                    payload.get("state", "unknown"),
                    payload.get("reason", ""),
                    payload.get("rtt_ms"),
                    service_for(int(port), payload.get("proto", result_protocol)),
                )
                self._probed += 1
                yield result
            await process.wait()
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    async def _scan_udp(self, address: str) -> AsyncIterator[PortResult]:
        options = self.options
        if self.engine_name == "go" and self.engines.go:
            produced = 0
            async for result in self._external_scan(
                self.engines.go,
                ["udpscan", "-host", address, "-p", _spec_text(options.ports.udp)],
                result_protocol="udp",
            ):
                produced += 1
                yield result
            if produced:
                return
            self.warnings.append("go engine returned nothing for udp, falling back to python engine")
        async for result in udp.scan(
            address,
            options.ports.udp,
            timeout=max(options.timeout * 2, 2.0),
            cancel=self._cancel,
        ):
            result.service = result.service or service_for(result.port, "udp")
            self._probed += 1
            yield result

    async def _detect_versions(self, host: HostResult, address: str) -> AsyncIterator[Event]:
        open_ports = [p for p in host.ports if p.is_open]
        if not open_ports:
            return
        timeout = max(self.options.timeout * 2.0, 3.0)
        sem = asyncio.Semaphore(min(16, len(open_ports)))

        async def worker(result: PortResult) -> PortResult:
            async with sem:
                if self._cancel.is_set():
                    return result
                detection = await versions.detect(address, result.port, timeout=timeout)
                versions.apply(detection, result)
                if not result.service:
                    result.service = service_for(result.port, result.protocol)
                return result

        tasks = [asyncio.create_task(worker(p)) for p in open_ports]
        try:
            for future in asyncio.as_completed(tasks):
                result = await future
                yield PortDiscovered(address, result, updated=True)
        finally:
            for task in tasks:
                task.cancel()
