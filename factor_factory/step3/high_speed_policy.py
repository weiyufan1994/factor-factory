from __future__ import annotations

import ast


HIGH_SPEED_CODE_PROFILE_VERSION = "factorforge_high_speed_code_profile_v1"
HIGH_SPEED_PREFERRED_BACKENDS = ["numpy", "polars"]
HIGH_SPEED_AVOID_BY_DEFAULT = [
    "python_row_loops",
    "pandas_groupby_iteration",
    "pandas_groupby_apply",
    "pandas_row_apply",
    "nested_python_for_loop",
    "sort_values_inside_loop",
    "list_append_inside_loop",
]


def _attribute_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return list(reversed(parts))


def _call_has_keyword_value(node: ast.Call, keyword_name: str, expected: object) -> bool:
    for keyword in node.keywords or []:
        if keyword.arg != keyword_name:
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and value.value == expected:
            return True
    return False


def _receiver_chain_contains_call(node: ast.AST, call_attr: str) -> bool:
    current = node
    while True:
        if isinstance(current, ast.Subscript):
            current = current.value
            continue
        if isinstance(current, ast.Attribute):
            current = current.value
            continue
        if isinstance(current, ast.Call):
            func = current.func
            if isinstance(func, ast.Attribute) and func.attr == call_attr:
                return True
            if isinstance(func, ast.Attribute):
                current = func.value
                continue
        return False


def _is_groupby_apply_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "apply":
        return False
    return _receiver_chain_contains_call(node.func.value, "groupby")


def _is_rolling_apply_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "apply":
        return False
    return _receiver_chain_contains_call(node.func.value, "rolling")


def _call_uses_name(node: ast.Call, names: set[str]) -> bool:
    chain = _attribute_chain(node.func)
    return bool(chain and chain[0] in names)


def _is_groupby_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "groupby"


def _for_iter_uses_groupby(node: ast.For, groupby_iterable_names: set[str]) -> bool:
    iter_node = node.iter
    if isinstance(iter_node, ast.Name) and iter_node.id in groupby_iterable_names:
        return True
    if _is_groupby_call(iter_node):
        return True
    if isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Name) and iter_node.func.id in {"iter", "enumerate"}:
        return bool(
            iter_node.args
            and _for_iter_uses_groupby(
                ast.For(target=node.target, iter=iter_node.args[0], body=[], orelse=[]),
                groupby_iterable_names,
            )
        )
    return False


def _contains_call_attr(node: ast.AST, attrs: set[str]) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr in attrs:
            return True
    return False


def _contains_list_append(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "append":
            return True
    return False


def build_high_speed_code_profile(text: str) -> dict:
    tree = ast.parse(text)
    import_aliases: dict[str, str] = {}
    slow_patterns: list[dict] = []
    vectorized_markers: list[dict] = []
    uses_pandas_vectorized = False
    groupby_iterable_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                import_aliases[alias.asname or root] = root
        elif isinstance(node, ast.ImportFrom):
            module_root = (node.module or "").split(".")[0]
            for alias in node.names:
                import_aliases[alias.asname or alias.name] = module_root
        elif isinstance(node, ast.Assign):
            if _is_groupby_call(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        groupby_iterable_names.add(target.id)

    numpy_names = {name for name, root in import_aliases.items() if root == "numpy"}
    polars_names = {name for name, root in import_aliases.items() if root == "polars"}
    pandas_names = {name for name, root in import_aliases.items() if root == "pandas"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr in {"iterrows", "itertuples"}:
                    slow_patterns.append({"code": attr, "line": getattr(node, "lineno", None)})
                elif attr == "apply" and _call_has_keyword_value(node, "axis", 1):
                    slow_patterns.append({"code": "pandas_apply_axis1", "line": getattr(node, "lineno", None)})
                elif _is_groupby_apply_call(node):
                    slow_patterns.append({"code": "pandas_groupby_apply", "line": getattr(node, "lineno", None)})
                elif _is_rolling_apply_call(node):
                    slow_patterns.append({"code": "pandas_rolling_apply", "line": getattr(node, "lineno", None)})
                elif attr in {"to_numpy", "rank", "shift", "diff", "rolling", "transform", "where", "clip", "fillna", "assign", "merge"}:
                    uses_pandas_vectorized = True
                    vectorized_markers.append({"code": f"pandas_{attr}", "line": getattr(node, "lineno", None)})
            if _call_uses_name(node, numpy_names):
                vectorized_markers.append({"code": "numpy_call", "line": getattr(node, "lineno", None)})
            if _call_uses_name(node, polars_names):
                vectorized_markers.append({"code": "polars_call", "line": getattr(node, "lineno", None)})
            if isinstance(node.func, ast.Name) and node.func.id == "range" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id == "len":
                    slow_patterns.append({"code": "range_len_loop", "line": getattr(node, "lineno", None)})
        elif isinstance(node, ast.For):
            nested_for = any(isinstance(child, ast.For) for stmt in node.body for child in ast.walk(stmt))
            if _for_iter_uses_groupby(node, groupby_iterable_names):
                slow_patterns.append({"code": "pandas_groupby_iteration", "line": getattr(node, "lineno", None)})
            if nested_for:
                slow_patterns.append({"code": "nested_python_for_loop", "line": getattr(node, "lineno", None)})
            if _contains_call_attr(node, {"sort_values"}):
                slow_patterns.append({"code": "sort_values_inside_loop", "line": getattr(node, "lineno", None)})
            if _contains_list_append(node):
                slow_patterns.append({"code": "list_append_inside_loop", "line": getattr(node, "lineno", None)})

    deduped_slow_patterns: list[dict] = []
    seen_slow: set[tuple[str, int | None]] = set()
    for item in slow_patterns:
        key = (str(item.get("code")), item.get("line"))
        if key not in seen_slow:
            seen_slow.add(key)
            deduped_slow_patterns.append(item)

    uses_numpy = bool(numpy_names)
    uses_polars = bool(polars_names)
    uses_pandas = bool(pandas_names) or "pd" in import_aliases
    vectorized_backend_present = bool(uses_numpy or uses_polars or uses_pandas_vectorized or vectorized_markers)
    return {
        "version": HIGH_SPEED_CODE_PROFILE_VERSION,
        "preferred_backends": HIGH_SPEED_PREFERRED_BACKENDS,
        "avoid_by_default": HIGH_SPEED_AVOID_BY_DEFAULT,
        "uses_numpy": uses_numpy,
        "uses_polars": uses_polars,
        "uses_pandas": uses_pandas,
        "uses_pandas_vectorized": bool(uses_pandas_vectorized),
        "vectorized_backend_present": vectorized_backend_present,
        "vectorized_markers": vectorized_markers[:20],
        "slow_patterns": deduped_slow_patterns,
        "requires_justification": bool(deduped_slow_patterns),
    }


def assert_high_speed_code_policy(text: str, contract: dict | None = None) -> dict:
    profile = build_high_speed_code_profile(text)
    contract = contract if isinstance(contract, dict) else {}
    policy = contract.get("high_speed_code_policy") if isinstance(contract.get("high_speed_code_policy"), dict) else {}
    justification = (
        contract.get("performance_justification")
        or contract.get("slow_pattern_justification")
        or policy.get("performance_justification")
        or policy.get("slow_pattern_justification")
    )
    allow_slow = bool(contract.get("allow_slow_patterns") is True or policy.get("allow_slow_patterns") is True)
    if profile.get("requires_justification") and not (allow_slow and str(justification or "").strip()):
        raise SystemExit(f"BLOCK_DIRECT_CODE_PERFORMANCE_RISK: {profile}")
    return profile
