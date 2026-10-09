"""Offline imports need neither a configured market-data root nor write access.

This is the initial SDK/Step3 scope, not an all-module or Linux-container audit.
The simulated-root case reproduces the root-guard regression on developer Macs;
the unmodified-identity case also runs as real root when invoked in a container.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
IMPORT_TARGETS = (
    "factor_factory.factors",
    "factor_factory.research_api",
    "factor_factory.portfolio_api",
    "factor_factory.result_artifacts",
    "factor_factory.data_api",
    "factor_factory.data_access.paths",
    "factor_factory.data_access.clean_layer",
    "factor_factory.step5.case_builder",
    "factor_factory.step5.evaluator",
    "factor_factory.data_access.calendar_snapshot",
    "factor_factory.evaluation_contract",
    "factor_factory.knowledge_context",
    "factor_factory.step6.journal",
    "factor_factory.step6.packets",
    "factor_factory.epistemic_kernel_inputs",
    "factor_factory.epistemic_ultimate_shadow",
    "factor_factory.epistemic_ultimate_source_first_bridge",
    "skills/factor-forge-step3/scripts/run_step3.py",
)


@pytest.mark.parametrize("target", IMPORT_TARGETS)
@pytest.mark.parametrize("identity", ("current-user", "simulated-root"))
def test_import_without_data_configuration_or_io(tmp_path, target, identity):
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("FACTORFORGE_", "PYTHON"))
    }
    env.update(HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    code = r'''
import importlib
import importlib.util
import os
from pathlib import Path
import sys

root, target, identity = sys.argv[1:]
sys.path.insert(0, root)
if identity == "simulated-root":
    os.geteuid = lambda: 0

# An import may read source/dependency files but cannot start work or open data.
def check_io(event, args):
    if event.startswith("socket.") or event in {"subprocess.Popen", "os.system"}:
        raise AssertionError(f"import attempted external I/O: {event}")
    if event in {"os.mkdir", "os.remove", "os.rename", "os.rmdir", "os.chmod",
                 "os.link", "os.symlink", "os.truncate"}:
        raise AssertionError(f"import attempted filesystem mutation: {event}")
    if event == "open":
        path, mode, flags = args
        if (flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise AssertionError(f"import attempted file write: {path}")
        if isinstance(path, (str, bytes)):
            name = os.fsdecode(path)
            if Path(name).suffix in {".parquet", ".csv", ".sqlite", ".h5", ".pkl"}:
                raise AssertionError(f"import attempted data read: {path}")

sys.addaudithook(check_io)
if target.endswith(".py"):
    spec = importlib.util.spec_from_file_location("import_safety_step3", Path(root) / target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
else:
    module = importlib.import_module(target)
assert Path(module.__file__).resolve().is_relative_to(Path(root).resolve())
'''
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code, str(ROOT), target, identity],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert list(tmp_path.iterdir()) == []


def test_local_reader_retains_explicit_root_requirement(monkeypatch, tmp_path):
    from factor_factory.data_access import paths

    monkeypatch.delenv("FACTORFORGE_LOCAL_DATA_ROOT", raising=False)
    monkeypatch.setattr(paths, "_running_as_root", lambda: True)
    monkeypatch.setattr(paths, "DEFAULT_EC2_PERSISTENT_ROOT", tmp_path / "absent")
    with pytest.raises(RuntimeError, match="FACTORFORGE_LOCAL_DATA_ROOT must be set"):
        paths.resolve_local_tushare_paths()
    monkeypatch.setenv("FACTORFORGE_LOCAL_DATA_ROOT", str(tmp_path / "explicit"))
    assert paths.default_local_data_root() == tmp_path / "explicit"


def test_clean_layer_configuration_is_read_at_use_time(monkeypatch, tmp_path):
    from factor_factory.data_access.clean_layer import resolve_clean_daily_layer_paths

    monkeypatch.delenv("FACTORFORGE_CLEAN_DAILY_DIR", raising=False)
    monkeypatch.setenv("FACTORFORGE_ROOT", str(tmp_path / "first-study"))
    assert resolve_clean_daily_layer_paths().root == tmp_path / "first-study/data/clean"
    monkeypatch.setenv("FACTORFORGE_ROOT", str(tmp_path / "second-study"))
    assert resolve_clean_daily_layer_paths().root == tmp_path / "second-study/data/clean"
    monkeypatch.setenv("FACTORFORGE_CLEAN_DAILY_DIR", str(tmp_path / "explicit-clean"))
    assert resolve_clean_daily_layer_paths().root == tmp_path / "explicit-clean"


def test_local_default_uses_current_home_not_import_time_home(monkeypatch, tmp_path):
    from factor_factory.data_access import paths

    monkeypatch.delenv("FACTORFORGE_LOCAL_DATA_ROOT", raising=False)
    monkeypatch.setattr(paths, "_running_as_root", lambda: False)
    monkeypatch.setattr(paths, "DEFAULT_EC2_PERSISTENT_ROOT", tmp_path / "absent")
    # expanduser consults the process home, so change it only for this test.
    monkeypatch.setenv("HOME", str(tmp_path / "current-home"))
    assert paths.default_local_data_root() == tmp_path / "current-home/.qlib/raw_tushare"


def test_implementation_loader_ignores_unrelated_or_protected_names(monkeypatch, tmp_path):
    from factor_factory.implementation_runtime import load_implementation

    unrelated = tmp_path / "unrelated-project"
    protected = tmp_path / "factor_factory"
    unrelated.mkdir()
    protected.mkdir()
    (tmp_path / "cleanup_helper.py").write_text("VALUE = 21\n")
    implementation = tmp_path / "factor.py"
    implementation.write_text("from cleanup_helper import VALUE\ndef result():\n    return 2 * VALUE\n")
    real_stat = Path.stat

    def guarded_stat(path, *args, **kwargs):
        if path in {unrelated, protected}:
            raise PermissionError("unrelated project is outside this study")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", guarded_stat)
    original_path = list(sys.path)
    module = load_implementation(implementation, workspace=tmp_path)
    assert module.result() == 42
    assert sys.path == original_path
    assert "cleanup_helper" not in sys.modules


def test_implementation_loader_reports_unreadable_python_candidate(monkeypatch, tmp_path):
    from factor_factory.implementation_runtime import load_implementation

    helper = tmp_path / "cleanup_helper.py"
    helper.write_text("VALUE = 21\n")
    implementation = tmp_path / "factor.py"
    implementation.write_text("from cleanup_helper import VALUE\n")
    real_stat = Path.stat

    def guarded_stat(path, *args, **kwargs):
        if path == helper:
            raise PermissionError("selected Python helper is unreadable")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", guarded_stat)
    with pytest.raises(PermissionError, match="selected Python helper"):
        load_implementation(implementation, workspace=tmp_path)
