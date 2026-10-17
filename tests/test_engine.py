from __future__ import annotations

import asyncio

import pytest

from netbreak.core import versions
from netbreak.core.backends import find as find_engines
from netbreak.core.engine import ScanEngine
from netbreak.core.events import PortDiscovered, ScanFinished, ScanStarted
from netbreak.core.models import ScanOptions
from netbreak.ports import PortSpec


def _options(port: int, **overrides) -> ScanOptions:
    values = dict(
        targets=["127.0.0.1"],
        ports=PortSpec(tcp=[port]),
        ping=False,
        engine="python",
        timeout=0.5,
        concurrency=50,
        retries=0,
        resolve=False,
    )
    values.update(overrides)
    return ScanOptions(**values)


async def _collect(engine: ScanEngine) -> ScanFinished | None:
    finished = None
    async for event in engine.run():
        if isinstance(event, ScanStarted):
            assert event.engine
            assert isinstance(event.hosts, list)
        if isinstance(event, ScanFinished):
            finished = event
    return finished


def test_open_port_is_detected(tcp_listener):
    _server, port = tcp_listener
    engine = ScanEngine(_options(port))
    finished = asyncio.run(_collect(engine))
    assert finished is not None
    assert finished.hosts
    host = engine.hosts[0]
    assert host.state == "up"
    assert [p.port for p in host.open_ports] == [port]
    assert host.ports[0].protocol == "tcp"
    assert host.ports[0].state == "open"


def test_unused_port_reports_closed_or_filtered():
    import socket

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    engine = ScanEngine(_options(port))
    asyncio.run(_collect(engine))
    assert engine.hosts[0].ports[0].state in ("closed", "filtered")


def test_ping_only_scan_has_no_ports():
    options = ScanOptions(
        targets=["127.0.0.1"],
        ports=PortSpec(),
        ping=False,
        tcp=False,
        udp=False,
        engine="python",
        resolve=False,
    )
    engine = ScanEngine(options)
    asyncio.run(_collect(engine))
    host = engine.hosts[0]
    assert host.state == "up"
    assert host.ports == []


def test_cancellation_is_recorded():
    options = ScanOptions(
        targets=["127.0.0.1"],
        ports=PortSpec(tcp=list(range(1, 401))),
        ping=False,
        engine="python",
        timeout=0.5,
        concurrency=20,
        retries=0,
        resolve=False,
    )
    engine = ScanEngine(options)

    async def run():
        async for event in engine.run():
            if isinstance(event, PortDiscovered):
                engine.cancel()

    asyncio.run(run())
    assert engine.cancelled


def test_go_engine_agrees_with_python(tcp_listener):
    engines = find_engines()
    if not engines.go:
        pytest.skip("go engine binary not built")
    _server, port = tcp_listener
    engine = ScanEngine(_options(port, engine="go"))
    asyncio.run(_collect(engine))
    assert engine.engine_name == "go"
    assert [p.port for p in engine.hosts[0].open_ports] == [port]


def test_native_engine_agrees_with_python(tcp_listener):
    engines = find_engines()
    if not engines.native:
        pytest.skip("native engine binary not built")
    _server, port = tcp_listener
    engine = ScanEngine(_options(port, engine="cpp"))
    asyncio.run(_collect(engine))
    assert engine.engine_name == "cpp"
    assert [p.port for p in engine.hosts[0].open_ports] == [port]


def test_version_detection_on_http_stub(http_stub):
    _server, port = http_stub
    detection = asyncio.run(versions.detect("127.0.0.1", port, timeout=2.0))
    assert detection.service == "http"
    assert detection.product is not None
    assert "nginx" in detection.product
    assert detection.version == "1.25.3"


def test_version_detection_fills_port_result(http_stub):
    _server, port = http_stub
    engine = ScanEngine(_options(port, version_detect=True))
    asyncio.run(_collect(engine))
    result = engine.hosts[0].ports[0]
    assert result.is_open
    assert result.product is not None
    assert "nginx" in result.product
