"""Emit standalone, reviewable source from the maintained DataFrame kernels.

The generated factor carries its implementation with it; executing a research
artifact does not import a moving SDK kernel or depend on the checkout path.
"""
from __future__ import annotations

import ast
from functools import lru_cache
from importlib.resources import files


SUPPORTED_MILLER_DERIVED_STATE_LAWS = {
    "miller_flow_v15_repair_confirmed_absorption_fp_v1",
    "miller_flow_v17_benchmark_relative_repaired_absorption_v1",
    "miller_flow_v18a_absolute_long_edge_gate_v1",
    "miller_flow_v18b_first_passage_repair_edge_v1",
    "miller_flow_v18c_crowding_filtered_repair_v1",
}
_KERNEL_MODULES = (
    "derived_state_common",
    "derived_state_moments",
    "derived_state_pressure",
    "derived_state_runtime",
)


@lru_cache(maxsize=1)
def _standalone_kernel_source() -> str:
    """Inline local helpers while preserving each numeric expression verbatim."""
    parts = []
    for name in _KERNEL_MODULES:
        source = files(__package__).joinpath(name + ".py").read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        omitted = set()
        for node in ast.parse(source).body:
            if isinstance(node, ast.ImportFrom) and node.level:
                if node.level != 1 or node.module not in _KERNEL_MODULES:
                    raise ValueError(f"unsupported derived-state helper import: {node.module}")
                omitted.update(range(node.lineno, node.end_lineno + 1))
        parts.append("".join(line for index, line in enumerate(lines, 1) if index not in omitted))
    return "\n\n".join(parts)


def _minute_derived_flow_state_adapter(law_id: str | None = None) -> str:
    """Bind the law in standalone source, retaining historical private callers."""
    law = str(law_id or "").strip()
    wrapper = f"""
def compute_factor_from_derived_state(daily_df=None, derived_state_df=None):
    _factorforge_direct_code_law_id = {law!r}
    return compute_derived_state(
        daily_df=daily_df,
        derived_state_df=derived_state_df,
        law_id=_factorforge_direct_code_law_id,
    )
"""
    return _standalone_kernel_source().rstrip() + "\n\n" + wrapper.lstrip()


def minute_derived_flow_state_law_source(law_id: str) -> str:
    clean_id = str(law_id or "").strip()
    if clean_id not in SUPPORTED_MILLER_DERIVED_STATE_LAWS:
        raise ValueError(f"unsupported moneyflow derived-state law: {clean_id}")
    source = _minute_derived_flow_state_adapter(clean_id)
    wrapper = """
def compute_factor(daily_df=None, minute_df=None):
    frame = daily_df if daily_df is not None else minute_df
    return compute_factor_from_derived_state(daily_df=frame, derived_state_df=frame)
"""
    return source.rstrip() + "\n\n" + wrapper.lstrip()
