# Private-fund-grade Factor Factory gap roadmap (2026-04-14)

## Purpose

This note records the current gap between:
- the **existing CPV-backed Step1–Step5 minimal reproducibility chain**, and
- a **private-fund-grade factor factory** capable of generalized, repeatable, production-oriented, investment-usable operation.

It is intended as a repository-retained path document for future engineering and research hardening.

## Current truthful status

The repository can now truthfully claim:
- Step1–Step5 repository skeleton is established,
- CPV sample path proves a real report-to-factor closed loop can run,
- contracts / fixtures / sample runners / handoff objects / bilingual docs now exist in-repo.

The repository cannot yet truthfully claim:
- private-fund-grade generalized factor production,
- stable cross-factor standardization,
- industrial backtesting and evaluation governance,
- full investment-deployment readiness.

## Definition: what "private-fund-grade factor factory" means

A private-fund-grade factor factory is not just a system that can run one good sample.
At minimum, it must satisfy all four conditions below:

1. **Generalizable**
   - not only CPV, but multiple factor families can pass through the pipeline with stable semantics
2. **Repeatable**
   - repeated runs under the same input have stable boundaries, clear provenance, and explainable outputs
3. **Production-capable**
   - the system supports batch operation, orchestration, retries, and failure handling without hand-guided babysitting
4. **Investment-usable**
   - outputs can enter real research, evaluation, portfolio, and risk workflows rather than stopping at a research toy stage

So the true requirement is a union of:
- research extraction capability,
- data/adapter engineering capability,
- backtest/evaluation capability,
- governance/audit capability.

## What already exists today

The current repository already has:
- Step1–Step5 minimal chain,
- CPV sample closed loop,
- handoff / contracts / docs / fixtures / runners,
- cleaned repository structure and naming doctrine,
- bilingual repository documentation.

That means the **factory skeleton exists**, and the **sample line exists**.
What is still missing is scale, stability, standardization, and investment-grade hardening.

## The 12 hard gaps

### 1. Multi-sample generalization matrix
**Current state**
- CPV is the main proof point.
- Other factor families do not yet have systematic pass records.

**Private-fund-grade expectation**
A real sample matrix should exist across factor families, for example:
- high-frequency price/volume
- money-flow
- fundamental
- alternative data
- event-driven

**Gap**
The repo currently proves "this path can work", not yet "this path works broadly".

### 2. Step 1 extraction stability and error-bound measurement
**Current state**
- Step 1 can extract factor ideas from reports.
- But prompt / route / chief-merge behavior is still model-sensitive.

**Private-fund-grade expectation**
Need explicit measurement of:
- which report types are error-prone,
- which formula classes are often missed,
- what is native vs inferred logic,
- error rate / ambiguity rate / correction rate.

**Gap**
Step 1 is currently a strong research assistant layer, not yet a tightly controlled production extraction module.

### 3. Step 2 spec standardization
**Current state**
- Step 2 can turn alpha idea into factor spec.
- But cross-step object dependence and sample-shaped repair logic still exist.

**Private-fund-grade expectation**
Need a stable `factor_spec_master` standard covering:
- input field definitions,
- calculation windows,
- normalization conventions,
- missing-value policy,
- lag policy,
- rebalance frequency,
- tradability boundaries.

**Gap**
Schema exists, but cross-factor standard stability is not yet proven.

### 4. Step 3 data mapping and implementation standardization
**Current state**
- Step 3 can resolve CPV data sources, qlib-friendly adapters, and first implementation.

**Private-fund-grade expectation**
Need a unified adapter standard for:
- daily / minute / fundamental / alternative data,
- field naming conventions,
- instrument / datetime semantics,
- source switching without upper-layer logic rewrites.

**Gap**
Current Step 3 still shows traces of being optimized around sample success rather than universal adapter-platform quality.

### 5. Step 4 backtest engine industrialization
**Current state**
- Step 4 can run lightweight sample paths and produce partial/diagnostic outputs.

**Private-fund-grade expectation**
Need stable support for:
- standard backtest interfaces,
- cost model,
- slippage model,
- rebalance logic,
- industry/size/style neutralization,
- long-short and bucket evaluation,
- OOS / walk-forward / rolling validation.

**Gap**
Current system can run backtests, but is not yet a private-fund research-standard backtest platform.

### 6. Step 5 evaluation still not investment-grade enough
**Current state**
- Step 5 can close a factor case and build evaluation output.

**Private-fund-grade expectation**
Need investment-usable criteria such as:
- IC / RankIC / ICIR,
- bucket returns,
- long-short returns,
- turnover / capacity / market-impact proxy,
- style exposure,
- industry concentration,
- drawdown and robustness,
- lifecycle monitoring.

