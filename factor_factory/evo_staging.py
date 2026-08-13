from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from factor_factory.evo_v2 import (
    BLOCK_EVO_V2_INVALID,
    BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
    EvoV2Error,
    artifact_sha256,
    canonical_json_bytes,
    evo_v2_paths,
    evo_v2_relative_paths,
    load_json_object,
    sha256_file,
    stable_json_hash,
    validate_economic_backprojection,
    validate_experience_transfer_bundle,
    validate_feedback_ledger,
    validate_mechanism_delta,
    validate_transfer_use_receipt,
)
from factor_factory.research_conjecture import (
    epistemic_evolution_lifecycle_path,
    validate_epistemic_evolution_lifecycle,
)
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.revision_council.evo_v2 import (
    validate_revision_council_evo_v2,
)


STAGING_MANIFEST_VERSION = "factorforge_evo_v2_staging_manifest_v1"
STAGING_MANIFEST_FILENAME = "staging_manifest.json"
NO_DERIVED_LAW_FILENAME = "no_derived_law.json"
STAGE_LOCK_FILENAME = ".staging.lock"

STAGE_ADMIT_FEEDBACK = "admit-feedback"
STAGE_ADMIT_COUNCIL_OUTCOME = "admit-council-outcome"
STAGE_ADMIT_TRANSFER = "admit-transfer"
STAGE_RECORD_USE = "record-use"
STAGES = {
    STAGE_ADMIT_FEEDBACK,
    STAGE_ADMIT_COUNCIL_OUTCOME,
    STAGE_ADMIT_TRANSFER,
    STAGE_RECORD_USE,
}

SHA256_HEX = frozenset("0123456789abcdef")


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value) <= SHA256_HEX
    )


def _dedupe(reasons: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(reason) for reason in reasons if str(reason)))


def _target_dir(workspace_root: Path, report_id: str) -> Path:
    # Reuse the core report-id/path validator rather than creating a second
    # identity grammar for staged materialization.
    return evo_v2_paths(workspace_root, report_id)["feedback_ledger"].parent


def staging_manifest_path(workspace_root: Path, report_id: str) -> Path:
    return _target_dir(workspace_root, report_id) / STAGING_MANIFEST_FILENAME


def no_derived_law_path(workspace_root: Path, report_id: str) -> Path:
    return _target_dir(workspace_root, report_id) / NO_DERIVED_LAW_FILENAME


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(root).as_posix()


