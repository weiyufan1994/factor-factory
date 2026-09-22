from __future__ import annotations

import binascii
import csv
import hashlib
import io
import math
import zlib
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping


BACKTEST_EVIDENCE_CONTRACT_VERSION = "factorforge_console_backtest_evidence_v2"
MAX_TABLE_ROWS = 100_000
FORMAL_QUANTILE_GROUP_COUNT = 10
FORMAL_TRADING_COST_RATE = 0.003
MAX_CHART_DIMENSION = 10_000
MAX_CHART_PIXELS = 40_000_000
MAX_CHART_DECODED_BYTES = 64 * 1024 * 1024
REQUIRED_VERIFIED_ROLES = {
    "rank_ic_chart",
    "pearson_ic_chart",
    "coverage_chart",
    "gross_nav_chart",
    "net_nav_chart",
    "quantile_nav_chart",
    "quantile_counts_chart",
    "long_short_diagnostic_chart",
    "long_side_returns_table",
    "long_side_nav_table",
    "long_side_turnover_table",
    "quantile_returns_table",
    "quantile_nav_table",
    "quantile_counts_table",
    "quantile_summary_table",
    "long_short_returns_table",
    "long_short_nav_table",
}


@dataclass(frozen=True)
class BacktestArtifact:
    artifact_id: str
    data: bytes | None = None
    sha256: str = ""
    byte_size: int = 0
    validation_error: str = ""
    content_validated: bool = False


def build_backtest_evidence_bundle(
    *,
    artifacts: Mapping[str, BacktestArtifact],
    core_metrics: Mapping[str, Any],
    validator_verdict: str,
    formal_verified: bool,
) -> dict[str, Any]:
    sources = {}
    for role, artifact in sorted(artifacts.items()):
        data = artifact.data or b""
        sources[role] = {
            "artifact_id": artifact.artifact_id,
            "sha256": artifact.sha256 or hashlib.sha256(data).hexdigest(),
            "byte_size": artifact.byte_size or len(data),
        }
    parse_errors = _artifact_errors(artifacts)

    nav = _parse_or_empty(
        artifacts,
        "long_side_nav_table",
        _parse_nav_table,
        parse_errors,
    )
    turnover = _parse_or_empty(
        artifacts,
        "long_side_turnover_table",
        _parse_turnover_table,
        parse_errors,
    )
    quantile_summary = _parse_or_empty(
        artifacts,
        "quantile_summary_table",
        _parse_quantile_summary_table,
        parse_errors,
    )
    quantile_nav = _parse_or_empty(
        artifacts,
        "quantile_nav_table",
        _parse_group_nav_table,
        parse_errors,
    )
    long_short = _parse_or_empty(
        artifacts,
        "long_short_nav_table",
        _parse_single_nav_table,
        parse_errors,
    )
    long_returns = _parse_or_empty(
        artifacts,
        "long_side_returns_table",
        lambda data: _parse_return_table(data, fields=("long_side_return",)),
        parse_errors,
    )
    quantile_returns = _parse_or_empty(
        artifacts,
        "quantile_returns_table",
        lambda data: _parse_return_table(data, fields=_formal_groups()),
        parse_errors,
    )
    quantile_counts = _parse_or_empty(
        artifacts,
        "quantile_counts_table",
        _parse_quantile_counts_table,
        parse_errors,
    )
    long_short_returns = _parse_or_empty(
        artifacts,
        "long_short_returns_table",
        lambda data: _parse_return_table(data, fields=("long_short_return",)),
        parse_errors,
    )

    checks = [
        *_nav_consistency(nav.get("summary", {}), core_metrics),
        *_turnover_consistency(turnover, core_metrics),
        *_quantile_consistency(quantile_summary, quantile_nav),
        *_formal_drawdown_consistency(nav.get("drawdown", {}), core_metrics),
        *_long_short_scalar_consistency(long_short, core_metrics),
        *_series_identity_checks(
            nav=nav,
            turnover=turnover,
            long_returns=long_returns,
            quantile_returns=quantile_returns,
            quantile_nav=quantile_nav,
            quantile_counts=quantile_counts,
            quantile_summary=quantile_summary,
            long_short_returns=long_short_returns,
            long_short_nav=long_short,
        ),
    ]
    missing_required_roles = sorted(REQUIRED_VERIFIED_ROLES - set(artifacts))
    invalid_required_roles = sorted(REQUIRED_VERIFIED_ROLES.intersection(parse_errors))
    if formal_verified:
        checks.append(
            {
                "check": "required_formal_step4_pack",
                "status": (
                    "PASS"
                    if not missing_required_roles and not invalid_required_roles
                    else "CONFLICT"
                ),
                "missing_roles": missing_required_roles,
                "invalid_roles": invalid_required_roles,
            }
        )
    for role, message in parse_errors.items():
        checks.append(
            {
                "check": f"{role}_parse",
                "status": "CONFLICT",
                "detail": message,
                "artifact_id": sources.get(role, {}).get("artifact_id", ""),
            }
        )
    consistency_status = (
        "CONFLICT"
        if any(item.get("status") == "CONFLICT" for item in checks)
        else "PASS"
        if checks
        else "NOT_CHECKED"
    )

    charts = {
        role: artifact.artifact_id
        for role, artifact in artifacts.items()
        if role.endswith("_chart") and role not in parse_errors
    }
    tables = {
        role: artifact.artifact_id
        for role, artifact in artifacts.items()
        if role.endswith("_table")
    }
    module_status = {
        "formal_step4_pack": _module_status(
            produced=not missing_required_roles and not invalid_required_roles,
            invalid=bool(invalid_required_roles),
            conflict=bool(formal_verified and missing_required_roles),
        ),
        "gross_net_nav": _module_status(
            produced=bool(nav),
            invalid=bool(
                {
                    "long_side_nav_table",
                    "long_side_returns_table",
                    "long_side_turnover_table",
                }.intersection(parse_errors)
            ),
            conflict=_check_conflict(
                checks,
                {
                    "gross_final_nav",
                    "net_final_nav",
                    "gross_nav_from_long_returns",
                    "net_nav_from_returns_and_turnover",
                    "long_side_return_from_G10",
                    "gross_max_drawdown",
                    "gross_recovery_days",
                },
            ),
        ),
        "annual_returns": _module_status(
            produced=_has_period_returns(nav.get("annual_returns")),
            invalid="long_side_nav_table" in parse_errors,
        ),
        "monthly_returns": _module_status(
            produced=_has_period_returns(nav.get("monthly_returns")),
            invalid="long_side_nav_table" in parse_errors,
        ),
        "drawdown_geometry": _module_status(
            produced=bool(nav.get("drawdown")),
            invalid="long_side_nav_table" in parse_errors,
        ),
        "quantile_nav": _module_status(
            produced=bool(quantile_nav) or "quantile_nav_chart" in charts,
            invalid=(
                bool(
                    {
                        "quantile_nav_table",
                        "quantile_returns_table",
                        "quantile_counts_table",
                    }.intersection(parse_errors)
                )
                or "quantile_nav_chart" in parse_errors
            ),
            conflict=_check_conflict(
                checks,
                {
                    "quantile_final_nav",
                    "quantile_group_set",
                    "quantile_table_dates",
                    "quantile_summary_statistics",
                    "long_side_return_from_G10",
                },
                prefixes=("G",),
            ),
        ),
        "quantile_summary": _module_status(
            produced=bool(quantile_summary),
            invalid=bool(
                {
                    "quantile_summary_table",
                    "quantile_nav_table",
                    "quantile_returns_table",
                    "quantile_counts_table",
                }.intersection(parse_errors)
            ),
            conflict=_check_conflict(
                checks,
                {
                    "quantile_final_nav",
                    "quantile_group_set",
                    "quantile_summary_statistics",
                },
            ),
        ),
        "long_short": _module_status(
            produced=bool(long_short) or "long_short_diagnostic_chart" in charts,
            invalid=(
                bool(
                    {
                        "long_short_nav_table",
                        "long_short_returns_table",
                        "quantile_returns_table",
                    }.intersection(parse_errors)
                )
                or "long_short_diagnostic_chart" in parse_errors
            ),
            conflict=_check_conflict(
                checks,
                {
                    "long_short_final_nav",
                    "long_short_nav_from_returns",
                    "long_short_return_from_deciles",
                },
            ),
        ),
        "rank_ic_timeseries": _module_status(
            produced="rank_ic_chart" in charts,
            invalid="rank_ic_chart" in parse_errors,
        ),
        "pearson_ic_timeseries": _module_status(
            produced="pearson_ic_chart" in charts,
            invalid="pearson_ic_chart" in parse_errors,
        ),
        "coverage": _module_status(
            produced="coverage_chart" in charts,
            invalid="coverage_chart" in parse_errors,
        ),
        "turnover_profile": _module_status(
            produced=bool(turnover),
            invalid="long_side_turnover_table" in parse_errors,
            conflict=_check_conflict(
                checks,
                {"turnover_mean_daily", "net_nav_from_returns_and_turnover"},
            ),
        ),
        "cost_sensitivity": "not_produced",
        "benchmark_excess": "not_produced",
        "ic_decay": "not_produced",
        "stability_slices": "not_produced",
        "factor_exposure": "not_produced",
        "fama_macbeth": _module_status(
            produced=_has_substantive_metric(core_metrics.get("fama_macbeth"))
        ),
    }
    evidence_class = "FORMAL VERIFIED" if formal_verified else "FORMAL UNVERIFIED"
    if consistency_status == "CONFLICT":
        evidence_class = "EVIDENCE CONFLICT"

    return {
        "contract_version": BACKTEST_EVIDENCE_CONTRACT_VERSION,
        "evidence_class": evidence_class,
        "validator_verdict": validator_verdict,
        "metrics": _plain_copy(core_metrics),
        "charts": charts,
        "tables": tables,
        "nav_summary": nav.get("summary", {}),
        "annual_returns": nav.get("annual_returns", []),
        "monthly_returns": nav.get("monthly_returns", []),
        "drawdown": nav.get("drawdown", {}),
        "turnover_profile": _without_internal(turnover),
        "quantile_summary": quantile_summary.get("rows", []),
        "quantile_profile": quantile_summary.get("profile", {}),
        "long_short_profile": _without_internal(long_short),
        "module_status": module_status,
        "consistency": {"status": consistency_status, "checks": checks},
        "parse_errors": parse_errors,
        "provenance": {
            "sources": sources,
            "deterministic_derivations": {
                "annual_returns": "calendar-year endpoint returns from formal gross/net NAV; no interpolation",
                "monthly_returns": "calendar-month endpoint returns from formal gross/net NAV; no interpolation",
                "drawdown": "running-peak drawdown geometry from formal gross/net NAV",
                "turnover_profile": "distribution summary from formal daily long-side turnover",
            },
        },
    }


