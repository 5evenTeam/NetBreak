from __future__ import annotations

import time

import pytest

tk = pytest.importorskip("tkinter")

from netbreak.desktop.app import NetBreakDesktop


def _root_or_skip() -> tk.Tk:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display available for Tk: {exc}")
    root.withdraw()
    return root


def test_desktop_window_builds():
    root = _root_or_skip()
    try:
        app = NetBreakDesktop(root)
        app.build()
        root.update()
        assert app.target_var.get() == "127.0.0.1"
        assert app.ports_var.get() == "top100"
    finally:
        root.destroy()


def test_desktop_scan_reports_open_port(tcp_listener):
    _server, port = tcp_listener
    root = _root_or_skip()
    try:
        app = NetBreakDesktop(root)
        app.build()
        app.target_var.set("127.0.0.1")
        app.ports_var.set(str(port))
        app.start_scan()
        deadline = time.time() + 20.0
        while time.time() < deadline:
            root.update()
            row = app._rows.get(f"127.0.0.1:{port}:tcp")
            if row is not None and row.is_open:
                break
            time.sleep(0.02)
        row = app._rows.get(f"127.0.0.1:{port}:tcp")
        assert row is not None
        assert row.is_open
        assert row.state == "open"
    finally:
        root.destroy()
