#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.artifact_identity import build_spec_hash
from factor_factory.mechanism_math.classifier import build_mechanism_math_contract
from factor_factory.mechanism_math.validator import validate_mechanism_math_contract

CONTRACT_VERSION = "factorforge_mechanism_math_contract_v1"
HANDOFF_NAMES = [
    "handoff_to_step3",
    "handoff_to_step5",
    "handoff_to_step6",
]
PRESERVED_IDENTITY_KEYS = [
    "spec_hash",
    "formula_hash",
    "run_id",
    "branch_id",
    "code_hash",
    "code_contract_hash",
    "custom_block_hash",
    "hybrid_hash",
]


class BackfillBlock(RuntimeError):
    def __init__(self, token: str, payload: dict[str, Any]):
        super().__init__(token)
        self.token = token
        self.payload = payload


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_factorforge_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    if os.getenv("FACTORFORGE_ROOT"):
        return Path(os.environ["FACTORFORGE_ROOT"]).expanduser().resolve()
    return REPO_ROOT


def identity_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    identity = payload.get("artifact_identity") or {}
    out = {
        "top_level_spec_hash": payload.get("spec_hash"),
    }
    for key in PRESERVED_IDENTITY_KEYS:
        out[f"artifact_identity.{key}"] = identity.get(key)
    return out


