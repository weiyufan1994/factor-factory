---
name: factor-forge-data-liaison
description: Resolve factor-research fields, information timing and coverage using the existing Data API, and identify the exact remaining data dependency.
---

# Factor Forge Data Liaison

Support Ultimate/Step3 as the research-side consumer of the existing Data API.
The economic hypothesis and observation map define the data need.

## Resolve the smallest real dependency

1. Read the published interface/catalog version and inspect the relevant response.
   Match fields, units, PIT availability, window, universe, warmup and join keys.
2. Reuse the Data group's versioned service acceptance and coverage. Research
   checks correct consumption; a new factor is not a new dataset certification.
3. Reuse the existing exchange calendar and daily status/valuation semantics
   where they match. A transport failure does not prove a coverage gap.
4. For an actual error or unsupported requirement, send the owner the interface,
   bounded parameters, affected fields/keys, expected/observed behavior and a
   minimal example. An unclear meaning is a question, not proven defective data.
5. Preserve unaffected research. After a supplier fix, recompute only outputs
   affected by changed consumed data or semantics; a metadata-only change does
   not by itself require a new backtest.

Resolve catalog entries, not arbitrary local/S3 paths. Knowledge can suggest a
dataset or historical pitfall; only the service and actual delivery establish
availability. Research remains responsible for lookahead and invalid joins.

## Deliver

Record resolved fields/dataset/version, timing/coverage, accepted reuse and the
specific remaining gap in the existing workspace handoff. When a new delivery
is necessary, use the existing `factorforge_data_request_v1` and
[request/receipt example](references/data-request-and-delivery.example.json).
A proxy that changes measurement returns to Step2 for explicit error review.

The Data group owns production repair, backfill and catalog maintenance.
This liaison performs scoped reads and dependency communication, not production
scans, dataset mutation, factor calculation or promotion.

## Optional signed organization mode

For an actual signed organization task, read
[hosted operation](references/hosted-operation.md) and its referenced envelopes.
Its session, attestation and admission rules apply to that mode only; ordinary
local consumption does not acquire a Host prerequisite.
