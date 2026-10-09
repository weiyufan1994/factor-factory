#!/usr/bin/env python3
"""Build a bounded, private-repository candidate Factor Forge source bundle."""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile, zipfile
from fnmatch import fnmatchcase
import tarfile
import tomllib
from pathlib import Path, PurePosixPath
try:
    from scripts.build_factorforge_knowledge_preview import _scrub, build_preview
    from scripts.build_factorforge_retrieval_index import active_workspace_exports
except ModuleNotFoundError:
    from build_factorforge_knowledge_preview import _scrub, build_preview
    from build_factorforge_retrieval_index import active_workspace_exports

TOP_LEVEL_DIRS = {"factor_factory", "scripts", "skills", "tests", "examples", "fixtures", "docs", "packaging"}
ROOT_FILES = {".gitignore", "AGENTS.md", "pyproject.toml", "requirements-test.txt", "requirements-knowledge.txt", "pytest-offline.ini"}
BINARY_SUFFIXES = {".parquet", ".pdf", ".pkl", ".sqlite"}
CACHE_DIRS = {".venv", "__pycache__", ".pytest_cache"}
EXPORT_ROOT = Path("knowledge/因子工厂/workspace_experience_exports")
ALLOWED_EXPORT_IDS = {"RPT_pdf_11d72_pfvv_20250508_mszq", "RPT_web_8596d811_20250508_mszq_intraday_momentum_pulse"}
AWS_ACCESS_KEY_VALUE = re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
PEM_PRIVATE_KEY = re.compile(rb"-----BEGIN (?P<label>[A-Z0-9 ]*PRIVATE KEY)-----\r?\n(?:[A-Za-z0-9+/=]+\r?\n)+-----END (?P=label)-----")

def _safe_relative(rel: str) -> bool:
    candidate = PurePosixPath(rel)
    return bool(rel) and not candidate.is_absolute() and ".." not in candidate.parts and "." not in candidate.parts

def _git_metadata(root: Path) -> tuple[list[str], str | None, str | None]:
    try:
        raw_paths = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root, stderr=subprocess.PIPE)
        paths = [item.decode("utf-8", "surrogateescape") for item in raw_paths.split(b"\0") if item]
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip() or None
        return paths, head, branch
    except (OSError, subprocess.CalledProcessError):
        paths = [name for name in ROOT_FILES if (root / name).is_file()]
        for directory in TOP_LEVEL_DIRS:
            candidate = root / directory
            if not candidate.is_dir() or candidate.is_symlink():
                continue
            for base, directories, filenames in os.walk(candidate, followlinks=False):
                base_path = Path(base)
                if any((base_path / name).is_symlink() for name in directories):
                    raise ValueError(f"unsafe symlink directory in fallback source selection: {base_path.relative_to(root)}")
                directories[:] = [name for name in directories if name not in CACHE_DIRS and name != ".git"]
                for filename in filenames:
                    path = base_path / filename
                    if path.is_file():
                        paths.append(path.relative_to(root).as_posix())
        return paths, None, None

def _excluded(path: str) -> bool:
    return path.endswith(".pyc") or any(part in CACHE_DIRS for part in PurePosixPath(path).parts)

