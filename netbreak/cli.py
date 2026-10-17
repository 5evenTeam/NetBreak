from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import replace

from . import __version__, output
from . import ports as portlib
from . import timing as timinglib
from .core.backends import find as find_engines
from .core.engine import ScanEngine
from .core.events import PortDiscovered, ScanFinished, ScanStarted, WarningRaised
from .core.models import HostResult, ScanOptions
from .ports import PortSpec

TIMING_FLAGS = ("T0", "T1", "T2", "T3", "T4", "T5")
DEFAULT_UDP_PORTS = [
    53, 67, 68, 69, 88, 111, 123, 135, 137, 138, 161, 162, 389, 427, 445,
    500, 514, 520, 631, 636, 873, 1025, 1433, 1434, 1701, 1812, 1813, 1900,
    2049, 3389, 3456, 3703, 44818, 4500, 4789, 5060, 5061, 5353, 5632, 6667,
    10000, 33434,
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netbreak",
        description="NetBreak 2.0 port scanner with a terminal UI, desktop app and Nmap style CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  netbreak 192.168.1.0/24\n"
            "  netbreak host.example.com -p 22,80,443 -sV\n"
            "  netbreak 10.0.0.1-20 -p- -T4 --open\n"
            "  netbreak 10.0.0.5 -sU --udp-ports 53,161\n"
            "  netbreak tui\n"
            "  netbreak gui\n"
        ),
    )
    parser.add_argument("targets", nargs="*", help="hosts, host ranges or CIDR blocks to scan")
    parser.add_argument("-p", "--ports", default=None, help="TCP ports, default top100 (-p- scans all)")
    parser.add_argument("--udp-ports", default=None, help="UDP port specification")
    parser.add_argument("--exclude-ports", default="", help="ports to remove from the scan")
    parser.add_argument("--top-ports", type=int, default=None, help="scan the N most common TCP ports")
    parser.add_argument("--timing", default=None, help="timing template T0 to T5")
    for name in TIMING_FLAGS:
        parser.add_argument(
            f"-{name}",
            dest="timing",
            action="store_const",
            const=name,
            help=argparse.SUPPRESS,
        )
    parser.add_argument("-sT", dest="tcp", action="store_true", default=None, help="force a TCP connect scan, the default")
    parser.add_argument("-sU", dest="udp", action="store_true", help="add a UDP scan")
    parser.add_argument("-sn", dest="ping_only", action="store_true", help="host discovery only, no ports")
    parser.add_argument("-sV", dest="version_detect", action="store_true", help="service and version detection")
    parser.add_argument("-O", dest="os_detect", action="store_true", help="operating system guess")
    parser.add_argument("-Pn", dest="skip_ping", action="store_true", help="skip host discovery")
    parser.add_argument("-6", dest="ipv6", action="store_true", help="scan IPv6 targets")
    parser.add_argument("--engine", choices=("auto", "go", "cpp", "python"), default="auto", help="scan engine")
    parser.add_argument("--open", dest="open_only", action="store_true", help="only report open ports")
    parser.add_argument("-oN", dest="out_normal", metavar="FILE", help="write a normal text report")
    parser.add_argument("-oX", dest="out_xml", metavar="FILE", help="write an XML report")
    parser.add_argument("-oJ", dest="out_json", metavar="FILE", help="write a JSON report")
    parser.add_argument("-oG", dest="out_grep", metavar="FILE", help="write a grepable report")
    parser.add_argument("-oA", dest="out_all", metavar="BASE", help="write all four report formats")
    parser.add_argument("-v", dest="verbose", action="count", default=0, help="verbose output, repeatable")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress live progress")
    parser.add_argument("--timeout", type=float, default=None, help="per probe timeout in seconds")
    parser.add_argument("--concurrency", type=int, default=None, help="simultaneous probes")
    parser.add_argument("--retries", type=int, default=None, help="extra attempts on filtered ports")
    parser.add_argument("--delay", type=float, default=None, help="delay in milliseconds between probes")
    parser.add_argument("--no-resolve", dest="no_resolve", action="store_true", help="skip reverse DNS lookups")
    parser.add_argument("--list-engines", action="store_true", help="show the detected native engines")
    parser.add_argument("--version", action="version", version=f"NetBreak {__version__}")
    return parser


