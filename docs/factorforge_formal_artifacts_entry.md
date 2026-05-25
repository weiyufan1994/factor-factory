# Factor Forge Formal Artifacts Entry

Version: factorforge_formal_artifact_prepare_v1

## Formal Entry

The host-side entry for new research-report artifacts is:

```bash
python3 scripts/prepare_factorforge_formal_artifacts.py \
  --report-id <CANONICAL_REPORT_ID> \
  --report-pdf <LOCAL_PDF_OR_S3_MANIFEST> \
  --end-step 3a \
  --write-report
```

This command is the only approved host-side boundary for producing Step1,
Step2, and Step3A formal artifacts before Step3B or worker dispatch.

The command never creates `runtime_context` and never dispatches a worker. It
only allows downstream execution when all requested step validators pass and the
canonical artifact identity chain is intact.

## Step Boundaries

Step1 owns PDF report understanding:

- `alpha_idea_master`
- primary/challenger/chief raw LLM outputs
- report map, alpha thesis, challenger thesis, ambiguity review
- Step1 provenance: PDF sha256, prompt hash, model/raw-output provenance

Step2 owns factor specification:

- `factor_spec_master`
- primary/challenger factor spec raw outputs
- factor consistency / auditor result
- `handoff_to_step3`
- artifact identity and implementation-mode contract

Step3A owns data preparation:

- `data_prep_master`
- `qlib_adapter_config`
- implementation plan stub
- local input paths, snapshot metadata, and data feasibility report

If `prepare_factorforge_formal_artifacts.py --end-step 3a` writes
`data_prep_master`, that means the command has actually executed Step3A. Step2
must not produce data-prep artifacts.

## Formal vs Debug

Formal Step1 requires primary/challenger/chief raw LLM outputs. Formal Step2
requires primary/challenger/auditor raw extraction outputs. Until a real host
PDF/LLM bridge is wired, these raw outputs must be supplied to the prepare
command.

`--allow-deterministic-debug` is only a debug fallback. It may use existing
deterministic builders to exercise the artifact chain, but produced artifacts
must carry provenance:

- `formal_llm_extraction=false`
- `debug_fallback=true`
- `step*_extraction_mode=deterministic_debug_fallback`

Debug fallback artifacts must not be represented as formal LLM extraction.

## Minimal Artifact Identity

`factor_spec_master.artifact_identity` and
`handoff_to_step3.artifact_identity` must align on:

- `report_id`
- `factor_id`
- `source_type`
- `implementation_mode`
- `contract_version`
- `producer`
- `spec_hash`
- `branch_id`
- `artifact_role`

Mode-specific hashes are required:

- operator: `formula_hash`
- direct code: `code_hash` or `code_contract_hash`
- hybrid: `formula_hash`, `custom_block_hash`, `hybrid_hash`

## Blocking Contract

Any validator failure, report-id mismatch, missing artifact identity, or bad
handoff identity returns:

```text
BLOCK_FORMAL_ARTIFACT_SCHEMA_INVALID
```

When this token is returned, the host must not create runtime context, sync
worker artifacts, or start Step3B/Step4.
