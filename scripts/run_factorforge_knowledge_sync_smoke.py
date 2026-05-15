#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOTS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
POLLUTION_MARKERS = ["FACTORFORGE_KNOWLEDGE_SYNC_SMOKE", "factorforge_knowledge_sync_smoke"]


def is_tmp(path: Path) -> bool:
    raw = str(path)
    resolved = str(path.resolve())
    return raw.startswith("/tmp/") or resolved.startswith("/tmp/") or resolved.startswith("/private/tmp/")


def file_snapshot() -> set[str]:
    files: set[str] = set()
    for rel in CANONICAL_ROOTS:
        root = REPO_ROOT / rel
        if root.exists():
            files.update(str(item.relative_to(REPO_ROOT)) for item in root.rglob("*") if item.is_file())
    return files


def pollution_matches(new_files: set[str]) -> list[str]:
    return sorted(item for item in new_files if any(marker in item for marker in POLLUTION_MARKERS))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_cmd(cmd: list[str], *, env_root: Path | None = None) -> dict[str, Any]:
    env = dict(os.environ)
    if env_root is not None:
        env["FACTORFORGE_ROOT"] = str(env_root)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    return {"command": cmd, "rc": proc.returncode, "stdout_tail": proc.stdout[-5000:], "stderr_tail": proc.stderr[-5000:]}


def result(case: str, ok: bool, expected: str, actual: dict[str, Any]) -> dict[str, Any]:
    return {"case": case, "ok": bool(ok), "expected": expected, "actual": actual}


def build_source_fixture(root: Path) -> Path:
    source = root / "source_runtime"
    write_json(
        source / "objects" / "research_knowledge_base" / "knowledge_record__FACTORFORGE_KNOWLEDGE_SYNC_SMOKE.json",
        {"report_id": "FACTORFORGE_KNOWLEDGE_SYNC_SMOKE", "lesson": "smoke knowledge"},
    )
    write_json(
        source / "objects" / "factor_library_all" / "factor_record__FACTORFORGE_KNOWLEDGE_SYNC_SMOKE.json",
        {"report_id": "FACTORFORGE_KNOWLEDGE_SYNC_SMOKE", "status": "all"},
    )
    write_json(
        source / "objects" / "factor_library_official" / "factor_record__FACTORFORGE_KNOWLEDGE_SYNC_SMOKE.json",
        {"report_id": "FACTORFORGE_KNOWLEDGE_SYNC_SMOKE", "status": "official"},
    )
    vault_note = source / "knowledge" / "因子工厂" / "知识库" / "FACTORFORGE_KNOWLEDGE_SYNC_SMOKE.md"
    vault_note.parent.mkdir(parents=True, exist_ok=True)
    vault_note.write_text("# FACTORFORGE_KNOWLEDGE_SYNC_SMOKE\n\nHuman-readable vault note.\n", encoding="utf-8")
    retrieval = source / "knowledge" / "retrieval" / "factorforge_retrieval_index.jsonl"
    retrieval.parent.mkdir(parents=True, exist_ok=True)
    retrieval.write_text('{"id":"smoke","text":"retrieval smoke"}\n', encoding="utf-8")
    return source


