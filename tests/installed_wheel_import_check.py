"""Check every installed SDK module in a fresh, read-only child process.

Run with --python pointing to a wheel-only virtual environment. This verifies
imports, not data access, agent reasoning, research results or backend parity.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import tempfile


DISCOVER = r'''
import importlib.metadata as metadata
import json
import sys
items = []
for name in sys.argv[1:]:
    distribution = metadata.distribution(name)
    if distribution.read_text('direct_url.json'):
        direct = json.loads(distribution.read_text('direct_url.json'))
        if direct.get('dir_info', {}).get('editable'):
            raise RuntimeError('wheel-only environment required: ' + name)
    for file in distribution.files or []:
        parts = list(file.parts)
        if file.suffix != '.py' or not parts[0].isidentifier():
            continue
        if parts[-1] == '__init__.py':
            parts.pop()
        else:
            parts[-1] = file.stem
        if parts and all(part.isidentifier() for part in parts):
            items.append('.'.join(parts))
print(json.dumps(sorted(set(items))))
'''

PROBE = r'''
import importlib
import os
from pathlib import Path
import sys
import sysconfig

def deny_side_effects(event, args):
    if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system', 'os.fork'}:
        raise RuntimeError('import side effect: ' + event)
    if event in {'os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'os.symlink',
                 'os.link', 'os.chmod', 'os.truncate', 'os.utime'}:
        raise RuntimeError('import mutation: ' + event)
    if event == 'open':
        filename, mode, flags = args
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        ):
            raise RuntimeError('import write: ' + str(filename))
        if isinstance(filename, str) and Path(filename).suffix.lower() in {'.parquet', '.csv', '.feather'}:
            raise RuntimeError('import data read: ' + filename)

sys.addaudithook(deny_side_effects)
module = importlib.import_module(sys.argv[1])
path = Path(module.__file__).resolve()
installed = Path(sysconfig.get_paths()['purelib']).resolve()
if not path.is_relative_to(installed):
    raise RuntimeError('module not loaded from installed wheel: ' + str(path))
'''


def verify(python: str, distributions: list[str]) -> dict:
    with tempfile.TemporaryDirectory(prefix='factorforge-import-check-') as directory:
        environment = {name: value for name, value in os.environ.items()
                       if not name.startswith(('FACTORFORGE', 'PYTHON', 'PFVV'))}
        environment.update(HOME=directory, XDG_CACHE_HOME=directory)
        modules = json.loads(subprocess.check_output(
            [python, '-I', '-B', '-c', DISCOVER, *distributions],
            cwd=directory, env=environment, text=True,
        ))
        if not modules:
            raise RuntimeError('no installed Python modules discovered')

        def probe(module):
            try:
                result = subprocess.run(
                    [python, '-I', '-B', '-c', PROBE, module],
                    cwd=directory, env=environment, text=True,
                    capture_output=True, timeout=60, check=False,
                )
                return {'module': module, 'passed': result.returncode == 0,
                        'error': result.stderr[-3000:] if result.returncode else None}
            except subprocess.TimeoutExpired:
                return {'module': module, 'passed': False, 'error': 'import exceeded 60 seconds'}

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(probe, modules))
        unexpected_files = sorted(str(path.relative_to(directory)) for path in Path(directory).rglob('*'))
    return {
        'distributions': distributions, 'module_count': len(results),
        'passed': sum(row['passed'] for row in results),
        'failures': [row for row in results if not row['passed']],
        'unexpected_files': unexpected_files,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', required=True, help='Python executable in the installed-wheel environment')
    parser.add_argument('--report', type=Path, help='Optional check output; not a research result')
    args = parser.parse_args()
    result = verify(args.python, ['factor-factory', 'factorforge-data-api'])
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.report:
        args.report.write_text(text)
    print(text, end='')
    return int(bool(result['failures'] or result['unexpected_files']))


if __name__ == '__main__':
    raise SystemExit(main())
