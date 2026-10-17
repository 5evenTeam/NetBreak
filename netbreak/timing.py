from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Timing:
    template: str
    name: str
    concurrency: int
    timeout: float
    retries: int
    delay_ms: float

    def describe(self) -> str:
        return (
            f"{self.template} ({self.name}): concurrency={self.concurrency} "
            f"timeout={self.timeout}s retries={self.retries} delay={self.delay_ms}ms"
        )


TEMPLATES: dict[str, Timing] = {
    "T0": Timing("T0", "paranoid", 4, 10.0, 1, 1000.0),
    "T1": Timing("T1", "sneaky", 16, 8.0, 1, 400.0),
    "T2": Timing("T2", "polite", 64, 5.0, 1, 100.0),
    "T3": Timing("T3", "normal", 300, 2.0, 1, 0.0),
    "T4": Timing("T4", "aggressive", 900, 1.0, 2, 0.0),
    "T5": Timing("T5", "insane", 2000, 0.5, 2, 0.0),
}

DEFAULT_TEMPLATE = "T4"


def get(name: str) -> Timing:
    key = name.strip().upper()
    if not key.startswith("T"):
        key = "T" + key
    if key not in TEMPLATES:
        raise ValueError(f"unknown timing template {name!r}; use T0-T5")
    return TEMPLATES[key]


def table() -> list[Timing]:
    return [TEMPLATES[k] for k in sorted(TEMPLATES)]
