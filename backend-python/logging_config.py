"""统一日志配置。

特性：
- JSON 行结构化日志（便于 Loki/ELK 摄取）；本地开发可切回纯文本
- 通过 LOG_FORMAT=text|json 切换
- 自动注入 request_id（与中间件 g.request_id 联动）
- 默认 INFO，可通过 LOG_LEVEL 覆盖
"""

import json
import logging
import os
import sys
import re
from datetime import datetime, timezone
from typing import Any, Dict

try:
    from flask import g, has_request_context, request
except ImportError:  # 早期导入或非 Flask 环境
    g = None
    has_request_context = lambda: False  # noqa: E731
    request = None


_EMAIL_RE = re.compile(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b')
_MOBILE_RE = re.compile(r'(?<!\d)(?:(?:\+?86|0086)[\s-]?)?1[3-9]\d{9}(?!\d)')
_IPV4_RE = re.compile(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])')
_SENSITIVE_LOG_KEYS = frozenset({
    'authorization',
    'apikey',
    'companyname',
    'contactname',
    'cookie',
    'email',
    'idempotencykey',
    'internalnote',
    'mobile',
    'notes',
    'password',
    'phone',
    'rawrequestbody',
    'requestbody',
    'secret',
    'token',
})


def _redact_text(value: str) -> str:
    result = _EMAIL_RE.sub('[REDACTED_EMAIL]', value)
    result = _MOBILE_RE.sub('[REDACTED_MOBILE]', result)
    return _IPV4_RE.sub('[REDACTED_IP]', result)


def _redact_value(value: Any, *, key: Any = None) -> Any:
    normalized_key = re.sub(r'[^a-z0-9]', '', str(key or '').lower())
    if normalized_key in _SENSITIVE_LOG_KEYS:
        return '[REDACTED]'
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {str(item_key): _redact_value(item, key=item_key) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_redact_value(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """大厂常用的结构化 JSON 日志格式。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            'time': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': _redact_text(record.getMessage()),
        }
        if record.exc_info:
            payload['exception'] = _redact_text(self.formatException(record.exc_info))

        if has_request_context():
            try:
                payload['request_id'] = getattr(g, 'request_id', None)
                payload['method'] = request.method
                payload['path'] = request.path
            except Exception:
                pass

        # 非默认字段（用 logger.info("msg", extra={...})）
        for key, value in record.__dict__.items():
            if key in payload or key.startswith('_'):
                continue
            if key in (
                'args', 'created', 'exc_info', 'exc_text', 'filename', 'funcName',
                'levelname', 'levelno', 'lineno', 'message', 'module', 'msecs',
                'msg', 'name', 'pathname', 'process', 'processName', 'relativeCreated',
                'stack_info', 'thread', 'threadName', 'taskName',
            ):
                continue
            try:
                json.dumps(value)
                payload[key] = _redact_value(value, key=key)
            except (TypeError, ValueError):
                payload[key] = _redact_text(str(value))

        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(
            fmt='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )

    def format(self, record: logging.LogRecord) -> str:
        return _redact_text(super().format(record))


def configure_logging() -> None:
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    fmt = os.getenv('LOG_FORMAT', 'json' if os.getenv('NODE_ENV') == 'production' else 'text')

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == 'json' else TextFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # 降低噪声但保留关键信息
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