def _parse_or_empty(
    artifacts: Mapping[str, BacktestArtifact],
    role: str,
    parser: Any,
    errors: dict[str, str],
) -> dict[str, Any]:
    artifact = artifacts.get(role)
    if artifact is None:
        return {}
    if role in errors:
        return {}
    if artifact.data is None:
        errors[role] = "formal table payload is unavailable"
        return {}
    try:
        return parser(artifact.data)
    except (UnicodeError, ValueError, csv.Error) as exc:
        errors[role] = str(exc) or "invalid formal table"
        return {}


def artifact_validation_error(role: str, data: bytes) -> str:
    if role.endswith("_chart"):
        if len(data) < 45 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "formal chart is not a valid PNG container"
        offset = 8
        saw_ihdr = False
        saw_idat = False
        saw_iend = False
        saw_non_idat_after_idat = False
        saw_plte = False
        ihdr = b""
        idat_parts: list[bytes] = []
        palette_entries = 0
        while offset + 12 <= len(data):
            length = int.from_bytes(data[offset : offset + 4], "big")
            chunk_type = data[offset + 4 : offset + 8]
            if any(
                value not in range(ord("A"), ord("Z") + 1)
                and value not in range(ord("a"), ord("z") + 1)
                for value in chunk_type
            ) or (chunk_type[2] & 0x20):
                return "formal chart has an invalid PNG chunk type"
            chunk_end = offset + 12 + length
            if chunk_end > len(data):
                return "formal chart has a truncated PNG chunk"
            chunk_data = data[offset + 8 : offset + 8 + length]
            expected_crc = int.from_bytes(data[offset + 8 + length : chunk_end], "big")
            observed_crc = binascii.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
            if observed_crc != expected_crc:
                return "formal chart has an invalid PNG checksum"
            if not saw_ihdr:
                if chunk_type != b"IHDR" or length != 13:
                    return "formal chart lacks a PNG IHDR header"
                ihdr = chunk_data
                width = int.from_bytes(chunk_data[0:4], "big")
                height = int.from_bytes(chunk_data[4:8], "big")
                if (
                    width <= 0
                    or height <= 0
                    or width > MAX_CHART_DIMENSION
                    or height > MAX_CHART_DIMENSION
                    or width * height > MAX_CHART_PIXELS
                ):
                    return "formal chart has invalid dimensions"
                saw_ihdr = True
            elif chunk_type == b"IHDR":
                return "formal chart contains multiple PNG headers"
            if chunk_type == b"PLTE":
                if saw_plte or saw_idat or length == 0 or length % 3 or length > 768:
                    return "formal chart has an invalid PNG palette"
                saw_plte = True
                palette_entries = length // 3
            if chunk_type == b"IDAT":
                if saw_non_idat_after_idat:
                    return "formal chart has non-consecutive PNG image data"
                saw_idat = True
                idat_parts.append(chunk_data)
            elif saw_idat and chunk_type != b"IEND":
                saw_non_idat_after_idat = True
            if chunk_type == b"IEND":
                if length != 0:
                    return "formal chart has an invalid PNG terminator"
                saw_iend = True
                if chunk_end != len(data):
                    return "formal chart has trailing PNG data"
                break
            if chunk_type not in {b"IHDR", b"PLTE", b"IDAT", b"IEND"} and not (
                chunk_type[0] & 0x20
            ):
                return "formal chart contains an unknown critical PNG chunk"
            offset = chunk_end
        if not saw_ihdr or not saw_idat or not saw_iend:
            return "formal chart is missing required PNG chunks"
        decode_error = _png_image_data_error(
            ihdr=ihdr,
            compressed=b"".join(idat_parts),
            palette_entries=palette_entries,
        )
        if decode_error:
            return decode_error
    return ""


