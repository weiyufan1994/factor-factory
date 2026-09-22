from __future__ import annotations

import copy
import functools
import hashlib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from factor_factory.epistemic_candidate_definition_generation import (
    AUTHORITY_EFFECT,
    DEFINITION_BYTES_MANIFEST_DOMAIN,
    DEFINITION_CONTENT_DOMAIN,
    DEFINITION_ROW_DOMAIN,
    DEFINITION_ROW_MANIFEST_DOMAIN,
    GENERATION_BASIS_DOMAIN,
    GENERATION_CONTENT_DOMAIN,
    R14_GENERATION_BASIS_FIELDS,
    R14_MANIFEST_RAW_SHA256,
    CandidateDefinitionGenerationError,
    _definition_serialized_bytes,
    compile_candidate_definition,
    compile_candidate_generation,
    compile_definition_bytes_manifest,
    compile_derivation_contract,
    compile_exact_instance_schema,
    compile_generation_basis,
    load_and_verify_r14_packet,
    validate_candidate_definition_packet,
    validate_compiled_objects,
    write_candidate_definition_packet,
)
from factor_factory.research_org.contracts import strict_json_loads
from factor_factory.research_org.rfc8785_canonical import framed_sha256

PROJECTS_ROOT = Path(__file__).resolve().parents[2]
R14_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r14-20260828/packet_manifest.json"
)
R14_REVIEW_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r14-review-20260828/packet_manifest.json"
)
H1_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-s1-closure-readiness-"
    "h1-20260828/packet_manifest.json"
)
H1_REVIEW_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-s1-closure-readiness-"
    "h1-review-20260828/packet_manifest.json"
)


@functools.lru_cache(maxsize=1)
def _compiled() -> tuple[dict, dict, dict, dict, bytes, dict, dict]:
    source = load_and_verify_r14_packet(R14_MANIFEST)
    basis = compile_generation_basis(source)
    contract = compile_derivation_contract(source)
    definition = compile_candidate_definition(
        source, contract=contract, generation_basis=basis
    )
    raw = _definition_serialized_bytes(definition)
    manifest = compile_definition_bytes_manifest(definition, definition_raw=raw)
    generation = compile_candidate_generation(
        generation_basis=basis,
        definition=definition,
        bytes_manifest=manifest,
    )
    return source, basis, contract, definition, raw, manifest, generation


def test_r14_generation_basis_and_candidate_definition_are_closed() -> None:
    _, basis, contract, definition, raw, manifest, generation = _compiled()
    assert len(basis) == 62
    assert set(basis) == set(R14_GENERATION_BASIS_FIELDS)
    assert definition["definition_row_count"] == 160
    assert definition["candidate_fail_count"] == 99
    assert definition["candidate_blocked_count"] == 61
    assert definition["branch_selection_review_target_count"] == 10
    assert definition["input_availability_sensitive_row_count"] == 11
    assert [row["definition_ordinal"] for row in definition["definition_rows"]] == list(
        range(160)
    )
    assert [
        row["global_obligation_ordinal"] for row in definition["definition_rows"]
    ] == list(range(10, 170))
    assert all(
        row["candidate_definition_row_sha256"]
        == framed_sha256(
            DEFINITION_ROW_DOMAIN,
            {
                key: value
                for key, value in row.items()
                if key != "candidate_definition_row_sha256"
            },
        )
        for row in definition["definition_rows"]
    )
    assert (
        definition["definition_row_manifest_sha256"]
        == hashlib.sha256(
            DEFINITION_ROW_MANIFEST_DOMAIN.encode()
            + b"\x00"
            + b"".join(
                bytes.fromhex(row["candidate_definition_row_sha256"])
                for row in definition["definition_rows"]
            )
        ).hexdigest()
    )
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1
    assert strict_json_loads(raw, label="definition") == definition
    assert manifest["definition_file_count"] == 1
    assert (
        manifest["definition_bytes_manifest_sha256"]
        == hashlib.sha256(
            DEFINITION_BYTES_MANIFEST_DOMAIN.encode()
            + b"\x00"
            + bytes.fromhex(manifest["ordered_definition_files"][0]["file_row_sha256"])
        ).hexdigest()
    )
    assert generation["candidate_definition_generation_id"] == (
        "ffexpdef::" + framed_sha256(GENERATION_BASIS_DOMAIN, basis)
    )
    assert generation["definition_content_sha256"] == definition["content_sha256"]
    assert (
        generation["definition_bytes_manifest_sha256"]
        == manifest["definition_bytes_manifest_sha256"]
    )
    assert (
        contract["external_design_review_required_before_steward_decision_admission"]
        is True
    )


def test_definition_exact_instance_schema_and_authority_boundary() -> None:
    source, _, contract, definition, raw, manifest, generation = _compiled()
    schema = compile_exact_instance_schema(definition)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(definition)
    validate_compiled_objects(
        source,
        contract=contract,
        schema=schema,
        definition=definition,
        definition_raw=raw,
        bytes_manifest=manifest,
        generation=generation,
    )
    assert (
        framed_sha256(
            DEFINITION_CONTENT_DOMAIN,
            {
                key: value
                for key, value in definition.items()
                if key != "content_sha256"
            },
        )
        == definition["content_sha256"]
    )
    assert (
        framed_sha256(
            GENERATION_CONTENT_DOMAIN,
            {
                key: value
                for key, value in generation.items()
                if key != "content_sha256"
            },
        )
        == generation["content_sha256"]
    )
    for payload in (contract, definition, manifest, generation):
        assert payload["authority_effect"] == AUTHORITY_EFFECT
        assert payload["signed"] is False
    assert definition["active"] is False
    assert definition["may_activate"] is False
    assert definition["may_materialize_or_execute"] is False
    assert generation["contains_steward_decision_or_signature_ref"] is False
    assert generation["contains_os_activation_ref"] is False
    assert generation["contains_materialization_or_execution_ref"] is False


