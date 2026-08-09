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

Operational status:

- the shell helpers are archived/manual evidence, not registered Factor Forge
  entrypoints;
- they fail closed unless `FACTORFORGE_ARCHIVED_MANUAL_ACK=1` is set;
- cache/workspace paths must be supplied explicitly, and remote artifact upload
  remains disabled unless `ALLOW_REMOTE_WRITE=1` plus an explicit `UPLOAD_S3`
  are both provided.