def _png_image_data_error(
    *,
    ihdr: bytes,
    compressed: bytes,
    palette_entries: int,
) -> str:
    width = int.from_bytes(ihdr[0:4], "big")
    height = int.from_bytes(ihdr[4:8], "big")
    bit_depth = ihdr[8]
    color_type = ihdr[9]
    compression_method = ihdr[10]
    filter_method = ihdr[11]
    interlace_method = ihdr[12]
    allowed_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    if color_type not in allowed_depths or bit_depth not in allowed_depths[color_type]:
        return "formal chart has an unsupported PNG pixel format"
    if compression_method != 0 or filter_method != 0 or interlace_method not in {0, 1}:
        return "formal chart has an unsupported PNG encoding"
    if color_type == 3 and (
        palette_entries <= 0 or palette_entries > 2**bit_depth
    ):
        return "formal chart has an invalid indexed PNG palette"
    if color_type in {0, 4} and palette_entries:
        return "formal chart has a forbidden PNG palette"

    bits_per_pixel = channels[color_type] * bit_depth
    pass_layout = _png_pass_layout(
        width=width,
        height=height,
        bits_per_pixel=bits_per_pixel,
        interlaced=interlace_method == 1,
    )
    expected_size = sum(
        (row_bytes + 1) * pass_height
        for _, pass_height, row_bytes in pass_layout
    )
    if expected_size > MAX_CHART_DECODED_BYTES:
        return "formal chart exceeds the decoded PNG memory budget"
    try:
        decoded = _bounded_zlib_decompress(compressed, expected_size)
    except zlib.error:
        return "formal chart has undecodable PNG image data"
    if decoded is None or len(decoded) != expected_size:
        return "formal chart has invalid PNG scanline data"
    return _png_scanline_error(
        decoded=decoded,
        pass_layout=pass_layout,
        filter_bytes_per_pixel=max(1, (bits_per_pixel + 7) // 8),
        indexed_bit_depth=bit_depth if color_type == 3 else 0,
        palette_entries=palette_entries,
    )


def _png_pass_layout(
    *,
    width: int,
    height: int,
    bits_per_pixel: int,
    interlaced: bool,
) -> list[tuple[int, int, int]]:
    if not interlaced:
        row_bytes = (width * bits_per_pixel + 7) // 8
        return [(width, height, row_bytes)]
    layout: list[tuple[int, int, int]] = []
    for start_x, start_y, step_x, step_y in (
        (0, 0, 8, 8),
        (4, 0, 8, 8),
        (0, 4, 4, 8),
        (2, 0, 4, 4),
        (0, 2, 2, 4),
        (1, 0, 2, 2),
        (0, 1, 1, 2),
    ):
        if width <= start_x or height <= start_y:
            continue
        pass_width = (width - start_x + step_x - 1) // step_x
        pass_height = (height - start_y + step_y - 1) // step_y
        row_bytes = (pass_width * bits_per_pixel + 7) // 8
        layout.append((pass_width, pass_height, row_bytes))
    return layout


def _png_scanline_error(
    *,
    decoded: bytes,
    pass_layout: list[tuple[int, int, int]],
    filter_bytes_per_pixel: int,
    indexed_bit_depth: int,
    palette_entries: int,
) -> str:
    offset = 0
    for pass_width, pass_height, row_bytes in pass_layout:
        previous = bytearray(row_bytes)
        for _ in range(pass_height):
            filter_type = decoded[offset]
            offset += 1
            if filter_type > 4:
                return "formal chart has an invalid PNG row filter"
            raw = decoded[offset : offset + row_bytes]
            offset += row_bytes
            reconstructed = bytearray(row_bytes)
            for index, value in enumerate(raw):
                left = (
                    reconstructed[index - filter_bytes_per_pixel]
                    if index >= filter_bytes_per_pixel
                    else 0
                )
                above = previous[index]
                upper_left = (
                    previous[index - filter_bytes_per_pixel]
                    if index >= filter_bytes_per_pixel
                    else 0
                )
                predictor = 0
                if filter_type == 1:
                    predictor = left
                elif filter_type == 2:
                    predictor = above
                elif filter_type == 3:
                    predictor = (left + above) // 2
                elif filter_type == 4:
                    predictor = _png_paeth(left, above, upper_left)
                reconstructed[index] = (value + predictor) & 0xFF
            if indexed_bit_depth and _png_palette_index_out_of_range(
                reconstructed,
                pixel_count=pass_width,
                bit_depth=indexed_bit_depth,
                palette_entries=palette_entries,
            ):
                return "formal chart references an undefined PNG palette index"
            previous = reconstructed
    if offset != len(decoded):
        return "formal chart has invalid PNG scanline data"
    return ""


def _png_paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _png_palette_index_out_of_range(
    row: bytearray,
    *,
    pixel_count: int,
    bit_depth: int,
    palette_entries: int,
) -> bool:
    mask = (1 << bit_depth) - 1
    for pixel in range(pixel_count):
        bit_offset = pixel * bit_depth
        shift = 8 - bit_depth - (bit_offset % 8)
        palette_index = (row[bit_offset // 8] >> shift) & mask
        if palette_index >= palette_entries:
            return True
    return False


def _bounded_zlib_decompress(data: bytes, expected_size: int) -> bytes | None:
    decoder = zlib.decompressobj()
    output = bytearray()
    remaining = data
    while remaining:
        capacity = expected_size + 1 - len(output)
        if capacity <= 0:
            return None
        output.extend(decoder.decompress(remaining, capacity))
        if len(output) > expected_size:
            return None
        if decoder.unconsumed_tail:
            remaining = decoder.unconsumed_tail
        else:
            remaining = b""
    capacity = expected_size + 1 - len(output)
    if capacity <= 0 and not decoder.eof:
        return None
    output.extend(decoder.flush(max(capacity, 1)))
    if (
        len(output) > expected_size
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        return None
    return bytes(output)


def _artifact_errors(
    artifacts: Mapping[str, BacktestArtifact],
) -> dict[str, str]:
    errors: dict[str, str] = {}
    for role, artifact in artifacts.items():
        error = artifact.validation_error
        if (
            not error
            and role.endswith("_chart")
            and artifact.data is None
            and not artifact.content_validated
        ):
            error = "formal chart payload was not host-validated"
        if not error and artifact.data is not None:
            error = artifact_validation_error(role, artifact.data)
        if error:
            errors[role] = error
    return errors


def _read_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    raw_fields = [str(item or "").strip() for item in (reader.fieldnames or [])]
    if not raw_fields or any(not item for item in raw_fields[1:]):
        raise ValueError("missing or invalid CSV header")
    fields = ["datetime" if index == 0 and not item else item for index, item in enumerate(raw_fields)]
    if len(set(fields)) != len(fields):
        raise ValueError("duplicate CSV header")
    rows: list[dict[str, str]] = []
    for index, raw in enumerate(reader):
        if index >= MAX_TABLE_ROWS:
            raise ValueError(f"table exceeds {MAX_TABLE_ROWS} rows")
        if None in raw:
            raise ValueError("formal table row has surplus CSV fields")
        rows.append(
            {
                normalized: str(raw.get(original) or "").strip()
                for original, normalized in zip(raw_fields, fields)
            }
        )
    if not rows:
        raise ValueError("formal table is empty")
    return fields, rows


def _parse_nav_table(data: bytes) -> dict[str, Any]:
    fields, rows = _read_csv(data)
    date_field = fields[0]
    gross_field = "long_side_nav" if "long_side_nav" in fields else ""
    net_field = (
        "cost_adjusted_long_side_nav"
        if "cost_adjusted_long_side_nav" in fields
        else ""
    )
    if fields != ["datetime", "long_side_nav", "cost_adjusted_long_side_nav"]:
        raise ValueError("NAV table must contain both gross and net NAV columns")
    points = _dated_points(rows, date_field, (gross_field, net_field), positive=True)
    _require_complete_points(points, rows, (gross_field, net_field), label="NAV")
    _require_normalized_start(points, (gross_field, net_field), label="NAV")
    endpoint_returns = _endpoint_returns(points)
    summary = {
        "start_date": points[0][0].isoformat(),
        "end_date": points[-1][0].isoformat(),
        "period_count": len(points),
        "gross_final_nav": (
            next(
                (values.get(gross_field) for _, values in reversed(points) if values.get(gross_field) is not None),
                None,
            )
            if gross_field
            else None
        ),
        "net_final_nav": (
            next(
                (values.get(net_field) for _, values in reversed(points) if values.get(net_field) is not None),
                None,
            )
            if net_field
            else None
        ),
    }
    drawdown: dict[str, Any] = {}
    if gross_field:
        drawdown["gross"] = _drawdown_geometry(points, gross_field)
    if net_field:
        drawdown["net"] = _drawdown_geometry(points, net_field)
    return {
        "summary": summary,
        "annual_returns": endpoint_returns["annual"],
        "monthly_returns": endpoint_returns["monthly"],
        "drawdown": drawdown,
        "_points": points,
    }


def _parse_turnover_table(data: bytes) -> dict[str, Any]:
    fields, rows = _read_csv(data)
    date_field = fields[0]
    value_field = "long_side_turnover" if "long_side_turnover" in fields else ""
    if fields != ["datetime", "long_side_turnover"]:
        raise ValueError("turnover table lacks long_side_turnover")
    points = _dated_points(rows, date_field, (value_field,), positive=False)
    _require_complete_points(points, rows, (value_field,), label="turnover")
    values = [item[1][value_field] for item in points if item[1].get(value_field) is not None]
    if not values:
        raise ValueError("turnover table has no usable observations")
    if any(value > 1.0 for value in values):
        raise ValueError("turnover values must be within [0, 1]")
    if abs(values[0]) > 1e-12:
        raise ValueError("initial portfolio formation turnover must be zero")
    measurement_values = values[1:] if len(values) > 1 else values
    ordered = sorted(measurement_values)
    return {
        "start_date": points[0][0].isoformat(),
        "end_date": points[-1][0].isoformat(),
        "observation_count": len(values),
        "measurement_count": len(measurement_values),
        "mean_daily": sum(measurement_values) / len(measurement_values),
        "median_daily": _percentile(ordered, 0.5),
        "p95_daily": _percentile(ordered, 0.95),
        "max_daily": max(measurement_values),
        "mean_basis": "daily observations after initial portfolio formation",
        "_points": points,
    }


def _parse_quantile_summary_table(data: bytes) -> dict[str, Any]:
    fields, raw_rows = _read_csv(data)
    required_order = [
        "group",
        "mean_daily_return",
        "std_daily_return",
        "daily_ir",
        "final_nav",
        "member_count_min",
        "member_count_median",
        "member_count_max",
    ]
    required = set(required_order)
    if fields != required_order:
        raise ValueError("quantile summary lacks required columns")
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        group = raw.get("group", "")
        if not group or not group.startswith("G") or not group[1:].isdigit():
            raise ValueError("quantile summary has invalid group label")
        row = {"group": group}
        for field in fields:
            if field == "group":
                continue
            row[field] = _strict_optional_float(raw.get(field), field=field)
        for field in required - {"group"}:
            if row.get(field) is None:
                raise ValueError(f"quantile summary has missing {field}")
        for field in ("member_count_min", "member_count_median", "member_count_max"):
            value = row[field]
            if value is None or value <= 0:
                raise ValueError(f"quantile summary has invalid {field}")
        rows.append(row)
    rows.sort(key=lambda item: int(str(item["group"])[1:]))
    if len({item["group"] for item in rows}) != len(rows):
        raise ValueError("quantile summary has duplicate groups")
    _validate_formal_groups([str(item["group"]) for item in rows])
    final_navs = [item.get("final_nav") for item in rows]
    finite_navs = [item for item in final_navs if isinstance(item, float)]
    profile = {
        "group_count": len(rows),
        "bottom_group": rows[0]["group"] if rows else "",
        "top_group": rows[-1]["group"] if rows else "",
        "top_minus_bottom_final_nav": (
            finite_navs[-1] - finite_navs[0]
            if len(finite_navs) == len(rows) and len(rows) >= 2
            else None
        ),
        "final_nav_monotonic_direction": _monotonic_direction(finite_navs),
    }
    return {"rows": rows, "profile": profile}


def _parse_group_nav_table(data: bytes) -> dict[str, Any]:
    fields, rows = _read_csv(data)
    date_field = fields[0]
    group_fields = [item for item in fields[1:] if item.startswith("G") and item[1:].isdigit()]
    if fields != ["datetime", *group_fields]:
        raise ValueError("quantile NAV columns do not match the formal contract")
    _validate_formal_groups(group_fields)
    points = _dated_points(rows, date_field, tuple(group_fields), positive=True)
    _require_complete_points(points, rows, tuple(group_fields), label="quantile NAV")
    _require_normalized_start(points, tuple(group_fields), label="quantile NAV")
    return {
        "group_count": len(group_fields),
        "groups": group_fields,
        "start_date": points[0][0].isoformat(),
        "end_date": points[-1][0].isoformat(),
        "period_count": len(points),
        "final_nav": {
            group: points[-1][1][group]
            for group in group_fields
        },
        "_points": points,
    }


def _parse_single_nav_table(data: bytes) -> dict[str, Any]:
    fields, rows = _read_csv(data)
    if fields != ["datetime", "long_short_nav"]:
        raise ValueError("long-short NAV table must contain one series")
    date_field, value_field = fields
    points = _dated_points(rows, date_field, (value_field,), positive=True)
    _require_complete_points(points, rows, (value_field,), label="long-short NAV")
    _require_normalized_start(points, (value_field,), label="long-short NAV")
    first = points[0][1][value_field]
    final = points[-1][1][value_field]
    return {
        "series": value_field,
        "start_date": points[0][0].isoformat(),
        "end_date": points[-1][0].isoformat(),
        "period_count": len(points),
        "final_nav": final,
        "total_return": final / first - 1.0 if first and first > 0 else None,
        "drawdown": _drawdown_geometry(points, value_field),
        "_points": points,
    }


def _parse_return_table(data: bytes, *, fields: tuple[str, ...]) -> dict[str, Any]:
    csv_fields, rows = _read_csv(data)
    date_field = csv_fields[0]
    if csv_fields != ["datetime", *fields]:
        raise ValueError("return table columns do not match the formal contract")
    points = _dated_points(rows, date_field, fields, positive=None)
    _require_complete_points(points, rows, fields, label="return")
    return {
        "start_date": points[0][0].isoformat(),
        "end_date": points[-1][0].isoformat(),
        "period_count": len(points),
        "fields": list(fields),
        "_points": points,
    }


def _parse_quantile_counts_table(data: bytes) -> dict[str, Any]:
    csv_fields, rows = _read_csv(data)
    date_field = csv_fields[0]
    groups = _formal_groups()
    if csv_fields != ["datetime", *groups]:
        raise ValueError("quantile count columns do not match the formal contract")
    points = _dated_points(rows, date_field, groups, positive=True)
    _require_complete_points(points, rows, groups, label="quantile counts")
    for _, values in points:
        for group in groups:
            value = values[group]
            if value is None or not float(value).is_integer():
                raise ValueError("quantile counts must be positive integers")
    return {
        "start_date": points[0][0].isoformat(),
        "end_date": points[-1][0].isoformat(),
        "period_count": len(points),
        "_points": points,
    }


def _dated_points(
    rows: list[dict[str, str]],
    date_field: str,
    value_fields: tuple[str, ...],
    *,
    positive: bool | None,
) -> list[tuple[date, dict[str, float | None]]]:
    points: list[tuple[date, dict[str, float | None]]] = []
    seen: set[date] = set()
    for raw in rows:
        parsed_date = _parse_date(raw.get(date_field, ""))
        if parsed_date in seen:
            raise ValueError(f"duplicate date in formal table: {parsed_date.isoformat()}")
        values = {
            field: _strict_optional_float(raw.get(field), field=field)
            for field in value_fields
            if field
        }
        if not any(value is not None for value in values.values()):
            continue
        if positive is True and any(value is not None and value <= 0 for value in values.values()):
            raise ValueError("NAV values must be positive")
        if positive is False and any(value is not None and value < 0 for value in values.values()):
            raise ValueError("turnover values must be non-negative")
        seen.add(parsed_date)
        points.append((parsed_date, values))
    points.sort(key=lambda item: item[0])
    return points


def _require_complete_points(
    points: list[tuple[date, dict[str, float | None]]],
    rows: list[dict[str, str]],
    fields: tuple[str, ...],
    *,
    label: str,
) -> None:
    if not points or len(points) != len(rows):
        raise ValueError(f"{label} table has missing observations")
    if any(values.get(field) is None for _, values in points for field in fields):
        raise ValueError(f"{label} table contains missing values")


def _require_normalized_start(
    points: list[tuple[date, dict[str, float | None]]],
    fields: tuple[str, ...],
    *,
    label: str,
) -> None:
    first = points[0][1]
    if any(
        first.get(field) is None or abs(float(first[field]) - 1.0) > 1e-8
        for field in fields
    ):
        raise ValueError(f"{label} series must start at normalized NAV 1.0")


def _endpoint_returns(
    points: list[tuple[date, dict[str, float | None]]],
) -> dict[str, list[dict[str, Any]]]:
    fields = sorted({key for _, values in points for key in values})
    annual = _period_returns(points, fields, period="annual")
    monthly = _period_returns(points, fields, period="monthly")
    return {"annual": annual, "monthly": monthly}


def _period_returns(
    points: list[tuple[date, dict[str, float | None]]],
    fields: list[str],
    *,
    period: str,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, ...], list[tuple[date, dict[str, float | None]]]] = {}
    for point in points:
        key = (point[0].year,) if period == "annual" else (point[0].year, point[0].month)
        grouped.setdefault(key, []).append(point)
    previous = {field: points[0][1].get(field) for field in fields}
    results: list[dict[str, Any]] = []
    for period_index, key in enumerate(sorted(grouped)):
        period_points = grouped[key]
        row: dict[str, Any] = {"year": key[0]}
        if period == "monthly":
            row["month"] = key[1]
        for field in fields:
            end = next(
                (item[1].get(field) for item in reversed(period_points) if item[1].get(field) is not None),
                None,
            )
            denominator = previous.get(field)
            name = "gross_return" if field == "long_side_nav" else "net_return"
            period_values = [item[1].get(field) for item in period_points if item[1].get(field) is not None]
            enough_observations = period_index > 0 or len(period_values) >= 2
            row[name] = (
                end / denominator - 1.0
                if enough_observations and end is not None and denominator and denominator > 0
                else None
            )
            if end is not None:
                previous[field] = end
        results.append(row)
    return results


def _drawdown_geometry(
    points: list[tuple[date, dict[str, float | None]]],
    field: str,
) -> dict[str, Any]:
    valid = [(dt, values[field]) for dt, values in points if values.get(field) is not None]
    if not valid:
        return {}
    peak_date, peak_value = valid[0]
    worst_drawdown = 0.0
    worst_peak_date = peak_date
    trough_date = peak_date
    trough_index = 0
    for index, (dt, value) in enumerate(valid):
        assert value is not None
        if value >= peak_value:
            peak_date, peak_value = dt, value
        drawdown = value / peak_value - 1.0
        if drawdown < worst_drawdown:
            worst_drawdown = drawdown
            worst_peak_date = peak_date
            trough_date = dt
            trough_index = index
    if worst_drawdown == 0.0:
        return {
            "max_drawdown": 0.0,
            "peak_date": None,
            "trough_date": None,
            "recovery_date": None,
            "underwater_days": 0,
            "max_recovery_days": 0,
            "recovered": True,
        }
    recovery_date = None
    recovery_level = next(
        value for dt, value in valid if dt == worst_peak_date
    )
    for dt, value in valid[trough_index + 1 :]:
        if value >= recovery_level:
            recovery_date = dt
            break
    end_date = recovery_date or valid[-1][0]
    return {
        "max_drawdown": worst_drawdown,
        "peak_date": worst_peak_date.isoformat(),
        "trough_date": trough_date.isoformat(),
        "recovery_date": recovery_date.isoformat() if recovery_date else None,
        "underwater_days": (end_date - worst_peak_date).days,
        "max_recovery_days": _max_recovery_days(valid),
        "recovered": recovery_date is not None,
    }


def _max_recovery_days(valid: list[tuple[date, float | None]]) -> int:
    peak_value = float(valid[0][1])
    peak_date = valid[0][0]
    underwater_start = None
    maximum = 0
    for dt, raw_value in valid:
        value = float(raw_value)
        if value >= peak_value:
            if underwater_start is not None:
                maximum = max(maximum, (dt - underwater_start).days)
                underwater_start = None
            peak_value = value
            peak_date = dt
        elif underwater_start is None:
            underwater_start = peak_date
    if underwater_start is not None:
        maximum = max(maximum, (valid[-1][0] - underwater_start).days)
    return maximum


def _nav_consistency(
    nav_summary: Mapping[str, Any],
    core_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for key in ("gross_final_nav", "net_final_nav"):
        observed = _optional_float(nav_summary.get(key))
        expected = _metric_number(core_metrics.get(key), ("value", key))
        if observed is None or expected is None:
            continue
        checks.append(_numeric_check(key, observed, expected))
    return checks


def _turnover_consistency(
    turnover: Mapping[str, Any],
    core_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    observed = _optional_float(turnover.get("mean_daily"))
    expected = _metric_number(
        core_metrics.get("turnover"),
        ("long_side_turnover_mean_daily", "turnover_mean", "daily_turnover", "value"),
    )
    if observed is None or expected is None:
        return []
    return [_numeric_check("turnover_mean_daily", observed, expected)]


def _quantile_consistency(
    summary: Mapping[str, Any],
    nav: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = summary.get("rows") if isinstance(summary.get("rows"), list) else []
    final_nav = nav.get("final_nav") if isinstance(nav.get("final_nav"), dict) else {}
    checks: list[dict[str, Any]] = []
    summary_groups = {str(item.get("group") or "") for item in rows if isinstance(item, dict)}
    nav_groups = {str(item) for item in final_nav}
    if summary_groups and nav_groups:
        checks.append(
            {
                "check": "quantile_group_set",
                "status": "PASS" if summary_groups == nav_groups else "CONFLICT",
                "summary_groups": sorted(summary_groups),
                "nav_groups": sorted(nav_groups),
            }
        )
    for row in rows:
        if not isinstance(row, dict):
            continue
        group = str(row.get("group") or "")
        observed = _optional_float(final_nav.get(group))
        expected = _optional_float(row.get("final_nav"))
        if observed is None or expected is None:
            continue
        check = _numeric_check("quantile_final_nav", observed, expected)
        check["group"] = group
        checks.append(check)
    return checks


def _formal_drawdown_consistency(
    drawdown: Mapping[str, Any],
    core_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    gross = drawdown.get("gross") if isinstance(drawdown.get("gross"), Mapping) else {}
    checks: list[dict[str, Any]] = []
    observed_drawdown = _optional_float(gross.get("max_drawdown"))
    expected_drawdown = _metric_number(
        core_metrics.get("drawdown"),
        ("max_drawdown", "long_side_max_drawdown", "value"),
    )
    if observed_drawdown is not None and expected_drawdown is not None:
        checks.append(
            _numeric_check("gross_max_drawdown", observed_drawdown, expected_drawdown)
        )
    observed_recovery = _optional_float(gross.get("max_recovery_days"))
    expected_recovery = _metric_number(
        core_metrics.get("recovery"),
        ("recovery_days", "long_side_recovery_days", "value"),
    )
    if observed_recovery is not None and expected_recovery is not None:
        checks.append(
            _numeric_check("gross_recovery_days", observed_recovery, expected_recovery)
        )
    return checks


def _long_short_scalar_consistency(
    long_short: Mapping[str, Any],
    core_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    observed = _optional_float(long_short.get("final_nav"))
    expected = _metric_number(
        core_metrics.get("long_short_final_nav"),
        ("final_nav", "long_short_final_nav", "value"),
    )
    if observed is None or expected is None:
        return []
    return [_numeric_check("long_short_final_nav", observed, expected)]


def _series_identity_checks(
    *,
    nav: Mapping[str, Any],
    turnover: Mapping[str, Any],
    long_returns: Mapping[str, Any],
    quantile_returns: Mapping[str, Any],
    quantile_nav: Mapping[str, Any],
    quantile_counts: Mapping[str, Any],
    quantile_summary: Mapping[str, Any],
    long_short_returns: Mapping[str, Any],
    long_short_nav: Mapping[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    nav_points = _internal_points(nav)
    turnover_points = _internal_points(turnover)
    long_return_points = _internal_points(long_returns)
    quantile_return_points = _internal_points(quantile_returns)
    quantile_nav_points = _internal_points(quantile_nav)
    quantile_count_points = _internal_points(quantile_counts)
    long_short_return_points = _internal_points(long_short_returns)
    long_short_nav_points = _internal_points(long_short_nav)

    if nav_points and long_return_points:
        checks.append(
            _compounding_check(
                "gross_nav_from_long_returns",
                returns=long_return_points,
                nav=nav_points,
                return_field="long_side_return",
                nav_field="long_side_nav",
            )
        )
    if nav_points and long_return_points and turnover_points:
        checks.append(
            _net_compounding_check(
                returns=long_return_points,
                turnover=turnover_points,
                nav=nav_points,
            )
        )
    if quantile_return_points and quantile_nav_points:
        for group in _formal_groups():
            checks.append(
                _compounding_check(
                    f"{group}_nav_from_returns",
                    returns=quantile_return_points,
                    nav=quantile_nav_points,
                    return_field=group,
                    nav_field=group,
                )
            )
    if long_return_points and quantile_return_points:
        checks.append(
            _series_value_identity_check(
                "long_side_return_from_G10",
                left=long_return_points,
                right=quantile_return_points,
                left_field="long_side_return",
                right_field="G10",
            )
        )
    if long_short_return_points and long_short_nav_points:
        checks.append(
            _compounding_check(
                "long_short_nav_from_returns",
                returns=long_short_return_points,
                nav=long_short_nav_points,
                return_field="long_short_return",
                nav_field="long_short_nav",
            )
        )
    if quantile_return_points and long_short_return_points:
        checks.append(
            _long_short_return_identity(
                quantile_returns=quantile_return_points,
                long_short_returns=long_short_return_points,
            )
        )
    if quantile_return_points and quantile_nav_points and quantile_count_points:
        checks.append(
            _date_set_check(
                "quantile_table_dates",
                quantile_return_points,
                quantile_nav_points,
                quantile_count_points,
            )
        )
    summary_rows = (
        quantile_summary.get("rows")
        if isinstance(quantile_summary.get("rows"), list)
        else []
    )
    if summary_rows and quantile_return_points and quantile_nav_points and quantile_count_points:
        checks.append(
            _quantile_summary_statistics_check(
                rows=summary_rows,
                returns=quantile_return_points,
                nav=quantile_nav_points,
                counts=quantile_count_points,
            )
        )
    return checks


def _compounding_check(
    name: str,
    *,
    returns: list[tuple[date, dict[str, float | None]]],
    nav: list[tuple[date, dict[str, float | None]]],
    return_field: str,
    nav_field: str,
) -> dict[str, Any]:
    return_map = {dt: values[return_field] for dt, values in returns}
    nav_map = {dt: values[nav_field] for dt, values in nav}
    if set(return_map) != set(nav_map):
        return {
            "check": name,
            "status": "CONFLICT",
            "detail": "return and NAV dates differ",
        }
    dates = sorted(nav_map)
    max_difference = 0.0
    mismatch_date = None
    for previous_date, current_date in zip(dates, dates[1:]):
        previous_nav = nav_map[previous_date]
        current_nav = nav_map[current_date]
        current_return = return_map[current_date]
        assert previous_nav is not None and current_nav is not None and current_return is not None
        observed = current_nav / previous_nav - 1.0
        difference = abs(observed - current_return)
        if difference > max_difference:
            max_difference = difference
            mismatch_date = current_date
    return {
        "check": name,
        "status": "PASS" if max_difference <= 1e-8 else "CONFLICT",
        "max_absolute_difference": max_difference,
        "first_mismatch_date": mismatch_date.isoformat() if mismatch_date else None,
    }


def _net_compounding_check(
    *,
    returns: list[tuple[date, dict[str, float | None]]],
    turnover: list[tuple[date, dict[str, float | None]]],
    nav: list[tuple[date, dict[str, float | None]]],
) -> dict[str, Any]:
    return_map = {dt: values["long_side_return"] for dt, values in returns}
    turnover_map = {dt: values["long_side_turnover"] for dt, values in turnover}
    nav_map = {dt: values["cost_adjusted_long_side_nav"] for dt, values in nav}
    if not (set(return_map) == set(turnover_map) == set(nav_map)):
        return {
            "check": "net_nav_from_returns_and_turnover",
            "status": "CONFLICT",
            "detail": "return, turnover, and net NAV dates differ",
        }
    dates = sorted(nav_map)
    max_difference = 0.0
    mismatch_date = None
    for previous_date, current_date in zip(dates, dates[1:]):
        previous_nav = nav_map[previous_date]
        current_nav = nav_map[current_date]
        current_return = return_map[current_date]
        current_turnover = turnover_map[current_date]
        assert None not in {previous_nav, current_nav, current_return, current_turnover}
        observed = float(current_nav) / float(previous_nav) - 1.0
        expected = float(current_return) - float(current_turnover) * FORMAL_TRADING_COST_RATE
        difference = abs(observed - expected)
        if difference > max_difference:
            max_difference = difference
            mismatch_date = current_date
    return {
        "check": "net_nav_from_returns_and_turnover",
        "status": "PASS" if max_difference <= 1e-8 else "CONFLICT",
        "max_absolute_difference": max_difference,
        "first_mismatch_date": mismatch_date.isoformat() if mismatch_date else None,
        "cost_rate": FORMAL_TRADING_COST_RATE,
    }


def _long_short_return_identity(
    *,
    quantile_returns: list[tuple[date, dict[str, float | None]]],
    long_short_returns: list[tuple[date, dict[str, float | None]]],
) -> dict[str, Any]:
    quantile_map = {dt: values for dt, values in quantile_returns}
    long_short_map = {dt: values["long_short_return"] for dt, values in long_short_returns}
    if set(quantile_map) != set(long_short_map):
        return {
            "check": "long_short_return_from_deciles",
            "status": "CONFLICT",
            "detail": "decile and long-short return dates differ",
        }
    differences = []
    for dt in sorted(quantile_map):
        values = quantile_map[dt]
        expected = float(values["G10"]) - float(values["G01"])
        differences.append(abs(float(long_short_map[dt]) - expected))
    maximum = max(differences, default=0.0)
    return {
        "check": "long_short_return_from_deciles",
        "status": "PASS" if maximum <= 1e-12 else "CONFLICT",
        "max_absolute_difference": maximum,
    }


def _series_value_identity_check(
    name: str,
    *,
    left: list[tuple[date, dict[str, float | None]]],
    right: list[tuple[date, dict[str, float | None]]],
    left_field: str,
    right_field: str,
) -> dict[str, Any]:
    left_map = {dt: values[left_field] for dt, values in left}
    right_map = {dt: values[right_field] for dt, values in right}
    if set(left_map) != set(right_map):
        return {
            "check": name,
            "status": "CONFLICT",
            "detail": "formal series dates differ",
        }
    differences = [
        abs(float(left_map[dt]) - float(right_map[dt]))
        for dt in sorted(left_map)
    ]
    maximum = max(differences, default=0.0)
    return {
        "check": name,
        "status": "PASS" if maximum <= 1e-12 else "CONFLICT",
        "max_absolute_difference": maximum,
    }


def _date_set_check(
    name: str,
    *series: list[tuple[date, dict[str, float | None]]],
) -> dict[str, Any]:
    date_sets = [{dt for dt, _ in points} for points in series]
    aligned = bool(date_sets) and all(value == date_sets[0] for value in date_sets[1:])
    return {
        "check": name,
        "status": "PASS" if aligned else "CONFLICT",
        "period_counts": [len(value) for value in date_sets],
    }


def _quantile_summary_statistics_check(
    *,
    rows: list[Any],
    returns: list[tuple[date, dict[str, float | None]]],
    nav: list[tuple[date, dict[str, float | None]]],
    counts: list[tuple[date, dict[str, float | None]]],
) -> dict[str, Any]:
    row_map = {
        str(row.get("group") or ""): row
        for row in rows
        if isinstance(row, Mapping)
    }
    mismatches: list[str] = []
    for group in _formal_groups():
        row = row_map.get(group, {})
        return_values = [float(values[group]) for _, values in returns]
        count_values = sorted(float(values[group]) for _, values in counts)
        mean = sum(return_values) / len(return_values)
        std = _sample_std(return_values)
        expected = {
            "mean_daily_return": mean,
            "std_daily_return": std,
            "daily_ir": mean / std if std not in {None, 0.0} else None,
            "final_nav": float(nav[-1][1][group]),
            "member_count_min": min(count_values),
            "member_count_median": _percentile(count_values, 0.5),
            "member_count_max": max(count_values),
        }
        for field, expected_value in expected.items():
            observed = _optional_float(row.get(field))
            if observed is None or expected_value is None:
                mismatches.append(f"{group}.{field}")
                continue
            tolerance = max(1e-8, abs(expected_value) * 1e-8)
            if abs(observed - expected_value) > tolerance:
                mismatches.append(f"{group}.{field}")
    return {
        "check": "quantile_summary_statistics",
        "status": "PASS" if not mismatches else "CONFLICT",
        "mismatches": mismatches[:40],
        "mismatch_count": len(mismatches),
    }


def _numeric_check(name: str, observed: float, expected: float) -> dict[str, Any]:
    tolerance = max(1e-8, abs(expected) * 1e-8)
    return {
        "check": name,
        "status": "PASS" if abs(observed - expected) <= tolerance else "CONFLICT",
        "series_value": observed,
        "formal_scalar_value": expected,
        "absolute_difference": abs(observed - expected),
    }


def _metric_number(value: Any, aliases: tuple[str, ...]) -> float | None:
    direct = _optional_float(value)
    if direct is not None:
        return direct
    if isinstance(value, Mapping):
        for alias in aliases:
            found = _optional_float(value.get(alias))
            if found is not None:
                return found
    return None


def _module_status(*, produced: bool, invalid: bool = False, conflict: bool = False) -> str:
    if invalid:
        return "invalid_evidence"
    if conflict:
        return "evidence_conflict"
    return "available" if produced else "not_produced"


def _check_conflict(
    checks: list[dict[str, Any]],
    names: set[str],
    *,
    prefixes: tuple[str, ...] = (),
) -> bool:
    return any(
        item.get("status") == "CONFLICT"
        and (
            item.get("check") in names
            or any(str(item.get("check") or "").startswith(prefix) for prefix in prefixes)
        )
        for item in checks
    )


def _has_period_returns(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    return any(
        isinstance(item, Mapping)
        and (item.get("gross_return") is not None or item.get("net_return") is not None)
        for item in value
    )


def _has_substantive_metric(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_has_substantive_metric(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_substantive_metric(child) for child in value)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        return value
    return _optional_float(value) is not None


def _internal_points(
    value: Mapping[str, Any],
) -> list[tuple[date, dict[str, float | None]]]:
    points = value.get("_points")
    return points if isinstance(points, list) else []


def _without_internal(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): child for key, child in value.items() if not str(key).startswith("_")}


def _sample_std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _formal_groups() -> tuple[str, ...]:
    return tuple(
        f"G{index:02d}" for index in range(1, FORMAL_QUANTILE_GROUP_COUNT + 1)
    )


def _validate_formal_groups(groups: list[str]) -> None:
    expected = list(_formal_groups())
    if sorted(groups) != expected:
        raise ValueError(
            f"formal quantile evidence must contain exactly {FORMAL_QUANTILE_GROUP_COUNT} consecutive groups"
        )


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as exc:
        raise ValueError(f"invalid date in formal table: {value!r}") from exc


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _strict_optional_float(value: Any, *, field: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric value for {field}") from exc
    if not math.isfinite(number):
        raise ValueError(f"non-finite numeric value for {field}")
    return number


def _percentile(ordered: list[float], quantile: float) -> float | None:
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _monotonic_direction(values: list[float]) -> str:
    if len(values) < 2:
        return "not_available"
    if all(left <= right for left, right in zip(values, values[1:])):
        return "ascending"
    if all(left >= right for left, right in zip(values, values[1:])):
        return "descending"
    return "non_monotonic"


def _plain_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_copy(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_plain_copy(child) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
