# Local PDF input landing

Read after the source has actually been read. Use the selected checkout and one
factor workspace. The CLI accepts PDF-backed intake; formula/user-hypothesis
routes use their matching Step1 source producer, not a fabricated PDF.

`scripts/run_factorforge_local_step1.py` takes these JSON inputs:

| Input | Required envelope |
|---|---|
| `--source-json` | `report_id`, `source`, `reader_identity`; optional `reading_context` |
| `--primary-intake` | `intake`, `authorship` with role `primary_reader` |
| `--challenger-intake` | `intake`, `authorship` with role `challenger_reader` |
| `--chief-merge` | `chief_merge`, `authorship` with role `chief_merge` |

The source `reader_identity.role` is `local_source_reader`.
Each authorship object carries actual `agent_id`, `role`,
`authorship=agent_authored` and a `description`, not invented isolated identities.

The source has `source_type=pdf`, `source_uri`, `title`,
`local_cache_path` to actual PDF bytes, and
`original_source.content_sha256/description`. Use `reading_context` to disclose
already-known results and exposure. The chief supplies `final_factor` with name
and assembly, decision summary, confidence, rationale and complete authored
`research_discipline`. See the [source field guide](schema.md).

The discipline includes the mathematical object/statistic/information hints,
economic hypothesis, selected and rival math candidates, market-process thesis,
payoff projection, measurement program, conditions/falsifiers and knowledge
provenance. A checked cold start can use empty lessons plus
`similar_case_lessons_absence_reason` under the local content rules.
The CLI does not synthesize missing economics or query knowledge for the author.

Run from the selected checkout:

```sh
python3 scripts/run_factorforge_local_step1.py \
  --factor-workspace <workspace> --report-id <report_id> \
  --source-json <source.json> --primary-intake <primary.json> \
  --challenger-intake <challenger.json> --chief-merge <chief.json>
```

Outputs stay under the workspace's `objects/`: primary/challenger maps and
theses, their differences, `alpha_idea_master/alpha_idea_master__<report_id>.json`
and `handoff/handoff__<report_id>.json`. A landing result is not semantic
certification or completed Step2–6. Preserve partial/failed status; continue
through Ultimate's ordinary local route with actual accepted artifacts.
