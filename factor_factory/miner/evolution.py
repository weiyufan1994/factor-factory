from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from factor_factory.miner.candidates import validate_candidate_packet
from factor_factory.miner.cheap_screen import (
    validate_cheap_screen_summary,
    validate_search_control,
)
from factor_factory.miner.common import utc_now, workspace_path, write_json, write_markdown


BLOCK_EVOLUTION_EVIDENCE_INVALID = "BLOCK_FACTORFORGE_MINER_EVOLUTION_EVIDENCE_INVALID"
BLOCK_EVOLUTION_PROGRAM_MISSING = "BLOCK_FACTORFORGE_MINER_EVOLUTION_PROGRAM_MISSING"


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percentile_scores(
    values: dict[str, float],
    *,
    higher_is_better: bool = True,
) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(
        values.items(),
        key=lambda item: item[1],
        reverse=higher_is_better,
    )
    denominator = max(1, len(ordered) - 1)
    return {
        candidate_id: 1.0 - index / denominator
        for index, (candidate_id, _) in enumerate(ordered)
    }


def _complexity(packet: dict[str, Any]) -> float:
    program = packet.get("candidate_program_contract")
    program = program if isinstance(program, dict) else {}
    operator_count = len(program.get("operator_dependencies") or [])
    parameter_count = len(program.get("parameters") or {})
    return float(operator_count + parameter_count)


