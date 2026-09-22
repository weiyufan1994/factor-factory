from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from .report_source_contract import ReportSource, validate_report_source


class ReportRegistry:
    def __init__(self, registry_path: str | Path):
        self.registry_path = Path(registry_path)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if self.registry_path.exists():
            self._data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        else:
            self._data = {}

    def save(self) -> None:
        self.registry_path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def exists(self, report_id: str) -> bool:
        return report_id in self._data

    def register(self, source: ReportSource) -> ReportSource:
        validate_report_source(source)
        if not self.exists(source.report_id):
            self._data[source.report_id] = asdict(source)
            self.save()
        return source

    def update_status(self, report_id: str, status: str, **kwargs: Any) -> None:
        if report_id not in self._data:
            raise KeyError(f"unknown report_id: {report_id}")
        self._data[report_id]["status"] = status
        self._data[report_id].update(kwargs)
        self.save()

    def set_cache_path(self, report_id: str, local_cache_path: str) -> None:
        self.update_status(report_id, self._data[report_id].get("status", "registered"), local_cache_path=local_cache_path)

    def get(self, report_id: str) -> Optional[Dict[str, Any]]:
        return self._data.get(report_id)

    def list_all(self) -> List[Dict[str, Any]]:
        return list(self._data.values())

    def list_by_status(self, status: str) -> List[Dict[str, Any]]:
        return [x for x in self._data.values() if x.get("status") == status]
