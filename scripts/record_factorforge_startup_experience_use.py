#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factor_factory.startup_experience import record_use

def main():
    p=argparse.ArgumentParser(description="Record author decisions on default startup method advice; never executes markets")
    p.add_argument('--factor-workspace',type=Path,required=True)
    p.add_argument('--report-id',required=True)
    p.add_argument('--response-json',type=Path,required=True)
    a=p.parse_args()
    try:
        result=record_use(a.factor_workspace,a.report_id,json.loads(a.response_json.read_text()))
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print('BLOCK_STARTUP_EXPERIENCE_USE: '+str(exc),file=sys.stderr)
        return 2
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__':
    raise SystemExit(main())