def _build_options(args: argparse.Namespace) -> ScanOptions:
    template = timinglib.get(args.timing or timinglib.DEFAULT_TEMPLATE)
    if args.ping_only:
        spec = PortSpec()
        tcp = False
        udp = False
    else:
        tcp_text = args.ports
        udp_text = args.udp_ports
        want_udp = bool(args.udp)
        want_tcp = args.tcp is True or not want_udp
        if want_udp and not want_tcp:
            if udp_text or tcp_text or args.top_ports is not None:
                parsed = portlib.parse(
                    tcp_text or udp_text or "",
                    exclude=args.exclude_ports,
                    top=args.top_ports,
                )
                spec = PortSpec(
                    udp=sorted(set(parsed.tcp) | set(parsed.udp)),
                    excluded=parsed.excluded,
                )
            else:
                spec = PortSpec(udp=sorted(DEFAULT_UDP_PORTS))
        else:
            spec = portlib.parse(
                tcp_text or "",
                udp=udp_text,
                exclude=args.exclude_ports,
                top=args.top_ports,
            )
            if want_udp and not udp_text:
                spec.udp = list(spec.tcp)
        tcp = bool(spec.tcp)
        udp = bool(spec.udp)
    return ScanOptions(
        targets=list(args.targets),
        ports=spec,
        timeout=args.timeout if args.timeout is not None else template.timeout,
        concurrency=args.concurrency if args.concurrency is not None else template.concurrency,
        retries=args.retries if args.retries is not None else template.retries,
        delay_ms=args.delay if args.delay is not None else template.delay_ms,
        tcp=tcp,
        udp=udp,
        version_detect=args.version_detect,
        os_detect=args.os_detect,
        ping=not args.skip_ping,
        resolve=not args.no_resolve,
        engine=args.engine,
        ipv6=args.ipv6,
        timing=template.template,
        verbosity=args.verbose,
    )


def _only_open(hosts: list[HostResult]) -> list[HostResult]:
    trimmed = [replace(host, ports=[p for p in host.ports if p.is_open]) for host in hosts]
    return [host for host in trimmed if host.ports]


async def _consume(engine: ScanEngine, quiet: bool, verbose: int) -> list[HostResult]:
    live = not quiet and sys.stderr.isatty()
    hosts: list[HostResult] = []
    async for event in engine.run():
        if isinstance(event, ScanStarted):
            if not quiet:
                print(
                    f"NetBreak {__version__} scanning {len(event.hosts)} host(s), "
                    f"{event.ports} probes, engine {event.engine}",
                    file=sys.stderr,
                )
        elif isinstance(event, PortDiscovered) and event.port is not None:
            port = event.port
            if live and port.is_open and not event.updated:
                detail = port.version_string or port.service or ""
                print(
                    f"[open] {event.address:<15} {port.port}/{port.protocol:<4} {detail}".rstrip(),
                    file=sys.stderr,
                )
        elif isinstance(event, WarningRaised):
            print(f"[warn] {event.message}", file=sys.stderr)
        elif isinstance(event, ScanFinished):
            hosts = event.hosts
    return hosts or engine.hosts


def _plain_report(hosts: list[HostResult], options: ScanOptions, elapsed: float) -> None:
    sys.stdout.write(output.render("normal", hosts, options, elapsed))


