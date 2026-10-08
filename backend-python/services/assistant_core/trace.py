"""执行轨迹记录工具。"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Generator, List

from .schemas import ExecutionStep

logger = logging.getLogger('hengpintong.assistant.trace')


class Tracer:
    """记录每步执行的耗时与状态。绝不记录敏感原始数据。"""

    def __init__(self):
        self.steps: List[ExecutionStep] = []

    @contextmanager
    def step(self, step_id: str, step_type: str,
             skill: str | None = None,
             risk_level: str = 'low') -> Generator[ExecutionStep, None, None]:
        rec = ExecutionStep(step_id=step_id, type=step_type, skill=skill, risk_level=risk_level)
        start = time.perf_counter()
        try:
            yield rec
            if rec.status == 'pending':
                rec.status = 'ok'
        except Exception as e:
            rec.status = 'error'
            rec.error = type(e).__name__
            logger.warning(
                'assistant_step_failed',
                extra={'stepId': step_id, 'skill': skill, 'errorType': type(e).__name__},
            )
            # 不向上抛，由 executor 决定 on_error 策略
        finally:
            rec.duration_ms = (time.perf_counter() - start) * 1000
            self.steps.append(rec)

    def mark_skipped(self, step_id: str, step_type: str, skill: str | None = None, reason: str = '') -> None:
        self.steps.append(ExecutionStep(
            step_id=step_id, type=step_type, skill=skill,
            status='skipped', error=reason,
        ))
