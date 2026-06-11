#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOKEN_SOURCE_MISSING = "BLOCK_FACTORFORGE_LINEAGE_REPAIR_SOURCE_MISSING"
TOKEN_TARGET_EXISTS = "BLOCK_FACTORFORGE_LINEAGE_REPAIR_TARGET_EXISTS"
TOKEN_UNSAFE_ARTIFACT = "BLOCK_FACTORFORGE_LINEAGE_REPAIR_UNSAFE_ARTIFACT"
TOKEN_SEMANTIC_MUTATION = "BLOCK_FACTORFORGE_LINEAGE_REPAIR_SEMANTIC_MUTATION"

ARTIFACT_DIRS = {
    "alpha_idea_master": "alpha_idea_master",
    "factor_spec_master": "factor_spec_master",
    "data_prep_master": "data_prep_master",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def artifact_path(root: Path, artifact_kind: str, report_id: str) -> Path:
    rel = ARTIFACT_DIRS.get(artifact_kind)
    if not rel:
        raise ValueError(f"{TOKEN_UNSAFE_ARTIFACT}: unsupported artifact_kind={artifact_kind!r}")
    return root / "objects" / rel / f"{artifact_kind}__{report_id}.json"


def semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    clone = copy.deepcopy(payload)
    for key in ("report_id", "artifact_identity", "lineage_repair", "created_at_utc", "updated_at_utc"):
        clone.pop(key, None)
    return clone


def repaired_payload(source: dict[str, Any], *, artifact_kind: str, target_report_id: str, repair_contract: dict[str, Any]) -> dict[str, Any]:
    target = copy.deepcopy(source)
    target["report_id"] = target_report_id
    identity = target.get("artifact_identity") if isinstance(target.get("artifact_identity"), dict) else {}
    identity = copy.deepcopy(identity)
    identity["report_id"] = target_report_id
    identity["artifact_role"] = artifact_kind
    identity["producer"] = "factorforge_lineage_repair"
    identity["lineage_repair_status"] = "identity_wrapper_only"
    target["artifact_identity"] = identity
    target["lineage_repair"] = repair_contract
    return target


def repair(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.factorforge_root).expanduser().resolve()
    artifact_kind = str(args.artifact_kind)
    source = artifact_path(root, artifact_kind, args.source_report_id)
    target = artifact_path(root, artifact_kind, args.report_id)
    if not source.exists():
        raise ValueError(f"{TOKEN_SOURCE_MISSING}: {source}")
    if target.exists():
        raise ValueError(f"{TOKEN_TARGET_EXISTS}: {target}")
    source_payload = load_json(source)
    if not isinstance(source_payload, dict):
        raise ValueError(f"{TOKEN_UNSAFE_ARTIFACT}: source is not JSON object")
    semantic_before = stable_hash(semantic_payload(source_payload))
    repair_contract = {
        "contract_version": "factorforge_report_lineage_repair_v1",
        "status": "pass",
        "artifact_kind": artifact_kind,
        "target_report_id": args.report_id,
        "source_report_id": args.source_report_id,
        "source_artifact_path": str(source),
        "source_artifact_sha256": sha256_file(source),
        "target_artifact_path": str(target),
        "repair_reason": args.reason,
        "repair_scope": "identity_wrapper_only",
        "semantic_payload_sha256_before": semantic_before,
        "official_artifact_written": False,
        "formula_changed": False,
        "data_changed": False,
        "metrics_changed": False,
    }
    target_payload = repaired_payload(
        source_payload,
        artifact_kind=artifact_kind,
        target_report_id=args.report_id,
        repair_contract=repair_contract,
    )
    semantic_after = stable_hash(semantic_payload(target_payload))
    repair_contract["semantic_payload_sha256_after"] = semantic_after
    if semantic_before != semantic_after:
        raise ValueError(f"{TOKEN_SEMANTIC_MUTATION}: semantic payload changed")
    target_payload["lineage_repair"] = repair_contract
    write_json(target, target_payload)
    report = {
        "contract_version": "factorforge_report_lineage_repair_report_v1",
        "created_at_utc": utc_now(),
        "status": "pass",
        "block_token": None,
        "artifact_kind": artifact_kind,
        "target_report_id": args.report_id,
        "source_report_id": args.source_report_id,
        "target_artifact_path": str(target),
        "target_artifact_sha256": sha256_file(target),
        "source_artifact_path": str(source),
        "source_artifact_sha256": repair_contract["source_artifact_sha256"],
        "repair_scope": "identity_wrapper_only",
        "formula_changed": False,
        "data_changed": False,
        "metrics_changed": False,
        "official_artifact_written": False,
    }
    report_path = root / "objects" / "validation" / f"lineage_repair__{args.report_id}__{artifact_kind}.json"
    write_json(report_path, report)
    report["repair_report_path"] = str(report_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair report-local lineage wrappers without mutating formula/data/metrics payload.")
    parser.add_argument("--factorforge-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--source-report-id", required=True)
    parser.add_argument("--artifact-kind", required=True, choices=sorted(ARTIFACT_DIRS))
    parser.add_argument("--reason", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = repair(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
