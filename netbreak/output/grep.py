from __future__ import annotations

from ..core.models import HostResult, ScanOptions


def _port_field(port) -> str:
    service = port.service or ""
    version = port.version_string
    return f"{port.port}/{port.state}/{port.protocol}//{service}//{version}/"


def render(hosts: list[HostResult], options: ScanOptions, elapsed: float) -> str:
    lines: list[str] = []
    for host in hosts:
        label = f"{host.address} ({host.hostname or ''})"
        lines.append(f"Host: {label}\tStatus: {host.state.capitalize()}")
        if host.ports:
            ports = ", ".join(_port_field(port) for port in host.ports)
            lines.append(f"Host: {label}\tPorts: {ports}")
        if host.os_guess:
            lines.append(f"Host: {label}\tOS: {host.os_guess}")
    if not lines:
        lines.append("# no hosts scanned")
    lines.append(f"# NetBreak done in {elapsed:.2f}s")
    return "\n".join(lines) + "\n"
