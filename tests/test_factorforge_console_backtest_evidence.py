from __future__ import annotations

import base64
import binascii
import hashlib
import statistics
import zlib

import pytest

from factor_factory.console.backtest_evidence import (
    BACKTEST_EVIDENCE_CONTRACT_VERSION,
    BacktestArtifact,
    build_backtest_evidence_bundle,
)


def _artifact(name: str, text: str) -> BacktestArtifact:
    return BacktestArtifact(
        artifact_id=f"evaluations/report/self_quant_analyzer/{name}",
        data=text.encode("utf-8"),
    )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return (
        len(payload).to_bytes(4, "big")
        + kind
        + payload
        + checksum.to_bytes(4, "big")
    )


def _rgba_png(*, extra_chunks: tuple[bytes, ...] = ()) -> bytes:
    ihdr = (1).to_bytes(4, "big") * 2 + bytes((8, 6, 0, 0, 0))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + b"".join(extra_chunks)
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + _png_chunk(b"IEND", b"")
    )


def _formal_artifacts() -> dict[str, BacktestArtifact]:
    dates = ("2024-01-02", "2024-01-31", "2025-12-31")
    groups = tuple(f"G{group:02d}" for group in range(1, 11))
    long_returns = (0.01, -0.2, 0.5)
    turnovers = (0.0, 0.2, 0.4)
    gross_nav = (1.0, 0.8, 1.2)
    net_nav = (1.0, 0.7994, 0.7994 * 1.4988)
    quantile_returns_by_date = [
        {
            group: ((index - 5.5) / 4.5) * long_return
            for index, group in enumerate(groups, start=1)
        }
        for long_return in long_returns
    ]
    quantile_nav_by_date = [
        {group: 1.0 for group in groups},
        {group: 1.0 + quantile_returns_by_date[1][group] for group in groups},
        {
            group: (1.0 + quantile_returns_by_date[1][group])
            * (1.0 + quantile_returns_by_date[2][group])
            for group in groups
        },
    ]
    counts_by_date = [
        {group: 20 + index + offset for index, group in enumerate(groups, start=1)}
        for offset in range(3)
    ]
    long_short_returns = tuple(
        values["G10"] - values["G01"] for values in quantile_returns_by_date
    )
    long_short_nav = (
        1.0,
        1.0 + long_short_returns[1],
        (1.0 + long_short_returns[1]) * (1.0 + long_short_returns[2]),
    )
    quantile_summary_rows = []
    for group in groups:
        returns = [values[group] for values in quantile_returns_by_date]
        counts = [values[group] for values in counts_by_date]
        mean = statistics.mean(returns)
        std = statistics.stdev(returns)
        quantile_summary_rows.append(
            f"{group},{mean:.12g},{std:.12g},{mean / std:.12g},"
            f"{quantile_nav_by_date[-1][group]:.12g},{min(counts)},{statistics.median(counts):.12g},{max(counts)}\n"
        )
    quantile_summary = (
        "group,mean_daily_return,std_daily_return,daily_ir,final_nav,member_count_min,member_count_median,member_count_max\n"
        + "".join(quantile_summary_rows)
    )

    def series_csv(header: str, rows: list[list[object]]) -> str:
        return header + "\n" + "".join(
            ",".join(str(value) for value in row) + "\n" for row in rows
        )

    quantile_returns_csv = series_csv(
        "datetime," + ",".join(groups),
        [
            [dt, *(f"{values[group]:.12g}" for group in groups)]
            for dt, values in zip(dates, quantile_returns_by_date)
        ],
    )
    quantile_nav_csv = series_csv(
        "datetime," + ",".join(groups),
        [
            [dt, *(f"{values[group]:.12g}" for group in groups)]
            for dt, values in zip(dates, quantile_nav_by_date)
        ],
    )
    quantile_counts_csv = series_csv(
        "datetime," + ",".join(groups),
        [
            [dt, *(values[group] for group in groups)]
            for dt, values in zip(dates, counts_by_date)
        ],
    )
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    return {
        "long_side_nav_table": _artifact(
            "long_side_nav.csv",
            series_csv(
                "datetime,long_side_nav,cost_adjusted_long_side_nav",
                [
                    [dt, f"{gross:.12g}", f"{net:.12g}"]
                    for dt, gross, net in zip(dates, gross_nav, net_nav)
                ],
            ),
        ),
        "long_side_turnover_table": _artifact(
            "long_side_turnover.csv",
            series_csv(
                "datetime,long_side_turnover",
                [[dt, value] for dt, value in zip(dates, turnovers)],
            ),
        ),
        "quantile_summary_table": _artifact(
            "quantile_summary_table.csv",
            quantile_summary,
        ),
        "quantile_nav_table": _artifact(
            "quantile_nav_10groups.csv",
            quantile_nav_csv,
        ),
        "long_short_nav_table": _artifact(
            "long_short_nav_10groups.csv",
            series_csv(
                "datetime,long_short_nav",
                [[dt, f"{value:.12g}"] for dt, value in zip(dates, long_short_nav)],
            ),
        ),
        "long_side_returns_table": _artifact(
            "long_side_returns.csv",
            series_csv(
                "datetime,long_side_return",
                [[dt, value] for dt, value in zip(dates, long_returns)],
            ),
        ),
        "quantile_returns_table": _artifact(
            "quantile_returns_10groups.csv",
            quantile_returns_csv,
        ),
        "quantile_counts_table": _artifact(
            "quantile_counts_10groups.csv",
            quantile_counts_csv,
        ),
        "long_short_returns_table": _artifact(
            "long_short_returns_10groups.csv",
            series_csv(
                "datetime,long_short_return",
                [[dt, f"{value:.12g}"] for dt, value in zip(dates, long_short_returns)],
            ),
        ),
        "gross_nav_chart": BacktestArtifact(
            artifact_id="evaluations/report/self_quant_analyzer/long_side_nav.png",
            data=png,
        ),
        "net_nav_chart": BacktestArtifact(
            artifact_id="evaluations/report/self_quant_analyzer/cost_adjusted_long_side_nav.png",
            data=png,
        ),
        "quantile_nav_chart": BacktestArtifact(
            artifact_id="evaluations/report/self_quant_analyzer/quantile_nav_10groups.png",
            data=png,
        ),
        "long_short_diagnostic_chart": BacktestArtifact(
            artifact_id="evaluations/report/self_quant_analyzer/long_short_nav_10groups.png",
            data=png,
        ),
        "rank_ic_chart": BacktestArtifact(
            artifact_id="evaluations/report/self_quant_analyzer/rank_ic_timeseries.png",
            data=png,
        ),
        "pearson_ic_chart": BacktestArtifact(
            artifact_id="evaluations/report/self_quant_analyzer/pearson_ic_timeseries.png",
            data=png,
        ),
        "coverage_chart": BacktestArtifact(
            artifact_id="evaluations/report/self_quant_analyzer/coverage_by_day.png",
            data=png,
        ),
        "quantile_counts_chart": BacktestArtifact(
            artifact_id="evaluations/report/self_quant_analyzer/quantile_counts_10groups.png",
            data=png,
        ),
    }


