# Factor Forge project conventions

## Working in this checkout

- Inspect the working tree and active work before editing. Preserve changes from
  other tasks; use an isolated checkout or source copy when work overlaps.
- Do not use `git add .`, silently switch an existing study's pinned checkout,
  or copy generated code/results between factor identities.
- Framework code lives in `factor_factory/`, `scripts/`, and `skills/`; tests
  and offline fixtures live in `tests/` and `fixtures/`.
- Research uses `skills/factor-forge-ultimate/SKILL.md` as its entry. Read the
  active stage's Skill and only the references selected for that task. Project
  instructions do not replace a Skill when another agent works elsewhere.

## Engineering and research are different scopes

- Keep factor-specific work in its declared research workspace and runtime copy.
  Reusable framework fixes belong in the source tree after review.
- Do not mutate shared clean data, historical research conclusions or canonical
  knowledge as a side effect of a code/documentation change. Installation,
  publication, live data, OOS, worker/Host operations and index refresh require
  their own task scope; offline development does not imply that scope.
- Use the active checkout's entrypoints and manifest-bound paths. Never select
  artifacts by newest file, a convenient glob, or another machine's hardcoded path.
- State what actually ran. Author checks, independent review, offline tests,
  local IS, formal OOS and promotion are distinct outcomes. A JSON record or
  successful CLI cannot prove an agent executed or a mechanism is valid.

## Verification and handoff

- Run focused offline tests for the affected behavior. The distributable suite
  is `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -c pytest-offline.ini -p no:cacheprovider`;
  use it when the task and packaged fixtures support that scope. Do not enable
  live execution engines to turn skipped tests into passes.
- For Skill edits, check frontmatter, relative references, the actual selected
  reading path and consistency with consumers. Do not test wording as a proxy
  for research behavior.
- Handoffs identify the actual checkout/workspace, changed files, evidence,
  unresolved findings, responsible role and resume point. Include necessary
  context explicitly; do not assume another session loaded this AGENTS.md.
