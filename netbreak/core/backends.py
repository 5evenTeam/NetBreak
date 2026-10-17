from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ENV_ENGINE_DIR = "NETBREAK_ENGINE_DIR"


def _executable(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _search_roots() -> list[Path]:
    roots: list[Path] = []
    override = os.environ.get(ENV_ENGINE_DIR)
    if override:
        roots.append(Path(override))
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        roots.append(Path(bundle))
        roots.append(Path(bundle) / "engines")
    package_parent = Path(__file__).resolve().parents[2]
    roots.extend(
        [
            package_parent / "engines" / "go" / "bin",
            package_parent / "engines" / "cpp" / "bin",
            package_parent / "engines" / "cpp" / "build",
            package_parent / "bin",
            package_parent / "dist",
        ]
    )
    return roots


def _locate(name: str) -> str | None:
    executable = _executable(name)
    for root in _search_roots():
        candidate = root / executable
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


@dataclass
class Engines:
    go: str | None = None
    native: str | None = None

    def has(self, name: str) -> bool:
        return getattr(self, name, None) is not None

    def describe(self) -> str:
        parts = []
        parts.append("go" if self.go else "go(absent)")
        parts.append("native" if self.native else "native(absent)")
        parts.append("python")
        return ", ".join(parts)

    def best(self) -> str:
        if self.go:
            return "go"
        if self.native:
            return "cpp"
        return "python"


def find() -> Engines:
    return Engines(go=_locate("netbreak-engine"), native=_locate("netbreak-native"))
