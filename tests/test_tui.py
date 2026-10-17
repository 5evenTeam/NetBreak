from __future__ import annotations

import json
from datetime import datetime

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Input, RichLog, Select, Switch

from netbreak.tui.app import TABLE_COLUMNS, NetBreakApp


async def _scenario():
    app = NetBreakApp()
    async with app.run_test() as pilot:
        table = app.query_one("#results", DataTable)
        assert len(table.columns) == len(TABLE_COLUMNS)
        app.query_one("#timing", Select).value = "T5"
        app.query_one("#ports", Input).value = "1"
        app.action_scan()
        await pilot.pause(3.0)
        app.action_stop()
        await pilot.pause(0.2)
        log = app.query_one("#log", RichLog)
        assert log is not None
        assert app.engine is not None


def test_tui_builds_and_runs_a_scan():
    import asyncio

    asyncio.run(_scenario())


async def _toggle_scenario():
    app = NetBreakApp()
    async with app.run_test() as pilot:
        switch = app.query_one("#version-detect", Switch)
        assert switch.value is False
        app.action_toggle_version()
        await pilot.pause(0.1)
        assert switch.value is True
        app.action_clear()
        await pilot.pause(0.1)
        assert app.row_keys == set()


def test_tui_actions_toggle_and_clear():
    import asyncio

    asyncio.run(_toggle_scenario())


async def _export_scenario(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = NetBreakApp()
    async with app.run_test() as pilot:
        from netbreak.core.models import HostResult, PortResult
        from netbreak.ports import PortSpec

        app.hosts = [
            HostResult(
                "127.0.0.1",
                "127.0.0.1",
                None,
                "up",
                "user-set",
                None,
                None,
                [PortResult(80, "tcp", "open", "syn-ack", 0.5, "http")],
                0.5,
                "python",
            )
        ]
        app.query_one("#ports", Input).value = "80"
        app.action_export()
        await pilot.pause(0.1)


def test_tui_export_writes_json(tmp_path, monkeypatch):
    import asyncio

    asyncio.run(_export_scenario(tmp_path, monkeypatch))
    files = sorted(tmp_path.glob("netbreak_tui_*.json"))
    assert files
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["hosts"][0]["ports"][0]["port"] == 80
    assert datetime.now().year >= 2024