def test_builds_v2_bundle_from_formal_step4_tables() -> None:
    artifacts = _formal_artifacts()
    bundle = build_backtest_evidence_bundle(
        artifacts=artifacts,
        core_metrics={
            "gross_final_nav": 1.2,
            "net_final_nav": 1.19814072,
            "long_short_final_nav": 1.2,
            "turnover": {"long_side_turnover_mean_daily": 0.3},
            "drawdown": {"max_drawdown": -0.2},
            "recovery": {"recovery_days": 729},
        },
        validator_verdict="PASS",
        formal_verified=True,
    )

    assert bundle["contract_version"] == BACKTEST_EVIDENCE_CONTRACT_VERSION
    assert bundle["evidence_class"] == "FORMAL VERIFIED"
    assert [item["year"] for item in bundle["annual_returns"]] == [2024, 2025]
    assert [item["gross_return"] for item in bundle["annual_returns"]] == pytest.approx([-0.2, 0.5])
    assert [item["net_return"] for item in bundle["annual_returns"]] == pytest.approx([-0.2006, 0.4988])
    assert len(bundle["monthly_returns"]) == 2
    gross_drawdown = bundle["drawdown"]["gross"]
    assert gross_drawdown["max_drawdown"] == pytest.approx(-0.2)
    assert {key: value for key, value in gross_drawdown.items() if key != "max_drawdown"} == {
        "peak_date": "2024-01-02",
        "trough_date": "2024-01-31",
        "recovery_date": "2025-12-31",
        "underwater_days": 729,
        "max_recovery_days": 729,
        "recovered": True,
    }
    assert bundle["turnover_profile"]["mean_daily"] == 0.30000000000000004
    assert bundle["turnover_profile"]["p95_daily"] == 0.39
    assert bundle["quantile_profile"]["final_nav_monotonic_direction"] == "ascending"
    assert bundle["long_short_profile"]["final_nav"] == pytest.approx(1.2)
    assert bundle["module_status"]["quantile_summary"] == "available"
    assert bundle["module_status"]["formal_step4_pack"] == "available"
    assert bundle["module_status"]["long_short"] == "available"
    assert bundle["module_status"]["cost_sensitivity"] == "not_produced"
    assert bundle["consistency"]["status"] == "PASS"
    source = bundle["provenance"]["sources"]["long_side_nav_table"]
    assert source["sha256"] == hashlib.sha256(artifacts["long_side_nav_table"].data).hexdigest()