def _canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _artifact_ref(
    *,
    root: Path,
    name: str,
    path: Path,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    return {
        "name": name,
        "path": _relative_path(root, path),
        "sha256": _canonical_payload_sha256(payload),
    }


def _lifecycle_parent_sha256(payload: Mapping[str, Any]) -> str | None:
    events = payload.get("events")
    if not isinstance(events, list) or len(events) < 2:
        return None
    parent: dict[str, Any] = {
        "contract_version": payload.get("contract_version"),
        "report_id": payload.get("report_id"),
        "current_state": events[-2].get("to_state")
        if isinstance(events[-2], Mapping)
        else None,
        "events": events[:-1],
        "host_authority": payload.get("host_authority"),
    }
    parent["content_sha256"] = stable_hash(parent)
    return stable_hash(parent)


def _load_and_bind_lifecycle(
    *,
    root: Path,
    report_id: str,
    expected_parent_sha256: str,
    expected_content_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not _is_sha256(expected_parent_sha256):
        raise EvoV2Error(
            BLOCK_EVO_V2_INVALID,
            ["staging.expected_lifecycle_parent_sha256.invalid"],
        )
    if not _is_sha256(expected_content_sha256):
        raise EvoV2Error(
            BLOCK_EVO_V2_INVALID,
            ["staging.expected_lifecycle_content_sha256.invalid"],
        )
    path = epistemic_evolution_lifecycle_path(root, report_id)
    if not path.is_file() or path.is_symlink():
        raise EvoV2Error(
            BLOCK_EVO_V2_INVALID,
            ["staging.lifecycle.missing_or_symlink"],
        )
    payload = load_json_object(path)
    reasons = validate_epistemic_evolution_lifecycle(
        payload,
        report_id=report_id,
        workspace_root=root,
        require_signed_host_receipts=True,
    )
    if reasons:
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, reasons)
    parent_digest = _lifecycle_parent_sha256(payload)
    if parent_digest != expected_parent_sha256:
        raise EvoV2Error(
            BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
            ["staging.lifecycle.parent_sha256.cas_mismatch"],
        )
    if payload.get("content_sha256") != expected_content_sha256:
        raise EvoV2Error(
            BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
            ["staging.lifecycle.content_sha256.cas_mismatch"],
        )
    binding = {
        "path": _relative_path(root, path),
        "sha256": sha256_file(path),
        "parent_sha256": parent_digest,
        "content_sha256": payload["content_sha256"],
        "current_state": payload["current_state"],
    }
    return payload, binding


def _load_existing_payload(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise EvoV2Error(
            BLOCK_EVO_V2_INVALID,
            [f"staging.canonical_readback.invalid:{path.name}"],
        )
    payload = load_json_object(path)
    if path.read_bytes() != canonical_json_bytes(payload):
        raise EvoV2Error(
            BLOCK_EVO_V2_INVALID,
            [f"staging.canonical_readback.noncanonical_json:{path.name}"],
        )
    return payload


def _load_canonical_core(
    *,
    root: Path,
    report_id: str,
    names: Sequence[str],
) -> dict[str, dict[str, Any]]:
    paths = evo_v2_paths(root, report_id)
    return {name: _load_existing_payload(paths[name]) for name in names}


def _resolve_council_artifact(
    value: Any,
    *,
    root: Path,
) -> dict[str, Any]:
    if isinstance(value, dict) and set(value) == {"path", "sha256"}:
        raw_path = value.get("path")
        if not isinstance(raw_path, str) or "\\" in raw_path:
            raise EvoV2Error(BLOCK_EVO_V2_INVALID, ["staging.council_ref.invalid"])
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise EvoV2Error(BLOCK_EVO_V2_INVALID, ["staging.council_ref.invalid"])
        path = (root / relative).resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise EvoV2Error(
                BLOCK_EVO_V2_INVALID,
                ["staging.council_ref.path_escape"],
            ) from exc
        payload = _load_existing_payload(path)
        if sha256_file(path) != value.get("sha256"):
            raise EvoV2Error(
                BLOCK_EVO_V2_INVALID,
                ["staging.council_ref.sha256_mismatch"],
            )
        return payload
    if not isinstance(value, dict):
        raise EvoV2Error(
            BLOCK_EVO_V2_INVALID,
            ["staging.council_artifact.object_or_ref_required"],
        )
    return dict(value)


def _extract_validated_council_outcome(
    *,
    proposal: Mapping[str, Any],
    root: Path,
    report_id: str,
    feedback: Mapping[str, Any],
) -> tuple[str, dict[str, dict[str, Any]]]:
    reasons = validate_revision_council_evo_v2(
        proposal,
        workspace_root=root,
        required=True,
    )
    if reasons:
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, reasons)
    if proposal.get("report_id") != report_id:
        raise EvoV2Error(
            BLOCK_EVO_V2_INVALID,
            ["staging.council_proposal.report_id_mismatch"],
        )
    envelope = proposal.get("evo_v2")
    if not isinstance(envelope, Mapping):
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, ["staging.council_envelope.missing"])
    source_feedback = _resolve_council_artifact(
        envelope.get("feedback_ledger"),
        root=root,
    )
    if canonical_json_bytes(source_feedback) != canonical_json_bytes(feedback):
        raise EvoV2Error(
            BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
            ["staging.council_feedback.canonical_mismatch"],
        )
    outcome = envelope.get("derivation_outcome")
    if not isinstance(outcome, Mapping):
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, ["staging.council_outcome.missing"])
    outcome_name = outcome.get("outcome")
    if outcome_name == "MINIMAL_MECHANISM_DELTA":
        return outcome_name, {
            "mechanism_delta": _resolve_council_artifact(
                outcome.get("mechanism_delta"), root=root
            ),
            "economic_backprojection": _resolve_council_artifact(
                outcome.get("economic_backprojection"), root=root
            ),
        }
    if outcome_name == "NO_DERIVED_LAW":
        proof = outcome.get("no_derived_law")
        if not isinstance(proof, dict):
            raise EvoV2Error(
                BLOCK_EVO_V2_INVALID,
                ["staging.no_derived_law.object_required"],
            )
        # The full Council EVO validator above is the sole semantic authority
        # for this closed proof.  Staging only preserves its exact payload.
        return outcome_name, {"no_derived_law": dict(proof)}
    raise EvoV2Error(
        BLOCK_EVO_V2_INVALID,
        ["staging.council_outcome.invalid"],
    )


def _manifest_unsigned(payload: Mapping[str, Any]) -> dict[str, Any]:
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    return unsigned


