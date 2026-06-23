#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def find_repo_root(path: Path) -> Path:
    for parent in [path.resolve().parent, *path.resolve().parents]:
        if (parent / "factor_factory").is_dir() and (parent / ".git").exists():
            return parent
    raise RuntimeError(f"could not locate factor-factory repo root from {path}")


REPO_ROOT = find_repo_root(Path(__file__))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_workspace import (
    BLOCK_KNOWLEDGE_PROVENANCE_MISSING,
    BLOCK_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT,
    BLOCK_KNOWLEDGE_WRITE_PATH_INVALID,
    BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN,
    assert_path_under_workspace,
    is_repo_root_vault,
    load_workspace_manifest,
    validate_workspace_manifest,
    workspace_manifest_path,
)

DEFAULT_REGISTRY = REPO_ROOT / "data" / "alpha101_registry" / "alpha101_registry.json"
DEFAULT_PROVIDER = Path("/Users/humphrey/.qlib/qlib_data/cn_data")
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "alpha101_qlib_judge"
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge" / "因子工厂"
FACTOR_DIR = KNOWLEDGE_ROOT / "普通因子库"
KB_DIR = KNOWLEDGE_ROOT / "知识库"
ITER_DIR = KNOWLEDGE_ROOT / "研究迭代"
np: Any
pd: Any


def load_workspace(root: Path) -> dict[str, Any]:
    manifest_path = workspace_manifest_path(root)
    if not manifest_path.exists():
        raise SystemExit(f"BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MANIFEST_INVALID: missing {manifest_path}")
    manifest = load_workspace_manifest(manifest_path)
    failures = validate_workspace_manifest(manifest)
    if failures:
        raise SystemExit("\n".join(failures))
    return manifest


def resolve_runtime_roots(args: argparse.Namespace) -> tuple[Path | None, dict[str, Any], Path, Path | None]:
    if not args.workspace_root:
        raise SystemExit(BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN)
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_manifest = load_workspace(workspace_root)
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else workspace_root / "runs" / "alpha101_qlib_batch_judge"
    )
    knowledge_root = (
        Path(args.knowledge_root).expanduser().resolve()
        if args.knowledge_root
        else (workspace_root / "knowledge" / "human_readable" if workspace_root else None)
    )
    if workspace_root:
        assert_path_under_workspace(output_root, workspace_root, label="alpha101_output_root")
        if knowledge_root is not None:
            try:
                assert_path_under_workspace(knowledge_root, workspace_root, label="alpha101_knowledge_root")
            except ValueError as exc:
                if args.skip_writeback:
                    knowledge_root = None
                elif args.export_knowledge_vault:
                    raise SystemExit(BLOCK_KNOWLEDGE_PROVENANCE_MISSING) from exc
                else:
                    raise SystemExit(f"{BLOCK_KNOWLEDGE_WRITE_PATH_INVALID}: {exc}") from exc
    if knowledge_root and is_repo_root_vault(knowledge_root, REPO_ROOT) and not args.export_knowledge_vault:
        raise SystemExit(BLOCK_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT)
    return workspace_root, workspace_manifest, output_root, knowledge_root


@dataclass
class EvalContext:
    warnings: list[str] = field(default_factory=list)
    approximations: list[str] = field(default_factory=list)

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def approx(self, msg: str) -> None:
        if msg not in self.approximations:
            self.approximations.append(msg)


def _window(value: Any) -> int:
    try:
        out = int(round(float(value)))
    except Exception:
        out = 1
    return max(out, 1)


def _sanitize_numeric(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df, pd.DataFrame):
        return df.replace([np.inf, -np.inf], np.nan)
    if isinstance(df, pd.Series):
        return df.replace([np.inf, -np.inf], np.nan)
    return df


def rank(x: pd.DataFrame) -> pd.DataFrame:
    return _sanitize_numeric(x).rank(axis=1, pct=True)


def delay(x: pd.DataFrame, n: float) -> pd.DataFrame:
    return x.shift(_window(n))


def delta(x: pd.DataFrame, n: float) -> pd.DataFrame:
    return x - x.shift(_window(n))


def ts_sum(x: pd.DataFrame, n: float) -> pd.DataFrame:
    return x.rolling(_window(n), min_periods=_window(n)).sum()


def product(x: pd.DataFrame, n: float) -> pd.DataFrame:
    return x.rolling(_window(n), min_periods=_window(n)).apply(np.prod, raw=True)


def stddev(x: pd.DataFrame, n: float) -> pd.DataFrame:
    return x.rolling(_window(n), min_periods=_window(n)).std()


def ts_min(x: pd.DataFrame, n: float) -> pd.DataFrame:
    return x.rolling(_window(n), min_periods=_window(n)).min()


