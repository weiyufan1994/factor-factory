# Step2 implementation contracts

Read the section for the selected route when binding or changing an implementation. [The measurement program](../../../docs/contracts/mechanism_conditioned_measurement_program_v1.zh-CN.md) determines that route.

## Operator Formula Contract

For `implementation_mode=operator`, Step2 must parse `formula_text` into `formula_ir` using `factorforge_formula_ir_v1`. The spec must include `formula_hash`, `operator_set`, `required_fields`, `resolved_fields`, and `parse_status`. `paper_canonical_formula` sources require a successful `formula_ir`; unsupported syntax, unknown operators, negative windows, or missing field aliases must BLOCK rather than falling through to hybrid/direct_code.

The qlib bridge is explicit: Step2 may write a qlib expression draft only when the registry supports each operator. Unsupported qlib operators must be recorded as unsupported, not silently rewritten. The pandas reference evaluator is the parity ground truth for Step3B operator codegen.

## Direct-code Contract

For `implementation_mode=direct_code`, author the source-bound algorithm before
the initial Step2 validation. Put `implementation_contract.code_contract` on the
authored primary raw spec (or chief alpha idea), with actual `source_code`,
`entrypoint`/`function_name`, `required_fields`, input/output schema, dependencies,
information-time rules and `source_derivation` mapping the source/math to code.
The producer computes `code_hash` from the normalized source; do not supply a
placeholder. `source_derivation.not_fallback=true` asserts provenance, not review
approval. Pseudocode or a prose-only formula is not an executable source contract.

New source exports one `FACTOR` instance of `BaseFactor`, `PriceVolumeFactor`, or
`FundamentalFactor`, with `compute(inputs)` and explicit named input frames.
Set both entrypoint fields to `FACTOR`; declare output as
`{"index": ["datetime", "instrument"], "columns": ["factor_value"]}`.
The class may calculate a long table internally; `run(inputs)` normalizes it.
Historical `compute_factor` artifacts are readable by the shared runner, not
templates for new source. Smoke-spec builders contain synthetic research text;
use the actual Step2 source and derivation for a research spec.

This is a pure algorithm input, not permission to fetch data or calculate factor
returns. Preserve independent readings; append a chief-adjudicated input revision
and update its references rather than editing generated master/handoff fields.
Then run Step2 through Ultimate. Step3A binds real data and Step3B assembles the
implementation; Step2 independently reviews that actual code and its helpers
before acceptance/parity tests and Step4. Do not demand that later review before
the initial Step2 handoff, or treat the early contract as its replacement.

## Hybrid Contract

Hybrid mode is a bounded composition of an operator subgraph plus explicit custom Python blocks. Step2 must write `factorforge_hybrid_contract_v1` with `operator_subgraph`, nonempty `custom_blocks`, `boundary`, `formula_hash`, `custom_block_hash`, and `hybrid_hash`. Missing boundary/schema/hash fields must BLOCK as `BLOCK_INVALID_HYBRID_CONTRACT`.

Custom blocks are not free-form unsafe code: they must declare `function_name`, input/output schema, required fields, forbidden patterns, and source code. Operator outputs are protected by default; overwriting them requires an explicit boundary permission.
