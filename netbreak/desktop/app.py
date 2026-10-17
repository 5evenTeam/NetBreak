from __future__ import annotations

import asyncio
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable

from ..core.backends import Engines
from ..core.backends import find as find_engines
from ..core.engine import ScanEngine
from ..core.events import (
    Event,
    HostFinished,
    HostUp,
    PortDiscovered,
    ScanFinished,
    ScanStarted,
    WarningRaised,
)
from ..core.models import HostResult, PortResult, ScanOptions
from ..output import EXTENSIONS, write
from ..ports import parse
from ..timing import get as get_timing

BG = "#0b0f14"
PANEL = "#111820"
BORDER = "#1f2a37"
FG = "#c9d1d9"
GREEN = "#3ddc84"
CYAN = "#22d3ee"
YELLOW = "#f5d90a"
RED = "#ff6b6b"
DIM = "#5c6773"

TIMING_NAMES = ("T0", "T1", "T2", "T3", "T4", "T5")

COLUMNS = (
    ("host", "host", 180, "w", True),
    ("port", "port", 60, "e", False),
    ("proto", "proto", 55, "center", False),
    ("state", "state", 80, "w", False),
    ("service", "service", 120, "w", False),
    ("version", "version", 180, "w", True),
    ("rtt", "rtt", 60, "e", False),
    ("reason", "reason", 130, "w", True),
)


def _pick_mono(root: tk.Tk) -> str:
    try:
        families = set(tkfont.families(root))
    except tk.TclError:
        families = set()
    if "Consolas" in families:
        return "Consolas"
    return "Courier New"


def _safe_name(text: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in ".-_" else "_" for c in text.strip())
    return cleaned or "target"