**Gap**
Current Step 5 is closer to a research-closure layer than an investment-committee-ready decision layer.

### 7. Factor library and version governance
**Current state**
- Single factor-case closure exists.
- A full factor asset-management layer does not.

**Private-fund-grade expectation**
Need:
- factor registry,
- factor versioning,
- change history,
- factor lineage,
- freeze/deprecate rules,
- de-duplication and merge rules across related factors.

**Gap**
Current state is closer to "we can produce a factor" than "we can operate a factor library".

### 8. Quality control and failure-routing policy
**Current state**
- truthful partial discipline already exists.

**Private-fund-grade expectation**
Need stronger QC rules, such as:
- where automatic downgrade is allowed,
- where the chain must hard-stop,
- which outputs require human review,
- which missing fields make downstream execution invalid,
- how to detect hallucinated specs / fake logic / non-tradable implementations.

**Gap**
The current system has honesty discipline, but not yet full factory-grade rules.

### 9. Batch scheduling and orchestration
**Current state**
- Current usage is still mainly one-factor / one-sample oriented.

**Private-fund-grade expectation**
Need:
- multi-report intake scheduling,
- multiple alpha ideas entering Step2/3 concurrently,
- retries,
- queue and priority handling,
- failure alerting,
- summary ledgers and run accounting.

**Gap**
Current mode is still closer to manually directing one production line than to workshop automation.

### 10. Cost, latency, and throughput management
**Current state**
- Sample paths run, but cost/time profiles are not yet formalized.

**Private-fund-grade expectation**
Need visibility into:
- per-report extraction cost,
- per-factor build cost,
- backtest runtime,
- most expensive layer,
- most failure-prone layer,
- caching and reuse policy.

**Gap**
Current emphasis is still "make it work", not yet "make it operable".

### 11. Human review and research workflow integration
**Current state**
- chief merge and truthful partial already show governance intent.

**Private-fund-grade expectation**
Need explicit human workflow support for:
- review checkpoints,
- annotation and revision,
- spec override,
- pass / defer / reject markings,
- research team and PM interaction loops.

**Gap**
Current system can self-close some loops, but is not yet fully integrated with a real investment-research organization.

### 12. Final-mile connection from research result to portfolio decision
**Current state**
- The current practical endpoint is often `factor_case_master`.

**Private-fund-grade expectation**
Need linkage to:
- factor pool management,
- factor combination and optimization,
- risk model interaction,
- relation to current books/themes/styles,
- staged deployment,
- pre-live monitoring.

**Gap**
Current endpoint is "research complete", not "investment deployment complete".

## The 4 major blocks behind the 12 gaps

If compressed to the highest level, the repository still needs four large capability blocks:

### A. Generalization capability
Need to prove the factory is not CPV-only.

### B. Industrial capability
Need batch-safe, stable, low-failure operation rather than one-off success.

### C. Investment capability
Need outputs that are directly usable in research committee / PM workflows.

### D. Governance capability
Need auditable, maintainable, enforceable, versioned outputs rather than merely plausible outputs.

## Current positioning

The most accurate current positioning is:

> **Factor Factory v0.1:** sample closed loop established; repository skeleton built; CPV proves the report-to-factor path is real.
> It is not yet a private-fund-grade, batch-standardized, investment-deployable factor factory.

## Priority build order for the next stage

If resources are limited, the next four priorities should be:

### Priority 1 — Multi-sample generalization matrix
First prove the factory is not CPV-only.

### Priority 2 — Step 3/4 standardization
Unify adapter semantics and backtest interfaces.

### Priority 3 — Step 5 investment-grade evaluation
Upgrade from research closure to investment-usable evaluation.

### Priority 4 — Factor library and version governance
Let the factory accumulate reusable factor assets instead of rebuilding from scratch each time.

## Suggested staging roadmap

### P0 — from sample success to structured repeatability
- add 3–5 non-CPV factor samples
- harden Step1/Step2 schema and ambiguity measurement
- stabilize Step3 adapter semantics
- stabilize Step4 quick path and native path boundaries
- standardize Step5 evaluation payload fields

### P1 — from repeatability to production workflow
- batch scheduling / retries / ledgers
- factor registry and versioning
- QC and failure-routing rules
- cost/latency/throttling profiles
- human review checkpoints

### P2 — from production workflow to investment-grade factory
- portfolio-facing evaluation standard
- factor pool integration
- risk model and exposure controls
- staged deployment path
- lifecycle monitoring and retirement policy

## One-sentence summary

The right next target is not "more files" or "more sample runs" by themselves, but a factor factory where source code, fixtures, backtest standards, evaluation standards, governance, and portfolio-facing outputs are strong enough that the system is credible beyond a CPV demonstration.