def validate_evo_v2_staging_manifest(
    payload: Any,
    *,
    root: Path,
    report_id: str,
    verify_readback: bool = True,
) -> list[str]:
    reasons: list[str] = []
    fields = {
        "contract_version",
        "report_id",
        "host_authority",
        "events",
        "content_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        return ["staging_manifest.closed_shape_invalid"]
    if (
        payload.get("contract_version") != STAGING_MANIFEST_VERSION
        or payload.get("report_id") != report_id
        or payload.get("host_authority") != "ULTIMATE_HOST_FILE_LOCKED_CAS"
    ):
        reasons.append("staging_manifest.header.invalid")
    if payload.get("content_sha256") != stable_json_hash(_manifest_unsigned(payload)):
        reasons.append("staging_manifest.content_sha256_mismatch")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        reasons.append("staging_manifest.events.invalid")
        return _dedupe(reasons)
    event_fields = {
        "sequence",
        "stage",
        "outcome",
        "lifecycle_binding",
        "input_digests",
        "prior_artifact_refs",
        "output_artifact_refs",
        "parent_manifest_content_sha256",
        "prior_event_sha256",
        "event_sha256",
    }
    ref_fields = {"name", "path", "sha256"}
    lifecycle_fields = {
        "path",
        "sha256",
        "parent_sha256",
        "content_sha256",
        "current_state",
    }
    expected_stages = [
        STAGE_ADMIT_FEEDBACK,
        STAGE_ADMIT_COUNCIL_OUTCOME,
        STAGE_ADMIT_TRANSFER,
        STAGE_RECORD_USE,
    ]
    previous_event_sha: str | None = None
    previous_manifest_content: str | None = None
    branch: str | None = None
    canonical_paths = evo_v2_relative_paths(report_id)
    canonical_paths["no_derived_law"] = (
        PurePosixPath("objects")
        / "evo_v2"
        / report_id
        / NO_DERIVED_LAW_FILENAME
    ).as_posix()
    for index, event in enumerate(events):
        if not isinstance(event, dict) or set(event) != event_fields:
            reasons.append(f"staging_manifest.event[{index}].closed_shape_invalid")
            continue
        unsigned_event = dict(event)
        event_digest = unsigned_event.pop("event_sha256", None)
        if event_digest != stable_json_hash(unsigned_event):
            reasons.append(f"staging_manifest.event[{index}].sha256_mismatch")
        if event.get("sequence") != index + 1:
            reasons.append(f"staging_manifest.event[{index}].sequence_invalid")
        if index >= len(expected_stages) or event.get("stage") != expected_stages[index]:
            reasons.append(f"staging_manifest.event[{index}].stage_order_invalid")
        if event.get("prior_event_sha256") != previous_event_sha:
            reasons.append(f"staging_manifest.event[{index}].prior_event_mismatch")
        if event.get("parent_manifest_content_sha256") != previous_manifest_content:
            reasons.append(f"staging_manifest.event[{index}].parent_manifest_mismatch")
        lifecycle = event.get("lifecycle_binding")
        if not isinstance(lifecycle, dict) or set(lifecycle) != lifecycle_fields:
            reasons.append(f"staging_manifest.event[{index}].lifecycle.invalid")
        else:
            for field in (
                "sha256",
                "parent_sha256",
                "content_sha256",
            ):
                if not _is_sha256(lifecycle.get(field)):
                    reasons.append(
                        f"staging_manifest.event[{index}].lifecycle.{field}.invalid"
                    )
        inputs = event.get("input_digests")
        if (
            not isinstance(inputs, dict)
            or not inputs
            or any(not isinstance(key, str) or not _is_sha256(value) for key, value in inputs.items())
        ):
            reasons.append(f"staging_manifest.event[{index}].input_digests.invalid")
        refs_by_collection: dict[str, list[dict[str, Any]]] = {}
        for collection_name in ("prior_artifact_refs", "output_artifact_refs"):
            refs = event.get(collection_name)
            if not isinstance(refs, list):
                reasons.append(
                    f"staging_manifest.event[{index}].{collection_name}.invalid"
                )
                continue
            refs_by_collection[collection_name] = [
                ref for ref in refs if isinstance(ref, dict)
            ]
            for ref_index, ref in enumerate(refs):
                if not isinstance(ref, dict) or set(ref) != ref_fields:
                    reasons.append(
                        f"staging_manifest.event[{index}].{collection_name}[{ref_index}].invalid"
                    )
                    continue
                if not _is_sha256(ref.get("sha256")):
                    reasons.append(
                        f"staging_manifest.event[{index}].{collection_name}[{ref_index}].sha256.invalid"
                    )
                    continue
                if verify_readback and collection_name == "output_artifact_refs":
                    raw_path = ref.get("path")
                    if not isinstance(raw_path, str):
                        reasons.append(
                            f"staging_manifest.event[{index}].output_artifact_refs[{ref_index}].path.invalid"
                        )
                        continue
                    candidate = (root / raw_path).resolve(strict=False)
                    try:
                        candidate.relative_to(root)
                    except ValueError:
                        reasons.append(
                            f"staging_manifest.event[{index}].output_artifact_refs[{ref_index}].path_escape"
                        )
                        continue
                    if (
                        not candidate.is_file()
                        or candidate.is_symlink()
                        or sha256_file(candidate) != ref.get("sha256")
                    ):
                        reasons.append(
                            f"staging_manifest.event[{index}].output_artifact_refs[{ref_index}].readback_mismatch"
                        )
        outcome = event.get("outcome")
        if index == 0 and outcome != "QUALIFIED_CONTRADICTION":
            reasons.append("staging_manifest.feedback_outcome.invalid")
        if index == 1:
            if outcome not in {"MINIMAL_MECHANISM_DELTA", "NO_DERIVED_LAW"}:
                reasons.append("staging_manifest.council_outcome.invalid")
            branch = str(outcome)
        if index >= 2 and branch != "MINIMAL_MECHANISM_DELTA":
            reasons.append("staging_manifest.no_derived_branch_not_terminal")
        expected_prior_names: list[str] = []
        expected_output_names: list[str] = []
        expected_input_names: set[str] = set()
        expected_lifecycle_state: str | None = None
        if index == 0:
            expected_output_names = ["feedback_ledger"]
            expected_input_names = {"feedback_ledger"}
            expected_lifecycle_state = "QUALIFIED_CONTRADICTION"
        elif index == 1:
            expected_prior_names = ["feedback_ledger"]
            expected_input_names = {"council_proposal"}
            expected_lifecycle_state = str(outcome)
            expected_output_names = (
                ["mechanism_delta", "economic_backprojection"]
                if outcome == "MINIMAL_MECHANISM_DELTA"
                else ["no_derived_law"]
            )
        elif index == 2:
            expected_prior_names = [
                "feedback_ledger",
                "mechanism_delta",
                "economic_backprojection",
            ]
            expected_output_names = ["experience_transfer_bundle"]
            expected_input_names = {"experience_transfer_bundle"}
            expected_lifecycle_state = str(outcome)
            if outcome not in {"TRANSFER_RECORDED", "COLD_START_RECORDED"}:
                reasons.append("staging_manifest.transfer_outcome.invalid")
        elif index == 3:
            expected_prior_names = [
                "feedback_ledger",
                "mechanism_delta",
                "economic_backprojection",
                "experience_transfer_bundle",
            ]
            expected_output_names = ["transfer_use_receipt"]
            expected_input_names = {"transfer_use_receipt"}
            expected_lifecycle_state = str(outcome)
            prior_outcome = events[index - 1].get("outcome")
            if (
                outcome not in {"TRANSFER_RECORDED", "COLD_START_RECORDED"}
                or outcome != prior_outcome
            ):
                reasons.append("staging_manifest.use_outcome.invalid")
        if isinstance(inputs, dict) and set(inputs) != expected_input_names:
            reasons.append(f"staging_manifest.event[{index}].input_names.invalid")
        for collection_name, expected_names in (
            ("prior_artifact_refs", expected_prior_names),
            ("output_artifact_refs", expected_output_names),
        ):
            refs = refs_by_collection.get(collection_name, [])
            observed_names = [ref.get("name") for ref in refs]
            if observed_names != expected_names:
                reasons.append(
                    f"staging_manifest.event[{index}].{collection_name}.canonical_set_invalid"
                )
            for ref_index, ref in enumerate(refs):
                name = ref.get("name")
                if not isinstance(name, str) or ref.get("path") != canonical_paths.get(name):
                    reasons.append(
                        f"staging_manifest.event[{index}].{collection_name}[{ref_index}].canonical_path_invalid"
                    )
        if (
            isinstance(lifecycle, dict)
            and (
                lifecycle.get("path")
                != _relative_path(
                    root, epistemic_evolution_lifecycle_path(root, report_id)
                )
                or lifecycle.get("current_state") != expected_lifecycle_state
            )
        ):
            reasons.append(f"staging_manifest.event[{index}].lifecycle.binding_invalid")
        previous_event_sha = event_digest if isinstance(event_digest, str) else None
        # Reconstruct the manifest content at this event, which is the CAS
        # parent value required by the next append.
        prefix_payload = {
            "contract_version": STAGING_MANIFEST_VERSION,
            "report_id": report_id,
            "host_authority": "ULTIMATE_HOST_FILE_LOCKED_CAS",
            "events": events[: index + 1],
        }
        previous_manifest_content = stable_json_hash(prefix_payload)
    if len(events) > len(expected_stages):
        reasons.append("staging_manifest.too_many_events")
    return _dedupe(reasons)


def _load_manifest(root: Path, report_id: str) -> dict[str, Any] | None:
    path = staging_manifest_path(root, report_id)
    if not path.exists():
        return None
    payload = _load_existing_payload(path)
    reasons = validate_evo_v2_staging_manifest(
        payload,
        root=root,
        report_id=report_id,
        verify_readback=True,
    )
    if reasons:
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, reasons)
    return payload


