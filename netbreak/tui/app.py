from __future__ import annotations

import time
from datetime import datetime

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    ProgressBar,
    RichLog,
    Select,
    Static,
    Switch,
)

from .. import __version__, output
from .. import ports as portlib
from .. import timing as timinglib
from ..core.backends import find as find_engines
from ..core.engine import ScanEngine
from ..core.events import HostUp, PortDiscovered, ScanFinished, ScanStarted, WarningRaised
from ..core.models import HostResult, PortResult, ScanOptions

TIMING_CHOICES = [
    (f"{name} {timinglib.TEMPLATES[name].name}", name) for name in sorted(timinglib.TEMPLATES)
]
STATE_COLOURS = {
    "open": "green",
    "closed": "grey50",
    "filtered": "yellow",
    "open|filtered": "dark_orange",
    "unknown": "white",
}
TABLE_COLUMNS = ("host", "port", "proto", "state", "service", "version", "rtt", "reason")


class NetBreakApp(App[None]):
    CSS = """
    Screen {
        background: #0b0f14;
        color: #c8d6e5;
    }
    Header {
        background: #101820;
        color: #7bed9f;
    }
    Footer {
        background: #101820;
        color: #8395a7;
    }
    #toolbar {
        height: auto;
        padding: 0 1;
        background: #0b0f14;
    }
    #row-inputs, #row-options, #row-actions {
        height: auto;
        padding: 0;
    }
    #target {
        width: 3fr;
    }
    #ports {
        width: 2fr;
    }
    #udp-ports {
        width: 2fr;
    }
    #timing {
        width: 18;
    }
    #row-options Switch {
        margin: 0 1 0 0;
    }
    .optlabel {
        margin: 1 2 0 0;
        color: #8395a7;
    }
    #status {
        height: 1;
        padding: 0 1;
        color: #7bed9f;
        background: #101820;
    }
    #results {
        height: 1fr;
        background: #0b0f14;
        color: #c8d6e5;
    }
    #log {
        height: 12;
        background: #0b0f14;
        border-top: solid #1f2a35;
    }
    Button {
        margin: 0 1 0 0;
    }
    """

    BINDINGS = [
        ("s", "scan", "Scan"),
        ("x", "stop", "Stop"),
        ("c", "clear", "Clear"),
        ("e", "export", "Export"),
        ("v", "toggle_version", "Version"),
        ("o", "toggle_os", "OS"),
        ("u", "toggle_udp", "UDP"),
        ("q", "quit", "Quit"),
    ]

    TITLE = f"NetBreak {__version__}"
    SUB_TITLE = "TCP and UDP port scanner"

    def __init__(self) -> None:
        super().__init__()
        self.engines = find_engines()
        self.engine: ScanEngine | None = None
        self.hosts: list[HostResult] = []
        self.probed = 0
        self.total = 0
        self.open_count = 0
        self.started_at = 0.0
        self.running = False
        self.row_keys: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="toolbar"):
            with Horizontal(id="row-inputs"):
                yield Input(value="127.0.0.1", placeholder="target", id="target")
                yield Input(value="top100", placeholder="tcp ports", id="ports")
                yield Input(value="", placeholder="udp ports", id="udp-ports")
                yield Select(TIMING_CHOICES, value=timinglib.DEFAULT_TEMPLATE, allow_blank=False, id="timing")
            with Horizontal(id="row-options"):
                yield Switch(value=False, id="version-detect")
                yield Static("version detect", classes="optlabel")
                yield Switch(value=False, id="os-detect")
                yield Static("os detect", classes="optlabel")
                yield Switch(value=False, id="udp-enabled")
                yield Static("udp ports", classes="optlabel")
                yield Switch(value=False, id="skip-ping")
                yield Static("skip ping", classes="optlabel")
                yield Switch(value=False, id="show-all")
                yield Static("show all ports", classes="optlabel")
            with Horizontal(id="row-actions"):
                yield Button("Scan", id="scan", variant="success")
                yield Button("Stop", id="stop", variant="error")
                yield Button("Clear", id="clear")
                yield Button("Export JSON", id="export")
        yield ProgressBar(total=100, show_eta=False, id="progress")
        yield Static("idle", id="status")
        yield DataTable(id="results", zebra_stripes=True, cursor_type="row")
        yield RichLog(id="log", highlight=False, markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        for column in TABLE_COLUMNS:
            table.add_column(column, key=column)
        self.log_line(f"NetBreak {__version__} ready, engines: {self.engines.describe()}")
        self.log_line("s scans, x stops, c clears, e exports JSON, v/o/u toggle options")

    def log_line(self, message: str, style: str = "") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        text = f"[grey50]{stamp}[/grey50] {message}"
        if style:
            text = f"[{style}]{text}[/{style}]"
        self.query_one("#log", RichLog).write(text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "scan": self.action_scan,
            "stop": self.action_stop,
            "clear": self.action_clear,
            "export": self.action_export,
        }
        handler = mapping.get(event.button.id or "")
        if handler is not None:
            handler()

    def action_scan(self) -> None:
        if self.running:
            self.log_line("a scan is already running", "yellow")
            return
        options = self.build_options()
        if options is None:
            return
        self.query_one("#results", DataTable).clear()
        self.row_keys.clear()
        self.hosts = []
        self.probed = 0
        self.total = 0
        self.open_count = 0
        self.running = True
        self.run_scan(options)

    @work(exclusive=True, group="scan")
    async def run_scan(self, options: ScanOptions) -> None:
        engine = ScanEngine(options, self.engines)
        self.engine = engine
        self.started_at = time.perf_counter()
        self.log_line(
            f"scanning {', '.join(options.targets)} ports={options.ports.summary()} "
            f"engine={engine.engine_name} timing={options.timing}"
        )
        self.refresh_status()
        try:
            async for event in engine.run():
                if isinstance(event, ScanStarted):
                    self.total = event.ports
                    self.log_line(f"started: {len(event.hosts)} host(s), {event.ports} probes")
                elif isinstance(event, HostUp) and event.host is not None:
                    self.log_line(f"host up {event.host.label()} ({event.host.reason})", "green")
                elif isinstance(event, PortDiscovered) and event.port is not None:
                    self.probed += 1
                    if event.updated:
                        self.update_row(event)
                    else:
                        self.add_row(event)
                    self.refresh_status()
                elif isinstance(event, WarningRaised):
                    self.log_line(f"warning: {event.message}", "yellow")
                elif isinstance(event, ScanFinished):
                    self.hosts = event.hosts
                    state = "cancelled" if event.cancelled else "finished"
                    self.log_line(
                        f"{state} in {event.elapsed:.2f}s, {len(event.hosts)} host(s), "
                        f"{sum(len(h.open_ports) for h in event.hosts)} open port(s)",
                        "green",
                    )
        finally:
            self.running = False
            self.refresh_status()

    def build_options(self) -> ScanOptions | None:
        target = self.query_one("#target", Input).value.strip()
        if not target:
            self.log_line("no target given", "red")
            return None
        ports_text = self.query_one("#ports", Input).value.strip() or "top100"
        udp_text = self.query_one("#udp-ports", Input).value.strip()
        try:
            spec = portlib.parse(ports_text, udp=udp_text or None)
        except ValueError as exc:
            self.log_line(f"bad port specification: {exc}", "red")
            return None
        template = timinglib.get(str(self.query_one("#timing", Select).value))
        udp_enabled = self.query_one("#udp-enabled", Switch).value
        if udp_enabled and not spec.udp:
            spec.udp = [53, 67, 69, 123, 137, 161, 500, 1900, 5353]
        return ScanOptions(
            targets=[target],
            ports=spec,
            timeout=template.timeout,
            concurrency=template.concurrency,
            retries=template.retries,
            delay_ms=template.delay_ms,
            tcp=bool(spec.tcp),
            udp=bool(spec.udp),
            version_detect=self.query_one("#version-detect", Switch).value,
            os_detect=self.query_one("#os-detect", Switch).value,
            ping=not self.query_one("#skip-ping", Switch).value,
            resolve=True,
            engine="auto",
            ipv6=False,
            timing=template.template,
            verbosity=1,
        )

    def add_row(self, event: PortDiscovered) -> None:
        port = event.port
        if port is None:
            return
        if not port.is_open and not self.query_one("#show-all", Switch).value:
            return
        key = f"{event.address}:{port.port}:{port.protocol}"
        if key in self.row_keys:
            self.update_row(event)
            return
        table = self.query_one("#results", DataTable)
        table.add_row(
            event.address,
            str(port.port),
            port.protocol,
            self.state_text(port),
            port.service or "",
            port.version_string or self.banner_hint(port),
            self.rtt_text(port),
            port.reason or "",
            key=key,
        )
        self.row_keys.add(key)

    def update_row(self, event: PortDiscovered) -> None:
        port = event.port
        if port is None:
            return
        key = f"{event.address}:{port.port}:{port.protocol}"
        if key not in self.row_keys:
            self.add_row(event)
            return
        table = self.query_one("#results", DataTable)
        try:
            table.update_cell(key, "state", self.state_text(port))
            table.update_cell(key, "service", port.service or "")
            table.update_cell(key, "version", port.version_string or self.banner_hint(port))
            table.update_cell(key, "rtt", self.rtt_text(port))
            table.update_cell(key, "reason", port.reason or "")
        except Exception as exc:
            self.log_line(f"cannot update row {key}: {exc}", "yellow")

    def state_text(self, port: PortResult) -> str:
        colour = STATE_COLOURS.get(port.state, "white")
        return f"[{colour}]{port.state}[/{colour}]"

    def rtt_text(self, port: PortResult) -> str:
        return f"{port.rtt_ms:.2f}" if port.rtt_ms is not None else ""

    def banner_hint(self, port: PortResult) -> str:
        if not port.banner:
            return ""
        return port.banner.splitlines()[0][:48]

    def refresh_status(self) -> None:
        elapsed = time.perf_counter() - self.started_at if self.started_at else 0.0
        rate = self.probed / elapsed if elapsed > 1e-6 else 0.0
        state = "scanning" if self.running else "idle"
        self.query_one("#status", Static).update(
            f"{state} | probed {self.probed}/{self.total} | open {self.open_count} | "
            f"hosts {len(self.hosts) if self.hosts else 0} | {elapsed:.1f}s | {rate:.0f} probes/s"
        )
        bar = self.query_one("#progress", ProgressBar)
        span = max(self.total, 1)
        bar.update(total=span, progress=min(self.probed, span))

    def action_stop(self) -> None:
        if self.engine is not None and self.running:
            self.engine.cancel()
            self.log_line("stop requested", "yellow")
        else:
            self.log_line("nothing to stop")

    def action_clear(self) -> None:
        self.query_one("#results", DataTable).clear()
        self.row_keys.clear()
        self.hosts = []
        self.probed = 0
        self.total = 0
        self.open_count = 0
        self.started_at = 0.0
        self.refresh_status()
        self.log_line("cleared")

    def action_export(self) -> None:
        if not self.hosts:
            self.log_line("nothing to export yet", "yellow")
            return
        options = self.build_options()
        if options is None:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"netbreak_tui_{stamp}"
        try:
            written = output.write("json", f"{base}.json", self.hosts, options, self.elapsed())
            written_normal = output.write("normal", f"{base}.txt", self.hosts, options, self.elapsed())
        except OSError as exc:
            self.log_line(f"export failed: {exc}", "red")
            return
        self.log_line(f"exported {written}", "green")
        self.log_line(f"exported {written_normal}", "green")

    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at if self.started_at else 0.0

    def action_toggle_version(self) -> None:
        switch = self.query_one("#version-detect", Switch)
        switch.value = not switch.value

    def action_toggle_os(self) -> None:
        switch = self.query_one("#os-detect", Switch)
        switch.value = not switch.value

    def action_toggle_udp(self) -> None:
        switch = self.query_one("#udp-enabled", Switch)
        switch.value = not switch.value


def main() -> int:
    NetBreakApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
