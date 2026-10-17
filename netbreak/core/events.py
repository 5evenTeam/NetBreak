from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from .models import HostResult, PortResult


@dataclass
class Event:
    kind: ClassVar[str] = "event"

    @property
    def address(self) -> str:
        return ""


@dataclass
class ScanStarted(Event):
    hosts: list[str] = field(default_factory=list)
    ports: int = 0
    engine: str = "python"
    kind: ClassVar[str] = "started"


@dataclass
class HostUp(Event):
    host: HostResult | None = None
    kind: ClassVar[str] = "host-up"

    @property
    def address(self) -> str:
        return self.host.address if self.host else ""


@dataclass
class PortDiscovered(Event):
    address: str = ""
    port: PortResult | None = None
    updated: bool = False
    kind: ClassVar[str] = "port"


@dataclass
class HostFinished(Event):
    host: HostResult | None = None
    kind: ClassVar[str] = "host-finished"

    @property
    def address(self) -> str:
        return self.host.address if self.host else ""


@dataclass
class WarningRaised(Event):
    message: str = ""
    kind: ClassVar[str] = "warning"


@dataclass
class ScanFinished(Event):
    hosts: list[HostResult] = field(default_factory=list)
    elapsed: float = 0.0
    cancelled: bool = False
    kind: ClassVar[str] = "finished"
