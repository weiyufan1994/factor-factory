#!/usr/bin/env python3
"""Compare explicit Skill reading paths; no research or runtime side effects."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any


def _relative(path: str) -> str:
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts or not value.parts:
        raise ValueError(f"not a repository-relative guidance path: {path}")
    return value.as_posix()


def guidance_bytes(root: Path, path: str, ref: str | None = None) -> bytes:
    path = _relative(path)
    raw = (
        subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=root)
        if ref else (root / path).read_bytes()
    )
    raw.decode("utf-8")  # Fail on invalid guidance; no silent omission.
    return raw


def measure(root: Path, selection: dict[str, Any], *, baseline: str,
            opened: dict[str, Any] | None = None) -> dict[str, Any]:
    """Paths are an explicit scenario plan, not inferred mandatory-link closure."""
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{baseline}^{{commit}}"],
        cwd=root, text=True,
    ).strip()
    cache: dict[tuple[str | None, str], int] = {}

    def size(path: str, version: str) -> int:
        ref = revision if version == "before" else None
        key = (ref, path)
        if key not in cache:
            cache[key] = len(guidance_bytes(root, path, ref))
        return cache[key]

    seen: dict[str, set[str]] = {"before": set(), "after": set()}
    totals = {"before": 0, "after": 0}
    scenarios = []
    for scenario in selection["reading_scenarios"]:
        row = {"id": scenario["id"], "description": scenario["description"]}
        for version in ("before", "after"):
            paths = sorted({
                _relative(path)
                for group in scenario["sets"]
                for path in selection["reading_sets"][group][version]
            })
            required = sum(size(path, version) for path in paths)
            totals[version] += required
            seen[version].update(paths)
            cumulative = sum(size(path, version) for path in seen[version])
            row[version] = {
                "required_paths": paths,
                "stage_required_bytes": required,
                "cumulative_unique_bytes": cumulative,
                "cumulative_repeated_bytes": totals[version] - cumulative,
                "largest_required": sorted(
                    [{"path": path, "bytes": size(path, version)} for path in paths],
                    key=lambda item: (-item["bytes"], item["path"]),
                )[:5],
            }
        actual = (opened or {}).get(scenario["id"])
        row["actual_files_opened"] = None
        if actual is not None:
            paths = [_relative(path) for path in actual["guidance_files"]]
            row["actual_files_opened"] = len(set(paths))
            row["actual_reading"] = {
                "guidance_files": paths,
                "unique_guidance_bytes": sum(size(path, "after") for path in set(paths)),
                "repeat_open_count": len(paths) - len(set(paths)),
                "source_code_data_files": actual.get("source_code_data_files", []),
                "evidence_note": actual["evidence_note"],
            }
        scenarios.append(row)

    def discovery(version: str) -> dict[str, int]:
        names = selection["default"] + (
            selection["compatibility"] + selection["optional"] if version == "before" else []
        )
        mains = [f"skills/{name}/SKILL.md" for name in names]
        metadata_bytes = 0
        for path in mains:
            raw = guidance_bytes(root, path, revision if version == "before" else None)
            metadata = raw.split(b"---", 2)
            if len(metadata) < 3 or metadata[0].strip():
                raise ValueError(f"missing frontmatter: {path}")
            metadata_bytes += len(metadata[1])
        return {"skill_count": len(names), "main_bytes": sum(size(p, version) for p in mains),
                "metadata_bytes": metadata_bytes}

    return {
        "baseline_commit": revision,
        "measurement": "UTF-8 guidance bytes; explicit routes, not observed agent behavior",
        "context": selection["ordinary_context"],
        "discovery": {v: discovery(v) for v in ("before", "after")},
        "scenarios": scenarios,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline")
    parser.add_argument("--opened-guidance-log", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    config = json.loads((root / "packaging/research-skills.json").read_text(encoding="utf-8"))
    opened = json.loads(args.opened_guidance_log.read_text(encoding="utf-8")) if args.opened_guidance_log else None
    result = measure(root, config, baseline=args.baseline or config["baseline_ref"], opened=opened)
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
