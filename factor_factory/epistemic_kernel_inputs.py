"""Explicit input adaptation shared by the offline kernel and its legacy CLI.

No script-directory import, output publication, ambient lookup or import-time IO.
Diagnosis files are read only when explicitly named in a validated input.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from factor_factory.epistemic_kernel_composition_offline import compose_epistemic_kernel_candidate
from factor_factory.research_org.contracts import strict_json_loads

MAX_INPUT_BYTES = 32 * 1024 * 1024


HEX_32_RE = re.compile(r"[0-9a-fA-F]{64}\Z")


CLI_DIAGNOSIS_FIELDS = {
    "stage2_manifest_path",
    "fixture_json_path",
    "assertion_dependency_json_path",
}


INPUT_FIELDS = {
    "source_text",
    "source_lineage",
    "author_claims",
    "analyst_notes",
    "selected_semantic_body",
    "formalization_provenance",
    "pre_a0_predictions",
    "phase_policy_candidate",
    "retrieval_corpus_objects",
    "real_knowledge_inputs",
    "session_scope_secret_hex",
    "diagnosis_inputs",
}


class OfflineCandidateCliError(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise OfflineCandidateCliError(reason)


def _validate_input_payload(payload: Any) -> dict[str, Any]:
    _require(isinstance(payload, dict), "input:object_required")
    _require(set(payload) == INPUT_FIELDS, "input:closed_fields")
    _require(
        isinstance(payload["source_text"], str) and bool(payload["source_text"].strip()),
        "input.source_text:nonempty",
    )
    return payload


def validate_epistemic_kernel_input_payload(payload: Any) -> dict[str, Any]:
    """Validate the closed, explicit input object used by the offline kernel.

    This public spelling lets the Ultimate shadow adapter reuse the exact same
    input contract without importing a private helper or silently widening it.
    The returned object is the caller object after validation; no defaults or
    inferred research semantics are added.
    """

    return _validate_input_payload(payload)


def _read_bounded_raw_json(path_value: Any, *, label: str) -> bytes:
    _require(isinstance(path_value, str), f"{label}:path_string_required")
    path = Path(path_value)
    _require(path.is_absolute(), f"{label}:absolute_path_required")
    _require(path.is_file() and not path.is_symlink(), f"{label}:regular_file_required")
    raw = path.read_bytes()
    _require(0 < len(raw) <= MAX_INPUT_BYTES, f"{label}:size")
    strict_json_loads(raw, label=label)
    return raw


def _absolute_regular_json_path(path_value: Any, *, label: str) -> Path:
    _require(isinstance(path_value, str), f"{label}:path_string_required")
    path = Path(path_value)
    _require(path.is_absolute(), f"{label}:absolute_path_required")
    _require(path.is_file() and not path.is_symlink(), f"{label}:regular_file_required")
    _require(0 < path.stat().st_size <= MAX_INPUT_BYTES, f"{label}:size")
    return path


def _composition_inputs(input_payload: dict[str, Any]) -> dict[str, Any]:
    input_payload = _validate_input_payload(input_payload)
    source_inputs = {
        "source_bytes": input_payload["source_text"].encode("utf-8"),
        "source_lineage": input_payload["source_lineage"],
        "author_claims": input_payload["author_claims"],
        "analyst_notes": input_payload["analyst_notes"],
        "selected_semantic_body": input_payload["selected_semantic_body"],
        "formalization_provenance": input_payload["formalization_provenance"],
        "pre_a0_predictions": input_payload["pre_a0_predictions"],
        "phase_policy_candidate": input_payload["phase_policy_candidate"],
    }
    corpus = input_payload["retrieval_corpus_objects"]
    real_knowledge = input_payload["real_knowledge_inputs"]
    _require(
        not (corpus is not None and real_knowledge is not None),
        "input.retrieval:synthetic_and_real_modes_are_mutually_exclusive",
    )
    secret_hex = input_payload["session_scope_secret_hex"]
    if corpus is None and real_knowledge is None:
        _require(secret_hex is None, "input.session_scope_secret:forbidden_without_retrieval")
        secret = None
    else:
        _require(
            corpus is None or isinstance(corpus, list),
            "input.retrieval_corpus_objects:array_required",
        )
        _require(
            real_knowledge is None or isinstance(real_knowledge, dict),
            "input.real_knowledge_inputs:object_required",
        )
        _require(
            isinstance(secret_hex, str) and HEX_32_RE.fullmatch(secret_hex) is not None,
            "input.session_scope_secret_hex:exact32_bytes",
        )
        secret = bytes.fromhex(secret_hex)
    diagnosis = input_payload["diagnosis_inputs"]
    _require(diagnosis is None or isinstance(diagnosis, dict), "input.diagnosis_inputs")
    if diagnosis is not None:
        _require(
            set(diagnosis) == CLI_DIAGNOSIS_FIELDS,
            "input.diagnosis_inputs:closed_fields",
        )
        diagnosis = {
            "stage2_manifest_path": _absolute_regular_json_path(
                diagnosis["stage2_manifest_path"],
                label="input.diagnosis_inputs.stage2_manifest_path",
            ),
            "fixture_raw_bytes": _read_bounded_raw_json(
                diagnosis["fixture_json_path"],
                label="input.diagnosis_inputs.fixture_json_path",
            ),
            "assertion_dependency_raw_bytes": _read_bounded_raw_json(
                diagnosis["assertion_dependency_json_path"],
                label="input.diagnosis_inputs.assertion_dependency_json_path",
            ),
        }
    return {
        "source_inputs": source_inputs,
        "retrieval_corpus_objects": corpus,
        "real_knowledge_inputs": real_knowledge,
        "session_scope_secret": secret,
        "diagnosis_inputs": diagnosis,
    }


def epistemic_kernel_composition_inputs(
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    """Project a validated CLI object into the composition API's exact inputs."""

    return _composition_inputs(input_payload)


def build_candidate(input_payload: dict[str, Any]) -> dict[str, Any]:
    return compose_epistemic_kernel_candidate(
        **_composition_inputs(input_payload),
    )
