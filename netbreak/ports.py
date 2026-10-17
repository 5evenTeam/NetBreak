"""Port presets and range-spec parsing for NetBreak."""

from __future__ import annotations

# A curated set of the most commonly exposed TCP services.
TOP_PORTS: tuple[int, ...] = (
    21, 22, 23, 25, 53, 80, 88, 110, 111, 135, 139, 143, 389, 443, 445,
    465, 512, 513, 514, 587, 631, 636, 873, 993, 995, 1080, 1099, 1433,
    1521, 1723, 2049, 2082, 2083, 2086, 2087, 2095, 2096, 2121, 2181,
    3000, 3128, 3306, 3389, 4369, 4443, 4444, 5000, 5432, 5601, 5672,
    5900, 5985, 5986, 6000, 6379, 6443, 6666, 6667, 7001, 8000, 8008,
    8010, 8080, 8081, 8088, 8443, 8888, 9000, 9090, 9092, 9200, 9300,
    9418, 10000, 11211, 15672, 27017, 27018, 50000,
)

PRESETS: dict[str, tuple[int, ...]] = {
    "top100": TOP_PORTS,
    "full": tuple(range(1, 65536)),
}

MAX_PORT = 65535


def parse_ports(spec: str) -> list[int]:
    """Parse a port spec into a sorted, de-duplicated list of ports.

    Accepted forms:
        "top100"          curated preset of common services
        "full"            every TCP port, 1-65535
        "22,80,443"       explicit list
        "1-1000"          inclusive range
        mixes of the above, e.g. "22,80,443,8000-8100"
    """
    text = spec.strip().lower()
    if not text:
        raise ValueError("port spec is empty")
    if text in PRESETS:
        return list(PRESETS[text])

    ports: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                start_s, _, end_s = part.partition("-")
                start, end = int(start_s), int(end_s)
                if start > end:
                    start, end = end, start
                if start < 1 or end > MAX_PORT:
                    raise ValueError
                ports.update(range(start, end + 1))
            else:
                port = int(part)
                if not 1 <= port <= MAX_PORT:
                    raise ValueError
                ports.add(port)
        except ValueError:
            raise ValueError(f"bad port token: {part!r} (use top100, full, 80, or 1-1000)") from None

    if not ports:
        raise ValueError("no ports to scan in that spec")
    return sorted(ports)
