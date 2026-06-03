#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context

APPROVAL_VERSION = "factorforge_main_agent_multibranch_synthesis_approval_v1"
MATERIALIZATION_VERSION = "factorforge_multibranch_child_materialization_v1"
TOKEN_NOT_ENABLED = "BLOCK_FACTORFORGE_MULTIBRANCH_MATERIALIZATION_NOT_ENABLED"
TOKEN_APPROVAL_MISSING = "BLOCK_FACTORFORGE_MULTIBRANCH_APPROVAL_MISSING"
TOKEN_APPROVAL_INVALID = "BLOCK_FACTORFORGE_MULTIBRANCH_APPROVAL_INVALID"
TOKEN_SOURCE_CHANGED = "BLOCK_FACTORFORGE_MULTIBRANCH_SOURCE_SYNTHESIS_CHANGED"
TOKEN_ADAPTER_CHANGED = "BLOCK_FACTORFORGE_MULTIBRANCH_ADAPTER_SYNTHESIS_CHANGED"
TOKEN_FAILED = "BLOCK_FACTORFORGE_MULTIBRANCH_MATERIALIZATION_FAILED"
TOKEN_CHILD_COLLISION = "BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_ID_COLLISION"
TOKEN_DUP_HASH = "BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_FORMULA_DUPLICATE"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[WRITE] {path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tail(text: str, limit: int = 4000) -> str:
    return text[-limit:] if text else ""


def council_dir(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / report_id


def approval_path(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis_approval__{report_id}.json"


def aggregate_report_path(root: Path, report_id: str, loop_index: int) -> Path:
    return root / "objects" / "runtime_context" / f"multibranch_child_materialization__{report_id}__loop{loop_index:02d}.json"


def child_materialization_report_path(root: Path, parent: str, child: str) -> Path:
    digest = hashlib.sha256(f"{parent}\0{child}".encode("utf-8")).hexdigest()[:16]
    short_parent = parent[:40].rstrip("_")
    short_child = child[:40].rstrip("_")
    filename = f"child_revision_materialization__{short_parent}__{short_child}__{digest}.json"
    return root / "objects" / "runtime_context" / filename


def executable_revision_spec_path(root: Path, child: str) -> Path:
    return root / "objects" / "research_iteration_master" / f"executable_revision_spec__{child}.json"


def validate_approval(root: Path, report_id: str, approval: dict[str, Any]) -> None:
    if approval.get("contract_version") != APPROVAL_VERSION:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: invalid contract_version")
    if approval.get("parent_report_id") != report_id:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: parent_report_id mismatch")
    if approval.get("canonical_write_permission") is not False:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: canonical_write_permission must be false")
    if approval.get("execution_allowed_by_default") is not False:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: execution_allowed_by_default must be false")
    if approval.get("human_approval_required") is not True:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: human_approval_required must be true")
    source_path_raw = approval.get("source_multibranch_synthesis_path")
    if not isinstance(source_path_raw, str) or not source_path_raw:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: source_multibranch_synthesis_path missing")
    source_path = Path(source_path_raw).expanduser()
    if not source_path.is_absolute():
        source_path = root / source_path
    if not source_path.exists():
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: source synthesis missing")
    current_sha = sha256_file(source_path)
    if approval.get("source_multibranch_synthesis_sha256") != current_sha:
        raise ValueError(f"{TOKEN_SOURCE_CHANGED}: source multibranch synthesis changed after approval")
    branches = approval.get("selected_branches")
    if not isinstance(branches, list) or not branches:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: selected_branches missing")
    child_ids: set[str] = set()
    child_hashes: set[str] = set()
    for idx, raw in enumerate(branches):
        branch = raw if isinstance(raw, dict) else {}
        child = str(branch.get("child_report_id") or "")
        child_hash = str(branch.get("child_formula_hash") or "")
        law_id = str(branch.get("law_id") or "")
        branch_role = str(branch.get("branch_role") or "")
        if not child or not child_hash:
            raise ValueError(f"{TOKEN_APPROVAL_INVALID}: branch[{idx}] child identity missing")
        if child == report_id or child in child_ids:
            raise ValueError(f"{TOKEN_CHILD_COLLISION}: branch[{idx}]")
        if child_hash in child_hashes:
            raise ValueError(f"{TOKEN_DUP_HASH}: branch[{idx}]")
        adapter_path_raw = branch.get("adapter_synthesis_path")
        adapter_sha = str(branch.get("adapter_synthesis_sha256") or "")
        if not isinstance(adapter_path_raw, str) or not adapter_path_raw or not adapter_sha:
            raise ValueError(f"{TOKEN_APPROVAL_INVALID}: branch[{idx}] adapter synthesis identity missing")
        adapter_path = Path(adapter_path_raw).expanduser()
        if not adapter_path.is_absolute():
            adapter_path = root / adapter_path
        if not adapter_path.exists():
            raise ValueError(f"{TOKEN_APPROVAL_INVALID}: branch[{idx}] adapter synthesis missing")
        if sha256_file(adapter_path) != adapter_sha:
            raise ValueError(f"{TOKEN_ADAPTER_CHANGED}: branch[{idx}] adapter synthesis changed after approval")
        adapter = load_json(adapter_path)
        selected = adapter.get("selected_revision") if isinstance(adapter.get("selected_revision"), dict) else {}
        branch_context = adapter.get("branch_context") if isinstance(adapter.get("branch_context"), dict) else {}
        if (
            str(selected.get("child_formula") or "") != str(branch.get("child_formula") or "")
            or str(selected.get("law_id") or "") != law_id
            or str(branch_context.get("child_report_id") or "") != child
            or str(branch_context.get("law_id") or "") != law_id
            or str(branch_context.get("branch_role") or "") != branch_role
            or str(adapter.get("source_multibranch_synthesis_sha256") or "") != str(approval.get("source_multibranch_synthesis_sha256") or "")
        ):
            raise ValueError(f"{TOKEN_ADAPTER_CHANGED}: branch[{idx}] adapter synthesis content mismatch")
        child_ids.add(child)
        child_hashes.add(child_hash)


def run_child_materializer(root: Path, parent: str, branch: dict[str, Any], approval: dict[str, Any]) -> dict[str, Any]:
    child = str(branch["child_report_id"])
    branch_context = branch.get("branch_context") if isinstance(branch.get("branch_context"), dict) else {}
    command = [
        sys.executable,
        str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "materialize_step6_child_revision.py"),
        "--parent-report-id",
        parent,
        "--child-report-id",
        child,
        "--factorforge-root",
        str(root),
        "--synthesis-path",
        str(branch["adapter_synthesis_path"]),
        "--branch-group-id",
        str(approval["branch_group_id"]),
        "--branch-index",
        str(branch["branch_index"]),
        "--branch-role",
        str(branch["branch_role"]),
        "--branch-law-id",
        str(branch.get("law_id") or branch_context.get("law_id")),
        "--source-multibranch-synthesis-path",
        str(approval["source_multibranch_synthesis_path"]),
        "--source-multibranch-synthesis-sha256",
        str(approval["source_multibranch_synthesis_sha256"]),
        "--sibling-branch-count",
        str(approval["selected_branch_count"]),
    ]
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    env["FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE"] = "1"
    proc = subprocess.run(command, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    materialization_path = child_materialization_report_path(root, parent, child)
    spec_path = executable_revision_spec_path(root, child)
    return {
        "child_report_id": child,
        "branch_role": branch.get("branch_role"),
        "branch_index": branch.get("branch_index"),
        "law_id": branch.get("law_id") or branch_context.get("law_id"),
        "child_formula_hash": branch.get("child_formula_hash"),
        "materialization_command": command,
        "materialization_rc": proc.returncode,
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "materialization_report_path": str(materialization_path),
        "executable_revision_spec_path": str(spec_path),
        "materialization_report_exists": materialization_path.exists(),
        "executable_revision_spec_exists": spec_path.exists(),
    }


def existing_materialization_reusable(root: Path, report_id: str, approval: dict[str, Any], *, loop_index: int) -> dict[str, Any] | None:
    path = aggregate_report_path(root, report_id, loop_index)
    if not path.exists():
        return None
    report = load_json(path)
    if (
        report.get("contract_version") != MATERIALIZATION_VERSION
        or report.get("status") != "PASS"
        or report.get("parent_report_id") != report_id
        or int(report.get("loop_index") or -1) != loop_index
        or str(report.get("source_multibranch_synthesis_sha256") or "") != str(approval.get("source_multibranch_synthesis_sha256") or "")
        or int(report.get("selected_branch_count") or -1) != int(approval.get("selected_branch_count") or -2)
    ):
        return None
    children = report.get("children") if isinstance(report.get("children"), list) else []
    branches = approval.get("selected_branches") if isinstance(approval.get("selected_branches"), list) else []
    if len(children) != len(branches):
        return None
    by_child = {str(child.get("child_report_id") or ""): child for child in children if isinstance(child, dict)}
    for branch in branches:
        child_id = str(branch.get("child_report_id") or "")
        child = by_child.get(child_id)
        if not child:
            return None
        expected = {
            "branch_role": str(branch.get("branch_role") or ""),
            "branch_index": int(branch.get("branch_index") or -1),
            "law_id": str(branch.get("law_id") or ""),
            "child_formula_hash": str(branch.get("child_formula_hash") or ""),
        }
        actual = {
            "branch_role": str(child.get("branch_role") or ""),
            "branch_index": int(child.get("branch_index") or -1),
            "law_id": str(child.get("law_id") or ""),
            "child_formula_hash": str(child.get("child_formula_hash") or ""),
        }
        if actual != expected:
            return None
        report_path_raw = str(child.get("materialization_report_path") or "")
        spec_path_raw = str(child.get("executable_revision_spec_path") or "")
        if not report_path_raw or not spec_path_raw:
            return None
        report_path = Path(report_path_raw)
        spec_path = Path(spec_path_raw)
        if not report_path.is_absolute():
            report_path = root / report_path
        if not spec_path.is_absolute():
            spec_path = root / spec_path
        if not report_path.exists() or not spec_path.exists():
            return None
        child_report = load_json(report_path)
        child_spec = load_json(spec_path)
        if (
            str(child_report.get("child_report_id") or "") != child_id
            or str(child_report.get("child_formula_hash") or "") != expected["child_formula_hash"]
            or str(child_spec.get("child_report_id") or "") != child_id
            or str(child_spec.get("child_formula_hash") or "") != expected["child_formula_hash"]
        ):
            return None
    reused = dict(report)
    reused["materialization_reused"] = True
    reused["reused_existing_report_path"] = str(path)
    return reused


def materialize(root: Path, report_id: str, *, loop_index: int) -> dict[str, Any]:
    path = approval_path(root, report_id)
    if not path.exists():
        raise ValueError(TOKEN_APPROVAL_MISSING)
    approval = load_json(path)
    validate_approval(root, report_id, approval)
    existing = existing_materialization_reusable(root, report_id, approval, loop_index=loop_index)
    if existing is not None:
        print(f"SKIPPED_EXISTING_MULTIBRANCH_MATERIALIZATION: {aggregate_report_path(root, report_id, loop_index)}")
        return existing
    children: list[dict[str, Any]] = []
    for branch in approval["selected_branches"]:
        result = run_child_materializer(root, report_id, branch, approval)
        children.append(result)
        if result["materialization_rc"] != 0:
            payload = base_report(root, report_id, approval, loop_index, children, status="BLOCK")
            payload["block_reason"] = TOKEN_FAILED
            write_json(aggregate_report_path(root, report_id, loop_index), payload)
            raise ValueError(TOKEN_FAILED)
    payload = base_report(root, report_id, approval, loop_index, children, status="PASS")
    write_json(aggregate_report_path(root, report_id, loop_index), payload)
    return payload


def base_report(root: Path, report_id: str, approval: dict[str, Any], loop_index: int, children: list[dict[str, Any]], *, status: str) -> dict[str, Any]:
    return {
        "contract_version": MATERIALIZATION_VERSION,
        "created_at_utc": utc_now(),
        "status": status,
        "parent_report_id": report_id,
        "loop_index": loop_index,
        "branch_group_id": approval.get("branch_group_id"),
        "source_approval_path": str(approval_path(root, report_id)),
        "source_multibranch_synthesis_path": approval.get("source_multibranch_synthesis_path"),
        "source_multibranch_synthesis_sha256": approval.get("source_multibranch_synthesis_sha256"),
        "selected_branch_count": approval.get("selected_branch_count"),
        "children": children,
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "clean_data_touched": False,
        "official_promotion_written": False,
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Materialize all approved children from a main-agent multibranch synthesis approval.")
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--factorforge-root", default=None)
    ap.add_argument("--loop-index", type=int, default=1)
    ap.add_argument("--allow-manual", action="store_true")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if os.environ.get("FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE") != "1" and not args.allow_manual:
        print(TOKEN_NOT_ENABLED)
        return 1
    try:
        ctx = resolve_factorforge_context(args.factorforge_root)
        report = materialize(ctx.factorforge_root, args.report_id, loop_index=args.loop_index)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report.get("materialization_reused") is True:
        print("SKIPPED_EXISTING_MULTIBRANCH_MATERIALIZATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