def test_tamper_and_extra_field_fail_closed() -> None:
    source, _, contract, definition, raw, manifest, generation = _compiled()
    schema = compile_exact_instance_schema(definition)
    tampered = copy.deepcopy(definition)
    tampered["definition_rows"][0]["candidate_verdict"] = "FAIL"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(tampered)
    extra = copy.deepcopy(generation)
    extra["steward_approval"] = True
    with pytest.raises(CandidateDefinitionGenerationError):
        validate_compiled_objects(
            source,
            contract=contract,
            schema=schema,
            definition=definition,
            definition_raw=raw,
            bytes_manifest=manifest,
            generation=extra,
        )


def test_exact160_and_exact10_cross_splice_fail_closed() -> None:
    source, basis, contract, _, _, _, _ = _compiled()
    branch_splice = copy.deepcopy(source)
    branch_splice["SEMANTIC_DERIVATION_REGISTRY"]["semantic_derivation_rows"][0][
        "closed_branch_universe"
    ][0]["content_sha256"] = "0" * 64
    with pytest.raises(CandidateDefinitionGenerationError):
        compile_candidate_definition(
            branch_splice,
            contract=contract,
            generation_basis=basis,
        )
    target_reorder = copy.deepcopy(source)
    targets = target_reorder["CANDIDATE_DEFINITION_GENERATION_TARGET"][
        "branch_selection_target_rows"
    ]
    targets[0], targets[1] = targets[1], targets[0]
    with pytest.raises(CandidateDefinitionGenerationError):
        compile_candidate_definition(
            target_reorder,
            contract=contract,
            generation_basis=basis,
        )


def test_packet_writer_has_exact7_closure_and_reproducible_candidate_bytes(
    tmp_path: Path,
) -> None:
    output_a = tmp_path / "candidate-a"
    output_b = tmp_path / "candidate-b"
    manifest_a = write_candidate_definition_packet(
        output_a,
        r14_manifest_path=R14_MANIFEST,
        r14_review_manifest_path=R14_REVIEW_MANIFEST,
        h1_manifest_path=H1_MANIFEST,
        h1_review_manifest_path=H1_REVIEW_MANIFEST,
    )
    manifest_b = write_candidate_definition_packet(
        output_b,
        r14_manifest_path=R14_MANIFEST,
        r14_review_manifest_path=R14_REVIEW_MANIFEST,
        h1_manifest_path=H1_MANIFEST,
        h1_review_manifest_path=H1_REVIEW_MANIFEST,
    )
    expected_names = {
        "packet_manifest.json",
        "00_candidate_definition_derivation_contract.json",
        "01_closed_candidate_definition_bytes.schema.json",
        "02_candidate_definition.json",
        "03_definition_bytes_manifest.json",
        "04_candidate_definition_generation.json",
        "05_generation_validation_report.json",
    }
    assert {path.name for path in output_a.iterdir()} == expected_names
    assert {path.name for path in output_b.iterdir()} == expected_names
    assert manifest_a == manifest_b
    assert manifest_a["artifact_count"] == 6
    assert manifest_a["direct_predecessor_manifest_raw_sha256"] == (
        R14_MANIFEST_RAW_SHA256
    )
    assert manifest_a["permissions_opened_count"] == 0
    assert manifest_a["external_design_review_present"] is False
    assert manifest_a["owner_instruction_provenance_state"] == (
        "CHAT_CONTEXT_ONLY__NONAUTHORITY"
    )
    assert manifest_a["owner_instruction_ref"] is None
    assert manifest_a["owner_instruction_sha256"] is None
    assert manifest_a["owner_instruction_may_satisfy_any_contract_gate"] is False
    for name in expected_names:
        assert (output_a / name).read_bytes() == (output_b / name).read_bytes()
        assert (output_a / name).stat().st_nlink == 1
    assert (
        validate_candidate_definition_packet(
            output_a / "packet_manifest.json",
            r14_manifest_path=R14_MANIFEST,
            r14_review_manifest_path=R14_REVIEW_MANIFEST,
            h1_manifest_path=H1_MANIFEST,
            h1_review_manifest_path=H1_REVIEW_MANIFEST,
        )
        == manifest_a
    )
    report_path = output_a / "05_generation_validation_report.json"
    report_path.write_bytes(report_path.read_bytes() + b"\n")
    with pytest.raises(CandidateDefinitionGenerationError):
        validate_candidate_definition_packet(
            output_a / "packet_manifest.json",
            r14_manifest_path=R14_MANIFEST,
            r14_review_manifest_path=R14_REVIEW_MANIFEST,
            h1_manifest_path=H1_MANIFEST,
            h1_review_manifest_path=H1_REVIEW_MANIFEST,
        )
    with pytest.raises(CandidateDefinitionGenerationError):
        validate_candidate_definition_packet(
            output_b / "packet_manifest.json",
            r14_manifest_path=R14_MANIFEST,
            r14_review_manifest_path=R14_REVIEW_MANIFEST,
            h1_manifest_path=H1_MANIFEST,
            h1_review_manifest_path=H1_MANIFEST,
        )
    (output_b / "unexpected.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(CandidateDefinitionGenerationError):
        validate_candidate_definition_packet(
            output_b / "packet_manifest.json",
            r14_manifest_path=R14_MANIFEST,
            r14_review_manifest_path=R14_REVIEW_MANIFEST,
            h1_manifest_path=H1_MANIFEST,
            h1_review_manifest_path=H1_REVIEW_MANIFEST,
        )
