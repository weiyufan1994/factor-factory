"""Narrow adapter for study-local, prepared-state direct-code controllers.

The adapter intentionally owns no data access or evaluation logic.  It only
binds an already-prepared, manifest-referenced input set to a controller that
can process its own partitions and materialize one factor output file.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any


def run_partitioned_controller(
    module: Any,
    *,
    local_inputs: dict[str, Any],
    derived_state_root: Path,
    daily_input_path: Path,
    output_path: Path,
    run_dir: Path,
    report_id: str,
    factor_id: str,
    factorforge_root: Path,
    workspace_root: Path,
) -> Any:
    """Invoke ``compute_factor_partitioned`` with only declared keywords.

    A path return is deliberately constrained to ``output_path``.  This keeps
    the formal Step4 artifact location owned by Step4 and prevents a study
    controller from silently redirecting the result to an unbound location.
    Returning an in-memory DataFrame remains supported for small bounded
    Step3B samples.
    """
    fn = getattr(module, "compute_factor_partitioned", None)
    if not callable(fn):
        raise ValueError("compute_factor_partitioned is not callable")
    values = {
        "local_inputs": local_inputs, "derived_state_root": derived_state_root,
        "daily_input_path": daily_input_path, "output_path": output_path,
        "run_dir": run_dir, "report_id": report_id, "factor_id": factor_id,
        "factorforge_root": factorforge_root, "workspace_root": workspace_root,
    }
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        raise ValueError("compute_factor_partitioned has no inspectable signature") from exc
    parameters = signature.parameters
    accepts_kwargs = any(param.kind is inspect.Parameter.VAR_KEYWORD for param in parameters.values())
    unsupported_required = [
        name for name, param in parameters.items()
        if param.kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        and param.default is inspect.Parameter.empty and name not in values
    ]
    if unsupported_required:
        raise ValueError("compute_factor_partitioned has unsupported required parameter(s): " + ", ".join(unsupported_required))
    result = fn(**(values if accepts_kwargs else {name: value for name, value in values.items() if name in parameters}))
    if isinstance(result, (str, Path)):
        actual, expected = Path(result).expanduser().resolve(), output_path.expanduser().resolve()
        if actual != expected:
            raise ValueError("compute_factor_partitioned returned an output path outside the Step-owned target: " f"expected={expected}, actual={actual}")
        if not actual.is_file():
            raise ValueError("compute_factor_partitioned returned output_path but did not materialize it: " f"{actual}")
        return actual
    return result
