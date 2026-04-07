from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import json


class SchemaValidator:
    def __init__(self, schema_root: str | Path):
        self.schema_root = Path(schema_root)

    def validate(self, schema_name: str, payload: Dict[str, Any]) -> None:
        schema_path = self.schema_root / schema_name
        if not schema_path.exists():
            raise FileNotFoundError(f"schema not found: {schema_path}")
        # TODO: wire real jsonschema validation
        _ = json.loads(schema_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