def ts_max(x: pd.DataFrame, n: float) -> pd.DataFrame:
    return x.rolling(_window(n), min_periods=_window(n)).max()


def ts_rank(x: pd.DataFrame, n: float) -> pd.DataFrame:
    w = _window(n)
    return x.rolling(w, min_periods=w).rank(pct=True)


def ts_argmax(x: pd.DataFrame, n: float) -> pd.DataFrame:
    w = _window(n)
    return x.rolling(w, min_periods=w).apply(lambda a: float(np.nanargmax(a) + 1) if np.isfinite(a).any() else np.nan, raw=True)


def ts_argmin(x: pd.DataFrame, n: float) -> pd.DataFrame:
    w = _window(n)
    return x.rolling(w, min_periods=w).apply(lambda a: float(np.nanargmin(a) + 1) if np.isfinite(a).any() else np.nan, raw=True)


def correlation(x: pd.DataFrame, y: pd.DataFrame, n: float) -> pd.DataFrame:
    w = _window(n)
    return x.rolling(w, min_periods=w).corr(y)


def covariance(x: pd.DataFrame, y: pd.DataFrame, n: float) -> pd.DataFrame:
    w = _window(n)
    return x.rolling(w, min_periods=w).cov(y)


def signedpower(x: pd.DataFrame, a: float) -> pd.DataFrame:
    return np.sign(x) * (np.abs(x) ** a)


def sign(x: pd.DataFrame) -> pd.DataFrame:
    return np.sign(x)


def log(x: pd.DataFrame) -> pd.DataFrame:
    return np.log(x.where(x > 0))


def abs_op(x: pd.DataFrame) -> pd.DataFrame:
    return x.abs()


def min_op(x: Any, y: Any) -> Any:
    if isinstance(x, pd.DataFrame) or isinstance(y, pd.DataFrame):
        return pd.DataFrame(np.minimum(x, y), index=x.index, columns=x.columns)
    return min(x, y)


def max_op(x: Any, y: Any) -> Any:
    if isinstance(x, pd.DataFrame) or isinstance(y, pd.DataFrame):
        return pd.DataFrame(np.maximum(x, y), index=x.index, columns=x.columns)
    return max(x, y)


def scale(x: pd.DataFrame, a: float = 1.0) -> pd.DataFrame:
    denom = x.abs().sum(axis=1).replace(0, np.nan)
    return x.div(denom, axis=0) * float(a)


def decay_linear(x: pd.DataFrame, n: float) -> pd.DataFrame:
    w = _window(n)
    weights = np.arange(1, w + 1, dtype="float64")
    denom = weights.sum()
    return x.rolling(w, min_periods=w).apply(lambda a: float(np.dot(a, weights) / denom), raw=True)


def indneutralize(x: pd.DataFrame, _group: Any, ctx: EvalContext | None = None) -> pd.DataFrame:
    if ctx is not None:
        ctx.approx("indneutralize_approximated_by_cross_sectional_demean_no_industry_membership")
    return x.sub(x.mean(axis=1), axis=0)


def where(cond: pd.DataFrame, x: Any, y: Any) -> pd.DataFrame:
    return pd.DataFrame(np.where(cond, x, y), index=cond.index, columns=cond.columns)


def strip_outer_parens(text: str) -> str:
    s = text.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        wraps = True
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    wraps = False
                    break
        if wraps:
            s = s[1:-1].strip()
        else:
            break
    return s


