import importlib.util
import os
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STEP4_SCRIPTS = PROJECT_ROOT / "skills" / "factor-forge-step4" / "scripts"
LEGACY_REPO = Path("/home/ubuntu/.openclaw/workspace/repos/factor-factory")
LEGACY_RUNTIME = Path("/home/ubuntu/.openclaw/workspace/factorforge")


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("filename", "runtime_attribute"),
    [
        ("run_step4.py", "FACTORFORGE"),
        ("qlib_backtest_adapter.py", "FF"),
    ],
)
def test_step4_cold_import_ignores_inaccessible_legacy_paths(
    tmp_path,
    monkeypatch,
    filename,
    runtime_attribute,
):
    factor_root = tmp_path / "factor-workspace"
    factor_root.mkdir()
    original_exists = Path.exists

    def guarded_exists(path):
        if path in {LEGACY_REPO, LEGACY_RUNTIME}:
            raise PermissionError("legacy path is outside the service boundary")
        return original_exists(path)

    monkeypatch.setenv("FACTORFORGE_REPO_ROOT", str(PROJECT_ROOT))
    monkeypatch.setenv("FACTORFORGE_ROOT", str(factor_root))
    monkeypatch.setattr(Path, "exists", guarded_exists)

    module = _load_script(
        f"factorforge_{filename.replace('.', '_')}_permission_test",
        STEP4_SCRIPTS / filename,
    )

    assert module.REPO_ROOT == PROJECT_ROOT
    assert getattr(module, runtime_attribute) == factor_root


@pytest.mark.parametrize(
    ("filename", "runtime_attribute"),
    [
        ("run_step4.py", "FACTORFORGE"),
        ("qlib_backtest_adapter.py", "FF"),
    ],
)
def test_step4_cold_import_falls_back_when_legacy_paths_are_inaccessible(
    tmp_path,
    monkeypatch,
    filename,
    runtime_attribute,
):
    original_exists = Path.exists

    def guarded_exists(path):
        if path in {LEGACY_REPO, LEGACY_RUNTIME}:
            raise PermissionError("legacy path is outside the service boundary")
        return original_exists(path)

    monkeypatch.delenv("FACTORFORGE_REPO_ROOT", raising=False)
    monkeypatch.delenv("FACTORFORGE_ROOT", raising=False)
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    monkeypatch.setattr(Path, "exists", guarded_exists)

    module = _load_script(
        f"factorforge_{filename.replace('.', '_')}_fallback_permission_test",
        STEP4_SCRIPTS / filename,
    )

    assert module.REPO_ROOT == PROJECT_ROOT
    assert getattr(module, runtime_attribute) == PROJECT_ROOT


@pytest.mark.parametrize(
    "filename",
    ["self_quant_adapter.py", "qlib_backtest_adapter.py"],
)
def test_step4_matplotlib_cache_is_forced_inside_formal_factor_workspace(
    tmp_path,
    monkeypatch,
    filename,
):
    factor_workspace = tmp_path / "factor_research" / "FACTOR" / "research_id"
    factor_workspace.mkdir(parents=True)
    outside_cache = tmp_path / "outside" / "matplotlib"
    monkeypatch.setenv("FACTORFORGE_REPO_ROOT", str(PROJECT_ROOT))
    monkeypatch.setenv("FACTORFORGE_ROOT", str(factor_workspace))
    monkeypatch.setenv("FACTORFORGE_FACTOR_WORKSPACE", str(factor_workspace))
    monkeypatch.setenv("MPLCONFIGDIR", str(outside_cache))

    module = _load_script(
        f"factorforge_{filename.replace('.', '_')}_matplotlib_workspace_test",
        STEP4_SCRIPTS / filename,
    )

    expected = factor_workspace / ".cache" / "matplotlib"
    assert module.MPLCONFIGDIR == expected
    assert Path(os.environ["MPLCONFIGDIR"]) == expected
    assert expected.is_dir()
    assert not outside_cache.exists()


def test_native_qlib_report_sets_workspace_cache_before_matplotlib_import():
    source = (PROJECT_ROOT / "scripts/run_qlib_native_report.py").read_text(
        encoding="utf-8"
    )

    assert "FACTORFORGE_FACTOR_WORKSPACE" in source
    assert source.index('os.environ["MPLCONFIGDIR"]') < source.index(
        "import matplotlib"
    )
