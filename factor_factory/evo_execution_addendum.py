from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from factor_factory.evo_v2 import (
    artifact_sha256,
    canonical_json_bytes,
    evo_v2_paths,
    load_json_object,
    sha256_file,
    stable_json_hash,
    validate_experience_transfer_bundle,
    validate_transfer_use_receipt,
    with_content_hash,
)
from factor_factory.formula.parser import parse_formula
from factor_factory.evo_memory_runtime import protected_contract_hashes
from factor_factory.console.web_research_plan import (
    WebResearchPlanError,
    validate_materialized_web_research,
)
from factor_factory.research_conjecture import workspace_runtime_trust_manifest
from factor_factory.research_org.runtime_trust import (
    validate_public_trust_manifest,
    verify_signed_receipt_with_manifest,
)
from factor_factory.researcher_memory import (
    _evo_v2_transfer_use_change_receipt_reasons,
)
from factor_factory.evo_child_execution import (
    EVO_CHILD_EXECUTION_RESULT_VERSION,
    EVO_CHILD_EXECUTION_VERIFIER_CONTRACT_VERSION,
    EVO_CHILD_EXECUTION_VERIFIER_ID,
    validate_evidence_obligation_contract,
)


EXECUTION_ADDENDUM_VERSION = "factorforge_evo_execution_addendum_v1"
EXECUTION_ADDENDUM_RECEIPT_TYPE = "EVO_V2_EXECUTION_ADDENDUM_ADMITTED"
BLOCK_EVO_EXECUTION_ADDENDUM = (
    "BLOCK_FACTORFORGE_EVO_V2_EXECUTION_ADDENDUM_INVALID"
)