def compare_identity(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for key, before_value in before.items():
        after_value = after.get(key)
        checks[key] = {
            "before": before_value,
            "after": after_value,
            "preserved": before_value == after_value,
        }
    return checks


def canonical_contract(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def assert_factor_spec_preserved(
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    canonical_before: dict[str, Any],
    implementation_before: dict[str, Any],
    research_before: dict[str, Any],
) -> dict[str, Any]:
    hash_before = build_spec_hash(before)
    hash_after = build_spec_hash(after)
    checks = compare_identity(identity_snapshot(before), identity_snapshot(after))
    checks["build_spec_hash"] = {
        "before": hash_before,
        "after": hash_after,
        "preserved": hash_before == hash_after,
    }
    checks["canonical_spec"] = {
        "preserved": canonical_before == (after.get("canonical_spec") or {}),
    }
    checks["implementation_contract"] = {
        "preserved": implementation_before == (after.get("implementation_contract") or {}),
    }
    checks["research_contract"] = {
        "preserved": research_before == (after.get("research_contract") or {}),
    }
    failed = [key for key, item in checks.items() if item.get("preserved") is not True]
    if failed:
        raise RuntimeError(f"backfill would modify protected lineage fields: {failed}")
    return checks


def prepare_handoff_update(path: Path, contract: dict[str, Any]) -> dict[str, Any] | None:
    if not path.exists():
        return None
    before = load_json(path)
    existing = before.get("mechanism_math_contract")
    if isinstance(existing, dict) and existing:
        failures = validate_mechanism_math_contract(existing)
        if failures:
            raise BackfillBlock(
                "BLOCK_MECHANISM_MATH_BACKFILL_EXISTING_INVALID_HANDOFF",
                {
                    "path": str(path),
                    "failures": failures,
                },
            )
        if canonical_contract(existing) != canonical_contract(contract):
            raise BackfillBlock(
                "BLOCK_MECHANISM_MATH_BACKFILL_HANDOFF_CONFLICT",
                {
                    "path": str(path),
                    "reason": "valid existing handoff mechanism_math_contract differs from target contract",
                    "existing_math_model_status": existing.get("math_model_status"),
                    "existing_model_family": existing.get("model_family"),
                    "target_math_model_status": contract.get("math_model_status"),
                    "target_model_family": contract.get("model_family"),
                },
            )
        return {
            "path": str(path),
            "updated": False,
            "reason": "existing_valid_contract_matches",
            "payload": before,
            "identity_preservation": compare_identity(identity_snapshot(before), identity_snapshot(before)),
        }

    after = copy.deepcopy(before)
    before_identity = identity_snapshot(before)
    after["mechanism_math_contract"] = contract
    after_identity = identity_snapshot(after)
    identity_checks = compare_identity(before_identity, after_identity)
    failed = [key for key, item in identity_checks.items() if item.get("preserved") is not True]
    if failed:
        raise RuntimeError(f"backfill would modify protected handoff identity fields for {path}: {failed}")
    return {
        "path": str(path),
        "updated": True,
        "payload": after,
        "identity_preservation": identity_checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill legacy Factor Forge Step2 artifacts with a top-level "
            "mechanism_math_contract without changing canonical formula/code lineage."
        )
    )
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--factorforge-root")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = resolve_factorforge_root(args.factorforge_root)
    objects = root / "objects"
    spec_path = objects / "factor_spec_master" / f"factor_spec_master__{args.report_id}.json"
    if not spec_path.exists():
        print(f"BLOCK_MECHANISM_MATH_BACKFILL_INPUT_MISSING: {spec_path}", file=sys.stderr)
        raise SystemExit(1)

    before = load_json(spec_path)
    after = copy.deepcopy(before)
    canonical_before = copy.deepcopy(before.get("canonical_spec") or {})
    implementation_before = copy.deepcopy(before.get("implementation_contract") or {})
    research_before = copy.deepcopy(before.get("research_contract") or {})

    existing = before.get("mechanism_math_contract")
    if isinstance(existing, dict) and existing:
        failures = validate_mechanism_math_contract(existing)
        if failures:
            print(
                "BLOCK_MECHANISM_MATH_BACKFILL_EXISTING_INVALID: "
                + json.dumps(failures, ensure_ascii=False),
                file=sys.stderr,
            )
            raise SystemExit(1)
        contract = existing
        status = "already_present"
    else:
        contract = build_mechanism_math_contract(before)
        failures = validate_mechanism_math_contract(contract)
        if failures:
            print(
                "BLOCK_MECHANISM_MATH_BACKFILL_CONTRACT_INVALID: "
                + json.dumps(failures, ensure_ascii=False),
                file=sys.stderr,
            )
            raise SystemExit(1)
        after["mechanism_math_contract"] = contract
        status = "dry_run" if args.dry_run else "backfilled"

    try:
        preservation = assert_factor_spec_preserved(
            before=before,
            after=after,
            canonical_before=canonical_before,
            implementation_before=implementation_before,
            research_before=research_before,
        )

        handoff_updates: list[dict[str, Any]] = []
        prepared_handoffs: list[dict[str, Any]] = []
        for handoff_name in HANDOFF_NAMES:
            handoff_path = objects / "handoff" / f"{handoff_name}__{args.report_id}.json"
            update = prepare_handoff_update(handoff_path, contract)
            if update:
                prepared_handoffs.append(update)
                handoff_updates.append({key: value for key, value in update.items() if key != "payload"})
    except BackfillBlock as exc:
        print(
            exc.token + ": " + json.dumps(exc.payload, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(1)

    updated_paths: list[str] = []
    if not args.dry_run and status == "backfilled":
        write_json(spec_path, after)
        updated_paths.append(str(spec_path))

    if not args.dry_run:
        for update in prepared_handoffs:
            if update.get("updated"):
                path = Path(str(update["path"]))
                write_json(path, update["payload"])
                updated_paths.append(str(path))

    summary = {
        "status": status,
        "report_id": args.report_id,
        "factorforge_root": str(root),
        "factor_spec_path": str(spec_path),
        "contract_version": contract.get("contract_version") or CONTRACT_VERSION,
        "math_model_status": contract.get("math_model_status"),
        "model_family": contract.get("model_family"),
        "under_specified_reason": contract.get("under_specified_reason"),
        "lineage_preservation": preservation,
        "handoff_updates": handoff_updates,
        "updated_paths": updated_paths,
        "created_at_utc": utc_now(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
