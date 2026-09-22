#!/usr/bin/env python3
"""Publish a local, agent-authored Step1 packet into one factor workspace.

This is deliberately an input landing path, not a PDF/LLM bridge.  It never
calls a provider, creates a chief decision, or starts Step2--Step6.  The
caller supplies the source identity plus independently authored primary,
challenger, and chief JSON envelopes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_workspace import (
    BLOCK_OUTPUT_OUTSIDE_WORKSPACE,
    default_workspace_root,
    load_workspace_manifest,
    validate_workspace_manifest,
)
from factor_factory.measurement_program import (
    ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
    validate_measurement_program,
)
from skills.factor_forge_step1.modules.report_ingestion.builders.report_map_builder import (
    ReportMapBuilder,
)
from skills.factor_forge_step1.modules.report_ingestion.challenger.challenger_to_thesis import (
    challenger_intake_to_thesis,
)
from skills.factor_forge_step1.modules.report_ingestion.intake.pdf_skill_client import PdfSkillClient
from skills.factor_forge_step1.modules.report_ingestion.merge.merge_to_alpha_idea_master import (
    merge_to_alpha_idea_master,
)
from skills.factor_forge_step1.modules.report_ingestion.normalizers.intake_to_alpha_thesis import (
    intake_to_alpha_thesis,
)
from skills.factor_forge_step1.modules.report_ingestion.orchestration.step1_pipeline import (
    Step1Pipeline,
)
from skills.factor_forge_step1.modules.report_ingestion.registry.report_registry import ReportRegistry
from skills.factor_forge_step1.modules.report_ingestion.registry.report_source_contract import ReportSource
from skills.factor_forge_step1.modules.report_ingestion.validators.schema_validator import SchemaValidator
from skills.factor_forge_step1.modules.report_ingestion.writers.object_writer import ObjectWriter


VERSION = "factorforge_local_agent_authored_step1_v1"
SUCCESS_STATUS = "LOCAL_STEP1_INGESTED_NOT_INDEPENDENTLY_CERTIFIED"
PARTIAL_STATUS = "LOCAL_STEP1_PARTIAL_NOT_COMPLETE"
BLOCK_PREFIX = "BLOCK_LOCAL_STEP1"
SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
INTAKE_LIST_FIELDS = (
    "section_map",
    "variables",
    "signals",
    "subfactors",
    "formula_clues",
    "code_clues",
    "implementation_clues",
    "alpha_candidates",
    "evidence_clues",
    "ambiguities",
)


class LocalStep1Error(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_MISSING: {label}={path}") from exc
    except json.JSONDecodeError as exc:
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_JSON_INVALID: {label}={path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: {label} must be a JSON object")
    return payload


def require_text(payload: dict[str, Any], key: str, *, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: {label}.{key} must be a non-empty string")
    return value.strip()


def validate_authorship(payload: Any, *, role: str, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_IDENTITY_INVALID: {label}.authorship must be an object")
    agent_id = require_text(payload, "agent_id", label=f"{label}.authorship")
    actual_role = require_text(payload, "role", label=f"{label}.authorship")
    authorship = require_text(payload, "authorship", label=f"{label}.authorship")
    require_text(payload, "description", label=f"{label}.authorship")
    if actual_role != role:
        raise LocalStep1Error(
            f"{BLOCK_PREFIX}_IDENTITY_INVALID: {label}.authorship.role={actual_role!r}, expected {role!r}"
        )
    if authorship != "agent_authored":
        raise LocalStep1Error(
            f"{BLOCK_PREFIX}_IDENTITY_INVALID: {label}.authorship.authorship must be 'agent_authored'"
        )
    # Return the full caller-authored object; do not replace it with a synthetic identity.
    return deepcopy(payload)


def validate_source(payload: dict[str, Any], *, report_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if payload.get("report_id") != report_id:
        raise LocalStep1Error(f"{BLOCK_PREFIX}_IDENTITY_INVALID: source.report_id must equal --report-id")
    source = payload.get("source")
    if not isinstance(source, dict):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: source.source must be an object")
    source_type = require_text(source, "source_type", label="source.source")
    if source_type != "pdf":
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: local agent-authored Step1 accepts source.source_type='pdf'")
    require_text(source, "source_uri", label="source.source")
    require_text(source, "title", label="source.source")
    original = source.get("original_source")
    if not isinstance(original, dict):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_ORIGINAL_SOURCE_MISSING: source.source.original_source must be an object")
    content_sha256 = require_text(original, "content_sha256", label="source.source.original_source")
    if not SHA256_RE.fullmatch(content_sha256):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_ORIGINAL_SOURCE_INVALID: content_sha256 must be a 64-character SHA-256")
    require_text(original, "description", label="source.source.original_source")
    local_cache_path = Path(require_text(source, "local_cache_path", label="source.source")).expanduser()
    if not local_cache_path.is_file() or local_cache_path.suffix.lower() != ".pdf":
        raise LocalStep1Error(
            f"{BLOCK_PREFIX}_ORIGINAL_SOURCE_MISSING: source.source.local_cache_path must name an existing local PDF"
        )
    with local_cache_path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise LocalStep1Error(
                f"{BLOCK_PREFIX}_ORIGINAL_SOURCE_NOT_PDF: local_cache_path does not contain PDF header bytes"
            )
    if sha256_file(local_cache_path).lower() != content_sha256.lower():
        raise LocalStep1Error(
            f"{BLOCK_PREFIX}_ORIGINAL_SOURCE_HASH_MISMATCH: local PDF bytes do not match original_source.content_sha256"
        )
    identity = validate_authorship(payload.get("reader_identity"), role="local_source_reader", label="source")
    reading_context = payload.get("reading_context", {})
    if not isinstance(reading_context, dict):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: source.reading_context must be an object when supplied")
    return deepcopy(source), {"reader_identity": identity, "reading_context": deepcopy(reading_context)}


def validate_intake_envelope(payload: dict[str, Any], *, role: str, report_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = validate_authorship(payload.get("authorship"), role=role, label=role)
    intake = payload.get("intake")
    if not isinstance(intake, dict):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: {role}.intake must be an object")
    supplied_report_id = intake.get("report_id")
    if supplied_report_id is not None and supplied_report_id != report_id:
        raise LocalStep1Error(f"{BLOCK_PREFIX}_IDENTITY_INVALID: {role}.intake.report_id must match --report-id")
    if not isinstance(intake.get("report_meta", {}), dict):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: {role}.intake.report_meta must be an object")
    for field in INTAKE_LIST_FIELDS:
        if not isinstance(intake.get(field, []), list):
            raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: {role}.intake.{field} must be an array")
    final_factor = intake.get("final_factor")
    if not isinstance(final_factor, dict):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: {role}.intake.final_factor must be an object")
    require_text(final_factor, "name", label=f"{role}.intake.final_factor")
    if not isinstance(final_factor.get("assembly_steps"), list):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: {role}.intake.final_factor.assembly_steps must be an array")
    return deepcopy(intake), identity


def validate_chief_envelope(payload: dict[str, Any], *, report_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = validate_authorship(payload.get("authorship"), role="chief_merge", label="chief")
    chief = payload.get("chief_merge")
    if not isinstance(chief, dict):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_CHIEF_MISSING: chief.chief_merge must be an object")
    supplied_report_id = chief.get("report_id")
    if supplied_report_id is not None and supplied_report_id != report_id:
        raise LocalStep1Error(f"{BLOCK_PREFIX}_IDENTITY_INVALID: chief.chief_merge.report_id must match --report-id")
    final_factor = chief.get("final_factor")
    if not isinstance(final_factor, dict):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: chief.chief_merge.final_factor must be an object")
    require_text(final_factor, "name", label="chief.chief_merge.final_factor")
    if not isinstance(final_factor.get("assembly_steps"), list):
        raise LocalStep1Error(
            f"{BLOCK_PREFIX}_INPUT_SHAPE_INVALID: chief.chief_merge.final_factor.assembly_steps must be an array"
        )
    for field in ("chief_decision_summary", "chief_confidence", "chief_rationale"):
        require_text(chief, field, label="chief.chief_merge")
    validate_authored_research_discipline(chief)
    return deepcopy(chief), identity


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {
        "unknown", "none", "n/a", "todo", "tbd", "under_specified"
    }


def _nonempty_string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_nonempty_string(item) for item in value)


def validate_authored_research_discipline(chief: dict[str, Any]) -> None:
    """Validate authored fields without filling or rephrasing a single one."""
    discipline = chief.get("research_discipline")
    if not isinstance(discipline, dict):
        raise LocalStep1Error(
            f"{BLOCK_PREFIX}_AUTHORED_DISCIPLINE_REQUIRED: chief.chief_merge.research_discipline must be an object"
        )
    profile = discipline.get("research_compatibility_profile") or chief.get(
        "research_compatibility_profile"
    )
    flexible_local = (
        profile == ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
        and os.getenv("FACTORFORGE_LOCAL_IS_ONLY") == "1"
    )
    for field in (
        "step1_mathematical_object",
        "target_statistic_hint",
        "information_set_hint",
        "initial_return_source_hypothesis",
    ):
        if not _nonempty_string(discipline.get(field)):
            raise LocalStep1Error(f"{BLOCK_PREFIX}_AUTHORED_DISCIPLINE_INVALID: research_discipline.{field}")
    for field in ("what_must_be_true", "what_would_break_it"):
        if not _nonempty_string_list(discipline.get(field)):
            raise LocalStep1Error(f"{BLOCK_PREFIX}_AUTHORED_DISCIPLINE_INVALID: research_discipline.{field}")
    lessons = discipline.get("similar_case_lessons_imported")
    if not _nonempty_string_list(lessons) and not (
        flexible_local
        and isinstance(lessons, list)
        and not lessons
        and _nonempty_string(discipline.get("similar_case_lessons_absence_reason"))
    ):
        raise LocalStep1Error(f"{BLOCK_PREFIX}_AUTHORED_DISCIPLINE_INVALID: research_discipline.similar_case_lessons_imported")
    for field in (
        "economic_hypothesis",
        "market_process_thesis",
        "market_outcome_projection",
        "knowledge_reference_contract",
    ):
        if not isinstance(discipline.get(field), dict) or not discipline[field]:
            raise LocalStep1Error(f"{BLOCK_PREFIX}_AUTHORED_DISCIPLINE_INVALID: research_discipline.{field}")
    for field in ("math_hypothesis_candidates", "primary_mechanism_model_candidates"):
        if not isinstance(discipline.get(field), list) or not discipline[field]:
            raise LocalStep1Error(f"{BLOCK_PREFIX}_AUTHORED_DISCIPLINE_INVALID: research_discipline.{field}")
    program = discipline.get("mechanism_conditioned_measurement_program")
    node_ids = {
        str(item.get("id"))
        for item in (discipline.get("factor_knowledge_context") or {}).get("nodes", [])
        if isinstance(item, dict) and item.get("id")
    }
    node_ids.update(
        str(item)
        for item in (discipline.get("knowledge_reference_contract") or {}).get("cited_node_ids", [])
        if str(item).strip()
    )
    program_errors = validate_measurement_program(
        program,
        available_knowledge_node_ids=node_ids,
        require_web_executable=False,
        compatibility_profile=profile,
        scope="local_is_only" if os.getenv("FACTORFORGE_LOCAL_IS_ONLY") == "1" else "hosted_formal",
    )
    if program_errors:
        raise LocalStep1Error(
            f"{BLOCK_PREFIX}_AUTHORED_MEASUREMENT_PROGRAM_INVALID: {'; '.join(program_errors)}"
        )
    top_level_program = chief.get("mechanism_conditioned_measurement_program")
    if top_level_program is not None and top_level_program != program:
        raise LocalStep1Error(f"{BLOCK_PREFIX}_AUTHORED_DISCIPLINE_INCONSISTENT: top-level measurement program differs")
    for field in (
        "market_process_thesis",
        "economic_hypothesis_candidates",
        "preferred_economic_hypothesis",
        "alternative_return_source_tests",
        "primary_mathematical_model",
        "formula_as_observable_estimator",
    ):
        if field in chief and field in discipline and chief[field] != discipline[field]:
            raise LocalStep1Error(
                f"{BLOCK_PREFIX}_AUTHORED_DISCIPLINE_INCONSISTENT: chief.{field} differs from research_discipline.{field}"
            )


def validate_workspace(workspace: Path, *, report_id: str) -> dict[str, Any]:
    workspace = workspace.resolve()
    if workspace == REPO_ROOT.resolve() or workspace.name in {"objects", "knowledge", "factor_research"}:
        raise LocalStep1Error(f"{BLOCK_OUTPUT_OUTSIDE_WORKSPACE}: --factor-workspace is not one isolated factor workspace")
    manifest_path = workspace / "manifest.json"
    if not manifest_path.is_file():
        raise LocalStep1Error(f"{BLOCK_PREFIX}_WORKSPACE_MISSING: {manifest_path}")
    try:
        manifest = load_workspace_manifest(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalStep1Error(f"{BLOCK_PREFIX}_WORKSPACE_INVALID: manifest unreadable: {exc}") from exc
    failures = validate_workspace_manifest(manifest)
    if failures:
        raise LocalStep1Error(f"{BLOCK_PREFIX}_WORKSPACE_INVALID: {'; '.join(failures)}")
    if Path(str(manifest.get("workspace_root"))).expanduser().resolve() != workspace:
        raise LocalStep1Error(f"{BLOCK_PREFIX}_WORKSPACE_INVALID: manifest.workspace_root mismatch")
    expected = default_workspace_root(
        factorforge_root=Path(str(manifest["factorforge_root"])),
        factor_id=str(manifest["factor_id"]),
        research_id=str(manifest["research_id"]),
    ).resolve()
    if expected != workspace:
        raise LocalStep1Error(f"{BLOCK_PREFIX}_WORKSPACE_INVALID: workspace is not the manifest factor_research path")
    admitted_report_ids = {
        str(manifest.get("root_report_id") or ""),
        str(manifest.get("active_report_id") or ""),
        *[str(value) for value in (manifest.get("identity") or {}).get("report_ids", [])],
    }
    if report_id not in admitted_report_ids:
        raise LocalStep1Error(f"{BLOCK_PREFIX}_IDENTITY_INVALID: report_id is not admitted by workspace manifest")
    return manifest


def output_paths(workspace: Path, report_id: str) -> dict[str, Path]:
    raw_root = workspace / "step1" / "agent_authored_inputs" / report_id
    return {
        "registry": workspace / "data" / "report_ingestion" / "report_registry.json",
        "primary_intake": workspace / "objects" / "validation" / f"report_map_validation__{report_id}__intake.json",
        "primary_thesis": workspace / "objects" / "validation" / f"report_map_validation__{report_id}__alpha_thesis.json",
        "ambiguity": workspace / "objects" / "validation" / f"report_map_validation__{report_id}__ambiguity_review.json",
        "challenger_intake": workspace / "objects" / "validation" / f"report_map_validation__{report_id}__challenger_intake.json",
        "challenger_thesis": workspace / "objects" / "validation" / f"report_map_validation__{report_id}__challenger_alpha_thesis.json",
        "primary_map": workspace / "objects" / "report_maps" / f"report_map__{report_id}__primary.json",
        "challenger_map": workspace / "objects" / "report_maps" / f"report_map__{report_id}__challenger.json",
        "alpha": workspace / "objects" / "alpha_idea_master" / f"alpha_idea_master__{report_id}.json",
        "receipt": workspace / "step1" / f"local_step1_ingest__{report_id}.json",
        "partial": workspace / "step1" / f"local_step1_ingest__{report_id}__partial.json",
        "source_input": raw_root / "source.json",
        "primary_input": raw_root / "primary_intake.json",
        "challenger_input": raw_root / "challenger_intake.json",
        "chief_input": raw_root / "chief_merge.json",
    }


def assert_create_only(paths: dict[str, Path]) -> None:
    for label, path in paths.items():
        if label == "partial":
            continue
        if path.exists() or path.is_symlink():
            raise LocalStep1Error(f"{BLOCK_PREFIX}_OUTPUT_EXISTS: refusing to overwrite {label}={path}")


def write_create_only(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise LocalStep1Error(f"{BLOCK_PREFIX}_OUTPUT_EXISTS: refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_partial(path: Path, *, report_id: str, error: Exception) -> Path | None:
    if path.exists() or path.is_symlink():
        return None
    payload = {
        "contract_version": VERSION,
        "report_id": report_id,
        "status": PARTIAL_STATUS,
        "not_a_completion": True,
        "not_independently_certified": True,
        "error": f"{type(error).__name__}: {error}",
        "created_at_utc": utc_now(),
    }
    write_create_only(path, payload)
    return path


def build_pipeline(workspace: Path) -> Step1Pipeline:
    return Step1Pipeline(
        registry=ReportRegistry(workspace / "data" / "report_ingestion" / "report_registry.json"),
        # parse_response is reused as a local JSON parser only; no PDF tool or
        # provider request is built or sent on this path.
        pdf_skill_client=PdfSkillClient(model="local_agent_authored_input_no_provider"),
        report_map_builder=ReportMapBuilder(
            schema_validator=SchemaValidator(REPO_ROOT / "skills" / "factor_forge_step1" / "schemas")
        ),
        object_writer=ObjectWriter(workspace / "objects"),
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    workspace = Path(args.factor_workspace).expanduser().resolve()
    validate_workspace(workspace, report_id=args.report_id)
    paths = output_paths(workspace, args.report_id)
    try:
        source_envelope = read_json(Path(args.source_json).expanduser().resolve(), label="source-json")
        primary_envelope = read_json(Path(args.primary_intake).expanduser().resolve(), label="primary-intake")
        challenger_envelope = read_json(Path(args.challenger_intake).expanduser().resolve(), label="challenger-intake")
        chief_envelope = read_json(Path(args.chief_merge).expanduser().resolve(), label="chief-merge")
        source_payload, source_context = validate_source(source_envelope, report_id=args.report_id)
        primary_payload, primary_identity = validate_intake_envelope(
            primary_envelope, role="primary_reader", report_id=args.report_id
        )
        challenger_payload, challenger_identity = validate_intake_envelope(
            challenger_envelope, role="challenger_reader", report_id=args.report_id
        )
        chief_payload, chief_identity = validate_chief_envelope(chief_envelope, report_id=args.report_id)
        assert_create_only(paths)

        source = ReportSource(
            report_id=args.report_id,
            source_type=source_payload["source_type"],
            source_uri=source_payload["source_uri"],
            title=source_payload["title"],
            broker=source_payload.get("broker"),
            author=source_payload.get("author"),
            published_at=source_payload.get("published_at"),
            local_cache_path=source_payload.get("local_cache_path"),
            metadata=deepcopy(source_payload.get("metadata") or {}),
            tags=deepcopy(source_payload.get("tags") or []),
            status="agent_authored_local_input",
        )
        primary_text = json.dumps(primary_payload, ensure_ascii=False)
        challenger_text = json.dumps(challenger_payload, ensure_ascii=False)
        pipeline_result = build_pipeline(workspace).run_pdf_skill(source, primary_text, challenger_text)

        parser = PdfSkillClient(model="local_agent_authored_input_no_provider")
        primary = parser.parse_response(args.report_id, primary_text)
        challenger = parser.parse_response(args.report_id, challenger_text)
        alpha = merge_to_alpha_idea_master(
            primary,
            challenger,
            intake_to_alpha_thesis(primary),
            challenger_intake_to_thesis(challenger),
            chief_payload,
            agent_authored_only=True,
        )
        # Keep every supplied economic/math extension byte-for-byte in the local
        # evidence packet even if downstream normalizers only consume a subset.
        alpha.update(
            {
                "report_id": args.report_id,
                "source_uri": source.source_uri,
                "local_cache_path": source.local_cache_path,
                "local_step1_declaration": {
                    "contract_version": VERSION,
                    "status": SUCCESS_STATUS,
                    "provider_or_model_called": False,
                    "chief_generated_by_tool": False,
                    "independent_certification": False,
                    "statement": "This is a local landing of caller-supplied agent-authored inputs; it is not an independent review, provider attestation, semantic score, execution proof, or Step2--Step6 result.",
                },
                "agent_authored_evidence": {
                    "source": deepcopy(source_envelope),
                    "primary": {"authorship": primary_identity, "intake": deepcopy(primary_payload)},
                    "challenger": {"authorship": challenger_identity, "intake": deepcopy(challenger_payload)},
                    "chief": {"authorship": chief_identity, "chief_merge": deepcopy(chief_payload)},
                    "source_reading_context": source_context,
                },
            }
        )
        write_create_only(paths["source_input"], source_envelope)
        write_create_only(paths["primary_input"], primary_envelope)
        write_create_only(paths["challenger_input"], challenger_envelope)
        write_create_only(paths["chief_input"], chief_envelope)
        write_create_only(paths["alpha"], alpha)
        receipt = {
            "contract_version": VERSION,
            "report_id": args.report_id,
            "status": SUCCESS_STATUS,
            "not_independently_certified": True,
            "next_steps_started": [],
            "declaration": alpha["local_step1_declaration"],
            "artifact_paths": {
                "alpha_idea_master": str(paths["alpha"]),
                "primary_raw_input": str(paths["primary_input"]),
                "challenger_raw_input": str(paths["challenger_input"]),
                "chief_raw_input": str(paths["chief_input"]),
                "pipeline": pipeline_result,
            },
            "input_sha256": {
                "source": sha256_file(Path(args.source_json).expanduser().resolve()),
                "primary": sha256_file(Path(args.primary_intake).expanduser().resolve()),
                "challenger": sha256_file(Path(args.challenger_intake).expanduser().resolve()),
                "chief": sha256_file(Path(args.chief_merge).expanduser().resolve()),
            },
            "created_at_utc": utc_now(),
        }
        write_create_only(paths["receipt"], receipt)
        return receipt
    except Exception as exc:  # Preserve a non-completion marker; never synthesize missing inputs.
        # A duplicate target already has an authoritative create-only outcome.
        # Do not place a competing "partial" state beside it.
        if f"{BLOCK_PREFIX}_OUTPUT_EXISTS" in str(exc):
            raise LocalStep1Error(str(exc)) from exc
        partial = write_partial(paths["partial"], report_id=args.report_id, error=exc)
        raise LocalStep1Error(f"{exc}; partial_record={partial}" if partial else str(exc)) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factor-workspace", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--source-json", required=True)
    parser.add_argument("--primary-intake", required=True)
    parser.add_argument("--challenger-intake", required=True)
    parser.add_argument("--chief-merge", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2))
        return 0
    except (LocalStep1Error, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
