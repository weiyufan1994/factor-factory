from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any


def _row_count(value: Any) -> int:
    try:
        return int(len(value))
    except Exception:
        return 0


class OperatorProfiler:
    def __init__(self, enabled: bool = False, engine: str = 'pandas_formula_ir_optimized'):
        self.enabled = bool(enabled)
        self.engine = engine
        self.events: list[dict[str, Any]] = []

    @contextmanager
    def phase(self, *, node_id: str, operator: str, detail: dict | None = None, input_rows: int = 0):
        event = {
            'node_id': node_id,
            'operator': operator,
            'seconds': 0.0,
            'input_rows': int(input_rows or 0),
            'output_rows': 0,
            'input_cols': [],
            'output_name': None,
            'cache_hit': False,
            'engine': self.engine,
            'detail': dict(detail or {}),
        }
        if not self.enabled:
            yield event
            return
        start = time.perf_counter()
        try:
            yield event
        finally:
            event['seconds'] = max(0.0, float(time.perf_counter() - start))
            self.events.append(event)

    def set_output(self, event: dict[str, Any], value: Any, output_name: str | None = None) -> Any:
        if not self.enabled:
            return value
        event['output_rows'] = _row_count(value)
        if output_name:
            event['output_name'] = output_name
        return value

    def cache_hit(self, *, node_id: str, operator: str, value: Any, detail: dict | None = None, input_rows: int = 0) -> None:
        if not self.enabled:
            return
        self.events.append({
            'node_id': node_id,
            'operator': operator,
            'seconds': 0.0,
            'input_rows': int(input_rows or 0),
            'output_rows': _row_count(value),
            'input_cols': [],
            'output_name': None,
            'cache_hit': True,
            'engine': self.engine,
            'detail': dict(detail or {}),
        })

    def summary(self, compute_factor_seconds: float | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {
                'version': 'factorforge_operator_profile_v1',
                'enabled': False,
                'total_profiled_seconds': 0.0,
                'event_count': 0,
                'by_operator': {},
                'top_events': [],
                'unprofiled_compute_seconds': compute_factor_seconds,
            }

        by_operator: dict[str, dict[str, Any]] = {}
        total_seconds = 0.0
        for event in self.events:
            op = str(event.get('operator') or 'unknown')
            seconds = float(event.get('seconds') or 0.0)
            total_seconds += seconds
            bucket = by_operator.setdefault(op, {
                'count': 0,
                'cache_hit_count': 0,
                'total_seconds': 0.0,
                'max_seconds': 0.0,
                'rows': 0,
            })
            bucket['count'] += 1
            if event.get('cache_hit') is True:
                bucket['cache_hit_count'] += 1
            bucket['total_seconds'] += seconds
            bucket['max_seconds'] = max(float(bucket['max_seconds']), seconds)
            bucket['rows'] += int(event.get('output_rows') or event.get('input_rows') or 0)

        top_events = sorted(self.events, key=lambda item: float(item.get('seconds') or 0.0), reverse=True)[:10]
        top_events = [
            {
                'operator': event.get('operator'),
                'seconds': float(event.get('seconds') or 0.0),
                'node_id': event.get('node_id'),
                'cache_hit': bool(event.get('cache_hit')),
                'detail': event.get('detail') or {},
            }
            for event in top_events
        ]
        unprofiled = None
        if compute_factor_seconds is not None:
            unprofiled = max(0.0, float(compute_factor_seconds) - float(total_seconds))
        return {
            'version': 'factorforge_operator_profile_v1',
            'enabled': True,
            'total_profiled_seconds': float(total_seconds),
            'event_count': int(len(self.events)),
            'by_operator': by_operator,
            'top_events': top_events,
            'unprofiled_compute_seconds': unprofiled,
        }