def _rich_report(hosts: list[HostResult], options: ScanOptions, engine: ScanEngine) -> None:
    try:
        from rich.console import Console
        from rich.markup import escape
        from rich.table import Table
    except ImportError:
        _plain_report(hosts, options, engine.elapsed)
        return
    console = Console()
    total_open = sum(len(host.open_ports) for host in hosts)
    console.print(
        f"[bold]NetBreak {__version__}[/bold] engine={engine.engine_name} "
        f"hosts={len(hosts)} open={total_open} elapsed={engine.elapsed:.2f}s"
    )
    for host in hosts:
        console.print(f"\n[bold cyan]{escape(host.label())}[/bold cyan]")
        summary = f"[dim]{host.state} ({host.reason or 'unknown'})[/dim]"
        if host.rtt_ms is not None:
            summary += f" [dim]rtt {host.rtt_ms:.2f} ms[/dim]"
        if host.ttl:
            summary += f" [dim]ttl {host.ttl}[/dim]"
        console.print(summary)
        if host.os_guess:
            console.print(f"OS guess: {escape(host.os_guess)}")
        if not host.ports:
            console.print("[dim]no ports reported[/dim]")
            continue
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        for column in ("PORT", "STATE", "SERVICE", "VERSION", "RTT", "REASON"):
            table.add_column(column)
        for port in host.ports:
            colour = {"open": "green", "closed": "dim", "filtered": "yellow"}.get(port.state, "white")
            if port.version_string:
                version = port.version_string
            elif port.banner:
                version = port.banner.splitlines()[0][:60]
            else:
                version = ""
            table.add_row(
                f"{port.port}/{port.protocol}",
                f"[{colour}]{port.state}[/{colour}]",
                escape(port.service or ""),
                escape(version),
                f"{port.rtt_ms:.2f}" if port.rtt_ms is not None else "",
                escape(port.reason or ""),
            )
        console.print(table)


def _write_outputs(hosts: list[HostResult], options: ScanOptions, elapsed: float, args: argparse.Namespace) -> None:
    requested = []
    if args.out_normal:
        requested.append(("normal", args.out_normal))
    if args.out_xml:
        requested.append(("xml", args.out_xml))
    if args.out_json:
        requested.append(("json", args.out_json))
    if args.out_grep:
        requested.append(("grep", args.out_grep))
    for kind, path in requested:
        written = output.write(kind, path, hosts, options, elapsed)
        print(f"wrote {kind} report to {written}", file=sys.stderr)
    if args.out_all:
        for written in output.write_all(args.out_all, hosts, options, elapsed):
            print(f"wrote report to {written}", file=sys.stderr)


def run_scan(args: argparse.Namespace) -> int:
    options = _build_options(args)
    if not options.targets:
        print("error: no targets given", file=sys.stderr)
        return 2
    engine = ScanEngine(options, find_engines())
    try:
        asyncio.run(_consume(engine, args.quiet, args.verbose))
    except KeyboardInterrupt:
        engine.cancel()
        print("\ninterrupted, reporting partial results", file=sys.stderr)
    hosts = engine.hosts
    if args.open_only:
        hosts = _only_open(hosts)
    if args.quiet or not sys.stdout.isatty():
        _plain_report(hosts, options, engine.elapsed)
    else:
        _rich_report(hosts, options, engine)
    _write_outputs(hosts, options, engine.elapsed, args)
    return 0


def launch_tui() -> int:
    try:
        from .tui.app import NetBreakApp
    except ImportError as exc:
        print(f"terminal UI unavailable: {exc}. Use --cli to scan from the shell.", file=sys.stderr)
        return 1
    NetBreakApp().run()
    return 0


def launch_gui() -> int:
    try:
        from .desktop.app import main as gui_main
    except ImportError as exc:
        print(f"desktop app unavailable: {exc}", file=sys.stderr)
        return 1
    return gui_main()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    command: str | None = None
    if arguments and arguments[0] in {"tui", "gui", "desktop", "ui", "cli"}:
        command = arguments.pop(0)
        if command in {"desktop", "ui"}:
            command = "gui"
    for flag, name in (("--tui", "tui"), ("--gui", "gui")):
        if flag in arguments:
            arguments.remove(flag)
            command = name
    if command is None and "--cli" in arguments:
        arguments.remove("--cli")
        command = "cli"

    if command == "gui":
        return launch_gui()
    if command == "tui":
        return launch_tui()

    parser = build_parser()
    args = parser.parse_args(arguments)

    if args.list_engines:
        engines = find_engines()
        print(f"engine order: {engines.describe()}")
        print(f"  go engine:     {engines.go or 'not found'}")
        print(f"  native engine: {engines.native or 'not found'}")
        return 0

    if not args.targets:
        if command == "cli":
            print("error: no targets given", file=sys.stderr)
            return 2
        return launch_tui()
    return run_scan(args)


if __name__ == "__main__":
    raise SystemExit(main())
