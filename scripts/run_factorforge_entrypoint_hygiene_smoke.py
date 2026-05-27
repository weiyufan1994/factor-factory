#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "operations" / "factorforge-entrypoint-registry.json"

PRODUCTION_MAIN = {
    "scripts/prepare_factorforge_formal_artifacts.py",
    "scripts/build_factorforge_runtime_context.py",
    "scripts/run_factorforge_ultimate.py",
    "scripts/run_factorforge_ultimate_loop.py",
}
FORMAL_LLM_BOUNDARY = {
    "scripts/run_factorforge_step1_llm_bridge.py",
    "scripts/run_factorforge_step2_llm_bridge.py",
    "scripts/run_factorforge_humphrey_llm_provider.py",
}
RUNTIME_ROOTS = [
    "objects",
    "runs",
    "evaluations",
    "generated_code",
    "archive",
    "factorforge",
    "output",
    "tmp",
]
FORBIDDEN_FACTORFORGE_PATHS = [
    "scripts/topic_liquidity_hhi.py",
    "scripts/report_topic_liquidity_dragon_candidates.py",
    "scripts/ai_interests_record_candidates.remote.py",
    "scripts/append_limitup_topics_to_latest_topic_proposal.py",
    "factor_factory/data_access/topic_liquidity.py",
]


def read_registry() -> dict[str, Any]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def script_files() -> set[str]:
    return {
        str(path.relative_to(ROOT))
        for path in (ROOT / "scripts").rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and not path.name.endswith(".pyc")
    }


def registry_files(registry: dict[str, Any]) -> tuple[set[str], dict[str, list[str]]]:
    files: set[str] = set()
    owners: dict[str, list[str]] = {}
    for category, value in registry.items():
        if category in {"version", "purpose"}:
            continue
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, str):
                continue
            files.add(item)
            owners.setdefault(item, []).append(category)
    return files, owners


def case_registry_covers_scripts(registry: dict[str, Any]) -> dict[str, Any]:
    scripts = script_files()
    listed, owners = registry_files(registry)
    missing = sorted(scripts - listed)
    stale = sorted(listed - scripts)
    duplicates = {path: cats for path, cats in owners.items() if len(cats) > 1}
    return {
        "case": "entrypoint_registry_covers_every_script",
        "missing": missing,
        "stale": stale,
        "duplicates": duplicates,
        "ok": not missing and not stale and not duplicates,
    }


def case_production_entrypoints_are_single_set(registry: dict[str, Any]) -> dict[str, Any]:
    production = set(registry.get("production_main") or [])
    formal = set(registry.get("formal_llm_boundary") or [])
    return {
        "case": "production_entrypoints_are_single_set",
        "production_main": sorted(production),
        "formal_llm_boundary": sorted(formal),
        "ok": production == PRODUCTION_MAIN and formal == FORMAL_LLM_BOUNDARY,
    }


def case_runtime_dirs_absent_from_repo_root() -> dict[str, Any]:
    present = sorted(name for name in RUNTIME_ROOTS if (ROOT / name).exists())
    return {
        "case": "runtime_dirs_absent_from_repo_root",
        "present": present,
        "ok": not present,
    }


def case_provider_adapter_has_no_default_model_fallback() -> dict[str, Any]:
    path = ROOT / "scripts" / "run_factorforge_humphrey_llm_provider.py"
    text = path.read_text(encoding="utf-8")
    forbidden = [
        "DEFAULT_PROVIDER",
        "DEFAULT_STEP1_MODEL",
        "DEFAULT_STEP2_MODEL",
        "provider_wrapper_default",
    ]
    hits = [item for item in forbidden if item in text]
    required = [
        "formal_llm_provider_request object is required",
        "provider is required",
        "model is required",
    ]
    missing = [item for item in required if item not in text]
    return {
        "case": "provider_adapter_requires_bridge_contract",
        "forbidden_hits": hits,
        "missing_required_checks": missing,
        "ok": not hits and not missing,
    }


def case_deprecated_scripts_are_under_deprecated_dir(registry: dict[str, Any]) -> dict[str, Any]:
    deprecated = list(registry.get("deprecated_or_historical") or [])
    misplaced = sorted(path for path in deprecated if not path.startswith("scripts/deprecated/"))
    return {
        "case": "deprecated_scripts_are_under_deprecated_dir",
        "misplaced": misplaced,
        "ok": not misplaced,
    }


def case_adjacent_projects_migrated_out() -> dict[str, Any]:
    present = sorted(path for path in FORBIDDEN_FACTORFORGE_PATHS if (ROOT / path).exists())
    init_text = (ROOT / "factor_factory" / "data_access" / "__init__.py").read_text(encoding="utf-8")
    forbidden_exports = [
        name
        for name in [
            "align_topic_liquidity_to_daily",
            "get_topic_liquidity_leaders",
            "get_topic_liquidity_topics",
            "resolve_topic_liquidity_root",
        ]
        if name in init_text
    ]
    return {
        "case": "adjacent_projects_migrated_out",
        "present_paths": present,
        "forbidden_exports": forbidden_exports,
        "ok": not present and not forbidden_exports,
    }


def case_step12_blocks_repo_root_writes() -> dict[str, Any]:
    text = (ROOT / "scripts" / "step12_intake_common.py").read_text(encoding="utf-8")
    required = [
        "BLOCK_STEP12_ROOT_UNSPECIFIED",
        "ensure_non_repo_factorforge_root()",
        "resolve_factorforge_context",
    ]
    missing = [item for item in required if item not in text]
    return {
        "case": "step12_blocks_repo_root_writes",
        "missing": missing,
        "ok": not missing,
    }


def main() -> int:
    registry = read_registry()
    cases = [
        case_registry_covers_scripts(registry),
        case_production_entrypoints_are_single_set(registry),
        case_runtime_dirs_absent_from_repo_root(),
        case_provider_adapter_has_no_default_model_fallback(),
        case_deprecated_scripts_are_under_deprecated_dir(registry),
        case_adjacent_projects_migrated_out(),
        case_step12_blocks_repo_root_writes(),
    ]
    verdict = "ACCEPT" if all(case.get("ok") for case in cases) else "BLOCK"
    summary = {
        "version": "factorforge_entrypoint_hygiene_smoke_v1",
        "registry": str(REGISTRY),
        "verdict": verdict,
        "cases": cases,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