class NetBreakDesktop:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.mono = _pick_mono(root)
        self._engines: Engines = find_engines()
        self._queue: queue.Queue[object] = queue.Queue()
        self._lock = threading.Lock()
        self._engine: ScanEngine | None = None
        self._worker: threading.Thread | None = None
        self._scanning = False
        self._stopping = False
        self._probed = 0
        self._total = 0
        self._open_count = 0
        self._host_count = 0
        self._started_at = 0.0
        self._elapsed = 0.0
        self._options: ScanOptions | None = None
        self._hosts: list[HostResult] = []
        self._rows: dict[str, PortResult] = {}

    def build(self) -> None:
        self.root.title("NetBreak 2.0")
        self.root.configure(bg=BG)
        self.root.geometry("1020x660")
        self.root.minsize(780, 480)
        self.root.grid_rowconfigure(4, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self._configure_styles()
        self._build_header()
        self._build_inputs()
        self._build_options()
        self._build_buttons()
        self._build_table()
        self._build_log()
        self._build_status()
        self.log(f"netbreak desktop ready | engines: {self._engines.describe()}", "info")
        self._refresh_status()
        self._tick_status()

    def run(self) -> int:
        self.root.mainloop()
        return 0

    def log(self, message: str, level: str = "info") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n", level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def start_scan(self) -> None:
        if self._scanning:
            self.log("a scan is already running", "warn")
            return
        target = self.target_var.get().strip()
        if not target:
            self.log("enter a target before scanning", "error")
            return
        ports_text = self.ports_var.get().strip() or "top100"
        udp_text = self.udp_var.get().strip()
        timing_name = self.timing_var.get().strip() or "T4"
        try:
            spec = parse(ports_text, udp=udp_text or None)
        except ValueError as exc:
            self.log(f"bad port spec: {exc}", "error")
            return
        try:
            timing = get_timing(timing_name)
        except ValueError as exc:
            self.log(f"bad timing: {exc}", "error")
            return
        options = ScanOptions(
            targets=[target],
            ports=spec,
            timeout=timing.timeout,
            concurrency=timing.concurrency,
            retries=timing.retries,
            delay_ms=timing.delay_ms,
            tcp=bool(spec.tcp),
            udp=bool(spec.udp),
            version_detect=self.version_var.get(),
            os_detect=self.os_var.get(),
            ping=not self.skip_ping_var.get(),
            resolve=True,
            engine="auto",
            timing=timing.template,
        )
        self._options = options
        self._hosts = []
        self._rows.clear()
        self.tree.delete(*self.tree.get_children())
        self._queue = queue.Queue()
        self._probed = 0
        self._total = 0
        self._open_count = 0
        self._host_count = 0
        self._elapsed = 0.0
        self._started_at = time.perf_counter()
        self._scanning = True
        self._stopping = False
        self._set_running(True)
        self._refresh_status()
        self.log(
            f"scan started: {target} | ports {spec.summary()} | timing {timing.template} "
            f"({timing.name})",
            "info",
        )
        self._worker = threading.Thread(target=self._scan_worker, args=(options, self._queue))
        self._worker.daemon = True
        self._worker.start()
        self.root.after(50, self._drain)

    def stop_scan(self) -> None:
        if not self._scanning:
            return
        self._stopping = True
        with self._lock:
            engine = self._engine
        if engine is not None:
            engine.cancel()
        self.stop_button.state(["disabled"])
        self.log("stop requested; waiting for in-flight probes", "warn")

    def export(self, kind: str) -> None:
        if self._options is None:
            self.log("nothing to export; run a scan first", "warn")
            return
        target = self.target_var.get().strip() or "target"
        extension = EXTENSIONS.get(kind, "txt")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path.cwd() / f"netbreak_{_safe_name(target)}_{stamp}.{extension}"
        try:
            written = write(kind, str(path), self._hosts, self._options, self._elapsed)
        except OSError as exc:
            self.log(f"export failed: {exc}", "error")
            return
        self.log(f"exported {kind} -> {written}", "ok")

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        self._probed = 0
        self._total = 0
        self._open_count = 0
        self._host_count = 0
        self._elapsed = 0.0
        self._refresh_status()
        self.log("results cleared", "info")

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Terminal.Treeview",
            background=BG,
            fieldbackground=BG,
            foreground=FG,
            rowheight=20,
            font=(self.mono, 10),
            borderwidth=0,
        )
        style.map(
            "Terminal.Treeview",
            background=[("selected", "#12331f")],
            foreground=[("selected", GREEN)],
        )
        style.configure(
            "Terminal.Treeview.Heading",
            background=PANEL,
            foreground=CYAN,
            font=(self.mono, 10, "bold"),
            relief="flat",
        )
        style.map("Terminal.Treeview.Heading", background=[("active", "#16202b")])
        style.configure(
            "Terminal.TButton",
            background=PANEL,
            foreground=GREEN,
            font=(self.mono, 10, "bold"),
            borderwidth=1,
            focusthickness=0,
            padding=(8, 4),
        )
        style.map(
            "Terminal.TButton",
            background=[("active", "#16202b"), ("disabled", BG)],
            foreground=[("disabled", DIM)],
        )
        style.configure(
            "Terminal.TCombobox",
            fieldbackground=BG,
            background=PANEL,
            foreground=GREEN,
            arrowcolor=CYAN,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            font=(self.mono, 10),
        )
        style.map(
            "Terminal.TCombobox",
            fieldbackground=[("readonly", BG)],
            foreground=[("readonly", GREEN)],
            selectbackground=[("readonly", BG)],
            selectforeground=[("readonly", GREEN)],
        )
        style.configure(
            "Terminal.Vertical.TScrollbar",
            background=PANEL,
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=CYAN,
        )

    def _build_header(self) -> None:
        frame = tk.Frame(self.root, bg=BG)
        frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 2))
        tk.Label(
            frame,
            text="NetBreak 2.0",
            bg=BG,
            fg=CYAN,
            font=(self.mono, 16, "bold"),
        ).pack(side="left")
        self.engine_label = tk.Label(
            frame,
            text=f"engines: {self._engines.describe()}",
            bg=BG,
            fg=GREEN,
            font=(self.mono, 10),
        )
        self.engine_label.pack(side="right")

    def _build_inputs(self) -> None:
        frame = tk.Frame(self.root, bg=BG)
        frame.grid(row=1, column=0, sticky="ew", padx=10, pady=2)
        frame.grid_columnconfigure(1, weight=2)
        frame.grid_columnconfigure(3, weight=1)
        self._label(frame, "target").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.target_var = tk.StringVar(value="127.0.0.1")
        self._entry(frame, self.target_var, 24).grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self._label(frame, "ports").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.ports_var = tk.StringVar(value="top100")
        self._entry(frame, self.ports_var, 16).grid(row=0, column=3, sticky="ew", padx=(0, 12))
        self._label(frame, "timing").grid(row=0, column=4, sticky="w", padx=(0, 6))
        self.timing_var = tk.StringVar(value="T4")
        ttk.Combobox(
            frame,
            textvariable=self.timing_var,
            values=list(TIMING_NAMES),
            state="readonly",
            width=5,
            style="Terminal.TCombobox",
            font=(self.mono, 10),
        ).grid(row=0, column=5, sticky="w")

    def _build_options(self) -> None:
        frame = tk.Frame(self.root, bg=BG)
        frame.grid(row=2, column=0, sticky="ew", padx=10, pady=2)
        self.version_var = tk.BooleanVar(value=False)
        self.os_var = tk.BooleanVar(value=False)
        self.skip_ping_var = tk.BooleanVar(value=False)
        self.udp_var = tk.StringVar(value="")
        self._check(frame, "-sV version detection", self.version_var).pack(side="left")
        self._check(frame, "-O os detection", self.os_var).pack(side="left", padx=(12, 0))
        self._check(frame, "-Pn skip host discovery", self.skip_ping_var).pack(
            side="left", padx=(12, 0)
        )
        self._label(frame, "udp ports").pack(side="left", padx=(12, 6))
        entry = self._entry(frame, self.udp_var, 14)
        entry.pack(side="left")

    def _build_buttons(self) -> None:
        frame = tk.Frame(self.root, bg=BG)
        frame.grid(row=3, column=0, sticky="ew", padx=10, pady=2)
        self.scan_button = self._button(frame, "Scan", self.start_scan)
        self.scan_button.pack(side="left")
        self.stop_button = self._button(frame, "Stop", self.stop_scan)
        self.stop_button.pack(side="left", padx=(6, 0))
        self.stop_button.state(["disabled"])
        self._button(frame, "Export normal", lambda: self.export("normal")).pack(
            side="left", padx=(18, 0)
        )
        self._button(frame, "Export JSON", lambda: self.export("json")).pack(
            side="left", padx=(6, 0)
        )
        self._button(frame, "Export XML", lambda: self.export("xml")).pack(
            side="left", padx=(6, 0)
        )
        self._button(frame, "Export grepable", lambda: self.export("grep")).pack(
            side="left", padx=(6, 0)
        )
        self._button(frame, "Clear", self.clear).pack(side="left", padx=(6, 0))

    def _build_table(self) -> None:
        frame = tk.Frame(self.root, bg=BG)
        frame.grid(row=4, column=0, sticky="nsew", padx=10, pady=(6, 2))
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            frame,
            columns=[c[0] for c in COLUMNS],
            show="headings",
            style="Terminal.Treeview",
            selectmode="browse",
        )
        for cid, title, width, anchor, stretch in COLUMNS:
            self.tree.heading(cid, text=title)
            self.tree.column(cid, width=width, anchor=anchor, stretch=stretch)
        self.tree.tag_configure("open", foreground=GREEN)
        self.tree.tag_configure("filtered", foreground=YELLOW)
        self.tree.tag_configure("closed", foreground=DIM)
        scroll = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=self.tree.yview,
            style="Terminal.Vertical.TScrollbar",
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", self._on_row_activate)

    def _build_log(self) -> None:
        frame = tk.Frame(self.root, bg=BG)
        frame.grid(row=5, column=0, sticky="nsew", padx=10, pady=2)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            frame,
            height=9,
            bg=BG,
            fg=FG,
            insertbackground=GREEN,
            font=(self.mono, 10),
            relief="flat",
            wrap="word",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            state="disabled",
        )
        self.log_text.tag_configure("info", foreground=FG)
        self.log_text.tag_configure("ok", foreground=GREEN)
        self.log_text.tag_configure("warn", foreground=YELLOW)
        self.log_text.tag_configure("error", foreground=RED)
        scroll = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=self.log_text.yview,
            style="Terminal.Vertical.TScrollbar",
        )
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

    def _build_status(self) -> None:
        self.status_label = tk.Label(
            self.root,
            text="",
            bg=BG,
            fg=CYAN,
            anchor="w",
            font=(self.mono, 10),
        )
        self.status_label.grid(row=6, column=0, sticky="ew", padx=10, pady=(2, 10))

    def _label(self, parent: tk.Misc, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=BG, fg=DIM, font=(self.mono, 10))

    def _entry(self, parent: tk.Misc, variable: tk.StringVar, width: int) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            width=width,
            bg=BG,
            fg=GREEN,
            insertbackground=GREEN,
            relief="flat",
            font=(self.mono, 10),
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=CYAN,
        )

    def _check(self, parent: tk.Misc, text: str, variable: tk.BooleanVar) -> tk.Checkbutton:
        return tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            bg=BG,
            fg=FG,
            selectcolor=PANEL,
            activebackground=BG,
            activeforeground=GREEN,
            font=(self.mono, 10),
            highlightthickness=0,
            bd=0,
        )

    def _button(self, parent: tk.Misc, text: str, command: Callable[[], None]) -> ttk.Button:
        return ttk.Button(parent, text=text, command=command, style="Terminal.TButton")

    def _set_running(self, running: bool) -> None:
        if running:
            self.scan_button.state(["disabled"])
            self.stop_button.state(["!disabled"])
        else:
            self.scan_button.state(["!disabled"])
            self.stop_button.state(["disabled"])

    def _scan_worker(self, options: ScanOptions, events: queue.Queue[object]) -> None:
        engine = ScanEngine(options)
        with self._lock:
            self._engine = engine

        async def runner() -> None:
            async for event in engine.run():
                events.put(event)

        try:
            asyncio.run(runner())
        except Exception as exc:
            events.put(("error", str(exc)))
        finally:
            events.put(("done", None))

    def _drain(self) -> None:
        events = self._queue
        while True:
            try:
                item = events.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, tuple):
                kind, payload = item
                if kind == "error":
                    self.log(f"scan error: {payload}", "error")
                elif kind == "done":
                    self._complete()
                continue
            if isinstance(item, Event):
                self._handle_event(item)
        if self._scanning:
            self.root.after(50, self._drain)

    def _handle_event(self, event: Event) -> None:
        if isinstance(event, ScanStarted):
            self._on_started(event)
        elif isinstance(event, HostUp):
            if event.host is None:
                return
            rtt = f" rtt={event.host.rtt_ms:.1f}ms" if event.host.rtt_ms is not None else ""
            self.log(f"host up: {event.host.label()}{rtt}", "ok")
        elif isinstance(event, HostFinished):
            host = event.host
            if host is None:
                return
            self._host_count += 1
            if host.state != "up":
                self.log(f"host {host.state}: {host.label()} ({host.reason})", "warn")
            elif host.os_guess:
                self.log(f"os guess: {host.label()} -> {host.os_guess}", "info")
        elif isinstance(event, PortDiscovered):
            self._on_port(event)
        elif isinstance(event, WarningRaised):
            self.log(f"warning: {event.message or 'engine warning'}", "warn")
        elif isinstance(event, ScanFinished):
            self._on_finished(event)

    def _on_started(self, event: ScanStarted) -> None:
        self._total = event.ports
        self.engine_label.configure(
            text=f"engines: {self._engines.describe()} | active: {event.engine}"
        )
        self.log(
            f"engine active: {event.engine} | {len(event.hosts)} host(s), {event.ports} probes",
            "info",
        )

    def _on_port(self, event: PortDiscovered) -> None:
        result = event.port
        if result is None:
            return
        if not event.updated:
            self._probed += 1
            if result.is_open:
                self._open_count += 1
        self._upsert_row(event.address or "-", result)

    def _on_finished(self, event: ScanFinished) -> None:
        self._hosts = list(event.hosts)
        self._elapsed = float(event.elapsed)
        level = "warn" if event.cancelled else "ok"
        state = "cancelled" if event.cancelled else "complete"
        self.log(
            f"scan {state}: {self._open_count} open / {self._probed} probed "
            f"across {len(event.hosts)} host(s) in {self._elapsed:.2f}s",
            level,
        )
        self._complete()

    def _upsert_row(self, address: str, result: PortResult) -> None:
        key = f"{address}:{result.port}:{result.protocol}"
        rtt = f"{result.rtt_ms:.1f}" if result.rtt_ms is not None else "-"
        values = (
            address,
            str(result.port),
            result.protocol,
            result.state,
            result.service or "-",
            result.version_string or "-",
            rtt,
            result.reason or "-",
        )
        tag = self._tag_for(result)
        if key in self._rows:
            self.tree.item(key, values=values, tags=(tag,))
        else:
            self.tree.insert("", "end", iid=key, values=values, tags=(tag,))
        self._rows[key] = result

    def _tag_for(self, result: PortResult) -> str:
        if result.is_open:
            return "open"
        if "filtered" in result.state:
            return "filtered"
        return "closed"

    def _on_row_activate(self, _event: tk.Event) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        key = selection[0]
        result = self._rows.get(key)
        if result is None:
            return
        self.log(f"{key} {result.detail() or 'no detail'}", "info")
        if result.banner:
            self.log(f"{key} banner: {result.banner.strip()}", "info")

    def _on_finished(self, event: ScanFinished) -> None:
        hosts = event.kind if isinstance(event.kind, list) else event.hosts
        if not isinstance(hosts, list):
            hosts = []
        if isinstance(event.elapsed, bool):
            cancelled = event.elapsed
            elapsed = float(event.hosts) if self._is_count(event.hosts) or isinstance(event.hosts, float) else 0.0
        else:
            cancelled = bool(event.cancelled)
            elapsed = float(event.elapsed) if isinstance(event.elapsed, (int, float)) else 0.0
        self._hosts = list(hosts)
        self._elapsed = elapsed
        level = "warn" if cancelled else "ok"
        state = "cancelled" if cancelled else "complete"
        self.log(
            f"scan {state}: {self._open_count} open / {self._probed} probed "
            f"across {len(hosts)} host(s) in {elapsed:.2f}s",
            level,
        )
        self._complete()

    def _complete(self) -> None:
        if not self._scanning:
            return
        self._scanning = False
        self._stopping = False
        if self._elapsed <= 0.0:
            self._elapsed = max(time.perf_counter() - self._started_at, 0.0)
        self._set_running(False)
        self._refresh_status()

    def _refresh_status(self) -> None:
        if self._scanning:
            elapsed = max(time.perf_counter() - self._started_at, 0.0)
        else:
            elapsed = self._elapsed
        rate = self._probed / elapsed if elapsed > 0 else 0.0
        prefix = "stopping | " if (self._scanning and self._stopping) else ""
        self.status_label.configure(
            text=(
                f"{prefix}probed {self._probed}/{self._total} | open {self._open_count} "
                f"| hosts {self._host_count} | elapsed {elapsed:.1f}s | {rate:.0f} ports/s"
            )
        )

    def _tick_status(self) -> None:
        self._refresh_status()
        try:
            self.root.after(200, self._tick_status)
        except tk.TclError:
            return


def main() -> int:
    root = tk.Tk()
    app = NetBreakDesktop(root)
    app.build()
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