EXECUTION_TARGETS = {"FRESH_CHILD_PURGED_IS"}
IMPLEMENTATION_MODES = {
    "FORMULA_DIAGNOSTIC",
    "EVIDENCE_OBLIGATION",
}
REGISTERED_STATUS = "PREREGISTERED_AND_BOUND_NOT_EVALUATED"
ADDENDUM_STATUS = (
    "HOST_ATTESTED_PREREGISTERED_TRANSFER_TESTS_NOT_EXECUTED"
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TEST_FIELDS = {
    "test_id",
    "mapping_id",
    "disposition",
    "research_effect",
    "generated_question_ids",
    "statement",
    "source_distinguishing_test",
    "transferred_prediction",
    "execution_stage",
    "implementation_mode",
    "formula_or_law",
    "signal_column",
    "expected_signature",
    "falsifier",
    "required_evidence",
    "mechanism_prediction_ids",
    "economic_signature_ids",
    "multiple_testing_family",
    "affects_acceptance",
    "information_set",
    "current_factor_evidence",
    "status",
}
_PRIVATE_REF_FIELDS = {
    "admission_id",
    "admission_sha256",
    "relative_path",
    "file_sha256",
    "semantic_authority",
}
_PLAN_REF_FIELDS = {"path", "sha256", "semantic_sha256"}
FROZEN_WEB_RESEARCH_PLAN_PATH = "identity/web_research_plan.json"
# Backward-compatible public names.  The executable verifier module is the
# sole owner of their values and source-code binding.
EVO_CHILD_RESULT_CONTRACT_VERSION = EVO_CHILD_EXECUTION_RESULT_VERSION
EVO_CHILD_RESULT_VERIFIER_ID = EVO_CHILD_EXECUTION_VERIFIER_ID
EVO_CHILD_RESULT_VERIFIER_CONTRACT_VERSION = (
    EVO_CHILD_EXECUTION_VERIFIER_CONTRACT_VERSION
)
_AUTHORITY = {
    "knowledge_authority": "advisory_only",
    "preregistration_state": REGISTERED_STATUS,
    "execution_completed": False,
    "current_factor_evidence": False,
    "factor_verdict": "NOT_ISSUED",
    "protected_contract_change_allowed": False,
    "child_materialization_allowed": False,
    "child_execution_allowed": False,
    "oos_accessed": False,
    "canonical_memory_write_allowed": False,
    "skill_or_policy_mutation_allowed": False,
}


class EvoExecutionAddendumError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = list(
            dict.fromkeys(str(reason) for reason in reasons if str(reason))
        )
        super().__init__(";".join(self.reasons))


def _token(reason: str) -> str:
    return f"{BLOCK_EVO_EXECUTION_ADDENDUM}:{reason}"


def execution_addendum_path(workspace_root: Path, report_id: str) -> Path:
    if not isinstance(report_id, str) or _SAFE_ID.fullmatch(report_id) is None:
        raise EvoExecutionAddendumError([_token("report_id")])
    return (
        Path(workspace_root)
        / "objects"
        / "evo_v2"
        / report_id
        / "execution_addendum.json"
    )


def _within(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError:
        return False
    return True


def _canonical_payload(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise EvoExecutionAddendumError([_token(f"missing_or_unsafe:{path.name}")])
    try:
        payload = load_json_object(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise EvoExecutionAddendumError([_token(f"invalid_json:{path.name}")]) from exc
    if path.read_bytes() != canonical_json_bytes(payload):
        raise EvoExecutionAddendumError([_token(f"noncanonical_json:{path.name}")])
    return payload


def _ref_for(root: Path, path: Path) -> dict[str, str]:
    candidate = path.resolve(strict=True)
    if not _within(root, candidate) or not candidate.is_file():
        raise EvoExecutionAddendumError([_token(f"unsafe_ref:{path.name}")])
    return {
        "path": candidate.relative_to(root).as_posix(),
        "sha256": sha256_file(candidate),
    }


def _resolve_ref(root: Path, reference: Any, *, label: str) -> Path | None:
    if not isinstance(reference, Mapping) or set(reference) != {"path", "sha256"}:
        return None
    raw = reference.get("path")
    digest = reference.get("sha256")
    if (
        not isinstance(raw, str)
        or "\\" in raw
        or not isinstance(digest, str)
        or _SHA256.fullmatch(digest) is None
    ):
        return None
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != raw:
        return None
    candidate = root.joinpath(*relative.parts)
    if (
        not _within(root, candidate)
        or not candidate.is_file()
        or candidate.is_symlink()
        or sha256_file(candidate) != digest
    ):
        return None
    return candidate


def _private_ref_reasons(reference: Any) -> list[str]:
    if not isinstance(reference, Mapping) or set(reference) != _PRIVATE_REF_FIELDS:
        return ["private_admission_ref.fields"]
    reasons: list[str] = []
    for field in ("admission_id", "relative_path", "semantic_authority"):
        if not isinstance(reference.get(field), str) or not reference[field]:
            reasons.append(f"private_admission_ref.{field}")
    for field in ("admission_sha256", "file_sha256"):
        if (
            not isinstance(reference.get(field), str)
            or _SHA256.fullmatch(reference[field]) is None
        ):
            reasons.append(f"private_admission_ref.{field}")
    if reference.get("semantic_authority") != "factor_factory.evo_v2":
        reasons.append("private_admission_ref.semantic_authority")
    relative = PurePosixPath(str(reference.get("relative_path") or ""))
    if relative.is_absolute() or ".." in relative.parts:
        reasons.append("private_admission_ref.relative_path")
    return reasons


def _private_admission_readback_reasons(
    *,
    admissions_root: Path | None,
    reference: Any,
    transfer_bundle: Mapping[str, Any],
    transfer_use_receipt: Mapping[str, Any],
    trust_store: Any,
    repository_root: Path,
) -> list[str]:
    reasons = _private_ref_reasons(reference)
    if reasons:
        return reasons
    if admissions_root is None:
        return ["private_admission_readback_root_required"]
    try:
        root = Path(admissions_root).expanduser().resolve(strict=True)
        from factor_factory.researcher_memory import load_evo_v2_memory_admissions

        admissions = load_evo_v2_memory_admissions(
            root=root,
            repo_root=repository_root,
            trust_store=trust_store,
            source_workspace=None,
        )
    except (OSError, ValueError, TypeError) as exc:
        return [f"private_admission_readback:{type(exc).__name__}"]
    matching = [
        admission
        for admission in admissions
        if admission.get("admission_id") == reference.get("admission_id")
    ]
    path = root / str(reference.get("relative_path") or "")
    if (
        len(matching) != 1
        or matching[0].get("admission_sha256") != reference.get("admission_sha256")
        or matching[0].get("core_payloads", {}).get("experience_transfer_bundle")
        != transfer_bundle
        or matching[0].get("core_payloads", {}).get("transfer_use_receipt")
        != transfer_use_receipt
        or path.is_symlink()
        or not path.is_file()
        or sha256_file(path) != reference.get("file_sha256")
    ):
        reasons.append("private_admission_readback")
    return reasons


def _frozen_protected_contract_reasons(
    *,
    root: Path,
    change_receipt: Mapping[str, Any],
    repository_root: Path,
) -> list[str]:
    plan_path = root / "identity" / "web_research_plan.json"
    if plan_path.is_symlink() or not plan_path.is_file():
        return ["frozen_web_research_plan_required"]
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        expected = protected_contract_hashes(plan=plan, worktree=repository_root)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        return [f"frozen_protected_contracts:{type(exc).__name__}"]
    if change_receipt.get("protected_contracts") != expected:
        return ["protected_contracts_frozen_readback_mismatch"]
    return []


def _frozen_web_research_plan(
    *,
    root: Path,
    report_id: str,
    artifact_identity: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Load the one canonical, fully materialized parent research plan.

    The execution addendum is a child preregistration artifact.  It must not
    select columns from a plan-shaped JSON object that has never passed the
    Web materialization/readback gate or that belongs to another identity.
    """

    path = root / FROZEN_WEB_RESEARCH_PLAN_PATH
    reasons: list[str] = []
    if path.is_symlink() or not path.is_file() or not _within(root, path):
        return {}, {}, ["frozen_web_research_plan_json"]
    try:
        plan = load_json_object(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return {}, {}, ["frozen_web_research_plan_json"]
    try:
        materialized = validate_materialized_web_research(root)
    except (WebResearchPlanError, OSError, UnicodeError, ValueError, KeyError) as exc:
        reasons.append(f"frozen_web_research_plan_not_formal:{type(exc).__name__}")
        materialized = {}
    identity = plan.get("identity") if isinstance(plan, Mapping) else None
    if not isinstance(identity, Mapping):
        reasons.append("frozen_web_research_plan.identity")
    else:
        expected = {
            "factor_id": artifact_identity.get("factor_id"),
            "report_id": report_id,
            "research_id": artifact_identity.get("research_id"),
        }
        for field, value in expected.items():
            if identity.get(field) != value:
                reasons.append(f"frozen_web_research_plan.identity.{field}")
    file_sha256 = sha256_file(path)
    if materialized and materialized.get("plan_sha256") != file_sha256:
        reasons.append("frozen_web_research_plan.materialized_hash")
    reference = {
        "path": FROZEN_WEB_RESEARCH_PLAN_PATH,
        "sha256": file_sha256,
        "semantic_sha256": stable_json_hash(plan),
    }
    return plan, reference, reasons


def _frozen_daily_fields(plan: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    data_plan = plan.get("data_plan") if isinstance(plan, Mapping) else None
    fields = data_plan.get("daily_fields") if isinstance(data_plan, Mapping) else None
    if (
        not isinstance(fields, list)
        or not fields
        or any(not isinstance(value, str) or not value for value in fields)
    ):
        return [], ["frozen_web_research_plan.daily_fields"]
    return list(fields), []


def _validate_evidence_obligation(
    payload: Any,
    *,
    test_id: str,
    repository_root: Path,
) -> list[str]:
    fields = {
        "contract_version",
        "test_id",
        "evidence_kind",
        "artifact_contract",
        "verifier_id",
        "verifier_contract_version",
        "verifier_source_bundle_sha256",
        "input_role",
        "predicate",
        "information_set",
        "status",
        "content_sha256",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        return ["evidence_obligation.fields"]
    reasons: list[str] = []
    if payload.get("contract_version") != "factorforge_evo_execution_evidence_obligation_v1":
        reasons.append("evidence_obligation.contract_version")
    if payload.get("test_id") != test_id:
        reasons.append("evidence_obligation.test_id")
    if payload.get("evidence_kind") not in {
        "DATA_INPUT",
        "CONTROL_DATAMART",
        "VERIFIER_CONTRACT",
        "SOURCE_EVIDENCE",
    }:
        reasons.append("evidence_obligation.evidence_kind")
    for field in ("artifact_contract", "verifier_id"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            reasons.append(f"evidence_obligation.{field}")
    reasons.extend(
        validate_evidence_obligation_contract(
        payload,
        test_id=test_id,
        available_panel_columns=[
            "trade_date",
            "code",
            "future_return_1d",
            "label_start_date",
            "label_end_date",
            "label_start_price",
            "label_end_price",
        ],
        repository_root=repository_root,
        )
    )
    if payload.get("information_set") != "PURGED_IS_ONLY":
        reasons.append("evidence_obligation.information_set")
    if payload.get("status") != REGISTERED_STATUS:
        reasons.append("evidence_obligation.status")
    unsigned = {key: value for key, value in payload.items() if key != "content_sha256"}
    if payload.get("content_sha256") != stable_json_hash(unsigned):
        reasons.append("evidence_obligation.content_sha256")
    return reasons


def _load_after_plan(
    root: Path,
    change_receipt: Mapping[str, Any],
) -> tuple[dict[str, str], list[str]]:
    reasons: list[str] = []
    path = _resolve_ref(
        root,
        change_receipt.get("after_research_plan_ref"),
        label="after_research_plan",
    )
    if path is None:
        return {}, ["after_research_plan_ref"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, ["after_research_plan_json"]
    values = payload.get("registered_tests") if isinstance(payload, Mapping) else None
    if not isinstance(values, list):
        return {}, ["after_research_plan.registered_tests"]
    tests: dict[str, str] = {}
    for index, item in enumerate(values):
        if (
            not isinstance(item, Mapping)
            or set(item) != {"test_id", "text"}
            or not isinstance(item.get("test_id"), str)
            or _SAFE_ID.fullmatch(item["test_id"]) is None
            or not isinstance(item.get("text"), str)
            or not item["text"].strip()
        ):
            reasons.append(f"after_research_plan.registered_tests[{index}]")
            continue
        if item["test_id"] in tests:
            reasons.append(f"after_research_plan.registered_tests[{index}].duplicate")
        tests[item["test_id"]] = item["text"]
    return tests, reasons


def _canonical_core(
    root: Path,
    report_id: str,
    transfer_bundle: Mapping[str, Any],
    transfer_use_receipt: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    reasons: list[str] = []
    paths = evo_v2_paths(root, report_id)
    loaded: dict[str, dict[str, Any]] = {}
    for name in (
        "mechanism_delta",
        "economic_backprojection",
        "experience_transfer_bundle",
        "transfer_use_receipt",
    ):
        path = paths[name]
        try:
            loaded[name] = _canonical_payload(path)
        except EvoExecutionAddendumError as exc:
            reasons.extend(exc.reasons)
    if reasons:
        return {}, {}, {}, {}, reasons
    if loaded["experience_transfer_bundle"] != dict(transfer_bundle):
        reasons.append("canonical_transfer_bundle_mismatch")
    if loaded["transfer_use_receipt"] != dict(transfer_use_receipt):
        reasons.append("canonical_transfer_use_receipt_mismatch")
    known = {
        path.relative_to(root).as_posix(): loaded[name]
        for name, path in paths.items()
        if name in loaded
    }
    reasons.extend(
        f"experience_transfer_bundle:{reason}"
        for reason in validate_experience_transfer_bundle(
            loaded["experience_transfer_bundle"],
            mechanism_delta=loaded["mechanism_delta"],
            economic_backprojection=loaded["economic_backprojection"],
            workspace_root=root,
            known_artifacts=known,
            verify_refs=True,
        )
    )
    reasons.extend(
        f"transfer_use_receipt:{reason}"
        for reason in validate_transfer_use_receipt(
            loaded["transfer_use_receipt"],
            transfer_bundle=loaded["experience_transfer_bundle"],
            mechanism_delta=loaded["mechanism_delta"],
            workspace_root=root,
            known_artifacts=known,
            verify_refs=True,
        )
    )
    identity = loaded["experience_transfer_bundle"].get("artifact_identity")
    if (
        not isinstance(identity, Mapping)
        or identity.get("report_id") != report_id
        or any(
            loaded[name].get("artifact_identity") != identity
            for name in loaded
        )
    ):
        reasons.append("artifact_identity_mismatch")
    memory_state = (
        loaded["experience_transfer_bundle"]
        .get("retrieval_policy", {})
        .get("memory_state")
    )
    if memory_state != "ADMISSIBLE_MEMORY_FOUND":
        reasons.append("positive_memory_found_required")
    if loaded["transfer_use_receipt"].get("transfer_mode") != "MAPPINGS_USED":
        reasons.append("mappings_used_required")
    return (
        loaded["mechanism_delta"],
        loaded["economic_backprojection"],
        loaded["experience_transfer_bundle"],
        loaded["transfer_use_receipt"],
        list(dict.fromkeys(reasons)),
    )


def _validate_tests(
    *,
    tests: Any,
    execution_target: str,
    transfer_bundle: Mapping[str, Any],
    transfer_use_receipt: Mapping[str, Any],
    change_receipt: Mapping[str, Any],
    mechanism_delta: Mapping[str, Any],
    economic_backprojection: Mapping[str, Any],
    after_plan_tests: Mapping[str, str],
    required_evidence_refs: Mapping[str, Mapping[str, str]],
    required_evidence_payloads: Mapping[str, Mapping[str, Any]],
    available_columns: Sequence[str],
    repository_root: Path,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(tests, list) or not tests:
        return ["execution_tests.nonempty_array_required"]
    mappings = {
        str(item.get("mapping_id") or ""): item
        for item in transfer_bundle.get("transfer_mappings") or []
        if isinstance(item, Mapping)
    }
    uses = [
        item
        for item in transfer_use_receipt.get("uses") or []
        if isinstance(item, Mapping)
    ]
    change_uses = {
        str(item.get("mapping_id") or ""): item
        for item in change_receipt.get("mapping_uses") or []
        if isinstance(item, Mapping)
    }
    expected_mapping_order = [str(item.get("mapping_id") or "") for item in uses]
    expected_test_ids = [str(item.get("generated_test_id") or "") for item in uses]
    added_test_ids = list(
        (change_receipt.get("question_and_test_diff") or {}).get("added_test_ids")
        or []
    )
    observed_mapping_order: list[str] = []
    observed_test_ids: list[str] = []
    covered_predictions: set[str] = set()
    covered_economic: set[str] = set()
    for index, item in enumerate(tests):
        prefix = f"execution_tests[{index}]"
        if not isinstance(item, Mapping) or set(item) != _TEST_FIELDS:
            reasons.append(f"{prefix}.fields")
            continue
        test_id = str(item.get("test_id") or "")
        mapping_id = str(item.get("mapping_id") or "")
        if _SAFE_ID.fullmatch(test_id) is None:
            reasons.append(f"{prefix}.test_id")
        if _SAFE_ID.fullmatch(mapping_id) is None:
            reasons.append(f"{prefix}.mapping_id")
        observed_test_ids.append(test_id)
        observed_mapping_order.append(mapping_id)
        source_mapping = mappings.get(mapping_id)
        source_use = next(
            (use for use in uses if use.get("mapping_id") == mapping_id),
            None,
        )
        change_use = change_uses.get(mapping_id)
        if source_mapping is None or source_use is None or change_use is None:
            reasons.append(f"{prefix}.mapping_binding")
            continue
        if (
            test_id != source_use.get("generated_test_id")
            or item.get("disposition") != source_use.get("disposition")
            or item.get("research_effect") != source_use.get("research_effect")
            or item.get("generated_question_ids")
            != change_use.get("generated_question_ids")
            or item.get("source_distinguishing_test")
            != source_mapping.get("distinguishing_test")
            or item.get("transferred_prediction")
            != source_mapping.get("transferred_prediction")
        ):
            reasons.append(f"{prefix}.source_binding")
        all_prediction_ids = {
            str(item.get("prediction_id") or "")
            for item in mechanism_delta.get("distinctive_predictions") or []
            if isinstance(item, Mapping)
        }
        all_economic_ids = {
            str(item.get("signature_id") or "")
            for item in economic_backprojection.get("predicted_economic_signatures") or []
            if isinstance(item, Mapping)
        }
        disposition = source_mapping.get("disposition")
        expected_prediction_ids = (
            all_prediction_ids
            if disposition in {"adopted_for_test_only", "challenge_only"}
            else set()
        )
        expected_economic_ids = (
            all_economic_ids if disposition == "adopted_for_test_only" else set()
        )
        if item.get("statement") != after_plan_tests.get(test_id):
            reasons.append(f"{prefix}.after_plan_statement_binding")
        if item.get("execution_stage") != execution_target:
            reasons.append(f"{prefix}.execution_stage")
        mode = item.get("implementation_mode")
        formula = item.get("formula_or_law")
        signal_column = item.get("signal_column")
        if mode not in IMPLEMENTATION_MODES:
            reasons.append(f"{prefix}.implementation_mode")
        elif mode == "FORMULA_DIAGNOSTIC":
            formula_ir = (
                parse_formula(formula, available_columns=list(available_columns))
                if isinstance(formula, str)
                else {}
            )
            if (
                not isinstance(formula, str)
                or not formula.strip()
                or not isinstance(signal_column, str)
                or _SAFE_ID.fullmatch(signal_column) is None
                or formula_ir.get("parse_status") != "success"
                or not formula_ir.get("required_fields")
                or signal_column != f"evo_diagnostic__{test_id}"
            ):
                reasons.append(f"{prefix}.formula_diagnostic")
        elif formula is not None or signal_column is not None:
            reasons.append(f"{prefix}.evidence_obligation_formula_must_be_null")
        for field in (
            "statement",
            "source_distinguishing_test",
            "transferred_prediction",
            "expected_signature",
            "falsifier",
            "multiple_testing_family",
        ):
            if not isinstance(item.get(field), str) or not item[field].strip():
                reasons.append(f"{prefix}.{field}")
        if item.get("multiple_testing_family") != "diagnostic_only_no_acceptance":
            reasons.append(f"{prefix}.multiple_testing_family")
        if item.get("affects_acceptance") is not False:
            reasons.append(f"{prefix}.affects_acceptance")
        if item.get("information_set") != "PURGED_IS_ONLY":
            reasons.append(f"{prefix}.information_set")
        if item.get("current_factor_evidence") is not False:
            reasons.append(f"{prefix}.current_factor_evidence")
        if item.get("status") != REGISTERED_STATUS:
            reasons.append(f"{prefix}.status")
        required = item.get("required_evidence")
        if (
            not isinstance(required, list)
            or not required
            or any(not isinstance(value, str) or not value.strip() for value in required)
        ):
            reasons.append(f"{prefix}.required_evidence")
        elif any(value not in required_evidence_refs for value in required):
            reasons.append(f"{prefix}.required_evidence_unbound")
        else:
            for value in required:
                reasons.extend(
                    f"{prefix}.{reason}"
                    for reason in _validate_evidence_obligation(
                        required_evidence_payloads.get(value),
                        test_id=test_id,
                        repository_root=repository_root,
                    )
                )
        for field, accumulator in (
            ("mechanism_prediction_ids", covered_predictions),
            ("economic_signature_ids", covered_economic),
        ):
            values = item.get(field)
            if (
                not isinstance(values, list)
                or any(
                    not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None
                    for value in values
                )
                or len(values) != len(set(values))
            ):
                reasons.append(f"{prefix}.{field}")
            else:
                accumulator.update(values)
                expected_values = (
                    expected_prediction_ids
                    if field == "mechanism_prediction_ids"
                    else expected_economic_ids
                )
                if set(values) != expected_values:
                    reasons.append(f"{prefix}.{field}.mapping_coverage")
        questions = item.get("generated_question_ids")
        if (
            not isinstance(questions, list)
            or any(
                not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None
                for value in questions
            )
        ):
            reasons.append(f"{prefix}.generated_question_ids")
    if observed_mapping_order != expected_mapping_order:
        reasons.append("execution_tests.mapping_order")
    if observed_test_ids != expected_test_ids:
        reasons.append("execution_tests.test_id_order")
    if sorted(observed_test_ids) != sorted(added_test_ids):
        reasons.append("execution_tests.change_receipt_test_coverage")
    if len(observed_test_ids) != len(set(observed_test_ids)):
        reasons.append("execution_tests.duplicate_test_id")
    expected_predictions = {
        str(item.get("prediction_id") or "")
        for item in mechanism_delta.get("distinctive_predictions") or []
        if isinstance(item, Mapping)
    }
    expected_economic = {
        str(item.get("signature_id") or "")
        for item in economic_backprojection.get("predicted_economic_signatures") or []
        if isinstance(item, Mapping)
    }
    if covered_predictions != expected_predictions:
        reasons.append("execution_tests.mechanism_prediction_coverage")
    if covered_economic != expected_economic:
        reasons.append("execution_tests.economic_signature_coverage")
    return list(dict.fromkeys(reasons))


def _expected_refs(
    *,
    root: Path,
    report_id: str,
    change_receipt_ref: Mapping[str, Any],
) -> dict[str, Any]:
    paths = evo_v2_paths(root, report_id)
    refs = {
        name: _ref_for(root, paths[name])
        for name in (
            "mechanism_delta",
            "economic_backprojection",
            "experience_transfer_bundle",
            "transfer_use_receipt",
        )
    }
    change_path = _resolve_ref(root, change_receipt_ref, label="change_receipt")
    if change_path is None:
        raise EvoExecutionAddendumError([_token("change_receipt_ref")])
    refs["transfer_use_change_receipt"] = _ref_for(root, change_path)
    return refs


def _required_evidence_refs(
    *,
    root: Path,
    execution_tests: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, Any]]]:
    values: list[str] = []
    for item in execution_tests:
        for value in item.get("required_evidence") or []:
            if isinstance(value, str) and value not in values:
                values.append(value)
    output: dict[str, dict[str, str]] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for raw in values:
        relative = PurePosixPath(raw)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in raw
            or relative.as_posix() != raw
        ):
            raise EvoExecutionAddendumError([_token("required_evidence_ref_path")])
        path = root.joinpath(*relative.parts)
        if not _within(root, path) or path.is_symlink() or not path.is_file():
            raise EvoExecutionAddendumError(
                [_token(f"required_evidence_ref_missing:{raw}")]
            )
        output[raw] = _ref_for(root, path)
        payloads[raw] = _canonical_payload(path)
    return output, payloads


def _unsigned_payload(
    *,
    report_id: str,
    identity: Mapping[str, Any],
    execution_target: str,
    refs: Mapping[str, Any],
    frozen_plan_ref: Mapping[str, Any],
    change_receipt: Mapping[str, Any],
    private_admission_ref: Mapping[str, Any],
    required_evidence_refs: Mapping[str, Mapping[str, str]],
    execution_tests: Sequence[Mapping[str, Any]],
    host_attestation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": EXECUTION_ADDENDUM_VERSION,
        "report_id": report_id,
        "artifact_identity": dict(identity),
        "execution_target": execution_target,
        "source_refs": dict(refs),
        "frozen_web_research_plan_ref": dict(frozen_plan_ref),
        "before_research_plan_ref": dict(
            change_receipt["before_research_plan_ref"]
        ),
        "after_research_plan_ref": dict(change_receipt["after_research_plan_ref"]),
        "private_memory_admission_ref": dict(private_admission_ref),
        "required_evidence_refs": {
            key: dict(required_evidence_refs[key])
            for key in sorted(required_evidence_refs)
        },
        "protected_contracts": dict(change_receipt["protected_contracts"]),
        "execution_tests": [dict(item) for item in execution_tests],
        "execution_binding": {
            "state": REGISTERED_STATUS,
            "child_spec_must_consume_exact_addendum": True,
            "step4_must_emit_test_results": True,
            "formal_completion_requires_result_receipt": True,
            "registered_test_count": len(execution_tests),
            "execution_completed": False,
        },
        "host_attestation": dict(host_attestation),
        "authority": dict(_AUTHORITY),
        "status": ADDENDUM_STATUS,
    }


def build_evo_execution_addendum(
    *,
    workspace_root: Path,
    report_id: str,
    transfer_bundle: Mapping[str, Any],
    transfer_use_receipt: Mapping[str, Any],
    change_receipt: Mapping[str, Any],
    change_receipt_ref: Mapping[str, Any],
    private_admission_ref: Mapping[str, Any],
    execution_tests: Sequence[Mapping[str, Any]],
    execution_target: str,
    trust_store: Any,
    admissions_root: Path,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    repository = (
        Path(repository_root).expanduser().resolve(strict=True)
        if repository_root is not None
        else Path(__file__).resolve().parents[1]
    )
    if execution_target != "FRESH_CHILD_PURGED_IS":
        raise EvoExecutionAddendumError([_token("execution_target")])
    mechanism, economic, transfer, use, reasons = _canonical_core(
        root, report_id, transfer_bundle, transfer_use_receipt
    )
    reasons.extend(
        _private_admission_readback_reasons(
            admissions_root=admissions_root,
            reference=private_admission_ref,
            transfer_bundle=transfer,
            transfer_use_receipt=use,
            trust_store=trust_store,
            repository_root=repository,
        )
    )
    reasons.extend(
        _evo_v2_transfer_use_change_receipt_reasons(
            change_receipt,
            transfer_bundle=transfer,
            transfer_receipt=use,
            trust_store=trust_store,
            workspace=root,
            verify_refs=True,
        )
        if transfer and use
        else ["transfer_use_change_receipt.unbound"]
    )
    identity = transfer.get("artifact_identity") if transfer else {}
    plan, frozen_plan_ref, plan_reasons = _frozen_web_research_plan(
        root=root,
        report_id=report_id,
        artifact_identity=(identity if isinstance(identity, Mapping) else {}),
    )
    reasons.extend(plan_reasons)
    after_tests, after_reasons = _load_after_plan(root, change_receipt)
    reasons.extend(after_reasons)
    reasons.extend(
        _frozen_protected_contract_reasons(
            root=root,
            change_receipt=change_receipt,
            repository_root=repository,
        )
    )
    try:
        evidence_refs, evidence_payloads = _required_evidence_refs(
            root=root,
            execution_tests=execution_tests,
        )
    except EvoExecutionAddendumError as exc:
        reasons.extend(exc.reasons)
        evidence_refs = {}
        evidence_payloads = {}
    available_columns, columns_reasons = _frozen_daily_fields(plan)
    reasons.extend(columns_reasons)
    reasons.extend(
        _validate_tests(
            tests=list(execution_tests),
            execution_target=execution_target,
            transfer_bundle=transfer,
            transfer_use_receipt=use,
            change_receipt=change_receipt,
            mechanism_delta=mechanism,
            economic_backprojection=economic,
            after_plan_tests=after_tests,
            required_evidence_refs=evidence_refs,
            required_evidence_payloads=evidence_payloads,
            available_columns=available_columns,
            repository_root=repository,
        )
        if transfer and use and mechanism and economic
        else ["execution_tests.unbound_core"]
    )
    if reasons:
        raise EvoExecutionAddendumError([_token(reason) for reason in reasons])
    refs = _expected_refs(
        root=root,
        report_id=report_id,
        change_receipt_ref=change_receipt_ref,
    )
    identity = transfer["artifact_identity"]
    attestation_core = {
        "receipt_type": EXECUTION_ADDENDUM_RECEIPT_TYPE,
        "identity": dict(identity),
        "bindings": {
            "report_id": report_id,
            "execution_target": execution_target,
            "source_refs": refs,
            "frozen_web_research_plan_ref": frozen_plan_ref,
            "before_research_plan_ref": dict(
                change_receipt["before_research_plan_ref"]
            ),
            "after_research_plan_ref": dict(
                change_receipt["after_research_plan_ref"]
            ),
            "private_memory_admission_ref": dict(private_admission_ref),
            "required_evidence_refs": evidence_refs,
            "protected_contracts": dict(change_receipt["protected_contracts"]),
            "execution_tests_sha256": stable_json_hash(list(execution_tests)),
        },
        "outcome": {
            "state": REGISTERED_STATUS,
            "execution_completed": False,
            "current_factor_evidence": False,
            "factor_verdict": "NOT_ISSUED",
            "child_execution_allowed": False,
        },
    }
    if trust_store is None or not hasattr(trust_store, "sign"):
        raise EvoExecutionAddendumError([_token("host_trust_store")])
    host_attestation = trust_store.sign("host_admission", attestation_core)
    payload = with_content_hash(
        _unsigned_payload(
            report_id=report_id,
            identity=identity,
            execution_target=execution_target,
            refs=refs,
            frozen_plan_ref=frozen_plan_ref,
            change_receipt=change_receipt,
            private_admission_ref=private_admission_ref,
            required_evidence_refs=evidence_refs,
            execution_tests=execution_tests,
            host_attestation=host_attestation,
        )
    )
    validation = validate_evo_execution_addendum(
        payload,
        workspace_root=root,
        transfer_bundle=transfer,
        transfer_use_receipt=use,
        change_receipt=change_receipt,
        private_admission_ref=private_admission_ref,
        trust_store=trust_store,
        verify_refs=True,
        admissions_root=admissions_root,
        repository_root=repository,
    )
    if validation:
        raise EvoExecutionAddendumError([_token(reason) for reason in validation])
    return payload


def validate_evo_execution_addendum(
    payload: Any,
    *,
    workspace_root: Path,
    transfer_bundle: Mapping[str, Any] | None = None,
    transfer_use_receipt: Mapping[str, Any] | None = None,
    change_receipt: Mapping[str, Any] | None = None,
    private_admission_ref: Mapping[str, Any] | None = None,
    trust_store: Any = None,
    verify_refs: bool = True,
    admissions_root: Path | None = None,
    repository_root: Path | None = None,
) -> list[str]:
    reasons: list[str] = []
    fields = {
        "contract_version",
        "report_id",
        "artifact_identity",
        "execution_target",
        "source_refs",
        "frozen_web_research_plan_ref",
        "before_research_plan_ref",
        "after_research_plan_ref",
        "private_memory_admission_ref",
        "required_evidence_refs",
        "protected_contracts",
        "execution_tests",
        "execution_binding",
        "host_attestation",
        "authority",
        "status",
        "content_sha256",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        return ["execution_addendum.fields"]
    report_id = payload.get("report_id")
    if not isinstance(report_id, str) or _SAFE_ID.fullmatch(report_id) is None:
        reasons.append("execution_addendum.report_id")
        return reasons
    root = Path(workspace_root).expanduser().resolve(strict=True)
    repository = (
        Path(repository_root).expanduser().resolve(strict=True)
        if repository_root is not None
        else Path(__file__).resolve().parents[1]
    )
    if payload.get("contract_version") != EXECUTION_ADDENDUM_VERSION:
        reasons.append("execution_addendum.contract_version")
    target = payload.get("execution_target")
    if target != "FRESH_CHILD_PURGED_IS":
        reasons.append("execution_addendum.execution_target")
    if payload.get("status") != ADDENDUM_STATUS:
        reasons.append("execution_addendum.status")
    if payload.get("authority") != _AUTHORITY:
        reasons.append("execution_addendum.authority")
    binding = payload.get("execution_binding")
    expected_binding = {
        "state": REGISTERED_STATUS,
        "child_spec_must_consume_exact_addendum": True,
        "step4_must_emit_test_results": True,
        "formal_completion_requires_result_receipt": True,
        "registered_test_count": len(payload.get("execution_tests") or []),
        "execution_completed": False,
    }
    if binding != expected_binding:
        reasons.append("execution_addendum.execution_binding")
    if payload.get("content_sha256") != stable_json_hash(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    ):
        reasons.append("execution_addendum.content_sha256")

    mechanism: dict[str, Any] = {}
    economic: dict[str, Any] = {}
    transfer: dict[str, Any] = dict(transfer_bundle or {})
    use: dict[str, Any] = dict(transfer_use_receipt or {})
    if verify_refs:
        mechanism, economic, observed_transfer, observed_use, core_reasons = (
            _canonical_core(root, report_id, transfer, use)
        )
        reasons.extend(core_reasons)
        transfer = observed_transfer
        use = observed_use
        source_refs = payload.get("source_refs")
        change_ref = (
            source_refs.get("transfer_use_change_receipt")
            if isinstance(source_refs, Mapping)
            else None
        )
        try:
            expected_refs = _expected_refs(
                root=root,
                report_id=report_id,
                change_receipt_ref=change_ref,
            )
        except EvoExecutionAddendumError as exc:
            reasons.extend(reason.split(":", 1)[-1] for reason in exc.reasons)
            expected_refs = {}
        if source_refs != expected_refs:
            reasons.append("execution_addendum.source_refs")
    else:
        paths = evo_v2_paths(root, report_id)
        try:
            mechanism = _canonical_payload(paths["mechanism_delta"])
            economic = _canonical_payload(paths["economic_backprojection"])
        except EvoExecutionAddendumError as exc:
            reasons.extend(exc.reasons)

    if not transfer or not use:
        reasons.append("execution_addendum.core_payloads_required")
    identity = transfer.get("artifact_identity") if transfer else None
    if payload.get("artifact_identity") != identity:
        reasons.append("execution_addendum.artifact_identity")
    plan, expected_plan_ref, plan_reasons = _frozen_web_research_plan(
        root=root,
        report_id=report_id,
        artifact_identity=(identity if isinstance(identity, Mapping) else {}),
    )
    reasons.extend(plan_reasons)
    observed_plan_ref = payload.get("frozen_web_research_plan_ref")
    if (
        not isinstance(observed_plan_ref, Mapping)
        or set(observed_plan_ref) != _PLAN_REF_FIELDS
        or observed_plan_ref != expected_plan_ref
    ):
        reasons.append("execution_addendum.frozen_web_research_plan_ref")
    private_ref = payload.get("private_memory_admission_ref")
    reasons.extend(
        _private_admission_readback_reasons(
            admissions_root=admissions_root,
            reference=private_ref,
            transfer_bundle=transfer,
            transfer_use_receipt=use,
            trust_store=trust_store,
            repository_root=repository,
        )
    )
    if private_admission_ref is not None and private_ref != private_admission_ref:
        reasons.append("execution_addendum.private_admission_binding")
    source_refs = payload.get("source_refs")
    change_ref = (
        source_refs.get("transfer_use_change_receipt")
        if isinstance(source_refs, Mapping)
        else None
    )
    observed_change: dict[str, Any] = dict(change_receipt or {})
    if verify_refs:
        change_path = _resolve_ref(root, change_ref, label="change_receipt")
        if change_path is None:
            reasons.append("execution_addendum.change_receipt_ref")
        else:
            loaded_change = _canonical_payload(change_path)
            if observed_change and loaded_change != observed_change:
                reasons.append("execution_addendum.change_receipt_payload_binding")
            observed_change = loaded_change
    if not observed_change:
        reasons.append("execution_addendum.change_receipt_required")
    else:
        reasons.extend(
            f"execution_addendum.change_receipt:{reason}"
            for reason in _evo_v2_transfer_use_change_receipt_reasons(
                observed_change,
                transfer_bundle=transfer,
                transfer_receipt=use,
                trust_store=trust_store,
                workspace=root,
                verify_refs=verify_refs,
            )
        )
        if (
            payload.get("before_research_plan_ref")
            != observed_change.get("before_research_plan_ref")
            or payload.get("after_research_plan_ref")
            != observed_change.get("after_research_plan_ref")
            or payload.get("protected_contracts")
            != observed_change.get("protected_contracts")
        ):
            reasons.append("execution_addendum.change_receipt_projection")
        reasons.extend(
            _frozen_protected_contract_reasons(
                root=root,
                change_receipt=observed_change,
                repository_root=repository,
            )
        )
    evidence_refs = payload.get("required_evidence_refs")
    if not isinstance(evidence_refs, Mapping):
        reasons.append("execution_addendum.required_evidence_refs")
        evidence_refs = {}
        evidence_payloads: dict[str, dict[str, Any]] = {}
    else:
        try:
            expected_evidence_refs, evidence_payloads = _required_evidence_refs(
                root=root,
                execution_tests=payload.get("execution_tests") or [],
            )
        except EvoExecutionAddendumError as exc:
            reasons.extend(exc.reasons)
            expected_evidence_refs = {}
            evidence_payloads = {}
        if evidence_refs != expected_evidence_refs:
            reasons.append("execution_addendum.required_evidence_refs")
    after_tests, after_reasons = (
        _load_after_plan(root, observed_change) if observed_change else ({}, [])
    )
    reasons.extend(after_reasons)
    available_columns, columns_reasons = _frozen_daily_fields(plan)
    reasons.extend(columns_reasons)
    if transfer and use and observed_change and mechanism and economic:
        reasons.extend(
            _validate_tests(
                tests=payload.get("execution_tests"),
                execution_target=str(target),
                transfer_bundle=transfer,
                transfer_use_receipt=use,
                change_receipt=observed_change,
                mechanism_delta=mechanism,
                economic_backprojection=economic,
                after_plan_tests=after_tests,
                required_evidence_refs=evidence_refs,
                required_evidence_payloads=evidence_payloads,
                available_columns=available_columns,
                repository_root=repository,
            )
        )

    host = payload.get("host_attestation")
    public_manifest = workspace_runtime_trust_manifest(root, report_id=report_id)
    if (
        public_manifest is None
        or validate_public_trust_manifest(public_manifest)
    ):
        reasons.append("execution_addendum.workspace_trust_manifest")
    elif isinstance(host, Mapping):
        reasons.extend(
            f"execution_addendum.public_signature:{reason}"
            for reason in verify_signed_receipt_with_manifest(
                host,
                trust_manifest=public_manifest,
                expected_issuer="host_admission",
            )
        )
    if trust_store is None or not hasattr(trust_store, "verify"):
        reasons.append("execution_addendum.host_trust_store")
    elif not isinstance(host, Mapping):
        reasons.append("execution_addendum.host_attestation")
    else:
        reasons.extend(
            f"execution_addendum.host_signature:{reason}"
            for reason in trust_store.verify(host, expected_issuer="host_admission")
        )
        expected_host = {
            "receipt_type": EXECUTION_ADDENDUM_RECEIPT_TYPE,
            "identity": dict(identity or {}),
            "bindings": {
                "report_id": report_id,
                "execution_target": target,
                "source_refs": payload.get("source_refs"),
                "frozen_web_research_plan_ref": payload.get(
                    "frozen_web_research_plan_ref"
                ),
                "before_research_plan_ref": payload.get(
                    "before_research_plan_ref"
                ),
                "after_research_plan_ref": payload.get("after_research_plan_ref"),
                "private_memory_admission_ref": private_ref,
                "required_evidence_refs": payload.get("required_evidence_refs"),
                "protected_contracts": payload.get("protected_contracts"),
                "execution_tests_sha256": stable_json_hash(
                    payload.get("execution_tests")
                ),
            },
            "outcome": {
                "state": REGISTERED_STATUS,
                "execution_completed": False,
                "current_factor_evidence": False,
                "factor_verdict": "NOT_ISSUED",
                "child_execution_allowed": False,
            },
        }
        for key, value in expected_host.items():
            if host.get(key) != value:
                reasons.append(f"execution_addendum.host_binding:{key}")
    return list(dict.fromkeys(reasons))


def _cleanup_temporaries(path: Path, *, exact_target: bool) -> None:
    prefix = f".{path.name}."
    for candidate in path.parent.iterdir():
        if not candidate.name.startswith(prefix) or not candidate.name.endswith(".tmp"):
            continue
        metadata = candidate.lstat()
        linked_exact = (
            exact_target and metadata.st_nlink == 2 and candidate.samefile(path)
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (metadata.st_nlink != 1 and not linked_exact)
        ):
            raise EvoExecutionAddendumError([_token(f"unsafe_temporary:{candidate.name}")])
        candidate.unlink()


def _safe_output_parent(root: Path, path: Path) -> Path:
    """Create and revalidate an in-workspace output directory without symlinks."""

    resolved_root = root.resolve(strict=True)
    try:
        relative = path.relative_to(resolved_root)
    except ValueError as exc:
        raise EvoExecutionAddendumError([_token("unsafe_output_path")]) from exc
    current = resolved_root
    for part in relative.parent.parts:
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if current.is_symlink() or not current.is_dir():
            raise EvoExecutionAddendumError([_token("unsafe_output_parent")])
        try:
            current.resolve(strict=True).relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise EvoExecutionAddendumError([_token("unsafe_output_parent")]) from exc
    return current


def _write_once(root: Path, path: Path, payload: Mapping[str, Any]) -> bool:
    expected = canonical_json_bytes(payload)
    parent = _safe_output_parent(root, path)
    if parent != path.parent or not _within(root, path):
        raise EvoExecutionAddendumError([_token("unsafe_output_path")])
    if path.exists() or path.is_symlink():
        exact = path.is_file() and not path.is_symlink() and path.read_bytes() == expected
        _cleanup_temporaries(path, exact_target=exact)
        if not exact:
            raise EvoExecutionAddendumError([_token("immutable_conflict")])
        return False
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temporary)
    os.fchmod(descriptor, 0o600)
    try:
        offset = 0
        while offset < len(expected):
            written = os.write(descriptor, expected[offset:])
            if written <= 0:
                raise OSError("short write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temp_path, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
                raise EvoExecutionAddendumError([_token("immutable_conflict")])
            return False
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temp_path.unlink(missing_ok=True)


@contextmanager
def _lock(root: Path, report_id: str) -> Iterator[None]:
    path = execution_addendum_path(root, report_id).with_suffix(".lock")
    parent = _safe_output_parent(root, path)
    if parent != path.parent or not _within(root, path):
        raise EvoExecutionAddendumError([_token("unsafe_lock_path")])
    descriptor = os.open(
        path,
        os.O_CREAT
        | os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def materialize_evo_execution_addendum(
    *,
    workspace_root: Path,
    report_id: str,
    transfer_bundle: Mapping[str, Any],
    transfer_use_receipt: Mapping[str, Any],
    change_receipt: Mapping[str, Any],
    change_receipt_ref: Mapping[str, Any],
    private_admission_ref: Mapping[str, Any],
    execution_tests: Sequence[Mapping[str, Any]],
    execution_target: str,
    trust_store: Any,
    admissions_root: Path,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    payload = build_evo_execution_addendum(
        workspace_root=root,
        report_id=report_id,
        transfer_bundle=transfer_bundle,
        transfer_use_receipt=transfer_use_receipt,
        change_receipt=change_receipt,
        change_receipt_ref=change_receipt_ref,
        private_admission_ref=private_admission_ref,
        execution_tests=execution_tests,
        execution_target=execution_target,
        trust_store=trust_store,
        admissions_root=admissions_root,
        repository_root=repository_root,
    )
    path = execution_addendum_path(root, report_id)
    with _lock(root, report_id):
        written = _write_once(root, path, payload)
        observed = _canonical_payload(path)
        if observed != payload:
            raise EvoExecutionAddendumError([_token("readback_mismatch")])
    reasons = validate_evo_execution_addendum(
        observed,
        workspace_root=root,
        transfer_bundle=transfer_bundle,
        transfer_use_receipt=transfer_use_receipt,
        change_receipt=change_receipt,
        private_admission_ref=private_admission_ref,
        trust_store=trust_store,
        verify_refs=True,
        admissions_root=admissions_root,
        repository_root=repository_root,
    )
    if reasons:
        raise EvoExecutionAddendumError([_token(reason) for reason in reasons])
    return {
        "verdict": "PASS",
        "written": written,
        "status": observed["status"],
        "execution_completed": False,
        "ref": {
            **_ref_for(root, path),
            "content_sha256": observed["content_sha256"],
        },
        "payload": observed,
    }


def load_and_validate_evo_execution_addendum(
    *,
    workspace_root: Path,
    report_id: str,
    trust_store: Any,
    private_admission_ref: Mapping[str, Any] | None = None,
    admissions_root: Path | None = None,
    repository_root: Path | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    path = execution_addendum_path(root, report_id)
    try:
        payload = _canonical_payload(path)
        transfer = _canonical_payload(evo_v2_paths(root, report_id)["experience_transfer_bundle"])
        use = _canonical_payload(evo_v2_paths(root, report_id)["transfer_use_receipt"])
        source_refs = payload.get("source_refs") or {}
        change_path = _resolve_ref(
            root,
            source_refs.get("transfer_use_change_receipt"),
            label="change_receipt",
        )
        if change_path is None:
            return None, ["execution_addendum.change_receipt_ref"]
        change = _canonical_payload(change_path)
        reasons = validate_evo_execution_addendum(
            payload,
            workspace_root=root,
            transfer_bundle=transfer,
            transfer_use_receipt=use,
            change_receipt=change,
            private_admission_ref=private_admission_ref,
            trust_store=trust_store,
            verify_refs=True,
            admissions_root=admissions_root,
            repository_root=repository_root,
        )
        return (payload if not reasons else None), reasons
    except (EvoExecutionAddendumError, OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, EvoExecutionAddendumError):
            return None, exc.reasons
        return None, [f"execution_addendum.unexpected:{type(exc).__name__}"]


__all__ = [
    "ADDENDUM_STATUS",
    "BLOCK_EVO_EXECUTION_ADDENDUM",
    "EXECUTION_ADDENDUM_VERSION",
    "EvoExecutionAddendumError",
    "build_evo_execution_addendum",
    "execution_addendum_path",
    "load_and_validate_evo_execution_addendum",
    "materialize_evo_execution_addendum",
    "validate_evo_execution_addendum",
]
