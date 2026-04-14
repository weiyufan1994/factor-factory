---
name: factor-forge-step1
description: Run Step 1 of the Factor Factory pipeline — PDF report ingestion, dual-route reading (primary + challenger), chief merge, and canonical alpha_idea_master generation. Triggers when user provides a research report PDF and asks to extract the alpha factor, run the full Step 1 pipeline, or produce an alpha_idea_master object. Requires OpenClaw with google/gemini-3.1-pro-preview available via the pdf tool.
---

# Factor Factory Step 1 Skill

## What This Skill Does

Runs the complete Step 1 pipeline on a single research report PDF:

1. **Primary intake** — read PDF with pdf skill, extract structured intake (subfactors, final_factor, formula_clues, etc.)
2. **Challenger intake** — same PDF re-read with adversarial prompt to surface gaps and missed details
3. **Report map + thesis** — both routes produce structured thesis objects
4. **Diff** — intake_diff and thesis_diff compare primary vs challenger
5. **Chief merge** — authoritative adjudication producing canonical alpha_idea_master
6. **Writeback** — all objects written to workspace; handoff file ready for Step 2

## Prerequisites

- OpenClaw environment with `pdf` tool available
- `google/gemini-3.1-pro-preview` configured as the PDF model
- factorforge Python package accessible at `/home/ubuntu/.openclaw/workspace/factorforge`

## How to Run

### Step 1a: Run Primary Intake

Use the `pdf` tool with this prompt on the target PDF:

```
请阅读这篇研报，并严格按以下 JSON 结构输出，不要输出 JSON 以外的任何文字。
要求：
1. 把因子尽量拆到最小可拆分子因子；
2. 对每个子因子和最终合成因子，都分别给出 economic_logic、behavioral_logic、causal_chain；
3. 每条 logic 都要标明 source 是 native 还是 inferred；如果是根据表达式/公式推断，必须明确写 inferred；
4. 把报告中的公式、表达式、伪代码、实现线索尽量单列抽出；
5. 若报告未明确解释逻辑，可根据表达式做谨慎推断，但必须标注 inferred。
JSON 结构：
{
  "report_meta": {"title": "", "broker": "", "topic": ""},
  "section_map": [{"section_title": "", "summary": ""}],
  "variables": [""],
  "signals": [""],
  "subfactors": [{"name": "", "formula_or_expression": "", "implementation_clues": [""], "economic_logic": "", "economic_logic_source": "native|inferred", "behavioral_logic": "", "behavioral_logic_source": "native|inferred", "causal_chain": "", "causal_chain_source": "native|inferred", "ambiguities": [""]}],
  "final_factor": {"name": "", "assembly_steps": [""], "component_subfactors": [""], "economic_logic": "", "economic_logic_source": "native|inferred", "behavioral_logic": "", "behavioral_logic_source": "native|inferred", "causal_chain": "", "causal_chain_source": "native|inferred", "ambiguities": [""]},
  "formula_clues": [{"content": "", "location_hint": ""}],
  "code_clues": [{"content": "", "location_hint": ""}],
  "implementation_clues": [{"content": "", "location_hint": ""}],
  "alpha_candidates": [{"name": "", "logic": "", "direction": ""}],
  "evidence_clues": [{"clue": "", "location_hint": ""}],
  "ambiguities": [""]
}
```

Save the returned JSON as `primary_raw.txt`.

### Step 1b: Run Challenger Intake

Use the `pdf` tool with this prompt on the **same** PDF:

```
请作为 challenger reader 独立阅读这篇研报，并严格按与主路相同的 JSON 结构输出，不要输出 JSON 以外的任何文字。
要求：
1. 不要简单复述主路结论；
2. 优先识别主路可能遗漏的子因子、公式、实现线索和歧义；
3. 对每个子因子和最终合成因子，仍需分别给出 economic_logic、behavioral_logic、causal_chain，并标注 native 或 inferred；
4. 若你不同意主路可能的最终因子选择，请明确给出不同的 final_factor。
JSON 结构：[同上方]
```

Save the returned JSON as `challenger_raw.txt`.

### Step 1c: Execute Pipeline

Run the Python pipeline script:

```bash
cd /home/ubuntu/.openclaw/workspace/factorforge
python3 -c "
import sys; sys.path.insert(0, '.')
from skills.factor_forge_step1.modules.report_ingestion.orchestration.wiring import build_step1_pipeline
from skills.factor_forge_step1.modules.report_ingestion.registry.report_registry import ReportRegistry
from pathlib import Path

project_root = Path('/home/ubuntu/.openclaw/workspace/factorforge')
report_id = 'YOUR_REPORT_ID'

# Load primary and challenger JSON
primary_raw = open('/tmp/primary_raw.txt').read()
challenger_raw = open('/tmp/challenger_raw.txt').read()

# Build registry source (use existing or create minimal)
registry = ReportRegistry(project_root / 'data' / 'report_ingestion' / 'report_registry.json')
rec = registry.get(report_id)
from skills.factor_forge_step1.modules.report_ingestion.registry.report_source_contract import ReportSource
source = ReportSource(**{k: v for k, v in rec.items() if k in {'report_id','source_type','source_uri','title','broker','author','published_at','local_cache_path','metadata','tags','status'}})

pipe = build_step1_pipeline(project_root)
result = pipe.run_pdf_skill(source, primary_raw, challenger_raw)
print(result)
"
```

### Step 1d: Run Chief Merge

After pipeline completes, use the `pdf` tool to run chief merge (feed all context JSON):

Follow the prompt template in `references/chief_merge_prompt.md`.

### Step 1e: Write alpha_idea_master

```bash
python3 -c "
from pathlib import Path
# chief_merge_output.json 是 pdf tool 返回的 JSON
# Write to objects/alpha_idea_master/
"
```

## Output Locations

All objects are written under `/home/ubuntu/.openclaw/workspace/factorforge/objects/`:

| Object | Path pattern |
|--------|-------------|
| Primary intake | `validation/report_map_validation__${report_id}__intake.json` |
| Challenger intake | `validation/report_map_validation__${report_id}__challenger_intake.json` |
| Primary report_map | `report_maps/report_map__${report_id}__primary.json` |
| Challenger report_map | `report_maps/report_map__${report_id}__challenger.json` |
| Primary thesis | `validation/report_map_validation__${report_id}__alpha_thesis.json` |
| Challenger thesis | `validation/report_map_validation__${report_id}__challenger_alpha_thesis.json` |
| Alpha idea master | `alpha_idea_master/alpha_idea_master__${report_id}.json` |
| Handoff | `handoff/handoff__${report_id}.json` |

## Report ID Convention

Use the filename-safe ID derived from the PDF filename:
```
RPT_pdf_{8-char-hash}_{YYYY-MM-DD}_{broker}_{title}
```
Example: `RPT_pdf_fde3cba2_20200223-东吴证券-东吴证券_技术分析拥抱选股因子`

## Architecture Reference

See `references/architecture.md` for the full module map and data flow diagram.

## Prompt Templates

Core prompts are in `references/prompts.md`.

## Data Schemas

Structured object schemas are in `references/schema.md`.
