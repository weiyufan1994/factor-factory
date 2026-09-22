from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import time
from typing import Iterator


class PhaseTimer:
    def __init__(self) -> None:
        self.phase_seconds: dict[str, float] = {}
        self._start = time.perf_counter()

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.phase_seconds[name] = self.phase_seconds.get(name, 0.0) + (time.perf_counter() - started)

    def finish(self) -> dict[str, float]:
        out = {key: round(value, 6) for key, value in self.phase_seconds.items()}
        out["total"] = round(time.perf_counter() - self._start, 6)
        return out


def safe_file_size(path: str | Path | None) -> int:
    if not path:
        return 0
    p = Path(path)
    try:
        return int(p.stat().st_size)
    except OSError:
        return 0
