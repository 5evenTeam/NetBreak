"""The NetBreak Textual TUI."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Static,
)

from . import __version__
from .ports import parse_ports
from .scanner import CLOSED, FILTERED, OPEN, Scanner, ScanResult


class ScanStats:
    """Mutable counters describing the current (or last) scan."""

    def __init__(self) -> None:
        self.reset(0, "")

    def reset(self, total: int, ip: str) -> None:
        self.total = total
        self.ip = ip
        self.done = 0
        self.open = 0
        self.filtered = 0
        self.started = time.perf_counter()
        self.finished_at: float | None = None

    @property
    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.perf_counter()
        return max(end - self.started, 0.0)

    @property
    def rate(self) -> float:
        return self.done / self.elapsed if self.elapsed > 0 else 0.0

    @property
    def finished(self) -> bool:
        return self.finished_at is not None


class NetBreakApp(App):
    """NetBreak - a friendly TUI port scanner for authorized recon."""

    TITLE = "NetBreak"
    SUB_TITLE = "authorized recon only"

    CSS = """
    #controls { height: auto; padding: 1 2 0 2; }
    #title { text-style: bold; color: $accent; padding-bottom: 1; }
    #host { width: 2fr; }
    #ports { width: 2fr; }
    #scan { min-width: 12; }
    #stop, #export { min-width: 10; }
    #status-bar { height: auto; padding: 1 2 0 2; }
    #stats { padding: 0 1; color: $text-muted; }
    #results { height: 1fr; padding: 0 2; border-top: solid $primary; }
    """

    BINDINGS = [
        Binding("s", "start_scan", "Scan"),
        Binding("x", "stop_scan", "Stop"),
        Binding("e", "export_results", "Export"),
        Binding("c", "toggle_closed", "Closed"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        target: str = "",
        ports_spec: str = "top100",
        timeout: float = 1.0,
        concurrency: int = 400,
    ) -> None:
        super().__init__()
        self._target = target
        self._ports_spec = ports_spec
        self._timeout = timeout
        self._concurrency = concurrency
        self._cancel = asyncio.Event()
        self._results: list[ScanResult] = []
        self._hide_closed = True
        self._scanning = False
        self.stats = ScanStats()

    class PortFound(Message):
        """Posted once per finished port probe."""

        def __init__(self, result: ScanResult) -> None:
            self.result = result
            super().__init__()

    class ScanFinished(Message):
        """Posted when a scan completes or is stopped."""

        def __init__(self, cancelled: bool = False) -> None:
            self.cancelled = cancelled
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="controls"):
            yield Label(f"NetBreak v{__version__} - TCP connect scanner", id="title")
            with Horizontal():
                yield Input(
                    placeholder="target host or IP - e.g. 192.168.1.10 or vpn.example.com",
                    value=self._target,
                    id="host",
                )
                yield Input(
                    placeholder="ports - top100 | full | 1-1000 | 22,80,443",
                    value=self._ports_spec,
                    id="ports",
                )
            with Horizontal():
                yield Button("Scan", variant="primary", id="scan")
                yield Button("Stop", id="stop", disabled=True)
                yield Button("Export", id="export")
                yield Checkbox("Hide closed", value=self._hide_closed, id="hide-closed")
        with Vertical(id="status-bar"):
            yield ProgressBar(total=100, show_eta=False, id="progress")
            yield Static("Ready - enter a target and press Scan.", id="stats")
        yield DataTable(id="results")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Port", key="port")
        table.add_column("State", key="state")
        table.add_column("Service", key="service")
        table.add_column("Latency", key="latency")
        table.add_column("Detail", key="note")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.set_interval(0.35, self._refresh_status)
        if self._target:
            self.query_one("#ports", Input).focus()
        else:
            self.query_one("#host", Input).focus()

    # ---- buttons -----------------------------------------------------------

    @on(Button.Pressed, "#scan")
    def _pressed_scan(self) -> None:
        self.action_start_scan()

    @on(Button.Pressed, "#stop")
    def _pressed_stop(self) -> None:
        self.action_stop_scan()

    @on(Button.Pressed, "#export")
    def _pressed_export(self) -> None:
        self.action_export_results()

    @on(Checkbox.Changed, "#hide-closed")
    def _hide_closed_changed(self, event: Checkbox.Changed) -> None:
        self._hide_closed = event.value
        self._rebuild_table()

    # ---- actions -----------------------------------------------------------

    def action_start_scan(self) -> None:
        if self._scanning:
            self.notify("A scan is already running", severity="warning")
            return
        host = self.query_one("#host", Input).value.strip()
        spec = self.query_one("#ports", Input).value.strip() or "top100"
        if not host:
            self.notify("Enter a target host or IP first", severity="error")
            return
        try:
            ports = parse_ports(spec)
        except ValueError as exc:
            self.notify(f"Bad port spec: {exc}", severity="error")
            return

        self._results.clear()
        self._cancel = asyncio.Event()
        self.stats.reset(len(ports), ip="")
        self._scanning = True
        self.query_one(DataTable).clear()
        self.query_one("#scan", Button).disabled = True
        self.query_one("#stop", Button).disabled = False
        self.query_one(ProgressBar).update(total=len(ports), progress=0)
        self._refresh_status()
        self._run_scan(host, ports)

    def action_stop_scan(self) -> None:
        if not self._scanning:
            return
        self._cancel.set()
        self.query_one("#stop", Button).disabled = True
        self.notify("Stopping - waiting for in-flight probes to finish...")

    def action_toggle_closed(self) -> None:
        checkbox = self.query_one("#hide-closed", Checkbox)
        checkbox.value = not checkbox.value  # triggers the Changed handler

    def action_export_results(self) -> None:
        if not self._results:
            self.notify("Nothing to export yet - run a scan first", severity="warning")
            return
        host = self.query_one("#host", Input).value.strip() or "target"
        safe_host = "".join(c if c.isalnum() or c in ".-_" else "_" for c in host)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path.cwd() / f"netbreak_{safe_host}_{stamp}.json"
        payload = {
            "tool": "netbreak",
            "version": __version__,
            "target": host,
            "resolved_ip": self.stats.ip,
            "elapsed_seconds": round(self.stats.elapsed, 2),
            "ports_probed": self.stats.done,
            "open_ports": self.stats.open,
            "results": [asdict(r) for r in sorted(self._results, key=lambda r: r.port)],
        }
        try:
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            self.notify(f"Export failed: {exc}", severity="error")
            return
        self.notify(f"Saved {len(self._results)} results to {path}")

    # ---- scanning ----------------------------------------------------------

    @work(exclusive=True, group="netbreak-scan")
    async def _run_scan(self, host: str, ports: list[int]) -> None:
        cancelled = False
        try:
            # Resolution can block; keep it off the UI loop.
            scanner = await asyncio.to_thread(
                Scanner,
                host,
                ports,
                timeout=self._timeout,
                concurrency=self._concurrency,
            )
        except (OSError, ValueError) as exc:
            self.stats.finished_at = time.perf_counter()
            self.notify(f"Could not scan {host}: {exc}", severity="error", timeout=8)
            self.post_message(self.ScanFinished())
            return

        self.stats.ip = scanner.ip
        try:
            async for result in scanner.scan(self._cancel):
                self.stats.done += 1
                if result.state == OPEN:
                    self.stats.open += 1
                elif result.state == FILTERED:
                    self.stats.filtered += 1
                self._results.append(result)
                self.post_message(self.PortFound(result))
            cancelled = self._cancel.is_set()
        except asyncio.CancelledError:
            cancelled = True
        except Exception as exc:  # unexpected engine error - surface it, don't crash
            self.notify(f"Scan error: {exc}", severity="error", timeout=8)
        finally:
            self.stats.finished_at = time.perf_counter()
            self.post_message(self.ScanFinished(cancelled))

    @on(PortFound)
    def _port_found(self, event: PortFound) -> None:
        if not (self._hide_closed and event.result.state == CLOSED):
            self._add_row(event.result)

    @on(ScanFinished)
    def _scan_finished(self, event: ScanFinished) -> None:
        self._scanning = False
        self.query_one("#scan", Button).disabled = False
        self.query_one("#stop", Button).disabled = True
        if self.stats.total:
            self.query_one(ProgressBar).update(progress=self.stats.total)
        try:
            self.query_one(DataTable).sort("port")
        except Exception:
            pass
        if event.cancelled:
            self.notify(
                f"Stopped - {self.stats.open} open of {self.stats.done} probed",
                severity="warning",
            )
        else:
            self.notify(
                f"Done - {self.stats.open} open port(s) in {self.stats.elapsed:.1f}s"
            )

    # ---- helpers -----------------------------------------------------------

    def _add_row(self, result: ScanResult) -> None:
        latency = f"{result.latency_ms:.1f}" if result.latency_ms is not None else "-"
        self.query_one(DataTable).add_row(
            str(result.port),
            result.state,
            result.service or "-",
            latency,
            result.note or "",
            key=f"port-{result.port}",
        )

    def _rebuild_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for result in sorted(self._results, key=lambda r: r.port):
            if not (self._hide_closed and result.state == CLOSED):
                self._add_row(result)

    def _refresh_status(self) -> None:
        stats = self.stats
        if stats.total:
            self.query_one(ProgressBar).update(
                progress=min(stats.done, stats.total)
            )
            line = (
                f"probed [bold]{stats.done}/{stats.total}[/] "
                f"- [bold green]{stats.open} open[/] "
                f"- {stats.filtered} filtered "
                f"- {stats.rate:.0f} ports/s "
                f"- {stats.elapsed:.1f}s"
            )
            if stats.ip:
                line += f" - target [bold]{stats.ip}[/]"
            if self._scanning and self._cancel.is_set():
                line = "[yellow]stopping...[/] " + line
        elif self._scanning:
            line = "resolving target..."
        else:
            line = "Ready - enter a target and press Scan."
        self.query_one("#stats", Static).update(line)
