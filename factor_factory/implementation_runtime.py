"""Shared invocation contract for Step3 samples and Step4 factor execution.

Choose arguments before calling user code. Exceptions from the factor body are
never evidence that another signature or backend should be tried.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager, nullcontext
import hashlib
import importlib.util
import inspect
import keyword
from pathlib import Path
from stat import S_ISDIR, S_ISREG
import sys
from threading import RLock
import tokenize
from typing import Any, Callable


RUNTIME_VERSION = "factorforge_implementation_runtime_v1"
_IMPORT_LOCK = RLock()
_PRIMARY_ROLES = {'daily_df', 'minute_df', 'exchange_calendar'}


def implementation_input_identity(path: Path, workspace: Path, additional_paths: dict[str, Path]) -> dict:
    """Extend existing compute-cache identity for explicit frames and Python helpers.

    Ordinary import statements (including imports inside functions) select local
    packages. Hash their Python sources, including relative-import siblings;
    this does not execute code or invent a data-admission receipt.
    """
    def digest(file):
        value = hashlib.sha256()
        with file.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                value.update(block)
        return value.hexdigest()

    protected = {'factor_factory', 'factorforge_data_api', 'skills'} | set(sys.stdlib_module_names)
    pending = [path]
    inspected, roots, helpers = set(), set(), {}
    while pending:
        file = pending.pop()
        if file in inspected:
            continue
        inspected.add(file)
        try:
            with tokenize.open(file) as stream:
                tree = ast.parse(stream.read())
        except (SyntaxError, UnicodeError):
            if file == path:
                raise
            # An unused sibling's malformed text does not prevent importing a
            # valid helper. Its bytes still invalidate the conservative cache.
            continue
        for node in ast.walk(tree):
            names = ([item.name for item in node.names] if isinstance(node, ast.Import) else
                     [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
            for name in names:
                root = name.split('.', 1)[0]
                if root in roots or root in protected:
                    continue
                roots.add(root)
                module, package = workspace / (root + '.py'), workspace / root
                files = [module] if module.is_file() else sorted(package.rglob('*.py')) if package.is_dir() else []
                for helper in files:
                    helpers[str(helper.relative_to(workspace))] = digest(helper)
                    pending.append(helper)
    return {'additional_inputs': {name: {'path': str(file), 'sha256': digest(file)}
                                  for name, file in sorted(additional_paths.items())},
            'workspace_python_sources': dict(sorted(helpers.items()))}


def named_input_bindings(inputs: dict, *, key: str = 'additional_input_paths') -> dict[str, str]:
    """Explicit local file selectors; never infer auxiliary roles from daily rows."""
    bindings = inputs.get(key, {})
    if not isinstance(bindings, dict):
        raise ValueError(f'BLOCK_FACTOR_IMPLEMENTATION_INPUT_ROLE_INVALID: {key} must be an object')
    for role, path in bindings.items():
        if not isinstance(role, str) or not role.isidentifier() or keyword.iskeyword(role):
            raise ValueError(f'BLOCK_FACTOR_IMPLEMENTATION_INPUT_ROLE_INVALID: {role!r}')
        if role in _PRIMARY_ROLES:
            raise ValueError(f'BLOCK_FACTOR_IMPLEMENTATION_INPUT_ROLE_DUPLICATE: {role}')
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f'BLOCK_FACTOR_IMPLEMENTATION_INPUT_ROLE_MISSING: {role}')
        if Path(path).suffix.lower() not in {'.parquet', '.csv'}:
            raise ValueError(f'BLOCK_FACTOR_IMPLEMENTATION_INPUT_ROLE_FORMAT: {role}')
    return dict(bindings)


def load_named_inputs(inputs: dict, workspace: Path, *, window: dict | None = None) -> tuple[dict, dict[str, Path]]:
    """Load declared frames without joins, filtering or missing-value substitution."""
    import pandas as pd
    paths = {role: (workspace / value).resolve()
             for role, value in named_input_bindings(inputs).items()}
    for role, path in paths.items():
        if not path.is_file():
            raise ValueError(f'BLOCK_FACTOR_IMPLEMENTATION_INPUT_ROLE_MISSING: {role}={path}')
    frames = {
        role: pd.read_parquet(path) if path.suffix.lower() == '.parquet' else
        pd.read_csv(path, dtype={'ts_code': str, 'trade_date': str})
        for role, path in paths.items()
    }
    if window is not None:
        for role, frame in frames.items():
            if 'trade_date' not in frame.columns:
                continue
            dates = frame.trade_date.astype(str).str.replace('-', '', regex=False).str[:8]
            pd.to_datetime(dates, format='%Y%m%d', errors='raise')
            if not dates.between(str(window['start']), str(window['end'])).all():
                raise ValueError(f'BLOCK_FACTOR_IMPLEMENTATION_INPUT_ROLE_WINDOW: {role}')
    return frames, paths


@contextmanager
def workspace_imports(workspace: Path, *, modules: dict | None = None):
    """Scope ordinary workspace imports to one invocation, including lazy imports.

    Step processes execute one factor at a time. The lock also serializes callers
    of this shared import context inside a process; it is not a code sandbox.
    Framework/SDK/stdlib modules keep their existing authority. Same-name helper
    modules from another study are restored, never reused for the current study.
    """
    workspace = workspace.resolve()
    protected = {'factor_factory', 'factorforge_data_api', 'skills'} | set(sys.stdlib_module_names)
    roots = set()
    for path in workspace.iterdir():
        is_python_file = path.suffix == '.py'
        name = path.stem if is_python_file else path.name
        if not name.isidentifier() or name in protected:
            continue
        # Check names before filesystem access: unrelated projects are not
        # import candidates. stat() preserves permission errors across Python
        # versions, unlike is_file()/is_dir() on Python 3.14.
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            continue
        if (is_python_file and S_ISREG(mode)) or (not is_python_file and S_ISDIR(mode)):
            roots.add(name)
    belongs = lambda name: name.split('.', 1)[0] in roots
    active = dict(modules or {})
    with _IMPORT_LOCK:
        old_path = list(sys.path)
        old_modules = {name: value for name, value in list(sys.modules.items()) if belongs(name)}
        try:
            for name in old_modules:
                del sys.modules[name]
            sys.modules.update(active)
            repo = str(Path(__file__).resolve().parents[1])
            sys.path[:] = [repo, str(workspace), *[p for p in old_path if p not in {repo, str(workspace)}]]
            importlib.invalidate_caches()
            yield active
        finally:
            active.update({name: value for name, value in list(sys.modules.items()) if belongs(name)})
            for name in list(sys.modules):
                if belongs(name):
                    del sys.modules[name]
            sys.modules.update(old_modules)
            sys.path[:] = old_path
            importlib.invalidate_caches()


def load_implementation(path: Path, *, workspace: Path | None = None):
    """Import a generated artifact with explicit, temporary workspace visibility."""
    path = path.resolve()
    name = '_factorforge_implementation_' + hashlib.sha256(str(path).encode()).hexdigest()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot create implementation import spec: {path}')
    module = importlib.util.module_from_spec(spec)
    context = workspace_imports(workspace) if workspace is not None and workspace.is_dir() else nullcontext({})
    with context as dependencies:
        previous = sys.modules.get(name)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    module._factorforge_workspace = workspace if workspace is not None and workspace.is_dir() else None
    module._factorforge_workspace_modules = dependencies
    return module


def source_declares_factor_instance(source: str) -> bool:
    """Recognize only a module-level FACTOR binding, not comments/strings.

    A declaration is not type acceptance: implementation_callable checks the
    imported value is a BaseFactor instance before any factor executes.
    """
    tree = ast.parse(source)
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == 'FACTOR' for target in targets):
            return True
    return False


def source_declares_legacy_callable(source: str) -> bool:
    return any(isinstance(node, ast.FunctionDef) and node.name == 'compute_factor'
               for node in ast.parse(source).body)


def implementation_callable(implementation: Any) -> Callable:
    """Expose the same named-frame callable for class and legacy interfaces."""
    from factor_factory.factors import BaseFactor
    factor = getattr(implementation, 'FACTOR', implementation)
    if isinstance(factor, BaseFactor):
        def compute_factor(daily_df, minute_df=None, **additional_inputs):
            return factor.run({'daily_df': daily_df, 'minute_df': minute_df, **additional_inputs})
        return compute_factor
    if hasattr(implementation, 'FACTOR'):
        raise TypeError('FACTOR must be a BaseFactor instance')
    fn = getattr(implementation, 'compute_factor', None)
    if not callable(fn):
        raise TypeError('implementation requires a BaseFactor instance or compute_factor callable')
    return fn


def invoke_implementation(implementation: Any, daily_df: Any, minute_df: Any, *,
                          additional_inputs: dict[str, Any] | None = None) -> Any:
    """Run a BaseFactor instance/module FACTOR, or the legacy callable once."""
    workspace = getattr(implementation, '_factorforge_workspace', None)
    context = (workspace_imports(workspace, modules=implementation._factorforge_workspace_modules)
               if workspace is not None else nullcontext())
    with context as dependencies:
        # Registration supports normal Python features such as dataclasses in
        # a generated module; it has the same bounded lifetime as helper imports.
        name = getattr(implementation, '__name__', None)
        registered = name is not None and hasattr(implementation, '_factorforge_workspace')
        previous = sys.modules.get(name) if registered else None
        if registered:
            sys.modules[name] = implementation
        try:
            return invoke_factor(implementation_callable(implementation), daily_df, minute_df,
                                 additional_inputs=additional_inputs)
        finally:
            if workspace is not None:
                implementation._factorforge_workspace_modules = dependencies
            if registered:
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous


def _nonempty(frame: Any) -> bool:
    if frame is None:
        return False
    if hasattr(frame, "empty"):
        return not bool(frame.empty)
    if callable(getattr(frame, "is_empty", None)):
        return not frame.is_empty()
    return len(frame) > 0


def invoke_factor(
    fn: Callable,
    daily_df: Any,
    minute_df: Any,
    *,
    additional_inputs: dict[str, Any] | None = None,
) -> Any:
    """Bind a keyword or legacy interface, then execute it exactly once."""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        raise TypeError("BLOCK_FACTOR_IMPLEMENTATION_SIGNATURE_UNAVAILABLE") from exc
    params = list(signature.parameters.values())
    positional = [p for p in params if p.kind in (
        inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD
    )]
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
    frames = {"daily_df": daily_df, "minute_df": minute_df}
    for name, value in (additional_inputs or {}).items():
        if name in frames:
            raise TypeError(f"BLOCK_FACTOR_IMPLEMENTATION_INPUT_ROLE_DUPLICATE: {name}")
        if not isinstance(name, str) or not name.isidentifier():
            raise TypeError(f"BLOCK_FACTOR_IMPLEMENTATION_INPUT_ROLE_INVALID: {name!r}")
        frames[name] = value
    keywords = {
        name: value for name, value in frames.items()
        if accepts_kwargs or (
            name in signature.parameters and signature.parameters[name].kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        )
    }
    # Defaults make an incomplete call bind successfully. Do not let that
    # silently discard a positional input when another input accepts keywords.
    positional_inputs = [
        p for index, p in enumerate(positional)
        if index == 0 or p.name in frames
        or any(role in p.name.lower() for role in ("daily", "minute", "intraday"))
    ]
    keyword_complete = all(
        p.kind != inspect.Parameter.POSITIONAL_ONLY and p.name in keywords
        for p in positional_inputs
    )
    candidates = [((), keywords)] if keywords and keyword_complete else []
    # Named auxiliary roles must never be populated through the legacy
    # daily/minute positional fallback.  In particular, an exchange calendar
    # is a separate authority, not a synonym for minute bars.
    missing_named_roles = [
        p.name
        for p in params
        if p.name not in {"daily_df", "minute_df"}
        and p.default is inspect.Parameter.empty
        and p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
        and p.name not in frames
        and any(token in p.name.lower() for token in ("calendar", "universe", "benchmark"))
    ]
    if missing_named_roles:
        raise TypeError(
            "BLOCK_FACTOR_IMPLEMENTATION_INPUT_ROLE_MISSING: "
            + ",".join(sorted(missing_named_roles))
        )
    if positional:
        first = positional[0].name.lower()
        minute_first = "minute" in first or "intraday" in first
        arity = min(2, len(positional))
        if arity == 2 and positional[1] not in positional_inputs and positional[1].default is not inspect.Parameter.empty:
            # An optional configuration parameter is not the second frame.
            arity = 1
        if arity == 1:
            if minute_first:
                chosen = minute_df
            elif "daily" in first or "minute_df" in keywords:
                chosen = daily_df
            elif "daily_df" in keywords:
                chosen = minute_df
            else:
                chosen = minute_df if _nonempty(minute_df) else daily_df
            args = (chosen,)
        else:
            args = (minute_df, daily_df) if minute_first else (daily_df, minute_df)
        consumed = {p.name for p in positional[:len(args)]}
        candidates.append((args, {k: v for k, v in keywords.items() if k not in consumed}))
    elif any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
        candidates.append(((daily_df, minute_df), {}))
    last_error = None
    for args, kwargs in candidates:
        try:
            signature.bind(*args, **kwargs)
        except TypeError as exc:
            last_error = exc
            continue
        return fn(*args, **kwargs)
    raise TypeError(
        f"BLOCK_FACTOR_IMPLEMENTATION_SIGNATURE_MISMATCH: {signature}"
    ) from last_error


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
        node = node.value if isinstance(node, (ast.Attribute, ast.Subscript)) else node.func
    return node.id if isinstance(node, ast.Name) else None


def expects_polars(module: Any) -> bool:
    """Resolve an explicit input backend or infer actual Polars input usage.

    Comments, strings and NumPy ``select`` do not select a frame backend.
    Ambiguous implementations can declare METADATA['input_dataframe_backend']
    (or FACTORFORGE_DATAFRAME_BACKEND) as 'pandas' or 'polars'.
    """
    metadata = getattr(module, "METADATA", {})
    declared = getattr(module, "FACTORFORGE_DATAFRAME_BACKEND", None)
    if declared is None and isinstance(metadata, dict):
        declared = metadata.get("input_dataframe_backend")
    if declared is not None:
        if declared not in ("pandas", "polars"):
            raise ValueError("BLOCK_FACTOR_INPUT_DATAFRAME_BACKEND_INVALID")
        return declared == "polars"
    try:
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    except (AttributeError, OSError, TypeError, SyntaxError):
        return False
    polars_aliases: set[str] = set()
    pandas_aliases: set[str] = set()
    polars_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name in ("polars", "pandas"):
                    aliases = polars_aliases if item.name == "polars" else pandas_aliases
                    aliases.add(item.asname or item.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "polars":
            polars_imports.update(item.asname or item.name for item in node.names)
    if not polars_aliases and not polars_imports:
        return False
    inputs: set[str] = set()
    functions: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.setdefault(node.name, []).append(node)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "compute_factor":
            for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                inputs.add(arg.arg)
                annotation = arg.annotation
                if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
                    try:
                        annotation = ast.parse(annotation.value, mode="eval").body
                    except SyntaxError:
                        annotation = None
                if annotation is not None:
                    names = {_root_name(part) for part in ast.walk(annotation)}
                    if names & pandas_aliases:
                        return False
                    if names & (polars_aliases | polars_imports):
                        return True
    # Ignore unrelated helpers. Follow local calls used by compute_factor,
    # including both the selected body and a generated API wrapper.
    pending = ["compute_factor"]
    visited: set[str] = set()
    used_nodes: list[ast.AST] = []
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        for function in functions.get(name, []):
            for node in ast.walk(function):
                used_nodes.append(node)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in functions:
                        pending.append(node.func.id)
    # pandas also has filter(), so that method alone cannot choose Polars.
    frame_methods = {"with_columns", "select", "lazy"}
    expressions = {"col", "lit", "when", "all", "first", "last", "element"}
    for node in used_nodes:
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in frame_methods and _root_name(node.func.value) in inputs:
                return True
            if node.func.attr in expressions and _root_name(node.func.value) in polars_aliases:
                return True
        elif isinstance(node.func, ast.Name) and node.func.id in polars_imports:
            return True
    return False
