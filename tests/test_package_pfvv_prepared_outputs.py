"""Synthetic tests for the local PF/VV prepared-output packager."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/package_pfvv_prepared_outputs.py"
spec = importlib.util.spec_from_file_location("package_pfvv_prepared_outputs_test", MODULE)
packager = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(packager)


def _run(tmp_path: Path, *, status="COMPLETE", bad_hash=False, traversal=False) -> Path:
    root = tmp_path / "run"
    daily = root / "daily_measurements"
    daily.mkdir(parents=True)
    dates = ["20160104", "20160105"]
    rows = []
    for day in dates:
        path = daily / f"daily_{day}.parquet"
        execution = daily / f"execution_{day}.parquet"
        pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": [day], "pf_daily": [1.0], "vv_daily": [2.0]}).to_parquet(path, index=False)
        pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": [day], "execution_price_status": ["AVAILABLE"]}).to_parquet(execution, index=False)
        rows.append({"trade_date": day, "path": "../escape.parquet" if traversal else path.name,
                     "execution_path": execution.name, "output_sha256": "0" * 64 if bad_hash else hashlib.sha256(path.read_bytes()).hexdigest(),
                     "execution_sha256": hashlib.sha256(execution.read_bytes()).hexdigest()})
    plan = {"version": "pfvv_daily_source_plan_v1", "research_id": "synthetic", "trading_calendar": dates}
    manifest = {"version": "pfvv_daily_measurements_manifest_v1", "status": "COMPLETE", "research_id": "synthetic", "trading_calendar": dates, "days": rows}
    (root / "source_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (root / "execution_summary.json").write_text(json.dumps({"status": status, "returncode": 0}), encoding="utf-8")
    (root / "progress.log").write_text("synthetic\n", encoding="utf-8")
    (daily / "source_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (daily / "daily_measurements_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_completed_run_is_streamed_and_create_only(tmp_path: Path):
    root = _run(tmp_path)
    result = packager.package_pfvv_prepared_outputs(root, tmp_path / "prepared.tar.gz")
    assert result["calendar_days"] == 2 and result["sha256"]
    with pytest.raises(packager.PackageError, match="output_file"):
        packager.package_pfvv_prepared_outputs(root, tmp_path / "prepared.tar.gz")


@pytest.mark.parametrize("kwargs, error", [({"status": "FAILED"}, "execution_summary_not_complete"), ({"bad_hash": True}, "hash_mismatch"), ({"traversal": True}, "name_invalid")])
def test_invalid_run_fails_closed(tmp_path: Path, kwargs: dict, error: str):
    root = _run(tmp_path, **kwargs)
    with pytest.raises(packager.PackageError, match=error):
        packager.package_pfvv_prepared_outputs(root, tmp_path / "prepared.tar.gz")


def test_partial_is_retained_when_publication_loses_create_only_race(tmp_path: Path, monkeypatch):
    root = _run(tmp_path)
    output = tmp_path / "prepared.tar.gz"
    partial = Path(str(output) + ".partial")
    original_link = packager.os.link
    def fail_link(source, target):
        partial.write_bytes(Path(source).read_bytes())
        raise FileExistsError("synthetic race")
    monkeypatch.setattr(packager.os, "link", fail_link)
    with pytest.raises(FileExistsError):
        packager.package_pfvv_prepared_outputs(root, output)
    assert partial.is_file()
    monkeypatch.setattr(packager.os, "link", original_link)


def test_inner_plan_and_calendar_identity_are_required(tmp_path: Path):
    root = _run(tmp_path)
    inner = root / "daily_measurements" / "source_plan.json"
    inner.write_text(json.dumps({"version": "pfvv_daily_source_plan_v1", "research_id": "other", "trading_calendar": ["20160104", "20160105"]}), encoding="utf-8")
    with pytest.raises(packager.PackageError, match="source_plan_content_mismatch"):
        packager.package_pfvv_prepared_outputs(root, tmp_path / "mismatch.tar.gz")
