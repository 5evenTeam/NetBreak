from __future__ import annotations

import json
from dataclasses import asdict

from .. import __version__
from ..core.models import HostResult, ScanOptions


def _host(host: HostResult) -> dict:
    return {
        "target": host.target,
        "address": host.address,
        "hostname": host.hostname,
        "state": host.state,
        "reason": host.reason,
        "rtt_ms": host.rtt_ms,
        "ttl": host.ttl,
        "os_guess": host.os_guess,
        "engine": host.engine,
        "open_ports": len(host.open_ports),
        "ports": [asdict(port) for port in host.ports],
    }


def render(hosts: list[HostResult], options: ScanOptions, elapsed: float) -> str:
    payload = {
        "scanner": "netbreak",
        "version": __version__,
        "elapsed_seconds": elapsed,
        "options": {
            "targets": options.targets,
            "timing": options.timing,
            "engine": options.engine,
            "tcp": options.tcp,
            "udp": options.udp,
            "version_detect": options.version_detect,
            "os_detect": options.os_detect,
            "host_discovery": options.ping,
            "timeout": options.timeout,
            "concurrency": options.concurrency,
            "port_summary": options.ports.summary(),
            "tcp_ports": options.ports.tcp,
            "udp_ports": options.ports.udp,
        },
        "hosts": [_host(host) for host in hosts],
        "summary": {
            "hosts_total": len(hosts),
            "hosts_up": sum(1 for host in hosts if host.state == "up"),
            "open_ports": sum(len(host.open_ports) for host in hosts),
            "ports_probed": sum(len(host.ports) for host in hosts),
        },
    }
    return json.dumps(payload, indent=2) + "\n"
