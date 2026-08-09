# VP P0 Baseline Research Workspace

This workspace preserves historical research-side materials for the value-profile
P0 baseline branch. It is not a framework entrypoint and does not define an
official promoted factor.

Contents:
- `scripts/`: research-only evaluators and worker launch helpers.
- `docs/`: historical diagnostics, data notes, and full-window research plans.
- `results/`: reserved for local or copied evidence summaries.

Root-level `scripts/` should only contain reusable framework tools. New
factor-specific experiments should create their own `factor_research/<id>/`
workspace instead of writing here or in repo-root `docs/operations/`.
