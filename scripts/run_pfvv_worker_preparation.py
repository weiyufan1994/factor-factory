"""Stage this exact PF/VV preparation code on the dedicated research worker.

No shared data, checkout, catalog or existing run is changed. No credentials
are transported. The worker reads only the explicitly listed IS minute days.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zlib
import uuid

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples/mszq_intraday_momentum_pulse"
INSTANCE = "i-02cc0b6e93856fbb4"
REGION = "ap-southeast-1"
REMOTE_PARENT = "/opt/factorforge/research-runs"
FILES = ["pfvv_source_baseline_v1.py", "pfvv_source_baseline_dataframe_adapter_v1.py",
    "pfvv_source_baseline_partitioned_v1.py", "pfvv_daily_measurements_v1.py", "pfvv_reconstruction.json"]


def write_new(path, payload):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calendar", required=True)
    parser.add_argument("--factor-workspace", required=True)
    parser.add_argument("--research-id", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--catalog-sha256", required=True)
    parser.add_argument("--data-api-root", default=str(REPO.parent / 'factorforge-data-api'))
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--memory-budget-mb", type=int, default=2048)
    parser.add_argument("--bundle-uri", required=True,
        help="Explicit S3 URI where this exact code bundle will be staged separately; this tool never uploads it")
    args = parser.parse_args()
    if not args.bundle_uri.startswith('s3://') or args.bundle_uri.endswith('/'):
        raise ValueError('explicit_bundle_object_uri_required')
    workspace = Path(args.factor_workspace).resolve(strict=True)
    if REPO / "factor_research" not in workspace.parents:
        raise ValueError("workspace_must_be_under_selected_research_checkout")
    cal = pd.read_parquet(args.calendar)
    if set(cal.columns) != {"trade_date", "is_open"} or not cal.is_open.astype(str).isin(["True", "1"]).all():
        raise ValueError("explicit_open_calendar_required")
    dates = cal.trade_date.astype(str).tolist()
    if not dates or dates[0] < "20160104" or dates[-1] > "20250711" or dates != sorted(set(dates)):
        raise ValueError("explicit_unique_IS_calendar_required")
    plan = {"version": "pfvv_daily_source_plan_v1", "research_id": args.research_id,
        "trading_calendar": dates, "source_bucket": "yufan-data-lake",
        "source_prefix": "tushares/分钟数据/raw/stk_mins_1min/"}
    tag = "pfvv_source_daily_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + '_' + uuid.uuid4().hex[:8]
    control = workspace / "diagnostics" / tag
    control.mkdir(parents=True, exist_ok=False)
    remote = REMOTE_PARENT + "/" + tag
    sources = {}
    for name in FILES:
        path = EXAMPLES / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("code_source_not_regular")
        raw = path.read_bytes()
        sources[name] = {"sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "base64": base64.b64encode(raw).decode()}
    sdk_root = Path(args.data_api_root).resolve() / 'factorforge_data_api'
    additions = [(REPO/'factor_factory/__init__.py', 'factor_factory/__init__.py'),
        (REPO/'factor_factory/pfvv_preparation.py', 'factor_factory/pfvv_preparation.py')]
    additions += [(p, 'factorforge_data_api/' + str(p.relative_to(sdk_root)))
        for p in [*sdk_root.glob('*.py'), *sdk_root.glob('backends/*.py')]]
    catalog_bytes = Path(args.catalog).read_bytes()
    if hashlib.sha256(catalog_bytes).hexdigest() != args.catalog_sha256:
        raise ValueError('catalog_hash_mismatch_before_worker_bundle')
    additions.append((Path(args.catalog), 'data_catalog.json'))
    for path, name in additions:
        raw = path.read_bytes()
        sources[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                         'base64': base64.b64encode(raw).decode()}
    bundle_bytes = zlib.compress(json.dumps({"sources": sources, "plan": plan}).encode())
    bundle_sha256 = hashlib.sha256(bundle_bytes).hexdigest()
    bundle_path = control / 'source_bundle.json.zlib'
    with bundle_path.open('xb') as stream:
        stream.write(bundle_bytes)
    code = f'''import base64,hashlib,json,os,pathlib,shutil,subprocess,zlib
root=pathlib.Path({remote!r});parent=root.parent
assert str(parent)=={REMOTE_PARENT!r} and parent.is_dir() and parent.resolve()==parent
assert shutil.disk_usage(parent).free > 6*1024**3
assert root.name.startswith('pfvv_source_daily_')
root.mkdir(exist_ok=False)
src=root/'src';src.mkdir()
package=root/'source_bundle.json.zlib'
subprocess.run(['aws','s3','cp',{args.bundle_uri!r},str(package),'--only-show-errors'],check=True,timeout=120)
raw_bundle=package.read_bytes()
assert len(raw_bundle)=={len(bundle_bytes)} and hashlib.sha256(raw_bundle).hexdigest()=={bundle_sha256!r}
bundle=json.loads(zlib.decompress(raw_bundle))
for name,item in bundle['sources'].items():
 assert not pathlib.Path(name).is_absolute() and '..' not in pathlib.Path(name).parts and name in {list(sources)!r}
 raw=base64.b64decode(item['base64']);assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256']
 (src/name).parent.mkdir(parents=True,exist_ok=True)
 with (src/name).open('xb') as stream:stream.write(raw)
plan=root/'source_plan.json'
with plan.open('x') as stream:json.dump(bundle['plan'],stream)
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONPATH=str(src))
with (root/'progress.log').open('x') as log:
 result=subprocess.run(['/usr/bin/time','-v','/usr/bin/python3',str(src/'pfvv_daily_measurements_v1.py'),'--source-plan',str(plan),'--output-root',str(root/'daily_measurements'),'--catalog',str(src/'data_catalog.json'),'--catalog-sha256',{args.catalog_sha256!r},'--workers',{str(args.workers)!r},'--memory-budget-mb',{str(args.memory_budget_mb)!r},'--cache-root',str(root/'cache')],env=env,stdout=log,stderr=subprocess.STDOUT)
summary={{'status':'COMPLETE' if result.returncode==0 else 'FAILED_PRESERVE_PARTIAL','returncode':result.returncode,'remote_root':str(root),'factor_returns_evaluated':False,'oos_accessed':False}}
with (root/'execution_summary.json').open('x') as stream:json.dump(summary,stream)
print(json.dumps(summary));raise SystemExit(result.returncode)
'''
    command = "/usr/bin/python3 - <<'PFVV_WORKER'\n" + code + "\nPFVV_WORKER"
    parameters = {"commands": [command], "executionTimeout": ["43200"]}
    if len(json.dumps(parameters).encode()) > 60000:
        raise ValueError("transport_payload_budget")
    write_new(control / "source_plan.json", plan)
    write_new(control / "command_parameters.json", parameters)
    write_new(control / "run_location.json", {"instance_id": INSTANCE, "region": REGION,
        "remote_root": remote, "calendar_days": len(dates), "research_id": args.research_id,
        "sources": {n: {k: v[k] for k in ["sha256", "bytes"]} for n, v in sources.items()},
        "bundle": {"local_path": str(bundle_path), "planned_uri": args.bundle_uri,
            "sha256": bundle_sha256, "bytes": len(bundle_bytes), "uploaded_by_this_tool": False},
        "auto_retry": False, "catalog_write": False, "oos_accessed": False})
    if not args.execute:
        print(json.dumps({"prepared_only": True, "control": str(control), "bundle_path": str(bundle_path),
            "bundle_uri": args.bundle_uri, "bundle_sha256": bundle_sha256,
            "dispatch_requires_exact_bundle_staged_separately": True})); return
    response = subprocess.run(["aws", "ssm", "send-command", "--region", REGION,
        "--instance-ids", INSTANCE, "--document-name", "AWS-RunShellScript",
        "--comment", "PFVV explicit IS daily measurements and execution prices; no returns or OOS",
        "--parameters", "file://" + str(control / "command_parameters.json"),
        "--query", "Command.CommandId", "--output", "text", "--cli-connect-timeout", "15", "--cli-read-timeout", "30"],
        env={**os.environ, "AWS_MAX_ATTEMPTS": "1"}, capture_output=True, text=True)
    write_new(control / "dispatch.json", {"returncode": response.returncode,
        "command_id": response.stdout.strip() if response.returncode == 0 else None,
        "stderr": response.stderr})
    if response.returncode:
        raise RuntimeError("dispatch_failed_no_automatic_retry")
    print(json.dumps({"control": str(control), "command_id": response.stdout.strip(), "remote_root": remote}))


if __name__ == "__main__":
    main()
