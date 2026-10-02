#!/usr/bin/env python3
from __future__ import annotations
from dataclasses import asdict
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.hybrid_research.gp_adapter import evaluate_program, run_response_gp
from factor_factory.hybrid_research.synthetic import hidden_recovery_mse, make_synthetic_response
from factor_factory.hybrid_research.variation import DerivationScope

def main() -> None:
    scope=DerivationScope("demo:response-v1","causal kernels","finite signed impulses","zero","event","missing is not zero","signed J to y",("causal convolution","linear superposition"),("temporary response decays","two scales separate fast and slow response"),"number of response scales unknown",("transient_exponential_kernel","permanent_component","two_scale_superposition"),("parameter_search","structure_search"))
    fit,truth=make_synthetic_response(seed=20260927,length=24)
    result=run_response_gp(scope=scope,fit_data=fit,allowed_rates=(0.,.2,.5,1.),allowed_scales=(.3,.7,1.),seed=6,generations=2,population_size=6)
    payload=asdict(result)
    payload["hidden_evaluation"]={"model_label":truth.model_label,"recovery_mse":hidden_recovery_mse(evaluate_program(result.selected.program,fit),truth) if result.selected else None}
    print(json.dumps(payload,indent=2,sort_keys=True))
if __name__=="__main__": main()
