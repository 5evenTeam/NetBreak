from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..ports import PortSpec


class PortState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    FILTERED = "filtered"
    OPEN_FILTERED = "open|filtered"
    UNKNOWN = "unknown"


class HostState(str, Enum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass
class PortResult:
    port: int
    protocol: str = "tcp"
    state: str = PortState.CLOSED.value
    reason: str = ""
    rtt_ms: float | None = None
    service: str | None = None
    product: str | None = None
    version: str | None = None
    banner: str | None = None
    info: dict[str, str] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.state in (PortState.OPEN.value, PortState.OPEN_FILTERED.value)

    @property
    def version_string(self) -> str:
        parts = [p for p in (self.product, self.version) if p]
        return " ".join(parts)

    def detail(self) -> str:
        bits = []
        if self.service:
            bits.append(self.service)
        if self.version_string:
            bits.append(self.version_string)
        if self.banner and not self.version_string:
            bits.append(self.banner.splitlines()[0][:60])
        if self.info:
            bits.append("; ".join(f"{k}={v}" for k, v in self.info.items()))
        return " | ".join(bits)


@dataclass
class HostResult:
    target: str
    address: str
    hostname: str | None = None
    state: str = HostState.UNKNOWN.value
    reason: str = ""
    ttl: int | None = None
    os_guess: str | None = None
    ports: list[PortResult] = field(default_factory=list)
    rtt_ms: float | None = None
    engine: str = "python"

    @property
    def open_ports(self) -> list[PortResult]:
        return [p for p in self.ports if p.is_open]

    def label(self) -> str:
        name = f" ({self.hostname})" if self.hostname and self.hostname != self.target else ""
        return f"{self.target}{name} [{self.address}]"


@dataclass
class ScanOptions:
    targets: list[str]
    ports: PortSpec
    timeout: float = 1.0
    concurrency: int = 900
    retries: int = 1
    delay_ms: float = 0.0
    tcp: bool = True
    udp: bool = False
    version_detect: bool = False
    os_detect: bool = False
    ping: bool = True
    resolve: bool = True
    engine: str = "auto"
    ipv6: bool = False
    timing: str = "T4"
    verbosity: int = 1

    def target_count(self) -> int:
        return len(self.targets)

    def port_count(self) -> int:
        return self.ports.total
