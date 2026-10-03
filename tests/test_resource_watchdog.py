"""Bounded synthetic process monitoring only; no research or market execution."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resource_watchdog', ROOT/'scripts/run_factorforge_resource_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
GIB = guard.GIB


def report(tmp_path):
    return json.loads(next((tmp_path/'logs').glob('*.json')).read_text())


def fixture(tmp_path, monkeypatch, *, root_rss=100, free=500*GIB, available=8*GIB, exit_code=0, bad_log=False):
    calls = []
    class Broken(io.BytesIO):
        def read(self, *args): raise OSError('synthetic drain failure')
    class Child:
        pid = 999999
        stdout = Broken() if bad_log else io.BytesIO(b'SYNTHETIC OUTPUT\n')
        returncode = None
        ticks = 0
        def poll(self):
            self.ticks += 1
            if self.ticks > 3 and self.returncode is None: self.returncode = exit_code
            return self.returncode
        def wait(self):
            if self.returncode is None: self.returncode = exit_code
            return self.returncode
    child = Child()
    def start(argv, **kwargs): calls.append(('launch', list(argv), kwargs)); return child
    def kill(pgid, sig): calls.append(('kill', pgid, sig)); child.returncode = -9
    class Process:
        def __init__(self, pid=None): self.pid = pid
        def memory_info(self):
            return SimpleNamespace(rss={None:100,999999:root_rss,2:200,3:300}[self.pid])
        def children(self, recursive):
            assert recursive is True
            return [Process(2), Process(3)]
    class NoSuchProcess(Exception): pass
    monkeypatch.setitem(sys.modules, 'psutil', SimpleNamespace(Process=Process, NoSuchProcess=NoSuchProcess,
        virtual_memory=lambda: SimpleNamespace(available=available), process_iter=lambda: [],
        STATUS_ZOMBIE='zombie', STATUS_DEAD='dead'))
    monkeypatch.setattr(guard.subprocess, 'Popen', start)
    monkeypatch.setattr(guard.os, 'killpg', kill)
    count = [0]
    def disk(_):
        count[0] += 1
        return SimpleNamespace(free=500*GIB if count[0] == 1 else free)
    monkeypatch.setattr(guard.shutil, 'disk_usage', disk)
    monkeypatch.setattr(guard, 'POLL', 0.)
    monkeypatch.setattr(sys, 'argv', ['guard', '--cwd', str(tmp_path), '--minimum-required-gib', '3.615',
                                    '--run-reviewed-guard', '--', 'synthetic-executable', 'literal;argument'])
    return calls


def test_preview_never_spawns_or_creates_logs(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'argv', [x for x in sys.argv if x != '--run-reviewed-guard'])
    assert guard.main() == 2
    assert not calls and not (tmp_path/'logs').exists()


def test_success_sums_monitor_root_and_recursive_children(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch)
    assert guard.main() == 0
    assert [x[0] for x in calls] == ['launch']
    assert calls[0][1] == ['synthetic-executable', 'literal;argument']
    assert calls[0][2]['start_new_session'] is True and 'shell' not in calls[0][2]
    r = report(tmp_path)
    assert r['sampled_combined_peak_rss_bytes'] == 700 and r['sampled_peak_process_count'] == 4
    assert r['status'] == 'GUARDED_PROCESS_EXITED_ZERO'
    assert r['manager_gate_claim'] is False and r['instantaneous_hard_limit'] is False
    assert next((tmp_path/'logs').glob('*.log')).read_bytes() == b'SYNTHETIC OUTPUT\n'


@pytest.mark.parametrize('reason', ['RSS_BUDGET_EXCEEDED', 'DISK_SAFETY_FLOOR_EXCEEDED', 'WALL_TIMEOUT', 'LOG_STREAM_FAILED'])
def test_failures_stop_only_the_created_group(tmp_path, monkeypatch, reason):
    calls = fixture(tmp_path, monkeypatch, root_rss=5*GIB if reason.startswith('RSS') else 100,
                    free=300*GIB if reason.startswith('DISK') else 500*GIB,
                    bad_log=reason == 'LOG_STREAM_FAILED')
    if reason == 'WALL_TIMEOUT': monkeypatch.setattr(guard, 'TIMEOUT', -1)
    assert guard.main() == 2
    assert report(tmp_path)['failure'] == reason
    assert [x[1] for x in calls if x[0] == 'kill'] == [999999]


def test_nonzero_exit_stays_failure(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch, exit_code=7)
    assert guard.main() == 2
    assert report(tmp_path)['failure'] == 'GUARDED_PROCESS_NONZERO_EXIT'
    assert report(tmp_path)['child_exit_code'] == 7


def test_low_fresh_budget_starts_nothing(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch, available=2*GIB)
    with pytest.raises(RuntimeError, match='FRESH_BUDGET'): guard.main()
    assert not calls


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 0., -1., 4.01])
def test_bad_declared_requirement_rejected(value):
    with pytest.raises(ValueError): guard.resource_limits(500*GIB, 8*GIB, value)


def test_original_limits_and_disk_boundaries():
    assert guard.resource_limits(500*GIB, 8*GIB, 3.615) == (372*GIB, 4*GIB)
    assert guard.resource_limits(200*GIB, 4*GIB, 1.) == (128*GIB, int(.55*4*GIB))
    assert guard.resource_limits(200*GIB, 8*GIB, 4.) == (128*GIB, 4*GIB)
    with pytest.raises(RuntimeError, match='INITIAL_DISK'): guard.resource_limits(127*GIB, 8*GIB, 1.)


def test_exit_check_selects_only_owned_live_group(monkeypatch):
    def vanished(): raise ProcessLookupError()
    def never_read(): pytest.fail('other groups are not inspected further')
    rows = [SimpleNamespace(pid=1, status=lambda: 'running'),
            SimpleNamespace(pid=2, status=never_read),
            SimpleNamespace(pid=3, status=lambda: 'zombie'),
            SimpleNamespace(pid=4, status=never_read)]
    class NoSuchProcess(Exception): pass
    psutil = SimpleNamespace(process_iter=lambda: rows, STATUS_ZOMBIE='zombie',
                             STATUS_DEAD='dead', NoSuchProcess=NoSuchProcess)
    monkeypatch.setattr(guard.os, 'getpgid', lambda pid: vanished() if pid == 4 else 99 if pid != 2 else 88)
    assert guard.live_group_members(psutil, 99) == [1]


def test_successive_logs_do_not_replace_previous_evidence(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    assert guard.main() == 0
    saved = {p: p.read_bytes() for p in (tmp_path/'logs').iterdir()}
    fixture(tmp_path, monkeypatch)
    assert guard.main() == 0
    assert len(list((tmp_path/'logs').iterdir())) == 4
    assert all(p.read_bytes() == b for p, b in saved.items())


def test_real_small_subprocess_tree_is_observed_and_completes(tmp_path, monkeypatch):
    # Only tiny local Python processes. Host disk/RAM reads are synthetic so
    # this control test makes no claim about a research workload's capacity.
    import psutil
    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(available=8*GIB))
    monkeypatch.setattr(guard.shutil, 'disk_usage', lambda _: SimpleNamespace(free=500*GIB))
    leaf = 'import time; time.sleep(0.5); print("synthetic leaf")'
    middle = 'import subprocess,sys; subprocess.run([sys.executable,"-c",'+repr(leaf)+'],check=True)'
    root = 'import subprocess,sys; subprocess.run([sys.executable,"-c",'+repr(middle)+'],check=True)'
    monkeypatch.setattr(sys, 'argv', ['guard','--cwd',str(tmp_path),'--minimum-required-gib','.01',
                                    '--run-reviewed-guard','--',sys.executable,'-c',root])
    assert guard.main() == 0
    r = report(tmp_path)
    assert r['sampled_peak_process_count'] >= 4
    assert r['sampled_combined_peak_rss_bytes'] > 0
    assert 'synthetic leaf' in Path(r['log_path']).read_text()


def test_parent_zero_exit_with_silent_live_child_is_failure_and_child_is_stopped(tmp_path, monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(available=8*GIB))
    monkeypatch.setattr(guard.shutil, 'disk_usage', lambda _: SimpleNamespace(free=500*GIB))
    pid_path = tmp_path/'synthetic-child.pid'
    code = ('import subprocess,sys,pathlib; p=subprocess.Popen([sys.executable,"-c",'
            '"import time; time.sleep(30)"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
            'pathlib.Path('+repr(str(pid_path))+').write_text(str(p.pid))')
    monkeypatch.setattr(sys, 'argv', ['guard','--cwd',str(tmp_path),'--minimum-required-gib','.01',
                                    '--run-reviewed-guard','--',sys.executable,'-c',code])
    child = None
    try:
        assert guard.main() == 2
        r = report(tmp_path)
        assert r['child_exit_code'] == 0 and r['failure'] == 'OWNED_PROCESS_GROUP_LEFT_RUNNING'
        pid = int(pid_path.read_text())
        assert pid in r['live_owned_group_pids_at_parent_exit']
        try: child = psutil.Process(pid)
        except psutil.NoSuchProcess: return
        deadline = time.monotonic()+2
        while True:
            try:
                if not child.is_running() or child.status() in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                    break
            except psutil.NoSuchProcess:
                break  # Process disappearance is successful termination too.
            assert time.monotonic() < deadline
            time.sleep(.01)
    finally:
        # Contain even a failing control test to its own known synthetic child.
        if child is None and pid_path.exists():
            try: child = psutil.Process(int(pid_path.read_text()))
            except psutil.NoSuchProcess: pass
        if child is not None:
            try: child.kill()
            except psutil.NoSuchProcess: pass