def convert_ternary(expr: str) -> str:
    s = strip_outer_parens(expr)
    depth = 0
    qpos = -1
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "?" and depth == 0:
            qpos = i
            break
    if qpos < 0:
        return s
    depth = 0
    cpos = -1
    for i in range(qpos + 1, len(s)):
        ch = s[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ":" and depth == 0:
            cpos = i
            break
    if cpos < 0:
        raise ValueError(f"malformed ternary expression: {expr}")
    cond = convert_ternary(s[:qpos])
    yes = convert_ternary(s[qpos + 1 : cpos])
    no = convert_ternary(s[cpos + 1 :])
    return f"where(({cond}), ({yes}), ({no}))"


def convert_nested_ternaries(expr: str) -> str:
    s = expr
    while "?" in s:
        qpos = s.find("?")
        stack: list[int] = []
        start = -1
        for i, ch in enumerate(s[:qpos]):
            if ch == "(":
                stack.append(i)
            elif ch == ")" and stack:
                stack.pop()
        if stack:
            start = stack[-1]
            depth = 0
            end = -1
            for i in range(start, len(s)):
                if s[i] == "(":
                    depth += 1
                elif s[i] == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end < 0:
                raise ValueError(f"malformed parenthesized ternary expression: {expr}")
            inner = s[start + 1 : end]
            converted = convert_ternary(inner)
            s = s[:start] + converted + s[end + 1 :]
        else:
            s = convert_ternary(s)
    return s


def convert_formula(formula: str) -> str:
    expr = formula.strip()
    expr = convert_nested_ternaries(expr)
    expr = expr.replace("^", "**")
    expr = expr.replace("||", "|").replace("&&", "&")
    expr = re.sub(r"\bsum\s*\(", "ts_sum(", expr)
    expr = re.sub(r"\babs\s*\(", "abs_op(", expr)
    expr = re.sub(r"\bmin\s*\(", "min_op(", expr)
    expr = re.sub(r"\bmax\s*\(", "max_op(", expr)
    return expr


def load_registry(path: Path, limit: int | None = None, only: set[str] | None = None) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = sorted(payload["records"], key=lambda r: int(r["alpha_no"]))
    if only:
        normalized = {x.lower() for x in only}
        records = [r for r in records if r["factor_id"].lower() in normalized or f"alpha{int(r['alpha_no']):03d}" in normalized]
    if limit:
        records = records[:limit]
    return records


def load_qlib_wide(provider: Path, start: str, end: str, universe_limit: int | None = None) -> dict[str, pd.DataFrame]:
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=str(provider), region="cn")
    inst_file = provider / "instruments" / "all.txt"
    instruments = [line.split("\t")[0] for line in inst_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if universe_limit:
        instruments = instruments[:universe_limit]
    fields = ["$open", "$high", "$low", "$close", "$volume", "$amount"]
    raw = D.features(instruments, fields, start_time=start, end_time=end, freq="day")
    raw.columns = [c[1:] if isinstance(c, str) and c.startswith("$") else str(c).replace("$", "") for c in raw.columns]
    if raw.index.names[0] == "instrument":
        raw = raw.swaplevel().sort_index()
    out: dict[str, pd.DataFrame] = {}
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        wide = raw[col].unstack("instrument").sort_index().astype("float64")
        out[col] = wide.replace([np.inf, -np.inf], np.nan)
    close = out["close"]
    volume = out["volume"]
    amount = out["amount"]
    out["returns"] = close.pct_change(fill_method=None)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["vwap"] = (amount / volume).replace([np.inf, -np.inf], np.nan)
    bad_vwap = out["vwap"].notna().sum().sum() == 0
    if bad_vwap:
        out["vwap"] = (out["open"] + out["high"] + out["low"] + out["close"]) / 4.0
    out["cap"] = close * volume
    for n in [5, 10, 15, 20, 30, 40, 50, 60, 81, 120, 150, 180]:
        out[f"adv{n}"] = volume.rolling(n, min_periods=n).mean()
    return out


def evaluate_formula(formula: str, data: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, EvalContext, str]:
    ctx = EvalContext()
    expr = convert_formula(formula)
    if "IndClass." in expr:
        ctx.approx("IndClass_group_membership_unavailable_in_provider")
    if re.search(r"\bcap\b", expr):
        ctx.approx("cap_approximated_as_close_times_volume")
    env: dict[str, Any] = {
        "__builtins__": {},
        "np": np,
        "pd": pd,
        "rank": rank,
        "delay": delay,
        "delta": delta,
        "ts_sum": ts_sum,
        "stddev": stddev,
        "ts_min": ts_min,
        "ts_max": ts_max,
        "ts_rank": ts_rank,
        "ts_argmax": ts_argmax,
        "ts_argmin": ts_argmin,
        "correlation": correlation,
        "covariance": covariance,
        "product": product,
        "signedpower": signedpower,
        "sign": sign,
        "log": log,
        "abs_op": abs_op,
        "min_op": min_op,
        "max_op": max_op,
        "scale": scale,
        "decay_linear": decay_linear,
        "where": where,
        "indneutralize": lambda x, g: indneutralize(x, g, ctx),
        "IndClass": SimpleNamespace(sector="sector", industry="industry", subindustry="subindustry"),
    }
    env.update(data)
    result = eval(expr, env, {})
    if isinstance(result, (bool, np.bool_)):
        base = data["close"]
        result = pd.DataFrame(float(result), index=base.index, columns=base.columns)
    elif not isinstance(result, pd.DataFrame):
        base = data["close"]
        result = pd.DataFrame(result, index=base.index, columns=base.columns)
    if result.dtypes.apply(lambda x: x == bool).any():
        result = result.astype("float64")
    result = _sanitize_numeric(result.astype("float64"))
    return result, ctx, expr


def date_ic(factor: pd.DataFrame, fwd: pd.DataFrame, method: str) -> pd.Series:
    out: list[tuple[pd.Timestamp, float]] = []
    for dt in factor.index.intersection(fwd.index):
        x = factor.loc[dt]
        y = fwd.loc[dt]
        mask = x.notna() & y.notna()
        if mask.sum() < 20:
            out.append((dt, np.nan))
            continue
        out.append((dt, float(x[mask].corr(y[mask], method=method))))
    return pd.Series(dict(out)).sort_index()


def ir(s: pd.Series) -> float | None:
    clean = s.replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 2 or clean.std() == 0 or np.isnan(clean.std()):
        return None
    return float(clean.mean() / clean.std())


def sign_changes(vals: list[float]) -> int | None:
    clean = [v for v in vals if v is not None and not pd.isna(v)]
    if len(clean) < 3:
        return None
    diffs = np.diff(clean)
    signs = np.sign(diffs[diffs != 0])
    if len(signs) < 2:
        return 0
    return int(np.sum(signs[1:] != signs[:-1]))


def quantile_judge(factor: pd.DataFrame, fwd5: pd.DataFrame, start: str, end: str, step: int = 5) -> dict[str, Any]:
    dates = factor.index[(factor.index >= pd.Timestamp(start)) & (factor.index <= pd.Timestamp(end))]
    dates = dates[::step]
    rows: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    prev_sets: dict[str, set[str]] = {}
    turnovers: list[dict[str, float]] = []
    nav = {f"Q{i}": 1.0 for i in range(1, 11)}
    nav["LS_Q1_Q10"] = 1.0
    for dt in dates:
        x = factor.loc[dt]
        y = fwd5.loc[dt] if dt in fwd5.index else pd.Series(index=x.index, dtype="float64")
        mask = x.notna() & y.notna()
        if mask.sum() < 100:
            continue
        ranks = x[mask].rank(method="first")
        q = pd.qcut(ranks, 10, labels=False, duplicates="drop")
        if q.nunique() < 10:
            continue
        ret_by_q: dict[str, float] = {}
        sets: dict[str, set[str]] = {}
        row = {"datetime": dt.strftime("%Y-%m-%d")}
        for i in range(10):
            members = q.index[q == i]
            key = f"Q{i + 1}"
            sets[key] = set(members)
            val = float(y.loc[members].mean())
            ret_by_q[key] = val
            row[f"{key}_ret_5d"] = val
            nav[key] *= 1.0 + (0.0 if pd.isna(val) else val)
        ls = ret_by_q["Q1"] - ret_by_q["Q10"]
        row["LS_Q1_Q10_ret_5d"] = ls
        nav["LS_Q1_Q10"] *= 1.0 + (0.0 if pd.isna(ls) else ls)
        rows.append(row)
        nav_rows.append({"datetime": row["datetime"], **nav})
        trow: dict[str, float] = {"datetime": row["datetime"]}  # type: ignore[assignment]
        for key in ["Q1", "Q10"]:
            prev = prev_sets.get(key)
            cur = sets[key]
            if prev:
                trow[f"{key}_turnover"] = 1.0 - len(prev & cur) / max(len(cur), 1)
        cur_ls = sets["Q1"] | sets["Q10"]
        prev_ls = prev_sets.get("LS")
        if prev_ls:
            trow["LS_turnover"] = 1.0 - len(prev_ls & cur_ls) / max(len(cur_ls), 1)
        prev_sets = {**sets, "LS": cur_ls}
        turnovers.append(trow)
    ret_df = pd.DataFrame(rows)
    nav_df = pd.DataFrame(nav_rows)
    turn_df = pd.DataFrame(turnovers)
    quantile_means: dict[str, float | None] = {}
    for i in range(1, 11):
        col = f"Q{i}_ret_5d"
        quantile_means[f"Q{i}"] = float(ret_df[col].mean()) if col in ret_df and len(ret_df) else None
    spread = None
    if quantile_means.get("Q1") is not None and quantile_means.get("Q10") is not None:
        spread = float(quantile_means["Q1"] - quantile_means["Q10"])  # type: ignore[operator]
    ls_series = ret_df["LS_Q1_Q10_ret_5d"] if "LS_Q1_Q10_ret_5d" in ret_df else pd.Series(dtype="float64")
    ls_std = ls_series.std()
    sharpe = None if len(ls_series.dropna()) < 2 or not ls_std else float(ls_series.mean() / ls_std * math.sqrt(252 / step))
    return {
        "returns": ret_df,
        "nav": nav_df,
        "turnover": turn_df,
        "summary": {
            "rebalance_points": int(len(ret_df)),
            "quantile_mean_5d": quantile_means,
            "q1_q10_spread_5d": spread,
            "q1_q10_spread_bps_5d": None if spread is None else float(spread * 10000.0),
            "ls_sharpe_annualized": sharpe,
            "monotonicity_sign_changes": sign_changes([quantile_means[f"Q{i}"] for i in range(1, 11)]),
            "q1_turnover_mean": float(turn_df["Q1_turnover"].mean()) if "Q1_turnover" in turn_df else None,
            "q10_turnover_mean": float(turn_df["Q10_turnover"].mean()) if "Q10_turnover" in turn_df else None,
            "ls_turnover_mean": float(turn_df["LS_turnover"].mean()) if "LS_turnover" in turn_df else None,
            "final_nav_q1": float(nav_df["Q1"].iloc[-1]) if "Q1" in nav_df and len(nav_df) else None,
            "final_nav_q10": float(nav_df["Q10"].iloc[-1]) if "Q10" in nav_df and len(nav_df) else None,
            "final_nav_ls": float(nav_df["LS_Q1_Q10"].iloc[-1]) if "LS_Q1_Q10" in nav_df and len(nav_df) else None,
        },
    }


def decide(metrics: dict[str, Any]) -> str:
    oos = metrics.get("oos", {})
    is_ = metrics.get("is", {})
    oos_rankic = oos.get("rank_ic_mean_5d")
    oos_spread = (oos.get("quantile") or {}).get("q1_q10_spread_5d")
    is_rankic = is_.get("rank_ic_mean_5d")
    if oos_rankic is None or oos_spread is None:
        return "blocked"
    if oos_rankic > 0.02 and oos_spread > 0 and (is_rankic or 0) > 0:
        return "iterate"
    if oos_rankic < -0.01 and oos_spread < 0:
        return "reject_or_flip_test"
    return "watch"


def summarize_split(factor: pd.DataFrame, fwd1: pd.DataFrame, fwd5: pd.DataFrame, start: str, end: str) -> dict[str, Any]:
    date_mask = (factor.index >= pd.Timestamp(start)) & (factor.index <= pd.Timestamp(end))
    fac = factor.loc[date_mask]
    coverage = float(fac.notna().sum().sum() / fac.size) if fac.size else None
    active_dates = float((fac.notna().sum(axis=1) >= 100).mean()) if len(fac) else None
    pearson1 = date_ic(factor, fwd1, "pearson").loc[pd.Timestamp(start) : pd.Timestamp(end)]
    rank1 = date_ic(factor, fwd1, "spearman").loc[pd.Timestamp(start) : pd.Timestamp(end)]
    pearson5 = date_ic(factor, fwd5, "pearson").loc[pd.Timestamp(start) : pd.Timestamp(end)]
    rank5 = date_ic(factor, fwd5, "spearman").loc[pd.Timestamp(start) : pd.Timestamp(end)]
    q = quantile_judge(factor, fwd5, start, end, step=5)
    return {
        "start": start,
        "end": end,
        "coverage": coverage,
        "active_dates": active_dates,
        "pearson_ic_mean_1d": float(pearson1.mean()) if len(pearson1.dropna()) else None,
        "rank_ic_mean_1d": float(rank1.mean()) if len(rank1.dropna()) else None,
        "rank_ic_ir_1d": ir(rank1),
        "pearson_ic_mean_5d": float(pearson5.mean()) if len(pearson5.dropna()) else None,
        "rank_ic_mean_5d": float(rank5.mean()) if len(rank5.dropna()) else None,
        "rank_ic_ir_5d": ir(rank5),
        "ic_obs_5d": int(rank5.dropna().shape[0]),
        "quantile": q["summary"],
        "_frames": q,
    }


def write_csv_frames(out_dir: Path, split: str, frames: dict[str, Any]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for key in ["returns", "nav", "turnover"]:
        df = frames[key]
        path = out_dir / f"{split}_{key}.csv"
        df.to_csv(path, index=False)
        paths[f"{split}_{key}_csv"] = str(path)
    return paths


def fmt(v: Any, digits: int = 6) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "NA"
    if isinstance(v, float):
        return f"{v:.{digits}g}"
    return str(v)


def write_factor_records(record: dict[str, Any], metrics: dict[str, Any], artifacts: dict[str, str], run_id: str) -> dict[str, str]:
    factor_id = record["factor_id"]
    alpha_no = int(record["alpha_no"])
    report_id = f"ALPHA{alpha_no:03d}_QLIB_ONLY_20160101_20250711"
    decision = metrics["decision"]
    approx = metrics.get("approximations") or []
    warnings = metrics.get("warnings") or []
    formula = record["formula"]
    is_m = metrics["is"]
    oos_m = metrics["oos"]
    factor_md = FACTOR_DIR / f"{report_id}.md"
    kb_md = KB_DIR / f"{report_id}.md"
    iter_md = ITER_DIR / f"{report_id}.md"
    for p in [FACTOR_DIR, KB_DIR, ITER_DIR]:
        p.mkdir(parents=True, exist_ok=True)
    core_lines = [
        f"- source: `101 Formulaic Alphas`",
        f"- formula: `{formula}`",
        f"- qlib_provider: `{metrics['provider_uri']}`",
        f"- run_id: `{run_id}`",
        f"- approximation_flags: `{', '.join(approx) if approx else 'none'}`",
        f"- warnings: `{', '.join(warnings) if warnings else 'none'}`",
        "",
        "## Headline Metrics",
        f"- IS RankIC 1d: `{fmt(is_m.get('rank_ic_mean_1d'))}`",
        f"- IS RankIC IR 1d: `{fmt(is_m.get('rank_ic_ir_1d'))}`",
        f"- IS RankIC 5d: `{fmt(is_m.get('rank_ic_mean_5d'))}`",
        f"- IS RankIC IR 5d: `{fmt(is_m.get('rank_ic_ir_5d'))}`",
        f"- IS Q1-Q10 spread 5d bps: `{fmt((is_m.get('quantile') or {}).get('q1_q10_spread_bps_5d'))}`",
        f"- IS LS Sharpe annualized: `{fmt((is_m.get('quantile') or {}).get('ls_sharpe_annualized'))}`",
        f"- IS LS turnover mean: `{fmt((is_m.get('quantile') or {}).get('ls_turnover_mean'))}`",
        f"- OOS RankIC 1d: `{fmt(oos_m.get('rank_ic_mean_1d'))}`",
        f"- OOS RankIC IR 1d: `{fmt(oos_m.get('rank_ic_ir_1d'))}`",
        f"- OOS RankIC 5d: `{fmt(oos_m.get('rank_ic_mean_5d'))}`",
        f"- OOS RankIC IR 5d: `{fmt(oos_m.get('rank_ic_ir_5d'))}`",
        f"- OOS Q1-Q10 spread 5d bps: `{fmt((oos_m.get('quantile') or {}).get('q1_q10_spread_bps_5d'))}`",
        f"- OOS LS Sharpe annualized: `{fmt((oos_m.get('quantile') or {}).get('ls_sharpe_annualized'))}`",
        f"- OOS LS turnover mean: `{fmt((oos_m.get('quantile') or {}).get('ls_turnover_mean'))}`",
        "",
        "## Judge Protocol",
        "- mode: `qlib_only_partial_component`",
        "- RD-Agent: `not_used`",
        "- horizon: `1d IC and 5d IC / 5-trading-day non-overlap quantile NAV`",
        "- split: `IS 2016-01-01 to 2025-07-11; OOS 2025-07-12 to provider latest`",
        "- quantile direction: `Q1 minus Q10 is reported without automatic sign flip`",
        "",
        "## Artifacts",
    ]
    for key, path in sorted(artifacts.items()):
        core_lines.append(f"- `{key}`: `{path}`")
    factor_text = "\n".join([
        "---",
        f'report_id: "{report_id}"',
        f'factor_id: "{factor_id}"',
        f'decision: "{decision}"',
        'run_status: "success"',
        'final_status: "qlib_only_judged"',
        "tags:",
        '  - "factor"',
        '  - "library_all"',
        '  - "alpha101"',
        '  - "qlib_only"',
        "---",
        "",
        f"# {factor_id} ({report_id})",
        "",
        f"- decision: `{decision}`",
        "",
        *core_lines,
        "",
        "## Interpretation",
        "- This record is a controlled Qlib judge result, not a native RD-Agent research result.",
        "- Treat positive IC with weak LS/NAV as a ranking-only signal until portfolio construction confirms monetization.",
        "- OOS evidence with fewer than 60 rebalance points is preliminary.",
        "",
        "## Links",
        f"- [[知识库/{report_id}|Knowledge Record]]",
        f"- [[研究迭代/{report_id}|Research Iteration]]",
        "",
    ])
    knowledge_text = "\n".join([
        "---",
        f'report_id: "{report_id}"',
        f'factor_id: "{factor_id}"',
        f'decision: "{decision}"',
        "tags:",
        '  - "knowledge"',
        '  - "alpha101"',
        '  - "qlib_only"',
        "---",
        "",
        f"# Knowledge Record: {factor_id} ({report_id})",
        "",
        *core_lines,
        "",
        "## Durable Lessons",
        "- Alpha101 formula evidence should be separated into raw ranking strength, quantile monotonicity, LS monetization, and turnover cost risk.",
        "- Industry-neutralized formulas are approximate unless the provider exposes stable industry membership.",
        "- A factor can have usable RankIC while still failing LS implementation.",
        "",
        "## Links",
        f"- [[普通因子库/{report_id}|Factor Record]]",
        f"- [[研究迭代/{report_id}|Research Iteration]]",
        "",
    ])
    iter_text = "\n".join([
        "---",
        f'report_id: "{report_id}"',
        f'factor_id: "{factor_id}"',
        f'decision: "{decision}"',
        "iteration_no: 1",
        "tags:",
        '  - "iteration"',
        '  - "alpha101"',
        '  - "qlib_only"',
        "---",
        "",
        f"# Research Iteration: {factor_id} ({report_id})",
        "",
        *core_lines,
        "",
        "## Next Actions",
        "- If IS and OOS quantile evidence agree, rerun with cost model and tradability filters.",
        "- If RankIC and LS disagree, test sign, rank-only construction, and liquidity buckets before promotion.",
        "- If approximation flags are present, rerun after adding the missing source field or industry membership.",
        "",
        "## Links",
        f"- [[普通因子库/{report_id}|Factor Record]]",
        f"- [[知识库/{report_id}|Knowledge Record]]",
        "",
    ])
    factor_md.write_text(factor_text, encoding="utf-8")
    kb_md.write_text(knowledge_text, encoding="utf-8")
    iter_md.write_text(iter_text, encoding="utf-8")
    return {"factor_record": str(factor_md), "knowledge_record": str(kb_md), "iteration_record": str(iter_md)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Pure Qlib/pandas Alpha101 batch judge with factor-library writeback.")
    parser.add_argument("--workspace-root")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--provider", type=Path, default=DEFAULT_PROVIDER)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--knowledge-root", type=Path)
    parser.add_argument("--export-knowledge-vault", action="store_true")
    parser.add_argument("--start", default="2010-01-04")
    parser.add_argument("--is-start", default="2016-01-01")
    parser.add_argument("--is-end", default="2025-07-11")
    parser.add_argument("--oos-start", default="2025-07-12")
    parser.add_argument("--end", default=None)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--universe-limit", type=int)
    parser.add_argument("--skip-writeback", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace_root, workspace_manifest, output_root, knowledge_root = resolve_runtime_roots(args)
    global KNOWLEDGE_ROOT, FACTOR_DIR, KB_DIR, ITER_DIR, np, pd
    if knowledge_root is not None:
        KNOWLEDGE_ROOT = knowledge_root
        FACTOR_DIR = KNOWLEDGE_ROOT / "普通因子库"
        KB_DIR = KNOWLEDGE_ROOT / "知识库"
        ITER_DIR = KNOWLEDGE_ROOT / "研究迭代"
    if args.dry_run:
        print(json.dumps({
            "event": "alpha101_qlib_batch_guard_pass",
            "workspace_root": str(workspace_root) if workspace_root else None,
            "factor_id": workspace_manifest.get("factor_id"),
            "research_id": workspace_manifest.get("research_id"),
            "output_root": str(output_root),
            "knowledge_root": str(knowledge_root) if knowledge_root else None,
            "production_research_started": False,
        }, ensure_ascii=False, sort_keys=True))
        return

    import numpy as np_module
    import pandas as pd_module

    np = np_module
    pd = pd_module

    provider = args.provider.expanduser().resolve()
    if not provider.exists():
        raise SystemExit(f"missing qlib provider: {provider}")
    calendar_path = provider / "calendars" / "day.txt"
    calendar = calendar_path.read_text(encoding="utf-8").splitlines()
    provider_end = calendar[-1]
    end = args.end or provider_end
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = output_root / run_id
    out_root.mkdir(parents=True, exist_ok=True)
    records = load_registry(args.registry, limit=args.limit, only=set(args.only or []))
    print(json.dumps({
        "event": "alpha101_qlib_batch_start",
        "records": len(records),
        "provider": str(provider),
        "start": args.start,
        "end": end,
        "is": [args.is_start, args.is_end],
        "oos": [args.oos_start, end],
        "run_id": run_id,
        "rdagent": "not_used",
    }, ensure_ascii=False), flush=True)

    data = load_qlib_wide(provider, args.start, end, universe_limit=args.universe_limit)
    close = data["close"]
    fwd1 = close.shift(-1) / close - 1.0
    fwd5 = close.shift(-5) / close - 1.0
    summary_rows: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "mode": "qlib_only_partial_component",
        "rdagent": "not_used",
        "provider_uri": str(provider),
        "provider_calendar_start": calendar[0],
        "provider_calendar_end": provider_end,
        "is_window": [args.is_start, args.is_end],
        "oos_window": [args.oos_start, end],
        "records": [],
    }
    for idx, record in enumerate(records, 1):
        alpha_no = int(record["alpha_no"])
        factor_id = record["factor_id"]
        t0 = time.time()
        factor_dir = out_root / f"ALPHA{alpha_no:03d}_{factor_id}"
        factor_dir.mkdir(parents=True, exist_ok=True)
        print(json.dumps({"event": "factor_start", "idx": idx, "total": len(records), "factor_id": factor_id}, ensure_ascii=False), flush=True)
        try:
            factor, ctx, converted_expr = evaluate_formula(record["formula"], data)
            is_summary = summarize_split(factor, fwd1, fwd5, args.is_start, args.is_end)
            oos_summary = summarize_split(factor, fwd1, fwd5, args.oos_start, end)
            artifacts: dict[str, str] = {}
            artifacts.update(write_csv_frames(factor_dir, "is", is_summary.pop("_frames")))
            artifacts.update(write_csv_frames(factor_dir, "oos", oos_summary.pop("_frames")))
            metrics = {
                "factor_id": factor_id,
                "alpha_no": alpha_no,
                "formula": record["formula"],
                "converted_expression": converted_expr,
                "provider_uri": str(provider),
                "is": is_summary,
                "oos": oos_summary,
                "warnings": ctx.warnings,
                "approximations": ctx.approximations,
            }
            metrics["decision"] = decide(metrics)
            metrics_path = factor_dir / "metrics.json"
            metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            artifacts["metrics_json"] = str(metrics_path)
            if not args.skip_writeback:
                artifacts.update(write_factor_records(record, metrics, artifacts, run_id))
            row = {
                "alpha_no": alpha_no,
                "factor_id": factor_id,
                "status": "success",
                "decision": metrics["decision"],
                "is_rank_ic_mean_1d": is_summary.get("rank_ic_mean_1d"),
                "is_rank_ic_ir_1d": is_summary.get("rank_ic_ir_1d"),
                "is_rank_ic_mean_5d": is_summary.get("rank_ic_mean_5d"),
                "is_rank_ic_ir_5d": is_summary.get("rank_ic_ir_5d"),
                "is_q1_q10_spread_bps_5d": (is_summary.get("quantile") or {}).get("q1_q10_spread_bps_5d"),
                "is_ls_sharpe": (is_summary.get("quantile") or {}).get("ls_sharpe_annualized"),
                "is_ls_turnover": (is_summary.get("quantile") or {}).get("ls_turnover_mean"),
                "oos_rank_ic_mean_1d": oos_summary.get("rank_ic_mean_1d"),
                "oos_rank_ic_ir_1d": oos_summary.get("rank_ic_ir_1d"),
                "oos_rank_ic_mean_5d": oos_summary.get("rank_ic_mean_5d"),
                "oos_rank_ic_ir_5d": oos_summary.get("rank_ic_ir_5d"),
                "oos_q1_q10_spread_bps_5d": (oos_summary.get("quantile") or {}).get("q1_q10_spread_bps_5d"),
                "oos_ls_sharpe": (oos_summary.get("quantile") or {}).get("ls_sharpe_annualized"),
                "oos_ls_turnover": (oos_summary.get("quantile") or {}).get("ls_turnover_mean"),
                "approximations": ";".join(ctx.approximations),
                "elapsed_sec": round(time.time() - t0, 3),
                "metrics_json": str(metrics_path),
            }
        except Exception as exc:
            err_path = factor_dir / "error.txt"
            err_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
            row = {
                "alpha_no": alpha_no,
                "factor_id": factor_id,
                "status": "failed",
                "decision": "blocked",
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_sec": round(time.time() - t0, 3),
                "error_txt": str(err_path),
            }
            print(json.dumps({"event": "factor_failed", **row}, ensure_ascii=False), flush=True)
        summary_rows.append(row)
        manifest["records"].append(row)
        pd.DataFrame(summary_rows).to_csv(out_root / "alpha101_qlib_batch_summary.csv", index=False)
        (out_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"event": "factor_done", **row}, ensure_ascii=False), flush=True)
    summary_df = pd.DataFrame(summary_rows)
    summary_json = out_root / "alpha101_qlib_batch_summary.json"
    summary_json.write_text(json.dumps(summary_rows, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "event": "alpha101_qlib_batch_done",
        "run_id": run_id,
        "output_root": str(out_root),
        "summary_csv": str(out_root / "alpha101_qlib_batch_summary.csv"),
        "summary_json": str(summary_json),
        "success": int((summary_df["status"] == "success").sum()) if len(summary_df) else 0,
        "failed": int((summary_df["status"] == "failed").sum()) if len(summary_df) else 0,
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