def make_malicious_bundle(root: Path) -> Path:
    malicious = root / "malicious.tgz"
    payload = root / "evil.txt"
    payload.write_text("evil", encoding="utf-8")
    with tarfile.open(malicious, "w:gz") as tar:
        tar.add(payload, arcname="../evil.txt")
    return malicious


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=f"/tmp/factorforge_knowledge_sync_smoke")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).expanduser()
    if not is_tmp(root):
        print("BLOCK_NON_TMP_FACTORFORGE_ROOT")
        return 1
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    before = file_snapshot()
    cases: list[dict[str, Any]] = []

    source = build_source_fixture(root)
    bundle = root / "factorforge_knowledge_sync_smoke.tgz"
    bundle_proc = run_cmd(
        [
            sys.executable,
            "scripts/sync_factorforge_knowledge_bundle.py",
            "bundle",
            "--runtime-root",
            str(source),
            "--output",
            str(bundle),
            "--source-role",
            "mac_authoritative",
        ]
    )
    cases.append(result("bundle_local_pass", bundle_proc["rc"] == 0 and bundle.exists(), "local bundle created", bundle_proc))

    latest = root / "latest.json"
    latest_payload = {
        "schema_version": "factorforge_knowledge_latest_v1",
        "source_role": "mac_authoritative",
        "bundle_uri": str(bundle),
        "sha256": sha256_file(bundle),
        "size_bytes": bundle.stat().st_size,
    }
    write_json(latest, latest_payload)

    dest = root / "dest_runtime"
    apply_proc = run_cmd(
        [
            sys.executable,
            "scripts/sync_factorforge_knowledge_bundle.py",
            "apply",
            "--runtime-root",
            str(dest),
            "--source",
            str(latest),
            "--apply",
        ],
        env_root=dest,
    )
    created = dest / "objects" / "research_knowledge_base" / "knowledge_record__FACTORFORGE_KNOWLEDGE_SYNC_SMOKE.json"
    vault_created = dest / "knowledge" / "因子工厂" / "知识库" / "FACTORFORGE_KNOWLEDGE_SYNC_SMOKE.md"
    retrieval_created = dest / "knowledge" / "retrieval" / "factorforge_retrieval_index.jsonl"
    audit_files = sorted((dest / "objects" / "sync_audit").glob("sync_audit__*.json"))
    audit = load_json(audit_files[-1]) if audit_files else {}
    cases.append(
        result(
            "apply_latest_manifest_pass",
            apply_proc["rc"] == 0
            and created.exists()
            and vault_created.exists()
            and retrieval_created.exists()
            and audit.get("latest_manifest", {}).get("sha256") == latest_payload["sha256"],
            "latest manifest resolves bundle, verifies sha256, writes objects, vault, retrieval, and audit",
            {
                "proc": apply_proc,
                "created": str(created),
                "vault_created": str(vault_created),
                "retrieval_created": str(retrieval_created),
                "audit_count": len(audit_files),
            },
        )
    )

    second_proc = run_cmd(
        [
            sys.executable,
            "scripts/sync_factorforge_knowledge_bundle.py",
            "apply",
            "--runtime-root",
            str(dest),
            "--source",
            str(latest),
            "--apply",
        ],
        env_root=dest,
    )
    second_audits = sorted((dest / "objects" / "sync_audit").glob("sync_audit__*.json"))
    second_audit = load_json(second_audits[-1]) if second_audits else {}
    blocked = [item for item in second_audit.get("planned_changes", []) if item.get("action") == "overwrite-blocked"]
    cases.append(
        result(
            "protected_overwrite_blocked_pass",
            second_proc["rc"] == 0 and bool(blocked),
            "protected official/case/handoff/validation overwrite remains blocked by default",
            {"proc": second_proc, "blocked_count": len(blocked)},
        )
    )

    created.write_text('{"report_id":"STALE","status":"stale"}\n', encoding="utf-8")
    vault_created.write_text("# stale vault\n", encoding="utf-8")
    retrieval_created.write_text('{"id":"stale","text":"stale"}\n', encoding="utf-8")
    overwrite_proc = run_cmd(
        [
            sys.executable,
            "scripts/sync_factorforge_knowledge_bundle.py",
            "apply",
            "--runtime-root",
            str(dest),
            "--source",
            str(latest),
            "--apply",
            "--overwrite-unprotected",
        ],
        env_root=dest,
    )
    overwrite_audits = sorted((dest / "objects" / "sync_audit").glob("sync_audit__*.json"))
    overwrite_audit = load_json(overwrite_audits[-1]) if overwrite_audits else {}
    overwrites = [item for item in overwrite_audit.get("planned_changes", []) if item.get("action") == "overwrite"]
    still_blocked = [item for item in overwrite_audit.get("planned_changes", []) if item.get("action") == "overwrite-blocked"]
    cases.append(
        result(
            "overwrite_unprotected_pass",
            overwrite_proc["rc"] == 0
            and bool(overwrites)
            and bool(still_blocked)
            and load_json(created).get("report_id") == "FACTORFORGE_KNOWLEDGE_SYNC_SMOKE"
            and "Human-readable vault note" in vault_created.read_text(encoding="utf-8")
            and "retrieval smoke" in retrieval_created.read_text(encoding="utf-8"),
            "overwrite-unprotected refreshes ordinary objects/vault/retrieval while protected official overwrite stays blocked",
            {
                "proc": overwrite_proc,
                "overwrite_count": len(overwrites),
                "protected_blocked_count": len(still_blocked),
            },
        )
    )

    bad_latest = root / "bad_latest.json"
    bad_payload = dict(latest_payload)
    bad_payload["sha256"] = "0" * 64
    write_json(bad_latest, bad_payload)
    bad_proc = run_cmd(
        [
            sys.executable,
            "scripts/sync_factorforge_knowledge_bundle.py",
            "apply",
            "--runtime-root",
            str(root / "bad_dest"),
            "--source",
            str(bad_latest),
            "--apply",
        ]
    )
    token = "BLOCK_FACTORFORGE_KNOWLEDGE_BUNDLE_SHA256_MISMATCH"
    cases.append(
        result(
            "sha256_mismatch_block",
            bad_proc["rc"] == 1 and token in (bad_proc["stdout_tail"] + bad_proc["stderr_tail"]),
            "tampered latest sha256 blocks before apply",
            bad_proc,
        )
    )

    malicious = make_malicious_bundle(root)
    unsafe_proc = run_cmd(
        [
            sys.executable,
            "scripts/sync_factorforge_knowledge_bundle.py",
            "apply",
            "--runtime-root",
            str(root / "unsafe_dest"),
            "--source",
            str(malicious),
            "--apply",
        ]
    )
    cases.append(
        result(
            "unsafe_tar_path_block",
            unsafe_proc["rc"] == 1 and "Unsafe path in bundle" in (unsafe_proc["stdout_tail"] + unsafe_proc["stderr_tail"]),
            "tar path traversal blocks",
            unsafe_proc,
        )
    )

    after = file_snapshot()
    new_files = after - before
    pollution = pollution_matches(new_files)
    summary = {
        "verdict": "ACCEPT" if all(case["ok"] for case in cases) and not pollution else "BLOCK",
        "cases": cases,
        "canonical_pollution": {"polluted": bool(pollution), "new_files": pollution},
    }
    summary_path = root / "factorforge_knowledge_sync_smoke_summary.json"
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[SUMMARY] {summary_path}")
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