def test_accepts_historical_blank_index_header_for_turnover_table() -> None:
    artifacts = _formal_artifacts()
    turnover = artifacts["long_side_turnover_table"]
    artifacts["long_side_turnover_table"] = BacktestArtifact(
        artifact_id=turnover.artifact_id,
        data=turnover.data.replace(
            b"datetime,long_side_turnover", b",long_side_turnover", 1
        ),
    )

    bundle = build_backtest_evidence_bundle(
        artifacts=artifacts,
        core_metrics={"turnover": {"long_side_turnover_mean_daily": 0.3}},
        validator_verdict="PASS",
        formal_verified=True,
    )

    assert bundle["parse_errors"] == {}
    assert bundle["consistency"]["status"] == "PASS"
    assert bundle["module_status"]["turnover_profile"] == "available"


def test_conflicts_and_invalid_tables_are_not_published_as_available() -> None:
    artifacts = _formal_artifacts()
    quantile_nav_lines = artifacts["quantile_nav_table"].data.decode("utf-8").splitlines()
    final_values = quantile_nav_lines[-1].split(",")
    final_values[-1] = "1.19"
    artifacts["quantile_nav_table"] = _artifact(
        "quantile_nav_10groups.csv",
        "\n".join([*quantile_nav_lines[:-1], ",".join(final_values)]) + "\n",
    )
    artifacts["long_side_turnover_table"] = _artifact(
        "long_side_turnover.csv",
        "datetime,long_side_turnover\n"
        "2024-01-02,0.0\n"
        "2024-01-02,0.2\n",
    )
    bundle = build_backtest_evidence_bundle(
        artifacts=artifacts,
        core_metrics={
            "gross_final_nav": 1.50,
            "net_final_nav": 1.21,
            "turnover": {"long_side_turnover_mean_daily": 0.25},
        },
        validator_verdict="PASS",
        formal_verified=True,
    )

    assert bundle["evidence_class"] == "EVIDENCE CONFLICT"
    assert bundle["consistency"]["status"] == "CONFLICT"
    assert bundle["module_status"]["gross_net_nav"] == "invalid_evidence"
    assert bundle["module_status"]["quantile_nav"] == "evidence_conflict"
    assert bundle["module_status"]["turnover_profile"] == "invalid_evidence"
    assert "duplicate date" in bundle["parse_errors"]["long_side_turnover_table"]


