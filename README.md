# Factor Forge Ultimate

A researcher-led Step1–6 workflow: understand the source, formalize economic and mathematical mechanisms, implement and independently review code, evaluate evidence, and retain reusable lessons.

[中文使用说明](README.zh-CN.md) · [Ultimate Skill](skills/factor-forge-ultimate/SKILL.md) · [Validation scope](docs/publish-verification.zh-CN.md)

## D0.4 initial preview — 2026-09-28

This branch adds mechanism-constrained GP proposals, bounded MCTS scheduling,
forward mathematical induction, an optional derivation tutor, and an opt-in
Ultimate evidence/reflection bridge. These are experimental research tools,
not an automatically self-improving production system. Search remains off by
default; no installed Skills, live runtime, market data or private knowledge
store are changed by cloning this branch.

See [initial-version scope and quickstart](docs/releases/d04-initial.zh-CN.md)
for implemented features, remaining work and the offline test command.

## Start here

Use the Ultimate Skill and scripts from the same checkout. Preserve the author's baseline before proposing extensions. New local IS research uses `--local-is-only`; it does not require a Host deployment. Independent code review and real research records remain required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
export PYTHONPATH="$PWD"
export PFVV_MONTHLY_EXECUTION_ENGINE_PATH="$PWD/examples/mszq_intraday_momentum_pulse/local_is_execution_engine"
python scripts/build_factorforge_retrieval_index.py --runtime-root "$PWD"
python query_knowledge.py --query 'transient signal'
python -m pytest -c pytest-offline.ini -p no:cacheprovider
```

Market data, licensed source documents, the independent Data API SDK, runtime credentials and local deployment settings are not included. Cloud and machine identifiers in examples are placeholders. The semantic retrieval interface requires a separately configured encoder; lexical/graph retrieval is available without one.

This public source projection excludes private operational records and research outputs. It includes portable framework improvements, not the entire machine-specific runtime installation. Synthetic engineering tests are not evidence of factor profitability or completion of a new research study.

No new open-source license is granted by this update.
