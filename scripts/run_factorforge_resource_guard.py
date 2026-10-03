"""Outer resource watchdog, NOT a research gate. Default is non-executing.

The caller supplies an already selected argv and keeps all research approval
and manifest checks in the existing entrypoint. This is only a process monitor. Polling is not
a cgroup hard cap; spikes between samples and kill latency remain possible.
No retry, recovery, approval, or mathematical implementation is performed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import uuid

GIB, POLL, TIMEOUT = 1024**3, .05, 7200


def minimum_bytes(value):
    if not math.isfinite(value) or not 0 < value <= 4:
        raise ValueError('minimum-required-gib must be finite and in (0, 4]')
    return math.ceil(value*GIB)


def resource_limits(initial_free, available, minimum_required_gib):
    """Keep the original polling limits; required RAM is a caller estimate."""
    required = minimum_bytes(minimum_required_gib)
    if initial_free < 128*GIB:
        raise RuntimeError('INITIAL_DISK_BELOW_128_GIB')
    floor = max(128*GIB, initial_free-128*GIB)
    budget = min(4*GIB, int(.55*available))
    if budget < required:
        raise RuntimeError('FRESH_BUDGET_BELOW_DECLARED_REQUIREMENT')
    return floor, budget


def live_group_members(psutil, pgid):
    """Check only our owned group, including descendants reparented on exit."""
    members = []
    for item in psutil.process_iter():
        try:
            if os.getpgid(item.pid) != pgid:
                continue
            if item.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                members.append(item.pid)
        except (ProcessLookupError, psutil.NoSuchProcess):
            continue
    return members


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-reviewed-guard', action='store_true')
    parser.add_argument('--cwd', type=Path, required=True)
    parser.add_argument('--minimum-required-gib', type=float, required=True,
                        help='Caller-estimated minimum RAM, not proof the workload fits.')
    parser.add_argument('command', nargs=argparse.REMAINDER, help='-- followed by the exact reviewed argv')
    args = parser.parse_args()
    workspace = args.cwd.expanduser().resolve(strict=True)
    if not workspace.is_dir():
        parser.error('--cwd must be a directory')
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('an explicit command after -- is required')
    # Validate numeric arguments even for non-executing previews.
    minimum_bytes(args.minimum_required_gib)
    if not args.run_reviewed_guard:
        print(json.dumps({'status': 'NOT_EXECUTED_REVIEW_REQUIRED', 'command': command}))
        return 2
    import psutil
    initial_free = shutil.disk_usage(workspace).free
    available = psutil.virtual_memory().available
    floor, budget = resource_limits(initial_free, available, args.minimum_required_gib)
    logs = workspace/'logs'
    logs.mkdir(exist_ok=True)
    tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_'+uuid.uuid4().hex[:8]
    log_path = logs/('ultimate_guarded_'+tag+'.log')
    result_path = logs/('ultimate_guarded_'+tag+'.json')
    record = dict(command=command, cwd=str(workspace),
        guard_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        minimum_required_gib=args.minimum_required_gib, initial_free_bytes=initial_free,
        minimum_free_bytes=floor, available_memory_bytes=available, memory_budget_bytes=budget,
        timeout_seconds=TIMEOUT, poll_seconds=POLL, log_path=str(log_path),
        instantaneous_hard_limit=False, manager_gate_claim=False, retries=0)
    proc = None
    thread = None
    io_errors = []
    peak_processes = 0
    peak, min_free, start, failure = 0, initial_free, time.monotonic(), None
    # Exclusive creation before launch. Never truncate an existing result/log.
    with log_path.open('xb', buffering=0) as log, result_path.open('x') as result:
        try:
            proc = subprocess.Popen(command, cwd=workspace, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, start_new_session=True,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            monitor = psutil.Process()
            def drain():
                try:
                    while True:
                        block = proc.stdout.read(65536)
                        if not block:
                            break
                        view = memoryview(block)
                        while view:
                            written = log.write(view)
                            if not written:
                                raise OSError('LOG_WRITE_NO_PROGRESS')
                            view = view[written:]
                except BaseException as exc:
                    io_errors.append(type(exc).__name__+':'+str(exc))
            thread = threading.Thread(target=drain, daemon=True)
            thread.start()
            while proc.poll() is None:
                rss = monitor.memory_info().rss
                try:
                    root = psutil.Process(proc.pid)
                    processes = [root, *root.children(recursive=True)]
                except psutil.NoSuchProcess:
                    processes = []
                peak_processes = max(peak_processes, 1 + len(processes))
                for item in processes:
                    try:
                        rss += item.memory_info().rss
                    except psutil.NoSuchProcess:
                        pass
                peak = max(peak, rss)
                free = shutil.disk_usage(workspace).free
                min_free = min(min_free, free)
                if io_errors: failure = 'LOG_STREAM_FAILED'
                elif rss > budget: failure = 'RSS_BUDGET_EXCEEDED'
                elif free < floor: failure = 'DISK_SAFETY_FLOOR_EXCEEDED'
                elif time.monotonic()-start > TIMEOUT: failure = 'WALL_TIMEOUT'
                if failure:
                    break
                time.sleep(POLL)
        except BaseException as exc:
            failure = type(exc).__name__+':'+str(exc)
        finally:
            if proc is not None:
                if failure or proc.poll() is None:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                proc.wait()
                # A caller may exit zero while an inherited-group child is
                # still running with stdout closed. Pipe EOF is not completion.
                try:
                    remaining = live_group_members(psutil, proc.pid)
                    record['live_owned_group_pids_at_parent_exit'] = remaining
                    if remaining:
                        failure = failure or 'OWNED_PROCESS_GROUP_LEFT_RUNNING'
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                except Exception as exc:
                    failure = failure or 'OWNED_PROCESS_GROUP_CHECK_FAILED'
                    record['group_check_error'] = type(exc).__name__+':'+str(exc)
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                if thread is not None: thread.join(timeout=5)
                if thread is not None and thread.is_alive():
                    failure = failure or 'LOG_DRAIN_INCOMPLETE'
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    thread.join(timeout=2)
                if io_errors: failure = failure or 'LOG_STREAM_FAILED'
                if proc.returncode != 0: failure = failure or 'GUARDED_PROCESS_NONZERO_EXIT'
            record.update(status='FAILED' if failure else 'GUARDED_PROCESS_EXITED_ZERO',
                failure=failure, child_exit_code=None if proc is None else proc.returncode,
                sampled_combined_peak_rss_bytes=peak, sampled_peak_process_count=peak_processes, minimum_observed_free_bytes=min_free,
                elapsed_seconds=time.monotonic()-start, log_errors=io_errors)
            json.dump(record, result, indent=2); result.flush()
    print(json.dumps({'result': str(result_path), 'status': record['status']}))
    return 2 if failure else 0


if __name__ == '__main__':
    raise SystemExit(main())