def test_missing_formal_outputs_remain_explicitly_not_produced() -> None:
    bundle = build_backtest_evidence_bundle(
        artifacts={},
        core_metrics={},
        validator_verdict="NOT_RUN",
        formal_verified=False,
    )

    assert bundle["evidence_class"] == "FORMAL UNVERIFIED"
    assert bundle["consistency"]["status"] == "NOT_CHECKED"
    assert set(bundle["module_status"].values()) == {"not_produced"}
    assert bundle["annual_returns"] == []
    assert bundle["monthly_returns"] == []


def test_verified_claim_without_required_step4_pack_is_a_conflict() -> None:
    bundle = build_backtest_evidence_bundle(
        artifacts={},
        core_metrics={},
        validator_verdict="PASS",
        formal_verified=True,
    )

    assert bundle["evidence_class"] == "EVIDENCE CONFLICT"
    assert bundle["module_status"]["formal_step4_pack"] == "evidence_conflict"
    required_check = next(
        item
        for item in bundle["consistency"]["checks"]
        if item["check"] == "required_formal_step4_pack"
    )
    assert required_check["status"] == "CONFLICT"
    assert "long_side_nav_table" in required_check["missing_roles"]


def test_non_numeric_formal_nav_is_invalid_evidence() -> None:
    bundle = build_backtest_evidence_bundle(
        artifacts={
            "long_side_nav_table": _artifact(
                "long_side_nav.csv",
                "datetime,long_side_nav,cost_adjusted_long_side_nav\n"
                "2024-01-02,1.0,1.0\n"
                "2024-01-03,not-a-number,1.01\n",
            )
        },
        core_metrics={},
        validator_verdict="PASS",
        formal_verified=True,
    )

    assert bundle["evidence_class"] == "EVIDENCE CONFLICT"
    assert bundle["module_status"]["gross_net_nav"] == "invalid_evidence"
    assert "invalid numeric value" in bundle["parse_errors"]["long_side_nav_table"]


def test_monotonic_nav_does_not_invent_an_underwater_episode() -> None:
    bundle = build_backtest_evidence_bundle(
        artifacts={
            "long_side_nav_table": _artifact(
                "long_side_nav.csv",
                "datetime,long_side_nav,cost_adjusted_long_side_nav\n"
                "2024-01-02,1.0,1.0\n"
                "2024-01-03,1.01,1.005\n"
                "2024-01-04,1.02,1.01\n",
            )
        },
        core_metrics={"gross_final_nav": 1.02, "net_final_nav": 1.01},
        validator_verdict="PASS",
        formal_verified=True,
    )

    assert bundle["drawdown"]["gross"] == {
        "max_drawdown": 0.0,
        "peak_date": None,
        "trough_date": None,
        "recovery_date": None,
        "underwater_days": 0,
        "max_recovery_days": 0,
        "recovered": True,
    }


def test_complete_role_map_with_malformed_payloads_cannot_verify() -> None:
    artifacts = _formal_artifacts()
    artifacts["quantile_returns_table"] = _artifact(
        "quantile_returns_10groups.csv",
        "datetime,G01\n2024-01-02,0.01\n",
    )
    artifacts["rank_ic_chart"] = BacktestArtifact(
        artifact_id="evaluations/report/self_quant_analyzer/rank_ic_timeseries.png",
        data=b"not-a-png",
    )

    bundle = build_backtest_evidence_bundle(
        artifacts=artifacts,
        core_metrics={},
        validator_verdict="PASS",
        formal_verified=True,
    )

    assert bundle["evidence_class"] == "EVIDENCE CONFLICT"
    assert bundle["module_status"]["formal_step4_pack"] == "invalid_evidence"
    assert bundle["module_status"]["rank_ic_timeseries"] == "invalid_evidence"
    assert "rank_ic_chart" not in bundle["charts"]
    assert "return table columns" in bundle["parse_errors"]["quantile_returns_table"]
    assert "valid PNG" in bundle["parse_errors"]["rank_ic_chart"]


