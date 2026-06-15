#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def find_repo_root(path: Path) -> Path:
    for parent in [path.resolve().parent, *path.resolve().parents]:
        if (parent / "factor_factory").is_dir() and (parent / ".git").exists():
            return parent
    raise RuntimeError(f"could not locate factor-factory repo root from {path}")


REPO_ROOT = find_repo_root(Path(__file__))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_workspace import (
    BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN,
    assert_path_under_workspace,
    load_workspace_manifest,
    validate_workspace_manifest,
    workspace_manifest_path,
)

ALPHA101_PDF_NAME = "101_formulaic_alphas_arxiv_1601.00991.pdf"


def load_workspace(root: Path) -> dict:
    manifest_path = workspace_manifest_path(root)
    if not manifest_path.exists():
        raise SystemExit(f"BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MANIFEST_INVALID: missing {manifest_path}")
    manifest = load_workspace_manifest(manifest_path)
    failures = validate_workspace_manifest(manifest)
    if failures:
        raise SystemExit("\n".join(failures))
    return manifest


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, dict]:
    if not args.workspace_root:
        raise SystemExit(BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN)
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    manifest = load_workspace(workspace_root)
    pdf_path = (
        Path(args.pdf).expanduser().resolve()
        if args.pdf
        else workspace_root / "inputs" / "alpha101_sources" / ALPHA101_PDF_NAME
    )
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else workspace_root / "data" / "alpha101_registry" / "alpha101_registry.json"
    )
    assert_path_under_workspace(output, workspace_root, label="alpha101_registry_output")
    return pdf_path, output, manifest


def normalize_formula(text: str) -> str:
    text = re.sub(r"(?m)^\s*\d+\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("Ts_ArgMax", "ts_argmax")
    text = text.replace("Ts_ArgMin", "ts_argmin")
    text = text.replace("Ts_Rank", "ts_rank")
    text = text.replace("SignedPower", "signedpower")
    text = text.replace("IndNeutralize", "indneutralize")
    text = text.replace("Sign(", "sign(")
    text = text.replace("Log(", "log(")
    return text


def extract_formula_section(pdf_path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    start_marker = "A.1. Formulaic Expressions for Alphas"
    end_marker = "A.1. Functions and Operators"
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start == -1 or end == -1:
        raise RuntimeError("could not locate Alpha101 formula appendix section")
    return text[start:end]


def parse_alpha101(pdf_path: Path) -> list[dict[str, object]]:
    section = extract_formula_section(pdf_path)
    matches = list(re.finditer(r"Alpha#\s*(\d+)\s*:?", section))
    records: list[dict[str, object]] = []
    for idx, match in enumerate(matches):
        alpha_no = int(match.group(1))
        formula_start = match.end()
        formula_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(section)
        formula = normalize_formula(section[formula_start:formula_end])
        if not formula:
            raise RuntimeError(f"empty formula for Alpha{alpha_no:03d}")
        records.append(
            {
                "alpha_no": alpha_no,
                "factor_id": f"Alpha{alpha_no:03d}",
                "report_id": f"ALPHA{alpha_no:03d}_PAPER_20160101_CURRENT",
                "source_name": "101 Formulaic Alphas",
                "source_url": "https://arxiv.org/abs/1601.00991",
                "formula": formula,
            }
        )
    records = sorted(records, key=lambda row: int(row["alpha_no"]))
    alpha_nos = [int(row["alpha_no"]) for row in records]
    if alpha_nos != list(range(1, 102)):
        missing = sorted(set(range(1, 102)).difference(alpha_nos))
        extra = sorted(set(alpha_nos).difference(range(1, 102)))
        raise RuntimeError(f"expected Alpha001-Alpha101; missing={missing} extra={extra} count={len(records)}")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local Alpha101 canonical formula registry from the paper PDF.")
    parser.add_argument("--workspace-root", help="Factor research workspace root. Required for generated registry output.")
    parser.add_argument("--pdf", default=None, help="Path to the 101 Formulaic Alphas PDF.")
    parser.add_argument("--output", default=None, help="Output JSON registry path. Defaults inside the factor workspace.")
    parser.add_argument("--dry-run", action="store_true", help="Validate workspace/output guard without reading the PDF.")
    args = parser.parse_args()

    pdf_path, output, manifest = resolve_paths(args)
    if args.dry_run:
        print(json.dumps({
            "event": "alpha101_registry_guard_pass",
            "workspace_root": str(Path(args.workspace_root).expanduser().resolve()),
            "factor_id": manifest.get("factor_id"),
            "research_id": manifest.get("research_id"),
            "source_pdf": str(pdf_path),
            "output": str(output),
            "production_research_started": False,
        }, ensure_ascii=False, sort_keys=True))
        return 0

    records = parse_alpha101(pdf_path)
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_pdf": str(pdf_path),
        "source_url": "https://arxiv.org/abs/1601.00991",
        "record_count": len(records),
        "records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} Alpha101 formulas to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
