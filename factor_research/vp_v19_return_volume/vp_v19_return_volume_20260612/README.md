# VP V19 Return-Volume Research Workspace

This workspace contains research-side artifacts for the VP V19 return-volume
covariation line.

It includes:

- `scripts/`: V19 evaluator and worker/materialization scripts;
- `data_helpers/`: local minute-bar sync helpers used by this research line;
- `docs/`: research notes and operational evidence;
- `results/`: reserved for durable result summaries when needed.

Key boundary:

- keep VP V19-specific code here, not in repo-root `scripts/`;
- reusable framework scripts must be promoted deliberately before moving back to
  repo-root `scripts/`;
- do not mix V19 return-volume artifacts with V18 value-occupation artifacts.