def test_surplus_csv_fields_cannot_hide_behind_an_exact_header() -> None:
    artifacts = _formal_artifacts()
    lines = artifacts["long_side_returns_table"].data.decode("utf-8").splitlines()
    lines[1] += ",SURPLUS"
    artifacts["long_side_returns_table"] = _artifact(
        "long_side_returns.csv", "\n".join(lines) + "\n"
    )

    bundle = build_backtest_evidence_bundle(
        artifacts=artifacts,
        core_metrics={},
        validator_verdict="PASS",
        formal_verified=True,
    )

    assert bundle["evidence_class"] == "EVIDENCE CONFLICT"
    assert "surplus CSV fields" in bundle["parse_errors"]["long_side_returns_table"]


def test_crc_valid_but_undecodable_png_cannot_verify() -> None:
    ihdr = (1).to_bytes(4, "big") * 2 + bytes((8, 6, 0, 0, 0))
    malformed = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", b"not-zlib")
        + _png_chunk(b"IEND", b"")
    )
    artifacts = _formal_artifacts()
    artifacts["rank_ic_chart"] = BacktestArtifact(
        artifact_id="evaluations/report/self_quant_analyzer/rank_ic_timeseries.png",
        data=malformed,
    )

    bundle = build_backtest_evidence_bundle(
        artifacts=artifacts,
        core_metrics={},
        validator_verdict="PASS",
        formal_verified=True,
    )

    assert bundle["evidence_class"] == "EVIDENCE CONFLICT"
    assert "undecodable PNG image data" in bundle["parse_errors"]["rank_ic_chart"]


@pytest.mark.parametrize(
    ("malformed", "expected_error"),
    [
        (
            _rgba_png(extra_chunks=(_png_chunk(b"a1cD", b"payload"),)),
            "invalid PNG chunk type",
        ),
        (
            _rgba_png(
                extra_chunks=(
                    _png_chunk(b"PLTE", b"\x00\x00\x00"),
                    _png_chunk(b"PLTE", b"\xff\xff\xff"),
                )
            ),
            "invalid PNG palette",
        ),
    ],
)
def test_invalid_png_chunk_structure_cannot_verify(
    malformed: bytes,
    expected_error: str,
) -> None:
    artifacts = _formal_artifacts()
    artifacts["rank_ic_chart"] = BacktestArtifact(
        artifact_id="evaluations/report/self_quant_analyzer/rank_ic_timeseries.png",
        data=malformed,
    )

    bundle = build_backtest_evidence_bundle(
        artifacts=artifacts,
        core_metrics={},
        validator_verdict="PASS",
        formal_verified=True,
    )

    assert bundle["evidence_class"] == "EVIDENCE CONFLICT"
    assert expected_error in bundle["parse_errors"]["rank_ic_chart"]


def test_indexed_png_cannot_reference_an_undefined_palette_entry() -> None:
    ihdr = (1).to_bytes(4, "big") * 2 + bytes((1, 3, 0, 0, 0))
    malformed = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"PLTE", b"\x00\x00\x00")
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\x80"))
        + _png_chunk(b"IEND", b"")
    )
    artifacts = _formal_artifacts()
    artifacts["rank_ic_chart"] = BacktestArtifact(
        artifact_id="evaluations/report/self_quant_analyzer/rank_ic_timeseries.png",
        data=malformed,
    )

    bundle = build_backtest_evidence_bundle(
        artifacts=artifacts,
        core_metrics={},
        validator_verdict="PASS",
        formal_verified=True,
    )

    assert bundle["evidence_class"] == "EVIDENCE CONFLICT"
    assert "undefined PNG palette index" in bundle["parse_errors"]["rank_ic_chart"]


