# Alpha101 Batch Qlib Research Workspace

This workspace contains Alpha101 batch-research helper scripts that were moved
out of repo-root `scripts/` to avoid mixing one-off factor research with shared
Factor Forge framework tooling.

Contents:
- `scripts/build_alpha101_registry.py`
- `scripts/build_alpha101_research_queue.py`
- `scripts/run_alpha101_qlib_batch_judge.py`
- `docs/`: reserved for Alpha101 batch research notes.
- `results/`: reserved for generated summaries.

These scripts require an explicit Factor Forge research workspace via
`--workspace-root`; they must not write canonical research outputs to repo-root
paths unless an explicit export/provenance flow is used.
