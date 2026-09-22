#!/usr/bin/env python3
"""Create-only local trial: portable knowledge, numerical example, integration diff."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

from build_factorforge_knowledge_preview import _scrub, build_preview
from build_factorforge_retrieval_index import active_workspace_exports


REPO = Path(__file__).resolve().parents[1]
BASE = "525d4656eb77ba613a39b445ff72ac7eb81bbeeb"
PATCH_PATHS = (
    "factor_factory/epistemic_ultimate_source_first_bridge.py",
    "factor_factory/local_is_execution.py", "factor_factory/primary_evaluator.py",
    "factor_factory/partitioned_direct_code.py", "factor_factory/research_conjecture.py",
    "factor_factory/workspace_experience_export.py",
    "factor_factory/knowledge_context.py", "factor_factory/knowledge_reference.py",
    "factor_factory/semantic_knowledge_retrieval.py", "factor_factory/research_knowledge_maintenance.py",
    "scripts/maintain_factorforge_knowledge.py", "scripts/build_factorforge_semantic_index.py",
    "requirements-knowledge.txt",
    "docs/operations/knowledge-maintenance.zh-CN.md",
    "scripts/build_factorforge_retrieval_index.py", "scripts/build_factorforge_local_trial.py",
    "scripts/run_factorforge_epistemic_source_first_advisory.py", "scripts/run_factorforge_ultimate.py",
    "scripts/run_factorforge_local_step1.py",
    "skills/factor_forge_step1/modules/report_ingestion/merge/merge_to_alpha_idea_master.py",
    "tests/test_run_factorforge_local_step1.py", "tests/test_step2_local_agent_spec_inputs.py",
    "scripts/write_factorforge_research_protocol.py", "scripts/validate_factorforge_research_protocol.py",
    "skills/factor-forge-step1/scripts/standardize_step1_research_fields.py",
    "skills/factor-forge-step1/SKILL.md", "skills/factor-forge-step1/references/prompts.md",
    "skills/factor-forge-step2/SKILL.md", "skills/factor-forge-step2/references/prompts.md",
    "skills/factor-forge-step2/scripts/run_step2.py", "skills/factor-forge-step2/scripts/validate_step2.py",
    "skills/factor-forge-step6/scripts/run_step6.py", "skills/factor-forge-step6/scripts/validate_step6.py",
    "skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py",
    "skills/factor-forge-step6/scripts/approve_main_agent_council_synthesis.py",
    "skills/factor-forge-step6-researcher/scripts/build_researcher_packet.py",
    "tests/test_researcher_packet_preserves_review.py",
    "tests/test_step6_reviewed_failure_projection.py",
    "tests/test_step6_researcher_identity.py",
    "tests/test_step6_authored_failure_projection.py",
    "tests/test_step6_council_phase_visibility.py",
    "skills/factor-forge-step6/scripts/attach_revision_council_to_step6.py",
    "tests/test_step6_council_attachment_producer_modes.py",
    "tests/test_step6_local_terminal_rejection.py",
    "tests/test_step6_primary_evaluator_validator.py",
    "tests/test_step6_local_terminal_protocol_gate.py",
    "factor_factory/mechanism_math/main_agent_memo.py",
    "tests/test_mechanism_math_dirac_review.py",
    "tests/test_factorforge_formula_specific_derivation.py",
    "tests/test_factorforge_measurement_program_research_equation_v2.py",
    "tests/test_factorforge_measurement_program_pipeline.py",
    "tests/test_main_agent_memo_step2_knowledge_projection.py",
    "tests/test_main_agent_memo_v1_direct_code_projection.py",
    "tests/test_pfvv_trade_ledger_encoding.py",
    "tests/test_pfvv_step4_pipeline_integration.py",
    "skills/factor-forge-step3/scripts/run_step3.py", "skills/factor-forge-step3/scripts/run_step3b.py",
    "skills/factor-forge-step3/scripts/validate_step3.py", "skills/factor-forge-step3/scripts/validate_step3b.py",
    "skills/factor-forge-step4/scripts/run_step4.py", "skills/factor-forge-step4/scripts/validate_step4.py",
    "skills/factor-forge-step5/scripts/run_step5.py", "skills/factor-forge-step5/scripts/validate_step5.py", "skills/factor-forge-step5/modules/evaluator.py",
    "skills/factor-forge-step5/modules/case_builder.py", "skills/factor-forge-step5/modules/rules.py",
    "skills/factor_forge_step5/modules/evaluator.py", "skills/factor_forge_step5/modules/case_builder.py",
    "skills/factor_forge_step5/modules/rules.py",
    "factor_factory/provenance.py",
    "skills/factor-forge-step3/SKILL.md", "skills/factor-forge-step4/SKILL.md",
    "skills/factor-forge-ultimate/SKILL.md", "skills/factor-forge-ultimate/references/current-operating-contract.md",
    "tests/test_factorforge_epistemic_ultimate_source_first_bridge.py",
    "tests/test_factorforge_epistemic_retrieval_kernel_adapter_offline.py",
    "tests/test_factorforge_knowledge_context.py", "tests/test_factorforge_ultimate_epistemic_shadow.py",
    "tests/test_factorforge_knowledge_reference_graph.py", "tests/test_factorforge_knowledge_reuse_workflow.py",
    "tests/test_factorforge_retrieval_index.py", "tests/test_factorforge_ultimate_knowledge_refresh.py",
    "tests/test_prepared_derived_state_hook.py", "tests/test_primary_evaluator_bridge.py",
    "tests/test_step4_parent_evaluation_memory.py", "tests/test_prepared_primary_knowledge_projection.py",
    "tests/test_factorforge_research_protocol_local_is_scope.py",
    "tests/test_factorforge_ultimate_local_is_scope.py", "tests/test_workspace_experience_export.py",
    "tests/test_step4_data_api_contract.py",
    "tests/test_step2_source_subject_routing.py", "tests/test_workspace_experience_corrections.py",
    "tests/test_conditional_operator_method_reference.py",
    "scripts/build_factorforge_knowledge_preview.py", "tests/test_factorforge_knowledge_preview.py",
    "tests/test_research_episode_index.py", "tests/test_research_knowledge_maintenance.py",
    "tests/test_semantic_knowledge_retrieval.py", "tests/test_research_note_reuse.py",
    "docs/quickstart-knowledge-preview.zh-CN.md", "docs/quickstart-local-trial.zh-CN.md",
    "knowledge/因子工厂/graph/nodes/METHOD_TRANSIENT_SIGNAL_MODELS_20260907.json",
    "knowledge/因子工厂/graph/nodes/METHOD_SPARSE_EVENT_PROJECTION_FAILURE_20260907.json",
    "knowledge/因子工厂/graph/nodes/METHOD_CONDITIONAL_OPERATOR_REFERENCE_20260908.json",
    "docs/research/conditional-operator-reference-20260908.zh-CN.md",
    "docs/research/mszq-source-baseline-comparison-20260908.zh-CN.md",
    "docs/research/transient-signal-methods.zh-CN.md", "tests/test_transient_signal_method_reference.py",
    "examples/mszq_intraday_momentum_pulse/candidate_v2.py",
    "examples/mszq_intraday_momentum_pulse/pfvv_source_baseline_v1.py",
    "examples/mszq_intraday_momentum_pulse/pfvv_source_baseline_dataframe_adapter_v1.py",
    "examples/mszq_intraday_momentum_pulse/pfvv_source_baseline_partitioned_v1.py",
    "examples/mszq_intraday_momentum_pulse/pfvv_monthly_evaluation_v1.py",
    "examples/mszq_intraday_momentum_pulse/pfvv_monthly_step4_backend_v1.py",
    "examples/mszq_intraday_momentum_pulse/pfvv_daily_lookup_store_v1.py",
    "examples/mszq_intraday_momentum_pulse/pfvv_prepared_inputs_v1.py",
    "examples/mszq_intraday_momentum_pulse/pfvv_daily_measurements_v1.py",
    "examples/mszq_intraday_momentum_pulse/pfvv_market_inputs_v1.py",
    "examples/mszq_intraday_momentum_pulse/local_is_execution_engine/mszq_step4_portfolio_evaluator_candidate_v1.py",
    "examples/mszq_intraday_momentum_pulse/local_is_execution_engine/mszq_evaluation_calendar_candidate_v1.py",
    "examples/mszq_intraday_momentum_pulse/local_is_execution_engine/mszq_v17_normalized_constraints_candidate_v1.py",
    "examples/mszq_intraday_momentum_pulse/local_is_execution_engine/README.zh-CN.md",
    "scripts/package_pfvv_prepared_outputs.py",
    "examples/mszq_intraday_momentum_pulse/pfvv_reconstruction.json",
    "tests/test_mszq_pfvv_source_baseline_v1.py",
    "tests/test_mszq_pfvv_source_baseline_dataframe_adapter_v1.py",
    "tests/test_mszq_pfvv_source_baseline_partitioned_v1.py",
    # partitioned/prepared-input tests remain patch-only because their end-to-end
    # cases import Step3 scripts that are not part of the standalone payload.
    "tests/test_mszq_pfvv_monthly_evaluation_v1.py",
    "tests/test_mszq_pfvv_prepared_inputs_v1.py",
    "tests/test_mszq_pfvv_daily_measurements_v1.py",
    "tests/test_mszq_pfvv_monthly_step4_backend_v1.py",
    "tests/test_mszq_pfvv_daily_lookup_store_v1.py",
    # daily-measurements test imports the patch-only partitioned test fixture.
    "tests/test_mszq_pfvv_market_inputs_v1.py",
    "tests/test_package_pfvv_prepared_outputs.py",
    "tests/test_local_trial_packaging_paths.py",
    "docs/research/pfvv-baseline-numerical-validation-20260908.zh-CN.md",
    "examples/mszq_intraday_momentum_pulse/recheck_projection.py",
    "examples/mszq_intraday_momentum_pulse/README.zh-CN.md", "tests/test_mszq_candidate_v2.py",
    "docs/research/new-b-knowledge-reuse-acceptance-20260908.zh-CN.md",
)
STANDALONE = tuple(path for path in PATCH_PATHS if path.startswith("examples/")) + (
    "tests/test_mszq_pfvv_source_baseline_v1.py",
    "tests/test_mszq_pfvv_source_baseline_dataframe_adapter_v1.py",
    "tests/test_mszq_pfvv_monthly_evaluation_v1.py",
    "docs/research/pfvv-baseline-numerical-validation-20260908.zh-CN.md",
    "tests/test_mszq_candidate_v2.py",
    "docs/research/new-b-knowledge-reuse-acceptance-20260908.zh-CN.md",
    "docs/research/transient-signal-methods.zh-CN.md",
    "factor_factory/__init__.py",
    "factor_factory/partitioned_direct_code.py",
    "factor_factory/primary_evaluator.py",
    "scripts/package_pfvv_prepared_outputs.py",
    "tests/test_mszq_pfvv_monthly_step4_backend_v1.py",
    "tests/test_mszq_pfvv_daily_lookup_store_v1.py",
    "tests/test_mszq_pfvv_market_inputs_v1.py",
    "tests/test_package_pfvv_prepared_outputs.py",
    "tests/test_pfvv_trade_ledger_encoding.py",
)

EXPORT_ROOT = Path("knowledge/因子工厂/workspace_experience_exports")
EXPORT_STATUS = "LOCAL_PROJECT_ADVISORY_CANDIDATE_NOT_CANONICAL"
EXPORT_VERSION = "factorforge_workspace_experience_export_v1"


def _candidate_export_patch(relative: Path) -> bytes:
    """Return a create-only, scrubbed patch for one explicitly chosen seed."""
    if relative.is_absolute() or relative.parent != EXPORT_ROOT:
        raise ValueError("candidate export must be an immediate relative member of workspace_experience_exports")
    if not relative.name.startswith("knowledge_record__") or relative.suffix != ".json":
        raise ValueError("candidate export must use knowledge_record__<report_id>.json")
    lexical_root = REPO / EXPORT_ROOT
    lexical_source = REPO / relative
    # Test the lexical path before resolution: a symlink located inside the
    # allowed directory must not inherit trust from its resolved destination.
    if lexical_root.is_symlink() or lexical_source.is_symlink():
        raise ValueError("candidate export must not use a symlink")
    source = lexical_source.resolve()
    export_root = lexical_root.resolve()
    if not source.is_file() or not source.is_relative_to(export_root):
        raise ValueError("candidate export must be a regular file under the default export directory")
    raw = source.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("candidate export has invalid advisory contract")
    if (
        payload.get("export_version") != EXPORT_VERSION
        or payload.get("export_status") != EXPORT_STATUS
        or payload.get("advisory_only") is not True
        or payload.get("same_factor_not_generalized") is not True
        or payload.get("canonical_promotion_allowed") is not False
        or not isinstance(payload.get("report_id"), str)
        or not isinstance(payload.get("factor_id"), str)
        or not payload["factor_id"].strip()
    ):
        raise ValueError("candidate export has invalid advisory contract")
    basename = f'knowledge_record__{payload["report_id"]}'
    if not (relative.stem == basename or
            (payload.get('export_revision') and relative.stem.startswith(basename + '__'))):
        raise ValueError("candidate export filename and report identity differ")
    if source not in {path.resolve() for path, _ in active_workspace_exports(export_root)}:
        raise ValueError("candidate export is superseded; package the active correction")
    sanitized = _scrub(payload)
    if not isinstance(sanitized, dict):
        raise ValueError("candidate export scrub produced invalid payload")
    sanitized["package_projection"] = {
        "projection_version": "factorforge_trial_candidate_export_seed_v1",
        "sanitized": True,
        "source_export_sha256": hashlib.sha256(raw).hexdigest(),
        "original_source_record_included": False,
        "original_source_record_verified_in_package": False,
    }
    # A portable seed is a new advisory projection, not a byte-identical copy
    # of the local history. Do not leave a dangling supersession chain whose
    # predecessor bytes were scrubbed or were deliberately not distributed.
    source_revision = sanitized.pop("export_revision", None)
    if source_revision is not None:
        sanitized["package_projection"]["source_revision_context_not_replayable"] = source_revision
    content = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    path = (EXPORT_ROOT / (basename + '.json')).as_posix()
    lines = list(difflib.unified_diff(
        [], content.splitlines(keepends=True), fromfile="/dev/null", tofile=f"b/{path}", lineterm="",
    ))
    patch = "\n".join((
        f"diff --git a/{path} b/{path}",
        "new file mode 100644",
        *lines,
        "",
    ))
    return patch.encode("utf-8")


def build(output: Path, *, candidate_exports: tuple[Path, ...] = ()) -> None:
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refuse existing trial output: {output}")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if head != BASE:
        raise ValueError("trial patch must be built against the documented base")
    if len(set(candidate_exports)) != len(candidate_exports):
        raise ValueError("duplicate candidate export paths are not allowed")
    # No git writes here: new files must be in the caller's explicit selection.
    selected = []
    for path in PATCH_PATHS:
        candidate = REPO / path
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        selected.append(path)
    tracked = subprocess.check_output(["git", "ls-files", "--", *selected], cwd=REPO, text=True).splitlines()
    untracked = [path for path in selected if path not in tracked]
    diff = (
        subprocess.check_output(
            ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--", *tracked], cwd=REPO,
        )
        if tracked else b""
    )
    for path in untracked:
        # `git diff --no-index` intentionally returns 1 when it found the
        # new file.  It is an expected diff status, not a packaging failure.
        completed = subprocess.run(
            ["git", "diff", "--binary", "--no-index", "/dev/null", path],
            cwd=REPO,
            stdout=subprocess.PIPE,
            check=False,
        )
        if completed.returncode not in (0, 1):
            raise subprocess.CalledProcessError(completed.returncode, completed.args)
        diff += completed.stdout
    for candidate_export in candidate_exports:
        diff += _candidate_export_patch(candidate_export)
    if not diff:
        raise ValueError("empty integration patch")
    with tempfile.TemporaryDirectory(prefix="factorforge-local-trial-") as temporary:
        preview = build_preview(source_root=REPO, output=Path(temporary) / "preview.zip")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("README.zh-CN.md", (REPO / "docs/quickstart-local-trial.zh-CN.md").read_bytes())
            archive.writestr("ultimate-integration.patch", diff)
            archive.writestr("requirements-numerical-test.txt", "numpy>=1.24\npandas>=2.1\npyarrow>=14.0\npsutil>=5.9\npytest>=7.0\n")
            for path in STANDALONE:
                archive.write(REPO / path, path)
            with zipfile.ZipFile(preview) as source:
                for name in source.namelist():
                    if name.startswith("/") or ".." in Path(name).parts:
                        raise ValueError("unsafe preview member")
                    archive.writestr("knowledge-preview/" + name, source.read(name))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--candidate-export", type=Path, action="append", default=[],
        help="Explicit relative candidate export to seed into this trial patch; repeatable.",
    )
    args = parser.parse_args()
    build(args.output, candidate_exports=tuple(args.candidate_export))
    print(args.output.resolve())
