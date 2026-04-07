from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import json

from ..models.extraction_artifact import ExtractionArtifact


class ObjectWriter:
    def __init__(self, object_root: str | Path):
        self.object_root = Path(object_root)
        self.object_root.mkdir(parents=True, exist_ok=True)

    def write_extraction_artifact(self, artifact: ExtractionArtifact) -> str:
        out_dir = self.object_root / "extraction_artifacts"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"extraction_artifact__{artifact.report_id}.json"
        out_path.write_text(json.dumps(artifact.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return str(out_path)

    def write_report_map(self, report_id: str, role: str, payload: Dict[str, Any]) -> str:
        out_dir = self.object_root / "report_maps"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"report_map__{report_id}__{role}.json"
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(out_path)

    def write_validation_result(self, report_id: str, payload: Dict[str, Any]) -> str:
        out_dir = self.object_root / "validation"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"report_map_validation__{report_id}.json"
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(out_path)