def _allowed(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(parts) and (parts[0] in TOP_LEVEL_DIRS or path in ROOT_FILES)

def _select(root: Path) -> tuple[list[str], list[str]]:
    candidates, _, _ = _git_metadata(root)
    selection = root / "packaging/research-files.toml"
    rules = tomllib.loads(selection.read_text(encoding="utf-8"))["framework"] if selection.is_file() else None
    selected, excluded = [], []
    for rel in sorted(set(candidates)):
        if not _safe_relative(rel):
            raise ValueError(f"unsafe source path reported by selection: {rel}")
        allowed = (_matches(rel, rules["include"]) and not _matches(rel, rules["exclude"])) if rules else _allowed(rel)
        (excluded if _excluded(rel) or not allowed else selected).append(rel)
    return selected, excluded


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def _snapshot_source(root: Path, revision: str, destination: Path) -> dict[str, str]:
    """Copy only chosen commit bytes; dirty/untracked work never enters a release."""
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)

    head = git("rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}").decode().strip()
    tree = git("rev-parse", f"{head}^{{tree}}").decode().strip()
    selector = "packaging/research-files.toml"
    rules = tomllib.loads(git("show", f"{head}:{selector}").decode())
    for group in ("framework", "knowledge_input", "data_sdk"):
        if not isinstance(rules.get(group, {}).get("include"), list):
            raise ValueError(f"missing distribution selection: {group}")
    framework = rules["framework"]

    def selected(path: str) -> bool:
        return not _excluded(path) and (
            (_matches(path, framework["include"]) and not _matches(path, framework["exclude"]))
            or _matches(path, rules["knowledge_input"]["include"])
        )

    destination.mkdir()
    # Streaming tar avoids materializing a repository-sized byte string. Extraction
    # uses validated individual regular members, never tar.extract/all or symlinks.
    process = subprocess.Popen(["git", "archive", "--format=tar", head], cwd=root,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdout is not None
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                if member.isdir() or not selected(member.name):
                    continue
                if not _safe_relative(member.name) or not member.isfile():
                    raise ValueError(f"unsafe selected Git member: {member.name}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"missing selected Git blob: {member.name}")
                target = destination / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream, target.open("xb") as output:
                    shutil.copyfileobj(stream, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
        stderr = process.stderr.read().decode() if process.stderr else ""
        if process.wait() != 0:
            raise ValueError(f"Git snapshot failed: {stderr.strip()}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
    return {"commit": head, "tree": tree}

def _check_file(source: Path, rel: str, *, within: Path | None = None) -> None:
    if source.is_symlink() or not source.is_file(): raise ValueError(f"unsafe or missing source path: {rel}")
    if within is not None:
        cursor = source.parent
        while cursor != within:
            if cursor.is_symlink(): raise ValueError(f"unsafe symlink ancestor in source path: {rel}")
            if within not in cursor.parents: raise ValueError(f"source path escapes expected root: {rel}")
            cursor = cursor.parent
    if source.suffix.casefold() in BINARY_SUFFIXES: raise ValueError(f"binary dataset/document is not publishable: {rel}")
    payload = source.read_bytes()
    if PEM_PRIVATE_KEY.search(payload) or AWS_ACCESS_KEY_VALUE.search(payload): raise ValueError(f"secret material detected in publish path: {rel}")

def _copy_mode(source: Path, target: Path, *, source_root: Path) -> None:
    _check_file(source, source.relative_to(source_root).as_posix(), within=source_root)
    target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
    target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)

def _package_export_seeds(source_root: Path, staging: Path) -> None:
    """Project precisely two active advisory records, never their originals."""
    active = {payload["report_id"]: (path, payload) for path, payload in active_workspace_exports(source_root / EXPORT_ROOT)}
    if not ALLOWED_EXPORT_IDS.issubset(active): raise ValueError("publish bundle is missing an approved active workspace export seed")
    target_root = staging / EXPORT_ROOT; target_root.mkdir(parents=True, exist_ok=True)
    for report_id in sorted(ALLOWED_EXPORT_IDS):
        source, payload = active[report_id]; _check_file(source, source.relative_to(source_root).as_posix(), within=source_root); raw = source.read_bytes(); sanitized = _scrub(payload)
        if not isinstance(sanitized, dict): raise ValueError(f"invalid scrubbed workspace export: {source.name}")
        revision = sanitized.pop("export_revision", None)
        sanitized["package_projection"] = {"projection_version": "factorforge_publish_candidate_seed_v1", "sanitized": True, "source_export_sha256": hashlib.sha256(raw).hexdigest(), "original_source_record_included": False, "original_source_record_verified_in_package": False}
        if revision is not None: sanitized["package_projection"]["source_revision_context_not_replayable"] = revision
        # Corrections become a stable basename: no unreplayable supersession chain.
        target = target_root / f"knowledge_record__{report_id}.json"
        target.write_text(json.dumps(sanitized, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"); target.chmod(0o644)

def _rebuild_staging_index(staging: Path) -> None:
    """Run the copied indexer so REPO_ROOT resolves to staging, never source."""
    stale = staging / "knowledge/retrieval"
    if stale.is_symlink(): raise ValueError("unsafe retrieval directory in staging")
    if stale.exists(): shutil.rmtree(stale)  # staging-only preview artifact
    command = [sys.executable, "scripts/build_factorforge_retrieval_index.py", "--runtime-root", str(staging)]
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH" and not key.startswith("FACTORFORGE_")}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try: subprocess.run(command, cwd=staging, check=True, capture_output=True, text=True, env=environment)
    except subprocess.CalledProcessError as exc: raise ValueError(f"staging-only retrieval index rebuild failed: {exc.stderr.strip() or exc.stdout.strip()}") from exc
    index = staging / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    paths = {json.loads(line)["source_path"] for line in index.read_text(encoding="utf-8").splitlines() if line.strip()}
    expected = {(EXPORT_ROOT / f"knowledge_record__{report_id}.json").as_posix() for report_id in ALLOWED_EXPORT_IDS}
    if paths != expected: raise ValueError("staging retrieval index source_paths do not match packaged export seeds")

def _inventory(staging: Path, *, head: str | None, branch: str | None, selected: list[str], excluded: list[str]) -> dict[str, object]:
    files = []
    for path in sorted(staging.rglob("*")):
        if path.is_symlink(): raise ValueError(f"symlink entered publish staging: {path.relative_to(staging)}")
        if path.is_file():
            rel = path.relative_to(staging).as_posix()
            if rel.endswith(".pyc") or any(part in CACHE_DIRS for part in PurePosixPath(rel).parts): raise ValueError(f"cache entered publish staging: {rel}")
            _check_file(path, rel, within=staging); raw = path.read_bytes()
            files.append({"path": rel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return {"format": "factorforge-publish-inventory-v1", "source_head": head, "source_branch": branch, "selected_paths": selected, "excluded_paths": excluded, "files": files}

def _copy_data_sdk(source: Path, target: Path, rules: dict) -> list[dict]:
    """Copy the explicit SDK input without its production build/operations scripts."""
    rows = []
    for base, directories, filenames in os.walk(source, followlinks=False):
        base_path = Path(base)
        directories[:] = [name for name in directories if name not in CACHE_DIRS and name != ".git"]
        for name in directories:
            if (base_path / name).is_symlink():
                raise ValueError(f"unsafe Data SDK directory: {base_path / name}")
        for name in sorted(filenames):
            path = base_path / name
            rel = path.relative_to(source).as_posix()
            if _excluded(rel) or not _matches(rel, rules["include"]):
                continue
            _copy_mode(path, target / rel, source_root=source)
            raw = (target / rel).read_bytes()
            rows.append({"path": rel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    if not (target / "pyproject.toml").is_file() or not (target / "factorforge_data_api/client.py").is_file():
        raise ValueError("selected Data SDK must include pyproject.toml and the real client")
    return sorted(rows, key=lambda row: row["path"])


def _build_wheel(source: Path, destination: Path, *, python: str) -> dict:
    """Build offline from a disposable source copy, then inspect the actual wheel."""
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="factorforge-wheel-") as temp:
        build_source = Path(temp) / "source"
        shutil.copytree(source, build_source)
        command = [python, "-B", "-c", (
            "import setuptools.build_meta, sys; "
            "setuptools.build_meta.build_wheel(sys.argv[1])"
        ), str(destination)]
        env = {key: value for key, value in os.environ.items()
               if key != "PYTHONPATH" and not key.startswith("FACTORFORGE_")}
        completed = subprocess.run(command, cwd=build_source, env=env, capture_output=True, text=True)
        if completed.returncode:
            raise ValueError("offline wheel build failed; install the build extra in the selected Python: "
                             + (completed.stderr or completed.stdout)[-2000:])
    candidates = list(destination.glob("*.whl"))
    if len(candidates) != 1:
        raise ValueError("wheel build did not produce exactly one wheel")
    wheel = candidates[0]
    expected = {path.relative_to(source).as_posix() for path in source.rglob("*.py")
                if path.relative_to(source).parts[0] in {"factor_factory", "factorforge_data_api"}}
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        packaged = {name for name in names if name.endswith(".py")}
        if packaged != expected:
            raise ValueError(f"wheel/source module mismatch: missing={sorted(expected - packaged)}, "
                             f"extra={sorted(packaged - expected)}")
        for name in packaged:
            if archive.read(name) != (source / name).read_bytes():
                raise ValueError(f"wheel source differs: {name}")
        if len(names) != len(set(names)) or any(not _safe_relative(name) for name in names):
            raise ValueError("duplicate or unsafe path in wheel")
    raw = wheel.read_bytes()
    return {"filename": wheel.name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "modules": sorted(packaged)}


def _build_tree_bundle(*, source_root: Path, output: Path, source_identity: dict | None = None,
                       data_sdk_root: Path | None = None, build_python: str | None = None) -> Path:
    """Internal staging path; public releases always arrive through a Git snapshot."""
    root, output = source_root.expanduser().resolve(), output.expanduser().resolve()
    if output.exists(): raise FileExistsError(f"refuse to overwrite existing output: {output}")
    selected, excluded = _select(root); _, head, branch = _git_metadata(root)
    if source_identity is not None:
        head, branch = source_identity["commit"], None
    quickstart = root / "docs/quickstart-publish.zh-CN.md"
    if not quickstart.is_file() or quickstart.is_symlink(): raise FileNotFoundError("required package guide missing: docs/quickstart-publish.zh-CN.md")
    with tempfile.TemporaryDirectory(prefix="factorforge-publish-") as temp:
        preview, staging = Path(temp) / "knowledge-preview.zip", Path(temp) / "factor-forge"; build_preview(source_root=root, output=preview); staging.mkdir()
        for rel in selected: _copy_mode(root / rel, staging / rel, source_root=root)
        for name in ("README.md", "README.zh-CN.md"): _copy_mode(quickstart, staging / name, source_root=root)
        with zipfile.ZipFile(preview) as archive:
            for name in archive.namelist():
                if name == "query_knowledge.py" or name.startswith("knowledge/"):
                    if not _safe_relative(name): raise ValueError(f"unsafe knowledge preview path: {name}")
                    if name.endswith("/"): continue
                    target = staging / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(archive.read(name)); target.chmod(0o755 if name == "query_knowledge.py" else 0o644)
        shutil.rmtree(staging / "knowledge/experience_previews", ignore_errors=True)
        _package_export_seeds(root, staging); _rebuild_staging_index(staging)
        inventory = _inventory(staging, head=head, branch=branch, selected=selected, excluded=excluded)
        inventory["source_commit"] = source_identity
        sdk = Path(temp) / "factorforge-data-api"
        if data_sdk_root is not None:
            rules = tomllib.loads((root / "packaging/research-files.toml").read_text(encoding="utf-8"))
            inventory["data_sdk_files"] = _copy_data_sdk(data_sdk_root, sdk, rules["data_sdk"])
        wheels = Path(temp) / "wheels"
        inventory["wheels"] = []
        if build_python is not None:
            inventory["wheels"].append(_build_wheel(staging, wheels / "framework", python=build_python))
            if data_sdk_root is not None:
                inventory["wheels"].append(_build_wheel(sdk, wheels / "data-api", python=build_python))
        output.mkdir(parents=True); shutil.copytree(staging, output / "factor-forge", copy_function=shutil.copy2)
        if data_sdk_root is not None:
            shutil.copytree(sdk, output / "factorforge-data-api", copy_function=shutil.copy2)
        if build_python is not None:
            (output / "wheels").mkdir()
            for wheel in wheels.rglob("*.whl"):
                shutil.copyfile(wheel, output / "wheels" / wheel.name)
        (output / "bundle_inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with zipfile.ZipFile(output / "factor-forge.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(staging).as_posix(); info = zipfile.ZipInfo(f"factor-forge/{rel}")
                    info.external_attr = (0o755 if path.stat().st_mode & 0o111 else 0o644) << 16; info.compress_type = zipfile.ZIP_DEFLATED; archive.writestr(info, path.read_bytes())
            for directory in (output / "factorforge-data-api", output / "wheels"):
                if directory.is_dir():
                    for path in sorted(directory.rglob("*")):
                        if path.is_file():
                            info = zipfile.ZipInfo(path.relative_to(output).as_posix())
                            info.external_attr = 0o644 << 16
                            info.compress_type = zipfile.ZIP_DEFLATED
                            archive.writestr(info, path.read_bytes())
            inventory_info = zipfile.ZipInfo("bundle_inventory.json")
            inventory_info.external_attr = 0o644 << 16; inventory_info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(inventory_info, json.dumps(inventory, ensure_ascii=False, indent=2) + "\n")
    return output


def build_publish_bundle(*, source_root: Path, output: Path, source_commit: str = "HEAD",
                         data_sdk_root: Path | None = None, build_python: str = sys.executable) -> Path:
    """Export selected Git bytes once, then build SDK wheels and a readable full tree."""
    root = source_root.expanduser().resolve(strict=True)
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"refuse to overwrite existing output: {output}")
    sdk = data_sdk_root.expanduser().resolve(strict=True) if data_sdk_root is not None else None
    with tempfile.TemporaryDirectory(prefix="factorforge-source-") as temp:
        snapshot = Path(temp) / "snapshot"
        identity = _snapshot_source(root, source_commit, snapshot)
        return _build_tree_bundle(source_root=snapshot, output=output, source_identity=identity,
                                  data_sdk_root=sdk, build_python=build_python)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--source-commit", default="HEAD", help="Selected Git commit; dirty files are never exported.")
    parser.add_argument("--data-sdk-root", type=Path, help="Explicit delivered Data API SDK source to include.")
    parser.add_argument("--build-python", default=sys.executable, help="Python with setuptools and wheel installed; no dependency downloads.")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(build_publish_bundle(source_root=Path(args.source_root), output=Path(args.output),
                               source_commit=args.source_commit, data_sdk_root=args.data_sdk_root,
                               build_python=args.build_python))
if __name__ == "__main__": main()
