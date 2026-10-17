from __future__ import annotations

from pathlib import Path

from ..core.models import HostResult, ScanOptions
from . import grep, jsonout, normal, xmlout

RENDERERS = {
    "normal": normal.render,
    "json": jsonout.render,
    "xml": xmlout.render,
    "grep": grep.render,
}

EXTENSIONS = {
    "normal": "txt",
    "json": "json",
    "xml": "xml",
    "grep": "gnmap",
}


def render(kind: str, hosts: list[HostResult], options: ScanOptions, elapsed: float) -> str:
    renderer = RENDERERS.get(kind)
    if renderer is None:
        raise ValueError(f"unknown output format {kind!r}")
    return renderer(hosts, options, elapsed)


def write(
    kind: str,
    path: str,
    hosts: list[HostResult],
    options: ScanOptions,
    elapsed: float,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(kind, hosts, options, elapsed), encoding="utf-8")
    return target


def write_all(
    base: str,
    hosts: list[HostResult],
    options: ScanOptions,
    elapsed: float,
) -> list[Path]:
    written = []
    for kind, extension in EXTENSIONS.items():
        written.append(write(kind, f"{base}.{extension}", hosts, options, elapsed))
    return written