def test_long_side_returns_must_equal_the_producer_defined_top_decile() -> None:
    artifacts = _formal_artifacts()
    dates = ("2024-01-02", "2024-01-31", "2025-12-31")
    alternate_returns = (0.02, -0.1, 0.4)
    alternate_gross = (1.0, 0.9, 1.26)
    alternate_net = (1.0, 0.8994, 0.8994 * 1.3988)
    artifacts["long_side_returns_table"] = _artifact(
        "long_side_returns.csv",
        "datetime,long_side_return\n"
        + "".join(
            f"{dt},{value:.12g}\n"
            for dt, value in zip(dates, alternate_returns)
        ),
    )
    artifacts["long_side_nav_table"] = _artifact(
        "long_side_nav.csv",
        "datetime,long_side_nav,cost_adjusted_long_side_nav\n"
        + "".join(
            f"{dt},{gross:.12g},{net:.12g}\n"
            for dt, gross, net in zip(dates, alternate_gross, alternate_net)
        ),
    )

    bundle = build_backtest_evidence_bundle(
        artifacts=artifacts,
        core_metrics={},
        validator_verdict="PASS",
        formal_verified=True,
    )

    checks = {
        item["check"]: item["status"] for item in bundle["consistency"]["checks"]
    }
    assert checks["gross_nav_from_long_returns"] == "PASS"
    assert checks["net_nav_from_returns_and_turnover"] == "PASS"
    assert checks["long_side_return_from_G10"] == "CONFLICT"
    assert bundle["evidence_class"] == "EVIDENCE CONFLICT"


def test_intermediate_nav_mutation_is_caught_even_when_final_nav_matches() -> None:
    artifacts = _formal_artifacts()
    nav_lines = artifacts["long_side_nav_table"].data.decode("utf-8").splitlines()
    middle = nav_lines[2].split(",")
    middle[1] = "0.9"
    artifacts["long_side_nav_table"] = _artifact(
        "long_side_nav.csv",
        "\n".join([nav_lines[0], nav_lines[1], ",".join(middle), nav_lines[3]]) + "\n",
    )
    long_short_lines = artifacts["long_short_nav_table"].data.decode("utf-8").splitlines()
    long_short_middle = long_short_lines[2].split(",")
    long_short_middle[1] = "1.05"
    artifacts["long_short_nav_table"] = _artifact(
        "long_short_nav_10groups.csv",
        "\n".join(
            [
                long_short_lines[0],
                long_short_lines[1],
                ",".join(long_short_middle),
                long_short_lines[3],
            ]
        )
        + "\n",
    )

    bundle = build_backtest_evidence_bundle(
        artifacts=artifacts,
        core_metrics={
            "gross_final_nav": 1.2,
            "net_final_nav": 1.19814072,
            "long_short_final_nav": 1.2,
            "turnover": {"long_side_turnover_mean_daily": 0.3},
        },
        validator_verdict="PASS",
        formal_verified=True,
    )

    check_status = {
        item["check"]: item["status"] for item in bundle["consistency"]["checks"]
    }
    assert bundle["evidence_class"] == "EVIDENCE CONFLICT"
    assert check_status["gross_final_nav"] == "PASS"
    assert check_status["gross_nav_from_long_returns"] == "CONFLICT"
    assert check_status["long_short_nav_from_returns"] == "CONFLICT"


def test_empty_fama_macbeth_payload_is_not_available() -> None:
    bundle = build_backtest_evidence_bundle(
        artifacts={},
        core_metrics={"fama_macbeth": {}},
        validator_verdict="NOT_RUN",
        formal_verified=False,
    )

    assert bundle["module_status"]["fama_macbeth"] == "not_produced"
