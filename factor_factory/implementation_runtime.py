"""Shared invocation contract for Step3 samples and Step4 factor execution.

Choose arguments before calling user code. Exceptions from the factor body are
never evidence that another signature or backend should be tried.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, Callable


RUNTIME_VERSION = "factorforge_implementation_runtime_v1"


def _nonempty(frame: Any) -> bool:
    if frame is None:
        return False
    if hasattr(frame, "empty"):
        return not bool(frame.empty)
    if callable(getattr(frame, "is_empty", None)):
        return not frame.is_empty()
    return len(frame) > 0


def invoke_factor(fn: Callable, daily_df: Any, minute_df: Any) -> Any:
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
