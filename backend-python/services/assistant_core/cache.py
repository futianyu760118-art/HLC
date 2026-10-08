"""助手查询结果缓存。

设计：
- 基于 functools.lru_cache 风格的内存缓存
- 缓存 key = hash(role + task_template_id + entities_sorted)
- TTL 控制缓存有效期（默认 120 秒）
- 最大缓存 128 条
- 线程安全（简单锁）
- 不缓存写操作 / high risk / fallback
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger('hengpintong.assistant.cache')

MAX_SIZE = 128
DEFAULT_TTL = 120  # 秒


class _Entry:
    __slots__ = ('value', 'expires_at')

    def __init__(self, value: Dict[str, Any], ttl: float):
        self.value = value
        self.expires_at = time.monotonic() + ttl


class AssistantCache:
    """简单的 TTL LRU 缓存。"""

    def __init__(self, max_size: int = MAX_SIZE, ttl: float = DEFAULT_TTL):
        self._data: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size
        self._ttl = ttl
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _make_key(role: str, task_template_id: str, entities: Dict[str, Any]) -> str:
        # 排序 entities 确保一致性
        sorted_ent = json.dumps(entities, sort_keys=True, ensure_ascii=False, default=str)
        raw = f'{role}:{task_template_id}:{sorted_ent}'
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, role: str, task_template_id: str, entities: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key = self._make_key(role, task_template_id, entities)
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            if now > entry.expires_at:
                # 过期
                del self._data[key]
                self._misses += 1
                return None
            # 命中：移到末尾（LRU）
            self._data.move_to_end(key)
            self._hits += 1
            return entry.value

    def put(self, role: str, task_template_id: str, entities: Dict[str, Any],
            value: Dict[str, Any], ttl: Optional[float] = None):
        key = self._make_key(role, task_template_id, entities)
        with self._lock:
            if key in self._data:
                del self._data[key]
            self._data[key] = _Entry(value, ttl or self._ttl)
            # 淘汰
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)

    def stats(self) -> Dict[str, int]:
        return {
            'hits': self._hits,
            'misses': self._misses,
            'size': len(self._data),
        }

    def clear(self):
        with self._lock:
            self._data.clear()


# 全局单例
query_cache = AssistantCache()
