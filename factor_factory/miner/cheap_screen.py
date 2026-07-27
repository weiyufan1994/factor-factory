from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from statistics import mean, pstdev, stdev
from typing import Any

import pandas as pd
from scipy.stats import t as student_t

from factor_factory.miner.candidates import validate_candidate_packet
from factor_factory.miner.common import read_json, utc_now, workspace_path, write_json, write_markdown
from factor_factory.miner.data_split import validate_data_split_reference
from factor_factory.miner.program_executor import (
    validate_program_execution_report,
)
from factor_factory.research_evidence import (
    resolve_workspace_evidence_path,
    sha256_file,
)


SEARCH_CONTROL_VERSION = "factorforge_miner_search_control_v1"
SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
BLOCK_SEARCH_CONTROL_INVALID = "BLOCK_FACTORFORGE_MINER_SEARCH_CONTROL_INVALID"
SCREENING_POLICY_VERSION = "factorforge_miner_cheap_screen_policy_v1"
BLOCK_CHEAP_SCREEN_REPLAY_INVALID = (
    "BLOCK_FACTORFORGE_MINER_CHEAP_SCREEN_REPLAY_INVALID"
)


def validate_search_control(
    control: Any,
    *,
    required_trial_count: int,
    required_program_hashes: set[str] | None = None,
    workspace_root: Path | None = None,
    expected_generation: int | None = None,
    expected_campaign_id: str | None = None,
    expected_data_snapshot_hash: str | None = None,
    expected_is_source_hash: str | None = None,
    expected_selection_window_id: str | None = None,
    expected_universe_id: str | None = None,
    _history_seen: set[Path] | None = None,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(control, dict):
        return [f"{BLOCK_SEARCH_CONTROL_INVALID}:missing"]
    if control.get("version") != SEARCH_CONTROL_VERSION:
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:version")
    if control.get("selection_window_role") != "IS_SEARCH":
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:window_role")
    if control.get("oos_sealed") is not True:
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:oos_not_sealed")
    for field, expected in (
        ("campaign_id", expected_campaign_id),
        ("selection_window_id", expected_selection_window_id),
        ("universe_id", expected_universe_id),
    ):
        value = control.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:{field}")
        elif expected is not None and value != expected:
            reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:{field}_mismatch")
    for field in ("sealed_oos_token_hash", "data_snapshot_hash"):
        value = control.get(field)
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value.lower()):
            reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:{field}")
    if (
        control.get("sealed_oos_token_hash")
        != control.get("data_split_manifest_sha256")
    ):
        reasons.append(
            f"{BLOCK_SEARCH_CONTROL_INVALID}:sealed_oos_token_binding"
        )
    if workspace_root is None:
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:workspace_root")
    else:
        split_reasons = validate_data_split_reference(
            workspace_root=workspace_root,
            manifest_ref=control.get("data_split_manifest_ref"),
            manifest_sha256=control.get("data_split_manifest_sha256"),
            expected_campaign_id=expected_campaign_id
            or control.get("campaign_id"),
            expected_is_panel_sha256=expected_is_source_hash,
            expected_selection_window_id=expected_selection_window_id
            or control.get("selection_window_id"),
            expected_universe_id=expected_universe_id
            or control.get("universe_id"),
        )
        reasons.extend(
            f"{BLOCK_SEARCH_CONTROL_INVALID}:data_split:{reason}"
            for reason in split_reasons
        )
    for field in ("purge_days", "embargo_days"):
        value = control.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:{field}")
    generation = control.get("generation")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 0
    ):
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:generation")
        generation = None
    elif (
        expected_generation is not None
        and generation != expected_generation
    ):
        reasons.append(
            f"{BLOCK_SEARCH_CONTROL_INVALID}:generation_mismatch"
        )
    trial_budget = control.get("trial_budget")
    trials_used = control.get("trials_used")
    tested_program_hashes = control.get("tested_program_hashes")
    tested_program_hashes = (
        tested_program_hashes if isinstance(tested_program_hashes, list) else []
    )
    normalized_hashes = [
        str(value).lower()
        for value in tested_program_hashes
        if isinstance(value, str)
    ]
    if (
        not isinstance(control.get("tested_program_hashes"), list)
        or len(normalized_hashes) != len(tested_program_hashes)
        or any(not SHA256_RE.fullmatch(value) for value in normalized_hashes)
        or len(set(normalized_hashes)) != len(normalized_hashes)
    ):
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:tested_program_hashes")
    if (
        isinstance(trial_budget, bool)
        or not isinstance(trial_budget, int)
        or trial_budget < 1
        or isinstance(trials_used, bool)
        or not isinstance(trials_used, int)
        or trials_used != len(normalized_hashes)
        or len(normalized_hashes) < required_trial_count
    ):
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:trial_ledger")
    elif trials_used > trial_budget:
        reasons.append("BLOCK_FACTORFORGE_MINER_TRIAL_BUDGET_EXCEEDED")
    required_program_hashes = {
        str(value).lower() for value in (required_program_hashes or set())
    }
    if not required_program_hashes.issubset(set(normalized_hashes)):
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:current_programs_unrecorded")
    if (
        expected_data_snapshot_hash is not None
        and control.get("data_snapshot_hash") != expected_data_snapshot_hash
    ):
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:data_snapshot_hash_mismatch")
    if control.get("multiple_testing_policy") not in {
        "BH_FDR",
        "holm_bonferroni",
    }:
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:multiple_testing_policy")
    multiplicity_alpha = control.get("multiplicity_alpha")
    if (
        isinstance(multiplicity_alpha, bool)
        or not isinstance(multiplicity_alpha, (int, float))
        or not math.isfinite(float(multiplicity_alpha))
        or not 0 < float(multiplicity_alpha) <= 0.2
    ):
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:multiplicity_alpha")
    for field in ("cost_model_id", "capacity_model_id", "regime_plan_id"):
        value = control.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:{field}")
    policy = control.get("screening_policy")
    if not isinstance(policy, dict):
        reasons.append(f"{BLOCK_SEARCH_CONTROL_INVALID}:screening_policy")
    else:
        if policy.get("version") != SCREENING_POLICY_VERSION:
            reasons.append(
                f"{BLOCK_SEARCH_CONTROL_INVALID}:screening_policy_version"
            )
        if policy.get("return_unit") != "decimal":
            reasons.append(
                f"{BLOCK_SEARCH_CONTROL_INVALID}:screening_return_unit"
            )
        policy_values: dict[str, float] = {}
        for field in (
            "send_min_rank_ic",
            "send_min_group_spread",
            "send_min_long_end",
            "keep_min_abs_rank_ic",
            "keep_min_abs_group_spread",
        ):
            value = policy.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                reasons.append(
                    f"{BLOCK_SEARCH_CONTROL_INVALID}:screening_policy:{field}"
                )
            else:
                policy_values[field] = float(value)
        if (
            policy_values.get("send_min_rank_ic", -1)
            < policy_values.get("keep_min_abs_rank_ic", 0)
            or policy_values.get("send_min_group_spread", -1)
            < policy_values.get("keep_min_abs_group_spread", 0)
        ):
            reasons.append(
                f"{BLOCK_SEARCH_CONTROL_INVALID}:screening_policy_order"
            )
    previous_ref = control.get("previous_search_control_ref")
    previous_sha = control.get("previous_search_control_sha256")
    if generation == 0:
        if (
            previous_ref is not None
            and previous_ref != ""
        ) or (
            previous_sha is not None
            and previous_sha != ""
        ):
            reasons.append(
                f"{BLOCK_SEARCH_CONTROL_INVALID}:generation_zero_has_parent"
            )
    elif isinstance(generation, int) and generation > 0:
        if workspace_root is None:
            reasons.append(
                f"{BLOCK_SEARCH_CONTROL_INVALID}:history_workspace_missing"
            )
        elif (
            not isinstance(previous_ref, str)
            or not previous_ref.strip()
            or not isinstance(previous_sha, str)
            or not SHA256_RE.fullmatch(previous_sha.lower())
        ):
            reasons.append(
                f"{BLOCK_SEARCH_CONTROL_INVALID}:history_reference"
            )
        else:
            root = workspace_root.expanduser().resolve(strict=False)
            expected_previous_ref = (
                "objects/search_control/"
                f"search_control__g{generation - 1:02d}.json"
            )
            if previous_ref != expected_previous_ref:
                reasons.append(
                    f"{BLOCK_SEARCH_CONTROL_INVALID}:"
                    "history_reference_not_canonical"
                )
            previous_path = resolve_workspace_evidence_path(
                root, previous_ref
            )
            if previous_path is None or not previous_path.is_file():
                reasons.append(
                    f"{BLOCK_SEARCH_CONTROL_INVALID}:history_missing"
                )
            elif sha256_file(previous_path) != previous_sha:
                reasons.append(
                    f"{BLOCK_SEARCH_CONTROL_INVALID}:history_hash"
                )
            else:
                seen = set(_history_seen or set())
                if previous_path in seen:
                    reasons.append(
                        f"{BLOCK_SEARCH_CONTROL_INVALID}:history_cycle"
                    )
                else:
                    seen.add(previous_path)
                    try:
                        previous = read_json(previous_path)
                    except Exception:
                        reasons.append(
                            f"{BLOCK_SEARCH_CONTROL_INVALID}:history_invalid"
                        )
                    else:
                        previous_reasons = validate_search_control(
                            previous,
                            required_trial_count=0,
                            workspace_root=root,
                            expected_generation=generation - 1,
                            expected_campaign_id=control.get("campaign_id"),
                            expected_selection_window_id=control.get(
                                "selection_window_id"
                            ),
                            expected_universe_id=control.get("universe_id"),
                            _history_seen=seen,
                        )
                        reasons.extend(previous_reasons)
                        stable_fields = (
                            "selection_window_role",
                            "selection_window_id",
                            "universe_id",
                            "oos_sealed",
                            "sealed_oos_token_hash",
                            "data_split_manifest_ref",
                            "data_split_manifest_sha256",
                            "purge_days",
                            "embargo_days",
                            "trial_budget",
                            "multiple_testing_policy",
                            "multiplicity_alpha",
                            "cost_model_id",
                            "capacity_model_id",
                            "regime_plan_id",
                            "screening_policy",
                        )
                        for field in stable_fields:
                            if previous.get(field) != control.get(field):
                                reasons.append(
                                    f"{BLOCK_SEARCH_CONTROL_INVALID}:"
                                    f"history_policy_mismatch:{field}"
                                )
                        previous_hashes = previous.get(
                            "tested_program_hashes"
                        )
                        previous_hashes = (
                            previous_hashes
                            if isinstance(previous_hashes, list)
                            else []
                        )
                        previous_hashes = [
                            str(value).lower()
                            for value in previous_hashes
                            if isinstance(value, str)
                        ]
                        if (
                            len(normalized_hashes) <= len(previous_hashes)
                            or normalized_hashes[: len(previous_hashes)]
                            != previous_hashes
                        ):
                            reasons.append(
                                f"{BLOCK_SEARCH_CONTROL_INVALID}:"
                                "history_not_append_only"
                            )
    return reasons


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _corr(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(a) != len(b):
        return None
    ma = mean(a)
    mb = mean(b)
    da = [x - ma for x in a]
    db = [y - mb for y in b]
    denom = math.sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    if denom == 0:
        return None
    return sum(x * y for x, y in zip(da, db)) / denom


def _load_panel(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path).to_dict(orient="records")
    with Path(path).expanduser().open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _rank_ic_by_date(rows: list[dict[str, Any]], factor_col: str) -> list[float]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_date.setdefault(str(row["trade_date"]), []).append(row)
    out: list[float] = []
    for group in by_date.values():
        try:
            pairs = [
                (float(row[factor_col]), float(row["forward_return"]))
                for row in group
                if math.isfinite(float(row[factor_col]))
                and math.isfinite(float(row["forward_return"]))
            ]
        except (KeyError, ValueError):
            continue
        if len(pairs) < 2:
            continue
        factor = [pair[0] for pair in pairs]
        ret = [pair[1] for pair in pairs]
        value = _corr(_rank(factor), _rank(ret))
        if value is not None:
            out.append(value)
    return out


def _positive_mean_p_value(values: list[float]) -> tuple[float, str]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if len(clean) < 2:
        return 1.0, "insufficient_periods"
    sample_mean = mean(clean)
    sample_std = stdev(clean)
    if sample_std == 0:
        if sample_mean > 0:
            return max(0.0, min(1.0, 0.5 ** len(clean))), "exact_sign_all_positive"
        return 1.0, "degenerate_nonpositive"
    statistic = sample_mean / (sample_std / math.sqrt(len(clean)))
    return (
        float(student_t.sf(statistic, df=len(clean) - 1)),
        "one_sided_student_t",
    )


def _adjust_p_values(
    p_values: dict[str, float],
    *,
    method: str,
) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    count = len(ordered)
    adjusted: dict[str, float] = {}
    if method == "BH_FDR":
        running = 1.0
        for position in range(count, 0, -1):
            key, raw = ordered[position - 1]
            running = min(running, raw * count / position)
            adjusted[key] = min(1.0, running)
        return adjusted
    if method == "holm_bonferroni":
        running = 0.0
        for index, (key, raw) in enumerate(ordered):
            running = max(running, raw * (count - index))
            adjusted[key] = min(1.0, running)
        return adjusted
    raise ValueError(
        f"{BLOCK_SEARCH_CONTROL_INVALID}:multiple_testing_policy"
    )


def _apply_multiplicity(
    results: list[dict[str, Any]],
    search_control: dict[str, Any],
) -> dict[str, Any]:
    tested_hashes = [
        str(value)
        for value in search_control.get("tested_program_hashes") or []
    ]
    raw_by_hash = {program_hash: 1.0 for program_hash in tested_hashes}
    result_by_hash: dict[str, dict[str, Any]] = {}
    for row in results:
        program_hash = row.get("program_hash")
        if not isinstance(program_hash, str) or program_hash not in raw_by_hash:
            row["multiplicity_applicable"] = False
            row["multiplicity_pass"] = False
            continue
        raw = row.get("raw_p_value")
        raw_value = (
            float(raw)
            if isinstance(raw, (int, float))
            and not isinstance(raw, bool)
            and math.isfinite(float(raw))
            else 1.0
        )
        raw_by_hash[program_hash] = max(0.0, min(1.0, raw_value))
        result_by_hash[program_hash] = row
    method = str(search_control["multiple_testing_policy"])
    alpha = float(search_control["multiplicity_alpha"])
    adjusted = _adjust_p_values(raw_by_hash, method=method)
    for program_hash, row in result_by_hash.items():
        adjusted_value = adjusted[program_hash]
        passed = adjusted_value <= alpha
        row["multiplicity_applicable"] = True
        row["multiplicity_policy"] = method
        row["multiplicity_family_size"] = len(tested_hashes)
        row["multiplicity_alpha"] = alpha
        row["adjusted_p_value"] = adjusted_value
        row["multiplicity_pass"] = passed
        row["pre_multiplicity_decision"] = row.get("decision")
        if row.get("decision") == "send_to_formal_research" and not passed:
            row["decision"] = "keep_as_feature"
            row["failure_reason"] = (
                "BLOCK_FACTORFORGE_MINER_MULTIPLE_TESTING_NOT_PASSED"
            )
        row["eligible_for_research_queue"] = bool(
            row.get("signal_source") == "candidate_specific"
            and row.get("decision") == "send_to_formal_research"
            and passed
        )
    return {
        "policy": method,
        "alpha": alpha,
        "family_size": len(tested_hashes),
        "tested_program_hashes": tested_hashes,
        "raw_p_values_by_program_hash": raw_by_hash,
        "adjusted_p_values_by_program_hash": adjusted,
        "passed_program_hashes": sorted(
            program_hash
            for program_hash, value in adjusted.items()
            if value <= alpha
        ),
    }


def _endpoint_metrics(
    rows: list[dict[str, Any]],
    factor_col: str,
) -> tuple[float | None, float | None, float | None, float | None]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        try:
            factor = float(row[factor_col])
            forward_return = float(row["forward_return"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(factor) and math.isfinite(forward_return):
            by_date.setdefault(str(row["trade_date"]), []).append(row)
    daily_metrics: list[tuple[float, float, float, float]] = []
    for group in by_date.values():
        if len(group) < 4:
            continue
        frame = pd.DataFrame(
            {
                "factor": [float(row[factor_col]) for row in group],
                "forward_return": [
                    float(row["forward_return"]) for row in group
                ],
            }
        )
        try:
            frame["bucket"] = pd.qcut(
                frame["factor"],
                q=4,
                labels=False,
                duplicates="drop",
            )
        except ValueError:
            continue
        if frame["bucket"].nunique(dropna=True) != 4:
            continue
        bucket_rets = (
            frame.dropna(subset=["bucket"])
            .groupby("bucket", sort=True)["forward_return"]
            .mean()
            .tolist()
        )
        if len(bucket_rets) != 4:
            continue
        low_ret = float(bucket_rets[0])
        high_ret = float(bucket_rets[-1])
        signs = [
            1 if right >= left else -1
            for left, right in zip(bucket_rets, bucket_rets[1:])
        ]
        daily_metrics.append(
            (
                high_ret,
                low_ret,
                high_ret - low_ret,
                sum(signs) / len(signs),
            )
        )
    if not daily_metrics:
        return None, None, None, None
    return tuple(
        mean(metric[index] for metric in daily_metrics)
        for index in range(4)
    )


def _signal_rank_turnover(
    rows: list[dict[str, Any]],
    factor_col: str,
) -> float | None:
    by_date: dict[str, dict[str, float]] = {}
    for row in rows:
        try:
            value = float(row[factor_col])
            ts_code = str(row["ts_code"])
            trade_date = str(row["trade_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value) and ts_code:
            by_date.setdefault(trade_date, {})[ts_code] = value
    ranked_by_date: dict[str, dict[str, float]] = {}
    for trade_date, values_by_code in by_date.items():
        codes = list(values_by_code)
        if len(codes) < 2:
            continue
        ranks = _rank([values_by_code[code] for code in codes])
        ranked_by_date[trade_date] = {
            code: (rank - 0.5) / len(codes)
            for code, rank in zip(codes, ranks)
        }
    daily_turnover: list[float] = []
    ordered_dates = sorted(ranked_by_date)
    for previous_date, current_date in zip(ordered_dates, ordered_dates[1:]):
        previous = ranked_by_date[previous_date]
        current = ranked_by_date[current_date]
        common = sorted(set(previous).intersection(current))
        if not common:
            continue
        daily_turnover.append(
            0.5
            * mean(abs(current[code] - previous[code]) for code in common)
        )
    return mean(daily_turnover) if daily_turnover else None


def _screen_ready_candidate(
    packet: dict[str, Any],
    rows: list[dict[str, Any]],
    screen_window: str,
    universe: str,
    *,
    factor_col: str,
    signal_source: str,
    screening_policy: dict[str, Any],
) -> dict[str, Any]:
    ics = _rank_ic_by_date(rows, factor_col)
    rank_ic_mean = mean(ics) if ics else None
    rank_ic_ir = None
    if ics:
        std = pstdev(ics)
        rank_ic_ir = None if std == 0 else rank_ic_mean / std
    raw_p_value, p_value_method = _positive_mean_p_value(ics)
    long_ret, short_ret, spread, mono = _endpoint_metrics(rows, factor_col)
    coverage = len(rows)
    decision = "discard"
    if rank_ic_mean is not None and spread is not None and long_ret is not None:
        if (
            rank_ic_mean >= float(screening_policy["send_min_rank_ic"])
            and spread >= float(screening_policy["send_min_group_spread"])
            and long_ret >= float(screening_policy["send_min_long_end"])
        ):
            decision = "send_to_formal_research"
        elif (
            abs(rank_ic_mean)
            >= float(screening_policy["keep_min_abs_rank_ic"])
            or abs(spread)
            >= float(screening_policy["keep_min_abs_group_spread"])
        ):
            decision = "keep_as_feature"
    return {
        "candidate_id": packet["candidate_id"],
        "template_id": packet["template_id"],
        "program_hash": (
            packet.get("candidate_program_contract") or {}
        ).get("program_hash"),
        "screen_window": screen_window,
        "universe": universe,
        "data_source": "cheap_screen_panel",
        "factor_column": factor_col,
        "signal_source": signal_source,
        "rank_ic_mean": rank_ic_mean,
        "rank_ic_ir": rank_ic_ir,
        "rank_ic_ir_convention": "mean_over_population_std_unannualized",
        "ic_hit_rate": (sum(1 for x in ics if x > 0) / len(ics)) if ics else None,
        "ic_period_count": len(ics),
        "raw_p_value": raw_p_value,
        "raw_p_value_method": p_value_method,
        "group_spread_gross": spread,
        "long_end_gross": long_ret,
        "short_end_gross": short_ret,
        "monotonicity_score": mono,
        "endpoint_aggregation": "equal_weighted_daily_cross_sections",
        "turnover_estimate": _signal_rank_turnover(rows, factor_col),
        "turnover_definition": (
            "mean_one_way_cross_sectional_percentile_rank_migration"
        ),
        "coverage": coverage,
        "failure_reason": None,
        "decision": decision,
        "evidence_role": "exploratory_evidence",
        "promotion_forbidden_until_formal": True,
        "eligible_for_research_queue": signal_source == "candidate_specific",
        "screening_policy_version": screening_policy.get("version"),
    }


def _validate_candidate_manifest(
    manifest: dict[str, Any],
    *,
    campaign_id: str,
) -> list[str]:
    if manifest.get("campaign_id") != campaign_id:
        raise ValueError(
            f"{BLOCK_SEARCH_CONTROL_INVALID}:candidate_manifest_campaign_mismatch"
        )
    manifest_version = manifest.get("version")
    generation = manifest.get("generation")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 0
        or (
            manifest_version == "factorforge_miner_candidate_manifest_v1"
            and generation != 0
        )
        or (
            manifest_version
            == "factorforge_miner_mutation_population_v1"
            and generation < 1
        )
        or manifest_version
        not in {
            "factorforge_miner_candidate_manifest_v1",
            "factorforge_miner_mutation_population_v1",
        }
    ):
        raise ValueError(
            f"{BLOCK_SEARCH_CONTROL_INVALID}:candidate_manifest_generation"
        )
    candidate_ids: list[str] = []
    ready_program_hashes: list[str] = []
    for packet in manifest.get("candidates") or []:
        if not isinstance(packet, dict):
            raise ValueError(
                "BLOCK_FACTORFORGE_MINER_CANDIDATE_PACKET_INVALID"
            )
        validate_candidate_packet(packet)
        if packet.get("campaign_id") != campaign_id:
            raise ValueError(
                f"{BLOCK_SEARCH_CONTROL_INVALID}:candidate_campaign_mismatch"
            )
        mutation_lineage = packet.get("mutation_lineage")
        if manifest_version == "factorforge_miner_mutation_population_v1":
            if (
                not isinstance(mutation_lineage, dict)
                or mutation_lineage.get("generation") != generation
            ):
                raise ValueError(
                    f"{BLOCK_SEARCH_CONTROL_INVALID}:"
                    "candidate_generation_mismatch"
                )
        elif mutation_lineage is not None:
            raise ValueError(
                f"{BLOCK_SEARCH_CONTROL_INVALID}:"
                "base_candidate_has_mutation_lineage"
            )
        candidate_ids.append(str(packet.get("candidate_id") or ""))
        contract = packet.get("candidate_program_contract") or {}
        if (
            packet.get("dependency_status") == "ready"
            and contract.get("program_hash")
        ):
            ready_program_hashes.append(str(contract["program_hash"]))
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("BLOCK_FACTORFORGE_MINER_CANDIDATE_ID_DUPLICATE")
    if len(ready_program_hashes) != len(set(ready_program_hashes)):
        raise ValueError(
            f"{BLOCK_SEARCH_CONTROL_INVALID}:duplicate_program_hash"
        )
    return ready_program_hashes


def _empty_screen_result(
    packet: dict[str, Any],
    *,
    screen_window: str,
    universe: str,
    factor_column: str | None,
    signal_source: str,
    failure_reason: Any,
    decision: str,
    screening_policy: dict[str, Any],
) -> dict[str, Any]:
    return {
        "candidate_id": packet["candidate_id"],
        "template_id": packet["template_id"],
        "program_hash": (
            packet.get("candidate_program_contract") or {}
        ).get("program_hash"),
        "screen_window": screen_window,
        "universe": universe,
        "data_source": "cheap_screen_panel",
        "factor_column": factor_column,
        "signal_source": signal_source,
        "rank_ic_mean": None,
        "rank_ic_ir": None,
        "rank_ic_ir_convention": None,
        "ic_hit_rate": None,
        "group_spread_gross": None,
        "long_end_gross": None,
        "short_end_gross": None,
        "monotonicity_score": None,
        "endpoint_aggregation": None,
        "turnover_estimate": None,
        "turnover_definition": None,
        "coverage": 0,
        "failure_reason": failure_reason,
        "decision": decision,
        "evidence_role": "exploratory_evidence",
        "promotion_forbidden_until_formal": True,
        "eligible_for_research_queue": False,
        "screening_policy_version": screening_policy.get("version"),
    }


def _compute_screen_results(
    *,
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    screen_window: str,
    universe: str,
    search_control: dict[str, Any],
    allow_fixture_shared_signal: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    screening_policy = dict(search_control["screening_policy"])
    results: list[dict[str, Any]] = []
    panel_columns = set(rows[0].keys()) if rows else set()
    for packet in manifest.get("candidates") or []:
        if (
            packet.get("cheap_screen_status") not in {"not_run", "ready"}
            and packet.get("dependency_status") != "ready"
        ):
            results.append(
                _empty_screen_result(
                    packet,
                    screen_window=screen_window,
                    universe=universe,
                    factor_column=packet.get(
                        "cheap_screen_factor_column"
                    ),
                    signal_source="not_available",
                    failure_reason=packet.get("dependency_status"),
                    decision=packet.get("dependency_status", "needs_data"),
                    screening_policy=screening_policy,
                )
            )
            continue
        factor_col = str(packet.get("cheap_screen_factor_column") or "")
        signal_source = "candidate_specific"
        if not factor_col or factor_col not in panel_columns:
            if (
                allow_fixture_shared_signal
                and "factor_ready_signal" in panel_columns
            ):
                factor_col = "factor_ready_signal"
                signal_source = "fixture_shared_signal"
            else:
                results.append(
                    _empty_screen_result(
                        packet,
                        screen_window=screen_window,
                        universe=universe,
                        factor_column=factor_col or None,
                        signal_source="missing_candidate_specific_signal",
                        failure_reason=(
                            "BLOCK_FACTORFORGE_MINER_CANDIDATE_SIGNAL_MISSING"
                        ),
                        decision="blocked_missing_candidate_signal",
                        screening_policy=screening_policy,
                    )
                )
                continue
        results.append(
            _screen_ready_candidate(
                packet,
                rows,
                screen_window,
                universe,
                factor_col=factor_col,
                signal_source=signal_source,
                screening_policy=screening_policy,
            )
        )
    multiplicity = _apply_multiplicity(results, search_control)
    return results, multiplicity


def _summary_workspace_path(
    workspace_root: Path,
    raw_path: Any,
) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    if not path.is_absolute():
        path = workspace_root / path
    return path.resolve(strict=False)


def _materialize_search_control(
    *,
    workspace_root: Path,
    campaign_id: str,
    search_control: dict[str, Any],
) -> Path:
    generation = int(search_control["generation"])
    path = workspace_path(
        workspace_root,
        "objects",
        "search_control",
        f"search_control__g{generation:02d}.json",
        campaign_id=campaign_id,
    )
    if path.is_file():
        if read_json(path) != search_control:
            raise ValueError(
                f"{BLOCK_SEARCH_CONTROL_INVALID}:"
                "canonical_control_immutable"
            )
    else:
        write_json(path, search_control)
    return path


def validate_cheap_screen_summary(
    summary: Any,
    *,
    workspace_root: Path,
    expected_campaign_id: str | None = None,
) -> list[str]:
    if not isinstance(summary, dict):
        return [f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:summary_missing"]
    reasons: list[str] = []
    if summary.get("version") != "factorforge_miner_cheap_screen_summary_v1":
        reasons.append(f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:version")
    campaign_id = summary.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        reasons.append(f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:campaign")
    elif (
        expected_campaign_id is not None
        and campaign_id != expected_campaign_id
    ):
        reasons.append(
            f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:campaign_mismatch"
        )
    if (
        summary.get("evidence_role") != "exploratory_evidence"
        or summary.get("promotion_forbidden_until_formal") is not True
        or summary.get("candidate_specific_evaluation_required") is not True
        or summary.get("search_control_verdict") != "PASS"
    ):
        reasons.append(
            f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:evidence_boundary"
        )
    root = workspace_root.expanduser().resolve(strict=False)
    paths = {
        "candidate_manifest": _summary_workspace_path(
            root, summary.get("candidate_manifest_path")
        ),
        "source_panel": _summary_workspace_path(
            root, summary.get("source_panel_path")
        ),
        "program_execution_report": _summary_workspace_path(
            root, summary.get("program_execution_report_path")
        ),
        "search_control": _summary_workspace_path(
            root, summary.get("search_control_ref")
        ),
    }
    for label, path in paths.items():
        if path != root and root not in path.parents:
            reasons.append(
                f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:{label}_outside_workspace"
            )
        elif not path.is_file():
            reasons.append(
                f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:{label}_missing"
            )
    if reasons:
        return list(dict.fromkeys(reasons))
    manifest_path = paths["candidate_manifest"]
    panel_path = paths["source_panel"]
    execution_report_path = paths["program_execution_report"]
    expected_hashes = {
        "candidate_manifest_sha256": sha256_file(manifest_path),
        "source_panel_sha256": sha256_file(panel_path),
        "program_execution_report_sha256": sha256_file(
            execution_report_path
        ),
        "search_control_sha256": sha256_file(paths["search_control"]),
    }
    for field, expected in expected_hashes.items():
        if summary.get(field) != expected:
            reasons.append(
                f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:{field}"
            )
    try:
        manifest = read_json(manifest_path)
        ready_hashes = _validate_candidate_manifest(
            manifest,
            campaign_id=str(campaign_id),
        )
        execution_report = read_json(execution_report_path)
        persisted_control = read_json(paths["search_control"])
    except Exception as exc:
        reasons.append(
            f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:input_invalid:{exc}"
        )
        return list(dict.fromkeys(reasons))
    if summary.get("generation") != manifest.get("generation"):
        reasons.append(
            f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:generation_binding"
        )
    expected_control_ref = (
        "objects/search_control/"
        f"search_control__g{int(manifest['generation']):02d}.json"
    )
    if (
        summary.get("search_control_ref") != expected_control_ref
        or summary.get("search_control") != persisted_control
    ):
        reasons.append(
            f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:search_control_binding"
        )
    execution_reasons = validate_program_execution_report(
        execution_report,
        workspace_root=root,
        candidate_manifest=manifest,
        output_panel_path=panel_path,
    )
    reasons.extend(execution_reasons)
    if (
        summary.get("program_execution_output_sha256")
        != execution_report.get("output_panel_sha256")
        or summary.get("program_execution_output_sha256")
        != expected_hashes["source_panel_sha256"]
        or summary.get("program_execution_source_sha256")
        != execution_report.get("source_panel_sha256")
    ):
        reasons.append(
            f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:execution_hash_binding"
        )
    if (
        summary.get("data_split_manifest_ref")
        != execution_report.get("data_split_manifest_ref")
        or summary.get("data_split_manifest_sha256")
        != execution_report.get("data_split_manifest_sha256")
        or persisted_control.get("data_split_manifest_ref")
        != execution_report.get("data_split_manifest_ref")
        or persisted_control.get("data_split_manifest_sha256")
        != execution_report.get("data_split_manifest_sha256")
    ):
        reasons.append(
            f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:data_split_binding"
        )
    control = persisted_control
    control_reasons = validate_search_control(
        control,
        required_trial_count=len(set(ready_hashes)),
        required_program_hashes=set(ready_hashes),
        workspace_root=root,
        expected_generation=int(manifest["generation"]),
        expected_campaign_id=str(campaign_id),
        expected_data_snapshot_hash=expected_hashes[
            "source_panel_sha256"
        ],
        expected_is_source_hash=execution_report.get(
            "source_panel_sha256"
        ),
        expected_selection_window_id=summary.get("screen_window"),
        expected_universe_id=summary.get("universe"),
    )
    reasons.extend(control_reasons)
    if reasons:
        return list(dict.fromkeys(reasons))
    try:
        expected_results, expected_multiplicity = _compute_screen_results(
            manifest=manifest,
            rows=_load_panel(panel_path),
            screen_window=str(summary.get("screen_window") or ""),
            universe=str(summary.get("universe") or ""),
            search_control=dict(control),
            allow_fixture_shared_signal=bool(
                summary.get("fixture_shared_signal_used")
            ),
        )
    except Exception as exc:
        reasons.append(
            f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:replay_failed:{exc}"
        )
        return list(dict.fromkeys(reasons))
    if summary.get("results") != expected_results:
        reasons.append(f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:results")
    if summary.get("multiplicity") != expected_multiplicity:
        reasons.append(
            f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:multiplicity"
        )
    fixture_used = any(
        row.get("signal_source") == "fixture_shared_signal"
        for row in expected_results
    )
    if summary.get("fixture_shared_signal_used") is not fixture_used:
        reasons.append(
            f"{BLOCK_CHEAP_SCREEN_REPLAY_INVALID}:fixture_binding"
        )
    return list(dict.fromkeys(reasons))


def run_cheap_screen(
    *,
    campaign_id: str,
    workspace_root: Path,
    candidate_manifest_path: Path,
    panel_path: Path,
    program_execution_report_path: Path,
    screen_window: str,
    universe: str,
    search_control: dict[str, Any] | None = None,
    allow_fixture_shared_signal: bool = False,
) -> dict[str, Any]:
    manifest = read_json(candidate_manifest_path)
    workspace = workspace_root.expanduser().resolve(strict=False)
    for label, path in (
        ("candidate_manifest", candidate_manifest_path),
        ("panel", panel_path),
        ("program_execution_report", program_execution_report_path),
    ):
        resolved = path.expanduser().resolve(strict=False)
        if resolved != workspace and workspace not in resolved.parents:
            raise ValueError(
                f"{BLOCK_SEARCH_CONTROL_INVALID}:{label}_outside_workspace"
            )
    ready_program_hashes = _validate_candidate_manifest(
        manifest,
        campaign_id=campaign_id,
    )
    execution_report = read_json(program_execution_report_path)
    execution_reasons = validate_program_execution_report(
        execution_report,
        workspace_root=workspace_root,
        candidate_manifest=manifest,
        output_panel_path=panel_path,
    )
    if execution_reasons:
        raise ValueError(";".join(execution_reasons))
    program_hashes = set(ready_program_hashes)
    search_control_reasons = validate_search_control(
        search_control,
        required_trial_count=len(program_hashes),
        required_program_hashes=program_hashes,
        workspace_root=workspace,
        expected_generation=int(manifest["generation"]),
        expected_campaign_id=campaign_id,
        expected_data_snapshot_hash=sha256_file(panel_path),
        expected_is_source_hash=execution_report.get(
            "source_panel_sha256"
        ),
        expected_selection_window_id=screen_window,
        expected_universe_id=universe,
    )
    if search_control_reasons:
        raise ValueError(";".join(search_control_reasons))
    if (
        (search_control or {}).get("data_split_manifest_ref")
        != execution_report.get("data_split_manifest_ref")
        or (search_control or {}).get("data_split_manifest_sha256")
        != execution_report.get("data_split_manifest_sha256")
        or execution_report.get("selection_window_id") != screen_window
        or execution_report.get("universe_id") != universe
    ):
        raise ValueError(
            f"{BLOCK_SEARCH_CONTROL_INVALID}:data_split_execution_binding"
        )
    persisted_control_path = _materialize_search_control(
        workspace_root=workspace,
        campaign_id=campaign_id,
        search_control=dict(search_control or {}),
    )
    rows = _load_panel(panel_path)
    results, multiplicity = _compute_screen_results(
        manifest=manifest,
        rows=rows,
        screen_window=screen_window,
        universe=universe,
        search_control=dict(search_control or {}),
        allow_fixture_shared_signal=allow_fixture_shared_signal,
    )
    summary = {
        "version": "factorforge_miner_cheap_screen_summary_v1",
        "campaign_id": campaign_id,
        "generation": int(manifest["generation"]),
        "generated_at_utc": utc_now(),
        "screen_window": screen_window,
        "universe": universe,
        "candidate_manifest_path": str(candidate_manifest_path),
        "candidate_manifest_sha256": sha256_file(candidate_manifest_path),
        "source_panel_path": str(panel_path),
        "source_panel_sha256": sha256_file(panel_path),
        "program_execution_report_path": str(program_execution_report_path),
        "program_execution_report_sha256": sha256_file(
            program_execution_report_path
        ),
        "program_execution_output_sha256": execution_report.get(
            "output_panel_sha256"
        ),
        "program_execution_source_sha256": execution_report.get(
            "source_panel_sha256"
        ),
        "data_split_manifest_ref": execution_report.get(
            "data_split_manifest_ref"
        ),
        "data_split_manifest_sha256": execution_report.get(
            "data_split_manifest_sha256"
        ),
        "evidence_role": "exploratory_evidence",
        "promotion_forbidden_until_formal": True,
        "candidate_specific_evaluation_required": True,
        "search_control": search_control,
        "search_control_ref": str(
            persisted_control_path.relative_to(workspace)
        ),
        "search_control_sha256": sha256_file(persisted_control_path),
        "search_control_verdict": "PASS",
        "fixture_shared_signal_used": any(
            row.get("signal_source") == "fixture_shared_signal" for row in results
        ),
        "multiplicity": multiplicity,
        "results": results,
    }
    write_json(workspace_path(workspace_root, "objects", "cheap_screen", "cheap_screen_summary.json", campaign_id=campaign_id), summary)
    result_path = workspace_path(workspace_root, "objects", "cheap_screen", "cheap_screen_results.parquet", campaign_id=campaign_id)
    pd.DataFrame(results).to_parquet(result_path, index=False)
    lines = ["# Miner Cheap Screen Report", "", f"campaign_id: `{campaign_id}`", "", "| candidate | decision | rank_ic_mean | group_spread |", "|---|---|---:|---:|"]
    for row in results:
        lines.append(f"| `{row['candidate_id']}` | `{row['decision']}` | `{row['rank_ic_mean']}` | `{row['group_spread_gross']}` |")
    write_markdown(workspace_path(workspace_root, "docs", "cheap_screen_report.md", campaign_id=campaign_id), "\n".join(lines))
    return summary