@contextmanager
def _stage_lock(root: Path, report_id: str) -> Iterator[None]:
    target = _target_dir(root, report_id)
    target.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise EvoV2Error(
            BLOCK_EVO_V2_INVALID,
            ["staging.target_directory.symlink_forbidden"],
        )
    try:
        target.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise EvoV2Error(
            BLOCK_EVO_V2_INVALID,
            ["staging.target_directory.path_escape"],
        ) from exc
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    # The lifecycle writer owns lifecycle.lock.  Taking it before the staging
    # lock prevents a valid lifecycle from changing between CAS validation and
    # the artifact/manifest commit.  No lifecycle writer takes staging.lock,
    # so this order cannot form a lock cycle.
    lock_paths = [
        epistemic_evolution_lifecycle_path(root, report_id).with_suffix(".lock"),
        target / STAGE_LOCK_FILENAME,
    ]
    descriptors: list[int] = []
    try:
        for lock_path in lock_paths:
            try:
                descriptor = os.open(lock_path, flags, 0o600)
            except OSError as exc:
                raise EvoV2Error(
                    BLOCK_EVO_V2_INVALID,
                    [f"staging.lock.open_failed:{lock_path.name}:{type(exc).__name__}"],
                ) from exc
            descriptors.append(descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        for descriptor in reversed(descriptors):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _assert_output_writable(path: Path, payload: Mapping[str, Any]) -> None:
    expected = canonical_json_bytes(payload)
    if not path.exists():
        return
    if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
        raise EvoV2Error(
            BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
            [f"staging.output.different_content_exists:{path.name}"],
        )


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    expected = canonical_json_bytes(payload)
    if path.exists():
        if path.read_bytes() != expected:
            raise EvoV2Error(
                BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
                [f"staging.output.different_content_exists:{path.name}"],
            )
        return
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        temporary_path.write_bytes(expected)
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _manifest_payload(
    *,
    report_id: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": STAGING_MANIFEST_VERSION,
        "report_id": report_id,
        "host_authority": "ULTIMATE_HOST_FILE_LOCKED_CAS",
        "events": events,
    }
    payload["content_sha256"] = stable_json_hash(payload)
    return payload


def _validate_stage_order(
    *,
    stage: str,
    manifest: Mapping[str, Any] | None,
) -> None:
    events = manifest.get("events") if isinstance(manifest, Mapping) else []
    events = events if isinstance(events, list) else []
    expected_index = {
        STAGE_ADMIT_FEEDBACK: 0,
        STAGE_ADMIT_COUNCIL_OUTCOME: 1,
        STAGE_ADMIT_TRANSFER: 2,
        STAGE_RECORD_USE: 3,
    }[stage]
    if len(events) != expected_index:
        raise EvoV2Error(
            BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
            [f"staging.stage_order.invalid:{stage}:existing_events={len(events)}"],
        )
    if stage in {STAGE_ADMIT_TRANSFER, STAGE_RECORD_USE}:
        council = events[1] if len(events) > 1 else {}
        if not isinstance(council, Mapping) or council.get("outcome") != "MINIMAL_MECHANISM_DELTA":
            raise EvoV2Error(
                BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
                ["staging.no_derived_law_branch_is_terminal"],
            )


def _stage_payloads(
    *,
    stage: str,
    root: Path,
    report_id: str,
    lifecycle: Mapping[str, Any],
    feedback_ledger: Mapping[str, Any] | None,
    council_proposal: Mapping[str, Any] | None,
    experience_transfer_bundle: Mapping[str, Any] | None,
    transfer_use_receipt: Mapping[str, Any] | None,
) -> tuple[
    str,
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    core_paths = evo_v2_paths(root, report_id)
    state = lifecycle.get("current_state")
    if stage == STAGE_ADMIT_FEEDBACK:
        if state != "QUALIFIED_CONTRADICTION" or not isinstance(feedback_ledger, Mapping):
            raise EvoV2Error(
                BLOCK_EVO_V2_INVALID,
                ["staging.admit_feedback.qualified_lifecycle_and_payload_required"],
            )
        payload = dict(feedback_ledger)
        reasons = validate_feedback_ledger(payload, workspace_root=root, verify_refs=True)
        if payload.get("artifact_identity", {}).get("report_id") != report_id:
            reasons.append("staging.feedback_ledger.report_id_mismatch")
        if reasons:
            raise EvoV2Error(BLOCK_EVO_V2_INVALID, reasons)
        return (
            "QUALIFIED_CONTRADICTION",
            {},
            {"feedback_ledger": payload},
            {"feedback_ledger": artifact_sha256(payload)},
        )

    feedback = _load_canonical_core(
        root=root,
        report_id=report_id,
        names=["feedback_ledger"],
    )["feedback_ledger"]
    if stage == STAGE_ADMIT_COUNCIL_OUTCOME:
        if not isinstance(council_proposal, Mapping):
            raise EvoV2Error(
                BLOCK_EVO_V2_INVALID,
                ["staging.council_proposal.required"],
            )
        outcome, outputs = _extract_validated_council_outcome(
            proposal=council_proposal,
            root=root,
            report_id=report_id,
            feedback=feedback,
        )
        if state != outcome:
            raise EvoV2Error(
                BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
                [f"staging.council_outcome.lifecycle_mismatch:{state}:{outcome}"],
            )
        known: dict[str, Mapping[str, Any]] = {
            evo_v2_relative_paths(report_id)["feedback_ledger"]: feedback,
        }
        if outcome == "MINIMAL_MECHANISM_DELTA":
            delta = outputs["mechanism_delta"]
            backprojection = outputs["economic_backprojection"]
            known[evo_v2_relative_paths(report_id)["mechanism_delta"]] = delta
            known[
                evo_v2_relative_paths(report_id)["economic_backprojection"]
            ] = backprojection
            reasons = validate_mechanism_delta(
                delta,
                feedback_ledger=feedback,
                workspace_root=root,
                known_artifacts=known,
                verify_refs=True,
            )
            reasons.extend(
                validate_economic_backprojection(
                    backprojection,
                    mechanism_delta=delta,
                    workspace_root=root,
                    known_artifacts=known,
                    verify_refs=True,
                )
            )
            if reasons:
                raise EvoV2Error(BLOCK_EVO_V2_INVALID, reasons)
            if no_derived_law_path(root, report_id).exists():
                raise EvoV2Error(
                    BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
                    ["staging.minimal_branch.no_derived_artifact_exists"],
                )
        else:
            if core_paths["mechanism_delta"].exists() or core_paths[
                "economic_backprojection"
            ].exists():
                raise EvoV2Error(
                    BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
                    ["staging.no_derived_branch.minimal_artifact_exists"],
                )
        return (
            outcome,
            {"feedback_ledger": feedback},
            outputs,
            {"council_proposal": _canonical_payload_sha256(council_proposal)},
        )

    prior = _load_canonical_core(
        root=root,
        report_id=report_id,
        names=["feedback_ledger", "mechanism_delta", "economic_backprojection"],
    )
    paths = evo_v2_relative_paths(report_id)
    known = {paths[name]: payload for name, payload in prior.items()}
    if stage == STAGE_ADMIT_TRANSFER:
        if not isinstance(experience_transfer_bundle, Mapping):
            raise EvoV2Error(
                BLOCK_EVO_V2_INVALID,
                ["staging.experience_transfer_bundle.required"],
            )
        transfer = dict(experience_transfer_bundle)
        reasons = validate_experience_transfer_bundle(
            transfer,
            mechanism_delta=prior["mechanism_delta"],
            economic_backprojection=prior["economic_backprojection"],
            workspace_root=root,
            known_artifacts={**known, paths["experience_transfer_bundle"]: transfer},
            verify_refs=True,
        )
        retrieval = transfer.get("retrieval_policy")
        memory_state = retrieval.get("memory_state") if isinstance(retrieval, Mapping) else None
        expected_state = (
            "COLD_START_RECORDED"
            if memory_state == "COLD_START_NO_ADMISSIBLE_MEMORY"
            else "TRANSFER_RECORDED"
        )
        if state != expected_state:
            reasons.append(
                f"staging.transfer.lifecycle_state_mismatch:{state}:{expected_state}"
            )
        if reasons:
            raise EvoV2Error(BLOCK_EVO_V2_INVALID, reasons)
        return (
            expected_state,
            prior,
            {"experience_transfer_bundle": transfer},
            {"experience_transfer_bundle": artifact_sha256(transfer)},
        )

    if stage == STAGE_RECORD_USE:
        if not isinstance(transfer_use_receipt, Mapping):
            raise EvoV2Error(
                BLOCK_EVO_V2_INVALID,
                ["staging.transfer_use_receipt.required"],
            )
        transfer = _load_existing_payload(core_paths["experience_transfer_bundle"])
        receipt = dict(transfer_use_receipt)
        known[paths["experience_transfer_bundle"]] = transfer
        known[paths["transfer_use_receipt"]] = receipt
        reasons = validate_transfer_use_receipt(
            receipt,
            transfer_bundle=transfer,
            mechanism_delta=prior["mechanism_delta"],
            workspace_root=root,
            known_artifacts=known,
            verify_refs=True,
        )
        retrieval = transfer.get("retrieval_policy")
        memory_state = retrieval.get("memory_state") if isinstance(retrieval, Mapping) else None
        expected_state = (
            "COLD_START_RECORDED"
            if memory_state == "COLD_START_NO_ADMISSIBLE_MEMORY"
            else "TRANSFER_RECORDED"
        )
        if state != expected_state:
            reasons.append(
                f"staging.use_receipt.lifecycle_state_mismatch:{state}:{expected_state}"
            )
        if reasons:
            raise EvoV2Error(BLOCK_EVO_V2_INVALID, reasons)
        return (
            expected_state,
            {**prior, "experience_transfer_bundle": transfer},
            {"transfer_use_receipt": receipt},
            {"transfer_use_receipt": artifact_sha256(receipt)},
        )
    raise EvoV2Error(BLOCK_EVO_V2_INVALID, [f"staging.stage.invalid:{stage}"])


def materialize_evo_v2_stage(
    *,
    workspace_root: Path,
    report_id: str,
    stage: str,
    expected_lifecycle_parent_sha256: str,
    expected_lifecycle_content_sha256: str,
    expected_staging_content_sha256: str,
    feedback_ledger: Mapping[str, Any] | None = None,
    council_proposal: Mapping[str, Any] | None = None,
    experience_transfer_bundle: Mapping[str, Any] | None = None,
    transfer_use_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, [f"staging.stage.invalid:{stage}"])
    root = workspace_root.resolve(strict=True)
    if not root.is_dir():
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, ["staging.workspace_root.invalid"])
    if expected_staging_content_sha256 != "ABSENT" and not _is_sha256(
        expected_staging_content_sha256
    ):
        raise EvoV2Error(
            BLOCK_EVO_V2_INVALID,
            ["staging.expected_staging_content_sha256.invalid"],
        )

    with _stage_lock(root, report_id):
        manifest = _load_manifest(root, report_id)
        current_manifest_digest = (
            manifest.get("content_sha256") if manifest is not None else "ABSENT"
        )
        existing_events = list(manifest.get("events") or []) if manifest else []
        immediate_replay = bool(
            existing_events and existing_events[-1].get("stage") == stage
        )
        if not immediate_replay:
            _validate_stage_order(stage=stage, manifest=manifest)
        # Lifecycle is deliberately re-read after acquiring the same staging
        # lock used for output CAS.  A caller must bind both the current and
        # reconstructable parent lifecycle content hashes.
        lifecycle, lifecycle_binding = _load_and_bind_lifecycle(
            root=root,
            report_id=report_id,
            expected_parent_sha256=expected_lifecycle_parent_sha256,
            expected_content_sha256=expected_lifecycle_content_sha256,
        )
        outcome, prior, outputs, input_digests = _stage_payloads(
            stage=stage,
            root=root,
            report_id=report_id,
            lifecycle=lifecycle,
            feedback_ledger=feedback_ledger,
            council_proposal=council_proposal,
            experience_transfer_bundle=experience_transfer_bundle,
            transfer_use_receipt=transfer_use_receipt,
        )
        core_paths = evo_v2_paths(root, report_id)
        output_paths = {
            name: (
                no_derived_law_path(root, report_id)
                if name == "no_derived_law"
                else core_paths[name]
            )
            for name in outputs
        }
        for name, payload in outputs.items():
            _assert_output_writable(output_paths[name], payload)
        prior_refs = [
            _artifact_ref(
                root=root,
                name=name,
                path=core_paths[name],
                payload=payload,
            )
            for name, payload in prior.items()
        ]
        output_refs = [
            _artifact_ref(
                root=root,
                name=name,
                path=output_paths[name],
                payload=payload,
            )
            for name, payload in outputs.items()
        ]
        parent_manifest_digest = (
            manifest.get("content_sha256") if manifest is not None else None
        )
        previous_event_sha = (
            existing_events[-1].get("event_sha256") if existing_events else None
        )
        event_unsigned = {
            "sequence": len(existing_events) + 1,
            "stage": stage,
            "outcome": outcome,
            "lifecycle_binding": lifecycle_binding,
            "input_digests": dict(sorted(input_digests.items())),
            "prior_artifact_refs": prior_refs,
            "output_artifact_refs": output_refs,
            "parent_manifest_content_sha256": parent_manifest_digest,
            "prior_event_sha256": previous_event_sha,
        }
        event = dict(event_unsigned)
        event["event_sha256"] = stable_json_hash(event_unsigned)

        # An immediate retry may still carry the pre-append CAS value.  It is
        # idempotent only when every lifecycle/input/prior/output binding is
        # byte-identical to the already admitted last event.
        if existing_events and existing_events[-1].get("stage") == stage:
            existing_event = existing_events[-1]
            replay_view = {
                key: existing_event.get(key)
                for key in (
                    "stage",
                    "outcome",
                    "lifecycle_binding",
                    "input_digests",
                    "prior_artifact_refs",
                    "output_artifact_refs",
                )
            }
            requested_view = {key: event.get(key) for key in replay_view}
            accepted_cas = {
                current_manifest_digest,
                existing_event.get("parent_manifest_content_sha256") or "ABSENT",
            }
            if replay_view == requested_view and expected_staging_content_sha256 in accepted_cas:
                return {
                    "stage": stage,
                    "outcome": outcome,
                    "idempotent_replay": True,
                    "written": {ref["name"]: ref for ref in output_refs},
                    "staging_manifest": {
                        "path": _relative_path(
                            root, staging_manifest_path(root, report_id)
                        ),
                        "content_sha256": current_manifest_digest,
                        "sha256": sha256_file(staging_manifest_path(root, report_id)),
                    },
                }
            raise EvoV2Error(
                BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
                [f"staging.idempotent_replay.content_mismatch:{stage}"],
            )

        if expected_staging_content_sha256 != current_manifest_digest:
            raise EvoV2Error(
                BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
                ["staging.manifest.content_sha256.cas_mismatch"],
            )
        next_manifest = _manifest_payload(
            report_id=report_id,
            events=[*existing_events, event],
        )
        manifest_reasons = validate_evo_v2_staging_manifest(
            next_manifest,
            root=root,
            report_id=report_id,
            verify_readback=False,
        )
        if manifest_reasons:
            raise EvoV2Error(BLOCK_EVO_V2_INVALID, manifest_reasons)

        for name, payload in outputs.items():
            _atomic_write(output_paths[name], payload)
        manifest_path = staging_manifest_path(root, report_id)
        if manifest_path.exists():
            # Manifest is the CAS commit record and therefore is the only
            # staged file that must change on a successful append.
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{manifest_path.name}.",
                suffix=".tmp",
                dir=manifest_path.parent,
            )
            os.close(descriptor)
            temporary_path = Path(temporary)
            try:
                temporary_path.write_bytes(canonical_json_bytes(next_manifest))
                os.replace(temporary_path, manifest_path)
            finally:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
        else:
            _atomic_write(manifest_path, next_manifest)

        readback_manifest = _load_manifest(root, report_id)
        if readback_manifest != next_manifest:
            raise EvoV2Error(
                BLOCK_EVO_V2_INVALID,
                ["staging.manifest.readback_mismatch"],
            )
        for name, payload in outputs.items():
            if _load_existing_payload(output_paths[name]) != payload:
                raise EvoV2Error(
                    BLOCK_EVO_V2_INVALID,
                    [f"staging.output.readback_mismatch:{name}"],
                )
        return {
            "stage": stage,
            "outcome": outcome,
            "idempotent_replay": False,
            "written": {ref["name"]: ref for ref in output_refs},
            "staging_manifest": {
                "path": _relative_path(root, manifest_path),
                "content_sha256": next_manifest["content_sha256"],
                "sha256": sha256_file(manifest_path),
            },
        }


__all__ = [
    "NO_DERIVED_LAW_FILENAME",
    "STAGE_ADMIT_COUNCIL_OUTCOME",
    "STAGE_ADMIT_FEEDBACK",
    "STAGE_ADMIT_TRANSFER",
    "STAGE_RECORD_USE",
    "STAGES",
    "STAGING_MANIFEST_VERSION",
    "materialize_evo_v2_stage",
    "no_derived_law_path",
    "staging_manifest_path",
    "validate_evo_v2_staging_manifest",
]
