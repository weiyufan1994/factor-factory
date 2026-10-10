# Installation checks on another machine

These commands operate on an unpacked delivery, not on a study or data mount.
They do not install global Skills, download market data or run OOS research.
The Linux template is provided for the remaining platform checks. It has not
been executed on the author's Mac, which currently has no container engine.

## Linux: Python 3.11 and 3.13, real root and non-root

From the directory containing `factor-forge/`, `factorforge-data-api/` and `wheels/`:

```sh
docker build --build-arg PYTHON_VERSION=3.11 \
  -f factor-forge/packaging/Dockerfile.offline-test -t factorforge-test-py311 .
docker run --rm --network none --read-only --tmpfs /tmp:rw,exec,size=2g \
  --user 0:0 factorforge-test-py311
docker run --rm --network none --read-only --tmpfs /tmp:rw,exec,size=2g \
  --user 10001:10001 factorforge-test-py311
```

Repeat with `PYTHON_VERSION=3.13` and tag `factorforge-test-py313`.
The image build needs public Python dependency access. Test execution has no
network and no host directory mounts. UID `0` is a real container root test;
UID `10001` is a separate non-root run, not an `os.getuid` mock.

Run installed-wheel imports separately, so source-path fallback cannot hide a
packaging defect:

```sh
docker run --rm --network none --read-only --tmpfs /tmp:rw,exec,size=2g \
  --user 10001:10001 factorforge-test-py311 \
  python tests/installed_wheel_import_check.py --python /usr/local/bin/python
```

The import checker uses isolated child interpreters and verifies every module
resolves from the installed distributions. It rejects editable installations.
Repeat for root and the other Python version. Preserve the actual logs and
dependency versions (`python -m pip freeze`) with the tested source commit.
An unexecuted template, a successful image build, or only one UID's result does
not count as the complete Linux matrix.

## macOS

Use the ordinary installation in `docs/quickstart-publish.zh-CN.md`, choosing the
constraints file for the tested Python version. Run the full offline suite,
the installed-wheel checker and the three manual examples. Do not describe
synthetic values or a mocked agent result as an independent factor study.
