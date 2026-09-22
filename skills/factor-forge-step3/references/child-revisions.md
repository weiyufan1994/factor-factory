# Step3 child revisions

Read only for an explicitly authorized child revision. Use the exact approved child spec; this file does not authorize creating a child.

  - Child revision runs created by the ultimate loop must consume
    direct-code laws through a versioned law registry rather than pasting every
    moneyflow/Miller variant into `run_step3b.py`. The executable revision spec
    should carry `law_id` plus `code_law_hash`; Step3B resolves the law through
    `factor_factory.factor_laws.*` and must BLOCK with
    `BLOCK_FACTORFORGE_DIRECT_CODE_LAW_MISSING` or
    `BLOCK_FACTORFORGE_DIRECT_CODE_LAW_HASH_MISMATCH` when the registry entry is
    absent or identity-mismatched. Runner edits for a new law are a framework
    smell unless the adapter contract itself changes.
  - Child revision runs created by the ultimate loop must consume
    `objects/research_iteration_master/executable_revision_spec__{child_report_id}.json`
    before generating code or factor values. A child report id must not silently
    rerun the parent formula: missing specs must BLOCK, non-audit no-op formula
    hashes must BLOCK, and Step3B metadata/handoff must expose the applied
    executable revision spec and child formula hash.
  - Child revisions preserve implementation mode. `implementation_mode=operator`
    requires Formula-IR parse/parity. `implementation_mode=direct_code` or
    `hybrid` requires a `direct_code_revision_contract` or hybrid mutation
    contract with target function/block, required fields, data timing contract,
    code-law hash, and mutation scope. Step3B must not replace a native minute
    or tick law with an unrelated parseable operator formula merely to satisfy
    Formula-IR.
