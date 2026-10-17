from __future__ import annotations

from .models import PortResult

TTL_BUCKETS = (
    (32, "Embedded/Network device"),
    (64, "Linux/Unix"),
    (128, "Windows"),
    (255, "Network device/Solaris"),
)


def _ttl_family(ttl: int) -> str:
    for ceiling, label in TTL_BUCKETS:
        if ttl <= ceiling:
            return label
    return "Unknown"


def guess(ttl: int | None, ports: list[PortResult]) -> str | None:
    hints: list[str] = []
    if ttl is not None:
        hints.append(f"{_ttl_family(ttl)} (ttl={ttl})")

    products = " ".join(
        " ".join(filter(None, (p.product, p.version, p.service))) for p in ports
    ).lower()
    if any(key in products for key in ("microsoft", "iis", "terminal services", "netbios")):
        hints.append("Windows services")
    if any(key in products for key in ("openssh", "ubuntu", "debian", "nginx", "apache", "postfix")):
        hints.append("Unix-like services")
    if "cisco" in products or "router" in products:
        hints.append("Network appliance")

    if not hints:
        return None
    return " | ".join(dict.fromkeys(hints))
