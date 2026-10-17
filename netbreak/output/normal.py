from __future__ import annotations

from datetime import datetime

from .. import __version__
from ..core.models import HostResult, PortResult, ScanOptions


def _row(port: PortResult) -> str:
    detail = port.version_string
    title = port.info.get("title")
    if title:
        detail = f"{detail} ({title})".strip()
    if not detail and port.banner:
        detail = port.banner.splitlines()[0][:60]
    service = port.service or ""
    return f"{port.port}/{port.protocol:<4}{port.state:<14}{service:<17}{detail}".rstrip()


def render(hosts: list[HostResult], options: ScanOptions, elapsed: float) -> str:
    lines: list[str] = []
    started = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"# NetBreak {__version__} scan started {started}")
    lines.append(
        f"# targets={len(options.targets)} {options.ports.summary()} "
        f"timing={options.timing} engine={options.engine}"
    )
    for host in hosts:
        lines.append("")
        headline = f"NetBreak scan report for {host.target}"
        if host.address and host.address != host.target:
            headline += f" ({host.address})"
        lines.append(headline)
        if host.state != "up":
            lines.append(f"Host is down ({host.reason or 'no response'}).")
            continue
        latency = f"{host.rtt_ms / 1000.0:.4f}s" if host.rtt_ms is not None else "unknown"
        ttl = f", ttl {host.ttl}" if host.ttl else ""
        lines.append(f"Host is up ({latency} latency{ttl}, {host.reason or 'unknown'}).")
        if host.hostname:
            lines.append(f"rDNS record: {host.hostname}")
        if host.os_guess:
            lines.append(f"OS guess: {host.os_guess}")
        if not host.ports:
            lines.append("No ports responded.")
            continue
        lines.append("")
        lines.append(f"{'PORT':<12}{'STATE':<14}{'SERVICE':<17}VERSION")
        for port in host.ports:
            lines.append(_row(port))
        lines.append("")
        lines.append(
            f"{len(host.open_ports)} open, {len(host.ports)} probed on {host.address} "
            f"via {host.engine} engine"
        )
    lines.append("")
    lines.append(f"# NetBreak finished: {len(hosts)} host(s) in {elapsed:.2f}s")
    return "\n".join(lines) + "\n"
