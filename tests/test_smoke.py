"""Smoke tests for NetBreak: parser, scanner, and TUI boot."""

import asyncio

import pytest

from netbreak.app import NetBreakApp
from netbreak.ports import parse_ports
from netbreak.scanner import OPEN, Scanner


def test_parse_ports_preset():
    ports = parse_ports("top100")
    assert 22 in ports and 80 in ports and 443 in ports
    assert len(ports) == len(set(ports))  # de-duplicated
    assert ports == sorted(ports)


def test_parse_ports_mixed_spec():
    assert parse_ports("22,80,443,1000-1002") == [22, 80, 443, 1000, 1001, 1002]
    assert parse_ports("1002-1000") == [1000, 1001, 1002]  # reversed range


def test_parse_ports_rejects_bad_input():
    for spec in ("", "not-a-port", "0", "70000", "1-70000"):
        with pytest.raises(ValueError):
            parse_ports(spec)


def test_scanner_detects_local_listener():
    """Open a local listener and confirm the scanner classifies it as open."""

    async def scenario():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            scanner = Scanner("127.0.0.1", [port], timeout=2.0, concurrency=4)
            return [r async for r in scanner.scan()][0]
        finally:
            server.close()
            await server.wait_closed()

    result = asyncio.run(scenario())
    assert result.state == OPEN


def test_scanner_marks_refused_port_closed():
    """A port with nothing listening must not be reported as open.

    Note: some hosts/firewalls silently drop loopback connection attempts
    instead of refusing them, so we accept either verdict here.
    """
    from netbreak.scanner import CLOSED, FILTERED, scan_port

    async def scenario():
        # Grab an ephemeral port, then close it so nothing is listening.
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        server.close()
        await server.wait_closed()
        return await scan_port("127.0.0.1", port, timeout=2.0)

    assert asyncio.run(scenario()).state in (CLOSED, FILTERED)


def test_tui_boots_and_completes_scan():
    """Drive the TUI headlessly: press Scan, wait for completion."""

    async def scenario():
        app = NetBreakApp(target="127.0.0.1", ports_spec="1-32")
        async with app.run_test(size=(110, 40)) as pilot:
            # Click rather than press "s": focus starts in an input, where
            # letter keys are typed as text.
            await pilot.click("#scan")
            for _ in range(120):  # up to 30s
                await asyncio.sleep(0.25)
                if app.stats.finished:
                    break
            assert app.stats.finished, "scan did not finish in time"
            assert app.stats.done == 32
            assert app.stats.ip == "127.0.0.1"

    asyncio.run(scenario())
