from __future__ import annotations

import math
from typing import Any, Iterable


def _to_float_list(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for value in values:
        try:
            x = float(value)
        except Exception:
            continue
        if math.isfinite(x):
            out.append(x)
    return out


def drawdown_geometry(nav_values: Iterable[Any]) -> dict[str, float | int | None]:
    nav = _to_float_list(nav_values)
    if not nav:
        return {
            "drawdown_area": None,
            "normalized_drawdown_area": None,
            "max_drawdown_episode_area": None,
            "recovery_pain_area": None,
            "max_drawdown": None,
            "recovery_days": None,
            "episode_count": 0,
        }

    high = nav[0]
    underwater: list[float] = []
    max_dd = 0.0
    trough_idx = 0
    high_idx_at_trough = 0
    current_episode_area = 0.0
    max_episode_area = 0.0
    episode_count = 0
    in_episode = False
    episode_start = 0
    trough_in_episode = 0
    recovery_days = None
    recovery_pain_area = None

    for idx, value in enumerate(nav):
        if value >= high:
            if in_episode:
                max_episode_area = max(max_episode_area, current_episode_area)
                if trough_in_episode == trough_idx and recovery_days is None:
                    recovery_days = idx - trough_idx
                    recovery_pain_area = sum(underwater[trough_idx:idx + 1])
                current_episode_area = 0.0
                in_episode = False
            high = value
            depth = 0.0
        else:
            depth = (high - value) / high if high else 0.0
            if not in_episode:
                in_episode = True
                episode_count += 1
                episode_start = idx
                trough_in_episode = idx
            current_episode_area += depth
            if depth > abs(max_dd):
                max_dd = -depth
                trough_idx = idx
                high_idx_at_trough = episode_start
                trough_in_episode = idx
        underwater.append(depth)

    if in_episode:
        max_episode_area = max(max_episode_area, current_episode_area)
        if trough_idx >= high_idx_at_trough and recovery_days is None:
            recovery_days = None
            recovery_pain_area = sum(underwater[trough_idx:])

    area = float(sum(underwater))
    return {
        "drawdown_area": area,
        "normalized_drawdown_area": area / len(underwater) if underwater else None,
        "max_drawdown_episode_area": float(max_episode_area),
        "recovery_pain_area": float(recovery_pain_area) if recovery_pain_area is not None else None,
        "max_drawdown": float(max_dd),
        "recovery_days": recovery_days,
        "episode_count": episode_count,
    }
