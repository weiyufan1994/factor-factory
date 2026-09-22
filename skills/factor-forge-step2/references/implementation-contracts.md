# Step2 implementation contracts

Read the section for the selected route when binding or changing an implementation. [The measurement program](../../../docs/contracts/mechanism_conditioned_measurement_program_v1.zh-CN.md) determines that route.

## Operator Formula Contract

For `implementation_mode=operator`, Step2 must parse `formula_text` into `formula_ir` using `factorforge_formula_ir_v1`. The spec must include `formula_hash`, `operator_set`, `required_fields`, `resolved_fields`, and `parse_status`. `paper_canonical_formula` sources require a successful `formula_ir`; unsupported syntax, unknown operators, negative windows, or missing field aliases must BLOCK rather than falling through to hybrid/direct_code.

The qlib bridge is explicit: Step2 may write a qlib expression draft only when the registry supports each operator. Unsupported qlib operators must be recorded as unsupported, not silently rewritten. The pandas reference evaluator is the parity ground truth for Step3B operator codegen.

## Hybrid Contract

Hybrid mode is a bounded composition of an operator subgraph plus explicit custom Python blocks. Step2 must write `factorforge_hybrid_contract_v1` with `operator_subgraph`, nonempty `custom_blocks`, `boundary`, `formula_hash`, `custom_block_hash`, and `hybrid_hash`. Missing boundary/schema/hash fields must BLOCK as `BLOCK_INVALID_HYBRID_CONTRACT`.

Custom blocks are not free-form unsafe code: they must declare `function_name`, input/output schema, required fields, forbidden patterns, and source code. Operator outputs are protected by default; overwriting them requires an explicit boundary permission.
