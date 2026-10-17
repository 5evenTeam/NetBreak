"""NetBreak entry point: TUI by default, --cli for one-shot scripted scans."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netbreak",
        description=f"NetBreak v{__version__} - a fast, friendly TUI port scanner.",
        epilog="Use NetBreak only on systems you own or have explicit permission to test.",
    )
    parser.add_argument("target", nargs="?", help="host or IP to scan")
    parser.add_argument(
        "-p",
        "--ports",
        default="top100",
        help="port spec: top100, full, 1-1000, 22,80,443 (default: top100)",
    )
    parser.add_argument(
        "-t", "--timeout", type=float, default=1.0,
        help="per-port timeout in seconds (default: 1.0)",
    )
    parser.add_argument(
        "-c", "--concurrency", type=int, default=400,
        help="max simultaneous probes (default: 400)",
    )
    parser.add_argument(
        "--cli", action="store_true",
        help="one-shot terminal scan instead of the TUI",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="with --cli, print results as JSON instead of a table",
    )
    parser.add_argument("--version", action="version", version=f"netbreak {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cli:
        if not args.target:
            build_parser().error("--cli requires a target host")
        return _run_cli_scan(args)

    from .app import NetBreakApp

    app = NetBreakApp(
        target=args.target or "",
        ports_spec=args.ports,
        timeout=args.timeout,
        concurrency=args.concurrency,
    )
    app.run()
    return 0


def _run_cli_scan(args: argparse.Namespace) -> int:
    from .ports import parse_ports
    from .scanner import FILTERED, OPEN, Scanner

    print(f"NetBreak {__version__} - scanning {args.target} (authorized testing only)")
    try:
        ports = parse_ports(args.ports)
    except ValueError as exc:
        print(f"error: bad port spec: {exc}", file=sys.stderr)
        return 2

    async def _scan():
        try:
            scanner = await asyncio.to_thread(
                Scanner,
                args.target,
                ports,
                timeout=args.timeout,
                concurrency=args.concurrency,
            )
        except OSError as exc:
            print(f"error: could not resolve {args.target}: {exc}", file=sys.stderr)
            return None
        return [result async for result in scanner.scan()]

    results = asyncio.run(_scan())
    if results is None:
        return 1

    open_ports = [r for r in results if r.state == OPEN]
    filtered = [r for r in results if r.state == FILTERED]

    if args.json:
        print(
            json.dumps(
                [asdict(r) for r in sorted(results, key=lambda r: r.port)],
                indent=2,
            )
        )
        return 0

    if open_ports:
        from rich.console import Console
        from rich.table import Table

        table = Table(title=f"Open ports on {args.target}", header_style="bold cyan")
        table.add_column("Port", justify="right")
        table.add_column("State")
        table.add_column("Service")
        table.add_column("Latency (ms)", justify="right")
        for r in sorted(open_ports, key=lambda r: r.port):
            latency = f"{r.latency_ms:.1f}" if r.latency_ms is not None else "-"
            table.add_row(str(r.port), r.state, r.service or "-", latency)
        Console().print(table)
    else:
        print("No open ports found.")

    print(f"{len(open_ports)} open - {len(filtered)} filtered - {len(results)} probed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
