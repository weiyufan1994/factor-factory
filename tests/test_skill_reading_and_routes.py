"""Document reachability/count arithmetic, not prose as a research-quality test."""
import json
from pathlib import Path
import re
import subprocess

import pytest

from scripts.measure_skill_reading import guidance_bytes, measure


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "packaging/research-skills.json").read_text())


def test_selected_skills_and_guidance_are_reachable():
    names = CONFIG["default"] + CONFIG["optional"] + CONFIG["compatibility"]
    assert len(names) == len(set(names))
    assert len(CONFIG["default"]) == 11
    paths = {f"skills/{name}/SKILL.md" for name in names}
    paths.update(path for group in CONFIG["reading_sets"].values() for path in group["after"])
    missing = []
    for name in sorted(paths):
        path = ROOT / name
        text = guidance_bytes(ROOT, name).decode()
        for target in re.findall(r"\]\(([^\s)]+)\)", text):
            target = target.split("#", 1)[0]
            if target and "://" not in target and not target.startswith("/"):
                if not (path.parent / target).exists():
                    missing.append(f"{name}: {target}")
    assert missing == []
    for name in names:
        text = guidance_bytes(ROOT, f"skills/{name}/SKILL.md").decode()
        assert re.search(r"^name: " + re.escape(name) + r"$", text, re.M)


@pytest.mark.parametrize("path", ["/private/input.md", "../input.md", "x/../../input.md", ""])
def test_measurement_rejects_non_repository_paths(tmp_path, path):
    with pytest.raises(ValueError):
        guidance_bytes(tmp_path, path)


def test_counting_deduplicates_paths_and_keeps_observed_reading_separate(tmp_path):
    main = tmp_path / "skills/test/SKILL.md"
    main.parent.mkdir(parents=True)
    main.write_text("---\nname: test\ndescription: example\n---\n", encoding="utf-8")
    (tmp_path / "guide.md").write_text("中文\n", encoding="utf-8")
    for command in (["git", "init", "-q"], ["git", "add", "skills/test/SKILL.md", "guide.md"],
                    ["git", "-c", "user.name=Offline Test", "-c", "user.email=offline@example.invalid",
                     "commit", "-qm", "fixture"]):
        subprocess.run(command, cwd=tmp_path, check=True)
    (tmp_path / "guide.md").write_text("中文 changed\n", encoding="utf-8")
    paths = ["skills/test/SKILL.md", "guide.md", "guide.md"]
    config = {"default": ["test"], "optional": [], "compatibility": [], "ordinary_context": "fixture",
              "reading_sets": {"common": {"before": paths, "after": paths}},
              "reading_scenarios": [{"id": name, "description": name, "sets": ["common"]} for name in ("one", "two")]}
    report = measure(tmp_path, config, baseline="HEAD")
    a, b = report["scenarios"]
    assert a["after"]["stage_required_bytes"] - a["before"]["stage_required_bytes"] == len(b" changed")
    assert b["after"]["cumulative_unique_bytes"] == a["after"]["stage_required_bytes"]
    assert b["after"]["cumulative_repeated_bytes"] == a["after"]["stage_required_bytes"]
    assert a["actual_files_opened"] is None and b["actual_files_opened"] is None
    opened = {"one": {"guidance_files": ["guide.md", "guide.md"],
                      "source_code_data_files": ["source.pdf"], "evidence_note": "Synthetic counting fixture only"}}
    observed = measure(tmp_path, config, baseline="HEAD", opened=opened)["scenarios"][0]
    assert observed["actual_files_opened"] == 1
    assert observed["actual_reading"]["repeat_open_count"] == 1
    assert observed["actual_reading"]["unique_guidance_bytes"] == len((tmp_path / "guide.md").read_bytes())
    assert observed["actual_reading"]["source_code_data_files"] == ["source.pdf"]


def test_missing_guidance_is_not_silently_omitted(tmp_path):
    with pytest.raises(FileNotFoundError):
        guidance_bytes(tmp_path, "missing.md")


def test_measurement_without_git_history_reports_required_source_checkout(tmp_path):
    with pytest.raises(ValueError, match="Git development checkout"):
        measure(tmp_path, {}, baseline="HEAD")


def test_measurement_cli_without_git_exits_without_writing_result(tmp_path):
    import sys

    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging/research-skills.json").write_text(
        json.dumps({"baseline_ref": "HEAD"}), encoding="utf-8"
    )
    output = tmp_path / "measurement.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/measure_skill_reading.py"),
         "--root", str(tmp_path), "--output", str(output)],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "Git development checkout" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output.exists()
