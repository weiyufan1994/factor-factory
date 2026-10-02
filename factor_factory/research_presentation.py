"""Human-readable, offline presentation of code and already computed results.

This module does not compute a second set of metrics or certify research. It
renders the same frames/results supplied by the common research API, with no
network resources or JavaScript. Annotated source remains copyable as plain text.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
import json
from pathlib import Path
from typing import Any

import pandas as pd


def write_factor_review(
    path: str | Path, *, factor_values: pd.DataFrame, source_code: str,
    metrics: Mapping[str, Any], command: str, title: str = "Factor code review",
    selected_dates: Sequence[str] = (), input_sample: pd.DataFrame | None = None,
    sample_rows: int = 5, notes: str = "",
) -> Path:
    """Render annotated source, factor head/tail/date slices, metrics and scope.

    ``metrics`` is an evaluate_factor result, not a caller-written score summary.
    Callers must pass the source actually executed (including local helpers) and
    archive the full factor table separately. A preview does not prove causality.
    """
    from .research_api import normalize_factor_frame

    if not isinstance(sample_rows, int) or isinstance(sample_rows, bool) or not 1 <= sample_rows <= 100:
        raise ValueError("sample_rows must be an integer in [1, 100]")
    frame = normalize_factor_frame(factor_values)
    table = frame.reset_index()

    def table_html(value: pd.DataFrame) -> str:
        return value.to_html(index=False, escape=True, na_rep="NaN", float_format=lambda x: f"{x:.10g}")

    source_lines = "\n".join(
        f'<span class="line"><span class="number">{number:03d}</span>'
        f'<span class="{"comment" if line.lstrip().startswith("#") else "code"}">{escape(line)}</span></span>'
        for number, line in enumerate(source_code.splitlines(), 1)
    )
    slices = []
    for day in selected_dates:
        timestamp = pd.Timestamp(day)
        selected = table.loc[table["datetime"] == timestamp]
        slices.append(
            f"<h3>{escape(timestamp.isoformat())} — {len(selected)} rows</h3>"
            + table_html(selected.head(sample_rows))
            + (f"<p>展示前 {sample_rows} 行；完整表见 factor_values 文件。</p>" if len(selected) > sample_rows else "")
        )
    metric_rows = [
        {"metric": name, **dict(metric)}
        for name, metric in metrics.get("metrics", {}).items()
    ]
    period_table = pd.DataFrame(metrics.get("periods", []))
    scope = {key: metrics.get(key) for key in (
        "api_version", "analysis", "status", "reason", "evaluation_scope", "account_simulation",
    )}
    # Show limitations alongside the score, including caller-supplied timing.
    # Keep the large per-date coverage table bounded, without hiding its count.
    context = {key: metrics[key] for key in (
        "warnings", "label_timing", "alignment", "inference", "model", "valuation",
    ) if key in metrics}
    coverage = dict(metrics.get("coverage") or {})
    coverage_dates = coverage.pop("by_date", [])
    context["coverage"] = {**coverage, "by_date_row_count": len(coverage_dates)}
    context_html = escape(json.dumps(context, ensure_ascii=False, indent=2, allow_nan=False))
    overview = pd.DataFrame([{
        "rows": len(frame), "instruments": frame.index.get_level_values("instrument").nunique(),
        "dates": frame.index.get_level_values("datetime").nunique(),
        "missing_values": int(frame.factor_value.isna().sum()),
        "dtype": str(frame.factor_value.dtype),
    }])
    content = f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
body{{font:15px/1.6 system-ui,sans-serif;max-width:1280px;margin:32px auto;padding:0 24px;color:#182734;background:#f6f8fb}}
h1,h2,h3{{line-height:1.3}} section{{background:white;border:1px solid #dbe3ed;border-radius:8px;padding:20px;margin:18px 0;overflow:auto}}
table{{border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:13px}} th,td{{border-bottom:1px solid #dbe3ed;padding:6px 12px;text-align:right;white-space:nowrap}}
th{{background:#eaf0f8}} pre{{white-space:pre;overflow:auto;font:13px/1.65 ui-monospace,monospace}}
.line{{display:block;min-height:1.65em}} .number{{display:inline-block;width:3.7em;color:#8792a1;user-select:none}} .comment{{color:#137345}}
.note{{border-left:4px solid #1f5a92;padding:10px 16px;background:#eaf2fc}} code{{font-family:ui-monospace,monospace}}
</style>
<h1>{escape(title)}</h1>
<p class="note">{escape(notes)}</p>
<section><h2>1. Reproduce without an AI</h2><pre>{escape(command)}</pre>
<p>源代码与输入可独立查看和重跑；表格来自传入的实际结果，不是手填效果说明。预览不替代完整文件或代码审查。</p></section>
<section><h2>2. Annotated source — complete supplied source</h2><pre>{source_lines}</pre></section>
<section><h2>3. Input sample</h2>{table_html(input_sample) if input_sample is not None else '<p>未提供输入切片。</p>'}</section>
<section><h2>4. Factor values — datetime / instrument / factor_value</h2>{table_html(overview)}
<h3>head({sample_rows})</h3>{table_html(table.head(sample_rows))}
<h3>tail({sample_rows})</h3>{table_html(table.tail(sample_rows))}
<h3>Specified date slices</h3>{''.join(slices) or '<p>未选择日期。</p>'}</section>
<section><h2>5. Analysis scope and metrics</h2>{table_html(pd.DataFrame([scope]))}
{table_html(pd.DataFrame(metric_rows)) if metric_rows else '<p>无可计算指标；查看 status/reason。</p>'}
<h3>Timing, alignment, coverage and warnings</h3><pre>{context_html}</pre>
{table_html(pd.DataFrame(coverage_dates).head(20)) if coverage_dates else ''}
<h3>Per-period rows (first 20)</h3>{table_html(period_table.head(20)) if not period_table.empty else '<p>无逐期结果。</p>'}</section>
<p>数据缺失、代码正确性、经济有效性是不同问题。此页不将 IC 或事件平均收益称为可交易净收益。</p>
</html>'''
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target