def _score_population(
    packets: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    usable = [
        row
        for row in results
        if row.get("signal_source") == "candidate_specific"
        and row.get("coverage", 0)
        and _number(row.get("rank_ic_mean")) is not None
        and _number(row.get("long_end_gross")) is not None
    ]
    metrics = {
        "rank_ic": {
            str(row["candidate_id"]): float(row["rank_ic_mean"]) for row in usable
        },
        "long_end": {
            str(row["candidate_id"]): float(row["long_end_gross"]) for row in usable
        },
        "spread": {
            str(row["candidate_id"]): float(row["group_spread_gross"])
            for row in usable
            if _number(row.get("group_spread_gross")) is not None
        },
        "hit_rate": {
            str(row["candidate_id"]): float(row["ic_hit_rate"])
            for row in usable
            if _number(row.get("ic_hit_rate")) is not None
        },
        "turnover": {
            str(row["candidate_id"]): float(row["turnover_estimate"])
            for row in usable
            if _number(row.get("turnover_estimate")) is not None
        },
        "complexity": {
            str(row["candidate_id"]): _complexity(packets[str(row["candidate_id"])])
            for row in usable
            if str(row["candidate_id"]) in packets
        },
    }
    ranks = {
        "rank_ic": _percentile_scores(metrics["rank_ic"]),
        "long_end": _percentile_scores(metrics["long_end"]),
        "spread": _percentile_scores(metrics["spread"]),
        "hit_rate": _percentile_scores(metrics["hit_rate"]),
        "turnover": _percentile_scores(
            metrics["turnover"],
            higher_is_better=False,
        ),
        "complexity": _percentile_scores(
            metrics["complexity"],
            higher_is_better=False,
        ),
    }
    population: list[dict[str, Any]] = []
    for row in results:
        candidate_id = str(row.get("candidate_id") or "")
        packet = packets.get(candidate_id, {})
        program = packet.get("candidate_program_contract")
        if not isinstance(program, dict) or not program.get("program_hash"):
            raise ValueError(f"{BLOCK_EVOLUTION_PROGRAM_MISSING}:{candidate_id}")
        if row.get("program_hash") != program.get("program_hash"):
            raise ValueError(
                f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:program_hash_mismatch:{candidate_id}"
            )
        metric_score = (
            0.25 * ranks["rank_ic"].get(candidate_id, 0.0)
            + 0.25 * ranks["long_end"].get(candidate_id, 0.0)
            + 0.15 * ranks["spread"].get(candidate_id, 0.0)
            + 0.10 * ranks["hit_rate"].get(candidate_id, 0.0)
            + 0.15 * ranks["turnover"].get(candidate_id, 0.0)
            + 0.10 * ranks["complexity"].get(candidate_id, 0.0)
        )
        eligible = (
            row.get("signal_source") == "candidate_specific"
            and row.get("decision")
            in {"send_to_formal_research", "keep_as_feature", "discard"}
        )
        population.append(
            {
                "candidate_id": candidate_id,
                "template_id": packet.get("template_id"),
                "family": packet.get("family"),
                "program_hash": program.get("program_hash"),
                "parent_program_hash": program.get("parent_program_hash"),
                "decision": row.get("decision"),
                "eligible_for_evolution": eligible,
                "evaluator_score": round(metric_score, 8) if eligible else None,
                "score_components": {
                    key: ranks[key].get(candidate_id, 0.0) for key in ranks
                },
                "metrics": {
                    key: row.get(key)
                    for key in (
                        "rank_ic_mean",
                        "rank_ic_ir",
                        "ic_hit_rate",
                        "group_spread_gross",
                        "long_end_gross",
                        "short_end_gross",
                        "monotonicity_score",
                        "turnover_estimate",
                        "coverage",
                    )
                },
                "complexity": _complexity(packet),
                "evidence_role": row.get("evidence_role"),
                "promotion_forbidden_until_formal": True,
            }
        )
    return population


def _select_elites(
    population: list[dict[str, Any]],
    *,
    elite_limit: int,
) -> list[dict[str, Any]]:
    ranked = sorted(
        (
            row
            for row in population
            if row.get("eligible_for_evolution")
            and row.get("evaluator_score") is not None
        ),
        key=lambda row: float(row["evaluator_score"]),
        reverse=True,
    )
    elites: list[dict[str, Any]] = []
    represented: set[str] = set()
    for row in ranked:
        family = str(row.get("family") or "unknown")
        if family in represented:
            continue
        elites.append(row)
        represented.add(family)
        if len(elites) >= elite_limit:
            return elites
    for row in ranked:
        if row in elites:
            continue
        elites.append(row)
        if len(elites) >= elite_limit:
            break
    return elites


def _mutation_briefs(elites: list[dict[str, Any]], generation: int) -> list[dict[str, Any]]:
    mutation_types = (
        "component_ablation",
        "normalization_variant",
        "parameter_neighbor",
        "null_control",
    )
    briefs: list[dict[str, Any]] = []
    for elite in elites:
        for mutation_type in mutation_types:
            briefs.append(
                {
                    "mutation_id": (
                        f"g{generation + 1:02d}__{elite['candidate_id']}__{mutation_type}"
                    ),
                    "parent_candidate_id": elite["candidate_id"],
                    "parent_program_hash": elite["program_hash"],
                    "family": elite.get("family"),
                    "mutation_type": mutation_type,
                    "research_question": (
                        "Which part of the candidate's executable estimator creates incremental "
                        "information rather than an alias or extra degree of freedom?"
                    ),
                    "required_program_change": (
                        "Materialize a new candidate-specific executable program and a distinct program hash."
                    ),
                    "required_lineage": [
                        "parent_program_hash",
                        "changed_math_object_or_component",
                        "added_or_removed_degrees_of_freedom",
                        "expected_metric_signature",
                        "kill_criteria",
                    ],
                    "oos_access_allowed": False,
                    "promotion_forbidden_until_formal": True,
                    "status": "proposal_requires_program_materialization",
                }
            )
    return briefs


def _program_hash(program: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(program, sort_keys=True).encode("utf-8")
    ).hexdigest()


def materialize_mutation_population(
    *,
    campaign_id: str,
    workspace_root: Path,
    candidate_manifest: dict[str, Any],
    mutation_briefs: list[dict[str, Any]],
    generation: int,
    forbidden_program_hashes: set[str] | None = None,
) -> dict[str, Any]:
    parents = {
        str(packet.get("candidate_id")): packet
        for packet in candidate_manifest.get("candidates") or []
        if isinstance(packet, dict) and packet.get("candidate_id")
    }
    candidates: list[dict[str, Any]] = []
    seen_program_hashes = set(forbidden_program_hashes or set())
    for brief in mutation_briefs:
        parent = parents.get(str(brief.get("parent_candidate_id") or ""))
        if not parent:
            continue
        parent_program = parent.get("candidate_program_contract")
        if not isinstance(parent_program, dict):
            continue
        mutation_type = str(brief.get("mutation_type") or "")
        parameters = deepcopy(parent_program.get("parameters") or {})
        changed_component = ""
        if mutation_type == "component_ablation":
            parameters["ablation"] = "identity_raw_field"
            changed_component = "replace derived estimator with first raw component"
        elif mutation_type == "normalization_variant":
            parameters["normalization"] = (
                "cross_sectional_zscore"
                if parameters.get("normalization") == "cross_sectional_rank"
                else "cross_sectional_rank"
            )
            changed_component = "cross-sectional normalization operator"
        elif mutation_type == "parameter_neighbor":
            if parent_program.get("entrypoint") == "turnover_acceleration":
                parameters["lookback"] = int(parameters.get("lookback") or 5) + 2
                changed_component = "turnover baseline lookback"
            elif parent_program.get("entrypoint") == "realized_var_over_range":
                parameters["range_floor"] = float(
                    parameters.get("range_floor") or 1e-6
                ) * 10.0
                changed_component = "range denominator floor"
            else:
                parameters["normalization"] = "cross_sectional_zscore"
                changed_component = "nearest executable normalization parameter"
        elif mutation_type == "null_control":
            parameters["null_control"] = "lag_one_period"
            changed_component = "lagged null-control estimator"
        else:
            continue
        program = {
            "language": parent_program.get("language"),
            "entrypoint": parent_program.get("entrypoint"),
            "required_fields": list(parent_program.get("required_fields") or []),
            "operator_dependencies": list(
                parent_program.get("operator_dependencies") or []
            ),
            "parameters": parameters,
        }
        program_hash = _program_hash(program)
        if program_hash == parent_program.get("program_hash"):
            raise ValueError(
                f"{BLOCK_EVOLUTION_PROGRAM_MISSING}:mutation_hash_unchanged"
            )
        if program_hash in seen_program_hashes:
            continue
        seen_program_hashes.add(program_hash)
        candidate_id = "miner_mut__" + hashlib.sha1(
            (
                f"{campaign_id}:{generation}:{brief.get('mutation_id')}:{program_hash}"
            ).encode("utf-8")
        ).hexdigest()[:14]
        packet = deepcopy(parent)
        packet.update(
            {
                "candidate_id": candidate_id,
                "candidate_version": "factorforge_miner_candidate_packet_v1",
                "formula_or_recipe": (
                    f"{parent_program.get('entrypoint')}({json.dumps(parameters, sort_keys=True)})"
                ),
                "parameters": parameters,
                "cheap_screen_factor_column": f"factor__{candidate_id}",
                "cheap_screen_status": "not_run",
                "formal_research_status": "not_started",
                "mutation_lineage": {
                    "generation": generation,
                    "mutation_id": brief.get("mutation_id"),
                    "mutation_type": mutation_type,
                    "parent_candidate_id": parent.get("candidate_id"),
                    "parent_program_hash": parent_program.get("program_hash"),
                    "changed_math_object_or_component": changed_component,
                    "added_or_removed_degrees_of_freedom": (
                        -1 if mutation_type == "component_ablation" else 0
                    ),
                },
            }
        )
        packet["candidate_program_contract"] = {
            **program,
            "program_hash": program_hash,
            "parent_program_hash": parent_program.get("program_hash"),
            "materialization_status": "executable_ready",
            "expected_factor_column": f"factor__{candidate_id}",
            "shared_fixture_signal_allowed": False,
        }
        candidates.append(packet)
    manifest = {
        "version": "factorforge_miner_mutation_population_v1",
        "campaign_id": campaign_id,
        "generation": generation,
        "generated_at_utc": utc_now(),
        "data_split_manifest_ref": candidate_manifest.get(
            "data_split_manifest_ref"
        ),
        "data_split_manifest_sha256": candidate_manifest.get(
            "data_split_manifest_sha256"
        ),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "all_program_hashes_distinct": len(
            {
                (packet.get("candidate_program_contract") or {}).get("program_hash")
                for packet in candidates
            }
        )
        == len(candidates),
        "promotion_forbidden_until_formal": True,
    }
    base = workspace_path(
        workspace_root,
        "objects",
        "evolution",
        f"g{generation:02d}",
        campaign_id=campaign_id,
    )
    write_json(base / "mutation_candidate_manifest.json", manifest)
    for packet in candidates:
        write_json(
            base / "candidates" / f"candidate_packet__{packet['candidate_id']}.json",
            packet,
        )
    return manifest


def build_evolution_round(
    *,
    campaign_id: str,
    workspace_root: Path,
    candidate_manifest: dict[str, Any],
    cheap_screen_summary: dict[str, Any],
    generation: int,
    elite_limit: int = 4,
) -> dict[str, Any]:
    replay_reasons = validate_cheap_screen_summary(
        cheap_screen_summary,
        workspace_root=workspace_root,
        expected_campaign_id=campaign_id,
    )
    if replay_reasons:
        raise ValueError(
            f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:"
            + ";".join(replay_reasons)
        )
    if candidate_manifest.get("campaign_id") != campaign_id:
        raise ValueError(f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:manifest_campaign")
    if cheap_screen_summary.get("campaign_id") != campaign_id:
        raise ValueError(f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:summary_campaign")
    if (
        candidate_manifest.get("generation") != generation
        or cheap_screen_summary.get("generation") != generation
    ):
        raise ValueError(
            f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:generation_binding"
        )
    if cheap_screen_summary.get("evidence_role") != "exploratory_evidence":
        raise ValueError(f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:evidence_role")
    if cheap_screen_summary.get("promotion_forbidden_until_formal") is not True:
        raise ValueError(f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:promotion_boundary")
    if cheap_screen_summary.get("fixture_shared_signal_used") is True:
        raise ValueError(f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:fixture_shared_signal")
    search_control = cheap_screen_summary.get("search_control")
    current_program_hashes = {
        str((packet.get("candidate_program_contract") or {}).get("program_hash"))
        for packet in candidate_manifest.get("candidates") or []
        if isinstance(packet, dict)
        and packet.get("dependency_status") == "ready"
        and (packet.get("candidate_program_contract") or {}).get("program_hash")
    }
    control_reasons = validate_search_control(
        search_control,
        required_trial_count=len(current_program_hashes),
        required_program_hashes=current_program_hashes,
        workspace_root=workspace_root,
        expected_generation=generation,
        expected_campaign_id=campaign_id,
        expected_data_snapshot_hash=cheap_screen_summary.get("source_panel_sha256"),
        expected_is_source_hash=cheap_screen_summary.get(
            "program_execution_source_sha256"
        ),
        expected_selection_window_id=cheap_screen_summary.get("screen_window"),
        expected_universe_id=cheap_screen_summary.get("universe"),
    )
    if control_reasons:
        raise ValueError(
            f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:"
            + ";".join(control_reasons)
        )

    packets: dict[str, dict[str, Any]] = {}
    for packet in candidate_manifest.get("candidates") or []:
        if not isinstance(packet, dict):
            raise ValueError(f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:candidate_packet")
        validate_candidate_packet(packet)
        if packet.get("campaign_id") != campaign_id:
            raise ValueError(
                f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:candidate_campaign"
            )
        candidate_id = str(packet.get("candidate_id") or "")
        if candidate_id in packets:
            raise ValueError(
                f"{BLOCK_EVOLUTION_EVIDENCE_INVALID}:candidate_id_duplicate"
            )
        packets[candidate_id] = packet
    population = _score_population(
        packets,
        [
            row
            for row in cheap_screen_summary.get("results") or []
            if isinstance(row, dict)
        ],
    )
    elites = _select_elites(population, elite_limit=max(1, elite_limit))
    briefs = _mutation_briefs(elites, generation)
    trial_budget = int(search_control["trial_budget"])
    trials_used = int(search_control["trials_used"])
    remaining_trial_budget = max(0, trial_budget - trials_used)
    briefs = briefs[:remaining_trial_budget]
    mutation_population = materialize_mutation_population(
        campaign_id=campaign_id,
        workspace_root=workspace_root,
        candidate_manifest=candidate_manifest,
        mutation_briefs=briefs,
        generation=generation + 1,
        forbidden_program_hashes=set(
            str(value)
            for value in search_control.get("tested_program_hashes") or []
        ),
    )
    family_count = len(
        {
            str(row.get("family"))
            for row in population
            if row.get("eligible_for_evolution")
        }
    )
    payload = {
        "version": "factorforge_miner_evolution_round_v1",
        "campaign_id": campaign_id,
        "generation": generation,
        "generated_at_utc": utc_now(),
        "selection_evidence_role": "exploratory_evidence",
        "oos_sealed": True,
        "remaining_trial_budget_before_mutation": remaining_trial_budget,
        "search_control": search_control,
        "evaluator_contract": {
            "candidate_specific_program_required": True,
            "shared_signal_forbidden": True,
            "score_is_for_search_only": True,
            "promotion_forbidden_until_formal": True,
            "score_components": [
                "rank_ic",
                "long_end",
                "spread",
                "hit_rate",
                "turnover_penalty",
                "complexity_penalty",
            ],
        },
        "diversity_contract": {
            "family_count": family_count,
            "elite_limit": elite_limit,
            "one_per_family_before_refill": True,
        },
        "population": population,
        "elites": [
            {
                "candidate_id": row["candidate_id"],
                "family": row.get("family"),
                "program_hash": row.get("program_hash"),
                "evaluator_score": row.get("evaluator_score"),
            }
            for row in elites
        ],
        "mutation_briefs": briefs,
        "mutation_population": {
            "generation": mutation_population.get("generation"),
            "candidate_count": mutation_population.get("candidate_count"),
            "manifest_path": (
                f"objects/evolution/g{generation + 1:02d}/"
                "mutation_candidate_manifest.json"
            ),
            "all_program_hashes_distinct": mutation_population.get(
                "all_program_hashes_distinct"
            ),
        },
        "promotion_forbidden_until_formal": True,
    }
    round_path = workspace_path(
        workspace_root,
        "objects",
        "evolution",
        f"evolution_round__g{generation:02d}.json",
        campaign_id=campaign_id,
    )
    write_json(round_path, payload)
    archive = {
        "version": "factorforge_miner_candidate_archive_v1",
        "campaign_id": campaign_id,
        "updated_at_utc": utc_now(),
        "latest_generation": generation,
        "programs": population,
        "failed_or_discarded": [
            row
            for row in population
            if row.get("decision") == "discard"
            or row.get("eligible_for_evolution") is not True
        ],
        "anti_repeat_program_hashes": [
            row.get("program_hash")
            for row in population
            if row.get("decision") == "discard" and row.get("program_hash")
        ],
    }
    write_json(
        workspace_path(
            workspace_root,
            "objects",
            "evolution",
            "candidate_archive.json",
            campaign_id=campaign_id,
        ),
        archive,
    )
    lines = [
        "# Miner Evolution Round",
        "",
        f"campaign_id: `{campaign_id}`",
        f"generation: `{generation}`",
        "",
        "| candidate | family | score |",
        "|---|---|---:|",
    ]
    for row in payload["elites"]:
        lines.append(
            f"| `{row['candidate_id']}` | `{row['family']}` | `{row['evaluator_score']}` |"
        )
    write_markdown(
        workspace_path(
            workspace_root,
            "docs",
            f"evolution_round__g{generation:02d}.md",
            campaign_id=campaign_id,
        ),
        "\n".join(lines),
    )
    return payload
