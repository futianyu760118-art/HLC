"""Read-only intelligent SQL query support for the assistant.

This module is the bounded escape hatch for questions that outgrow the fixed
skill set. It never exposes database credentials to the model and only executes
validated SELECT/CTE statements through SQLAlchemy.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from flask import g, has_request_context
from sqlalchemy import inspect, text
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from urllib.parse import quote_plus

from models import db

from . import llm_client, widgets as W
from .constants import (
    PAYROLL_AUTHORIZED_ROLES,
    PRIVILEGED_ROLES,
    ROLE_RECRUITER,
)
from .guardrails import mask_email, mask_id_card, mask_phone

logger = logging.getLogger('hengpintong.assistant.smart_query')

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_SCHEMA_TABLES = 80
MAX_SCHEMA_COLUMNS_PER_TABLE = 40
_READONLY_ENGINE: Optional[Engine] = None

WRITE_OR_DDL_RE = re.compile(
    r'\b('
    r'insert|update|delete|drop|truncate|alter|create|replace|merge|upsert|'
    r'grant|revoke|attach|detach|pragma|vacuum|analyze|call|execute|exec|'
    r'load|into|outfile|dumpfile|lock|unlock'
    r')\b',
    re.I,
)

COMMENT_RE = re.compile(r'(--|#|/\*|\*/)')
FOR_UPDATE_RE = re.compile(r'\bfor\s+update\b', re.I)
DANGEROUS_READ_RE = re.compile(
    r'\b(?:for\s+share|lock\s+in\s+share\s+mode)\b|'
    r'\b(?:load_file|sleep|benchmark|get_lock|release_lock|is_free_lock|is_used_lock|'
    r'master_pos_wait|wait_for_executed_gtid_set)\s*\(',
    re.I,
)
LIMIT_RE = re.compile(r'\blimit\s+\d+\b', re.I)
SENSITIVE_SQL_IDENTIFIER_RE = re.compile(
    r'\b(?:password|password_hash|token|secret|api_key|secret_ref)\b',
    re.I,
)
SQL_STRING_LITERAL_RE = re.compile(
    r"'(?:''|\\.|[^'])*'|\"(?:\"\"|\\.|[^\"])*\"",
    re.DOTALL,
)
SQL_FUNCTION_CALL_RE = re.compile(
    r'(?<![A-Za-z0-9_$:])([A-Za-z_][A-Za-z0-9_$]*)\s*\(',
    re.I,
)
SAFE_READ_FUNCTIONS = frozenset({
    'in', 'exists', 'over', 'partition',
    'abs', 'avg', 'ceil', 'ceiling', 'count', 'floor', 'max', 'min', 'round', 'sum',
    'coalesce', 'if', 'ifnull', 'nullif',
    'cast', 'convert', 'decimal', 'numeric', 'char', 'varchar', 'signed', 'unsigned',
    'concat', 'concat_ws', 'group_concat', 'lower', 'upper', 'length',
    'char_length', 'substr', 'substring', 'trim', 'ltrim', 'rtrim', 'replace',
    'date', 'time', 'datetime', 'strftime', 'julianday', 'date_format',
    'datediff', 'timestampdiff', 'unix_timestamp', 'from_unixtime', 'extract',
    'year', 'month', 'day', 'dayofmonth',
    'json_extract', 'json_unquote', 'json_array_length', 'json_length',
})
_TABLE_REFERENCE_RE = re.compile(
    r'\b(?:from|join)\s+([`"]?)([A-Za-z_][A-Za-z0-9_]*)\1'
    r'(?:\s+(?:as\s+)?([A-Za-z_][A-Za-z0-9_]*))?',
    re.I,
)
_SQL_RESERVED_ALIASES = frozenset({
    'where', 'join', 'left', 'right', 'inner', 'outer', 'full', 'cross', 'on',
    'group', 'order', 'having', 'limit', 'offset', 'union', 'intersect', 'except',
})
_TENANT_SCOPE_BOUNDARY_RE = re.compile(
    r'\b(?:'
    r'(?:left|right|full|inner|cross)\s+(?:outer\s+)?join|join|'
    r'where|group\s+by|order\s+by|having|limit'
    r')\b',
    re.I,
)


def build_schema_summary() -> str:
    """Return a compact schema summary for SQL planning prompts."""

    return _schema_summary_cached(_schema_signature())


def reset_readonly_engine_for_tests() -> None:
    global _READONLY_ENGINE
    if _READONLY_ENGINE is not None:
        _READONLY_ENGINE.dispose()
    _READONLY_ENGINE = None


def _schema_signature() -> str:
    try:
        tables = sorted(db.metadata.tables.keys())
        return '|'.join(tables)
    except Exception:
        return 'unknown'


@lru_cache(maxsize=4)
def _schema_summary_cached(_signature: str) -> str:
    lines: List[str] = []
    try:
        inspector = inspect(db.engine)
        table_names = sorted(inspector.get_table_names())[:MAX_SCHEMA_TABLES]
        metadata_tables = db.metadata.tables
        for table_name in table_names:
            table = metadata_tables.get(table_name)
            columns: List[str] = []
            if table is not None:
                for column in list(table.columns)[:MAX_SCHEMA_COLUMNS_PER_TABLE]:
                    marker = ' pk' if column.primary_key else ''
                    fks = [fk.column.table.name for fk in column.foreign_keys]
                    fk_marker = f' -> {",".join(sorted(set(fks)))}' if fks else ''
                    columns.append(f'{column.name}:{_type_name(column.type)}{marker}{fk_marker}')
            else:
                for column in inspector.get_columns(table_name)[:MAX_SCHEMA_COLUMNS_PER_TABLE]:
                    columns.append(f'{column["name"]}:{_type_name(column.get("type"))}')
            lines.append(f'- {table_name}({"; ".join(columns)})')
    except Exception:
        logger.exception('schema_summary_failed')
        for table_name, table in sorted(db.metadata.tables.items()):
            columns = [f'{c.name}:{_type_name(c.type)}' for c in list(table.columns)[:MAX_SCHEMA_COLUMNS_PER_TABLE]]
            lines.append(f'- {table_name}({"; ".join(columns)})')
    return '\n'.join(lines)


def _type_name(value: Any) -> str:
    """Return a compact SQLAlchemy type name without dialect compilation."""
    if value is None:
        return 'unknown'
    name = value.__class__.__name__
    length = getattr(value, 'length', None)
    precision = getattr(value, 'precision', None)
    scale = getattr(value, 'scale', None)
    if length:
        return f'{name}({length})'
    if precision:
        return f'{name}({precision},{scale or 0})'
    return name


def generate_sql_from_question(question: str, *, role: str, limit: int = DEFAULT_LIMIT, ctx=None) -> Optional[Dict[str, Any]]:
    """Ask the configured strong model for a read-only SQL plan."""

    deterministic = _deterministic_sql_plan(question)
    if deterministic:
        return deterministic
    if not llm_client.is_available():
        return None
    schema = build_schema_summary()
    prompt = {
        'user_question': question,
        'current_role': role,
        'schema_summary': schema,
        'rules': [
            '只能生成一条只读 SELECT 或 WITH ... SELECT 查询。',
            '不要生成 INSERT/UPDATE/DELETE/DDL/审批/发送/创建等副作用语句。',
            f'默认 LIMIT 不超过 {limit}；聚合统计可以返回更少行。',
            '字段名和表名必须来自 schema_summary。',
            '输出 JSON：{"sql": "...", "explanation": "...", "chart_hint": "table|bar|line|pie|none"}。',
        ],
    }
    if _current_request_tenant_id():
        prompt['rules'].extend([
            '只能查询含 tenant_id 的租户业务表，每个 FROM/JOIN 表必须使用别名。',
            'FROM 主表必须在 WHERE 中使用“别名.tenant_id = :tenant_id”绑定当前企业。',
            '每个 JOIN 表必须在自己的 JOIN ON 中使用“别名.tenant_id = :tenant_id”绑定当前企业。',
            '禁止 OR、CTE、子查询、UNION/INTERSECT/EXCEPT、通配符和敏感凭据字段。',
        ])
    raw = llm_client.json_chat_profile(
        'strong',
        [
            {
                'role': 'system',
                'content': (
                    '你是恒聘通 HRM 的只读 SQL 规划器。你只根据给定 schema 生成查询计划，'
                    '不回答业务结论，不编造表字段。'
                ),
            },
            {'role': 'user', 'content': json.dumps(prompt, ensure_ascii=False)},
        ],
        temperature=0.03,
        max_tokens=1400,
        timeout=_smart_sql_generation_timeout(),
        use_case='smart_sql_generation',
        retry_once=False,
        ctx=ctx,
    )
    if not isinstance(raw, dict):
        return None
    sql = raw.get('sql') or raw.get('query')
    if not isinstance(sql, str) or not sql.strip():
        return None
    return {
        'sql': sql,
        'explanation': str(raw.get('explanation') or raw.get('reason') or ''),
        'chart_hint': str(raw.get('chart_hint') or raw.get('chartHint') or 'table'),
    }


def validate_readonly_sql(
    sql: str,
    *,
    limit: int = DEFAULT_LIMIT,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Validate and normalize a SQL string.

    Returns ``(ok, normalized_sql, error)``. ``normalized_sql`` includes an
    appended LIMIT when the statement has none.
    """

    cleaned = _strip_sql(sql)
    if not cleaned:
        return False, '', 'SQL 为空。'
    if COMMENT_RE.search(cleaned):
        return False, '', 'SQL 中包含注释或可疑片段。'
    stripped = cleaned.rstrip(';').strip()
    if ';' in stripped:
        return False, '', '一次只允许执行一条 SELECT 查询。'
    if (
        WRITE_OR_DDL_RE.search(stripped)
        or FOR_UPDATE_RE.search(stripped)
        or DANGEROUS_READ_RE.search(stripped)
        or ':=' in stripped
    ):
        return False, '', '只支持只读 SELECT 查询，写入、删除、审批或 DDL 请走确认动作工具。'
    if not re.match(r'^\s*(select|with)\b', stripped, flags=re.I):
        return False, '', '只支持 SELECT 或 WITH ... SELECT 查询。'
    sql_without_literals = SQL_STRING_LITERAL_RE.sub("''", stripped)
    if any(
        match.group(1).lower() not in SAFE_READ_FUNCTIONS
        for match in SQL_FUNCTION_CALL_RE.finditer(sql_without_literals)
    ):
        return False, '', '智能查询禁止调用未审核的数据库函数。'
    if tenant_id:
        tenant_error = _validate_tenant_scoped_sql(stripped)
        if tenant_error:
            return False, '', tenant_error
    normalized = stripped
    if not LIMIT_RE.search(normalized):
        normalized = f'{normalized}\nLIMIT {max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))}'
    return True, normalized, None


def execute_smart_sql(
    *,
    question: str,
    sql: Optional[str],
    explanation: str,
    ctx: Any,
    limit: int = DEFAULT_LIMIT,
) -> Dict[str, Any]:
    """Execute a validated SELECT and return assistant skill output."""

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    generated: Optional[Dict[str, Any]] = None
    if not sql:
        generated = generate_sql_from_question(question, role=getattr(ctx, 'role', ''), limit=limit, ctx=ctx)
        sql = (generated or {}).get('sql')
        explanation = explanation or (generated or {}).get('explanation') or ''
    tenant_id = _current_request_tenant_id()
    ok, normalized_sql, error = validate_readonly_sql(
        sql or '',
        limit=limit,
        tenant_id=tenant_id,
    )
    if not ok:
        return _rejected_output(error or '只支持只读 SELECT 查询。', question, sql or '')

    result_proxy = None
    connection = None
    try:
        engine = get_readonly_engine()
        if engine is not None:
            connection = engine.connect()
            result_proxy = connection.execute(
                text(normalized_sql),
                {'tenant_id': tenant_id} if tenant_id else {},
            )
        else:
            result_proxy = db.session.execute(
                text(normalized_sql),
                {'tenant_id': tenant_id} if tenant_id else {},
            )
        rows = _fetch_rows(result_proxy, limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception('smart_sql_execute_failed')
        return {
            'entities': [],
            'widgets': [W.warning(f'智能查询执行失败：{exc}', level='warning')],
            'facts': {
                'ok': False,
                'sql': normalized_sql,
                'question': question,
                'error': str(exc),
            },
            'rows_count': 0,
            'summary_hint': '智能查询执行失败，请换个问法或缩小范围。',
        }
    finally:
        close = getattr(result_proxy, 'close', None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    redacted_rows = [_redact_row(row, getattr(ctx, 'role', '')) for row in rows]
    columns = _columns_from_rows(redacted_rows)
    tables = _extract_table_names(normalized_sql)
    summary = _summarize_result(question, normalized_sql, redacted_rows, explanation, ctx=ctx)
    widgets: List[Dict[str, Any]] = []
    if columns and redacted_rows:
        table_widget = W.data_table(columns, redacted_rows, title='智能查询结果')
        table_widget['type'] = 'data_table'
        widgets.append(table_widget)
    widgets.append({
        'type': 'source_citations',
        'title': '查询来源',
        'sources': [
            {
                'module': 'database',
                'recordType': 'table',
                'id': table_name,
                'title': table_name,
            }
            for table_name in tables
        ] or [{'module': 'database', 'recordType': 'query', 'title': '只读 SQL 查询'}],
    })
    return {
        'entities': [],
        'widgets': widgets,
        'facts': {
            'ok': True,
            'question': question,
            'sql': normalized_sql,
            'explanation': explanation,
            'tables': tables,
            'columns': [c['key'] for c in columns],
            'rows': redacted_rows,
            'row_count': len(redacted_rows),
            'generated': bool(generated),
        },
        'rows_count': len(redacted_rows),
        'summary_hint': summary,
    }


def _strip_sql(sql: str) -> str:
    value = (sql or '').strip()
    value = re.sub(r'^```(?:sql)?\s*', '', value, flags=re.I)
    value = re.sub(r'\s*```$', '', value)
    return value.strip()


def _smart_sql_generation_timeout() -> int:
    raw = os.getenv('ASSISTANT_SMART_SQL_GENERATION_TIMEOUT')
    try:
        value = int(raw) if raw else 8
    except ValueError:
        value = 8
    return max(2, min(value, 30))


def _smart_sql_summary_timeout() -> int:
    raw = os.getenv('ASSISTANT_SMART_SQL_SUMMARY_TIMEOUT')
    try:
        value = int(raw) if raw else 5
    except ValueError:
        value = 5
    return max(1, min(value, 20))


def _deterministic_sql_plan(question: str) -> Optional[Dict[str, Any]]:
    text_value = question or ''
    if _has_terms(text_value, ('低绩效', '绩效')) and _has_terms(text_value, ('考勤异常', '打卡异常', '迟到', '缺卡', '早退', '考勤')):
        tenant_scoped = bool(_current_request_tenant_id())
        return {
            'sql': (
                'SELECT e.name AS employee_name, e.department_id, pr.grade, pr.final_score, '
                'COUNT(ar.id) AS attendance_anomaly_count '
                'FROM employees e '
                'JOIN performance_reviews pr ON pr.employee_id = e.id '
                + ('AND pr.tenant_id = :tenant_id ' if tenant_scoped else '')
                + "LEFT JOIN attendance_records ar ON ar.employee_id = e.id "
                + ('AND ar.tenant_id = :tenant_id ' if tenant_scoped else '')
                + "AND COALESCE(ar.status, 'normal') <> 'normal' "
                + ('WHERE e.tenant_id = :tenant_id AND ' if tenant_scoped else 'WHERE ')
                + "CASE WHEN UPPER(COALESCE(pr.grade, '')) IN ('C', 'D', 'E', 'F') THEN 1 "
                "WHEN pr.grade IN ('不合格', '待改进') THEN 1 "
                'WHEN COALESCE(pr.final_score, 100) < 70 THEN 1 ELSE 0 END = 1 '
                'GROUP BY e.id, e.name, e.department_id, pr.grade, pr.final_score '
                'ORDER BY attendance_anomaly_count DESC, pr.final_score ASC'
            ),
            'explanation': '按低绩效员工与非正常考勤记录做只读交叉统计。',
            'chart_hint': 'table',
            'source': 'deterministic_hrm_template',
        }
    return None


def _has_terms(text_value: str, terms: Sequence[str]) -> bool:
    return any(term in text_value for term in terms)


def _current_request_tenant_id() -> Optional[str]:
    if not has_request_context():
        return None
    tenant_id = getattr(g, 'tenant_id', None)
    return str(tenant_id) if tenant_id is not None and str(tenant_id).strip() else None


def _validate_tenant_scoped_sql(sql: str) -> Optional[str]:
    """Fail closed on raw SQL unless every referenced table is tenant-bound.

    This intentionally supports a small flat-SELECT grammar. More expressive
    tenant analytics belong in reviewed skills or tenant-specific database
    views, not model-authored SQL.
    """

    if not re.match(r'^\s*select\b', sql, re.I):
        return '企业范围的智能查询只支持扁平 SELECT，不支持 CTE。'
    if re.search(r'\b(?:union|intersect|except|or|xor|not|is|straight_join)\b|\(\s*select\b', sql, re.I):
        return '企业范围的智能查询不支持 OR、子查询或集合查询。'
    if re.search(r'\bselect\s+\*|\b[A-Za-z_][A-Za-z0-9_]*\.\*', sql, re.I):
        return '企业范围的智能查询不支持通配符字段。'
    if SENSITIVE_SQL_IDENTIFIER_RE.search(sql):
        return '企业范围的智能查询禁止读取凭据或密钥字段。'
    if _top_level_from_clause_has_comma(sql):
        return '企业范围的智能查询不支持逗号连接。'

    structural_sql = SQL_STRING_LITERAL_RE.sub("''", sql)
    references: list[tuple[str, str, re.Match[str]]] = []
    aliases: set[str] = set()
    for match in _TABLE_REFERENCE_RE.finditer(structural_sql):
        table_name = match.group(2)
        raw_alias = match.group(3)
        if not raw_alias or raw_alias.lower() in _SQL_RESERVED_ALIASES:
            return f'企业范围的智能查询要求表 {table_name} 使用显式别名。'
        alias = raw_alias
        table_key = table_name.lower()
        alias_key = alias.lower()
        if alias_key in aliases:
            return '企业范围的智能查询包含重复表别名。'
        aliases.add(alias_key)
        table = db.metadata.tables.get(table_key)
        if table is None or 'tenant_id' not in table.columns:
            return f'企业范围的智能查询禁止访问非租户业务表：{table_name}。'
        references.append((table_key, alias_key, match))

    if not references:
        return '企业范围的智能查询必须引用租户业务表。'

    where_match = re.search(r'\bwhere\b', structural_sql, re.I)
    where_body: Optional[str] = None
    if where_match:
        where_tail = structural_sql[where_match.end():]
        boundary = re.search(r'\b(?:group\s+by|order\s+by|having|limit)\b', where_tail, re.I)
        where_body = where_tail[:boundary.start()] if boundary else where_tail

    base_alias = references[0][1]
    if where_body is None or not _has_exact_tenant_conjunct(where_body, base_alias):
        return f'企业范围的智能查询缺少 WHERE {base_alias}.tenant_id = :tenant_id 条件。'

    for _table_name, alias, match in references[1:]:
        join_tail = structural_sql[match.end():]
        boundary = _TENANT_SCOPE_BOUNDARY_RE.search(join_tail)
        join_clause = join_tail[:boundary.start()] if boundary else join_tail
        on_match = re.match(r'\s*on\b', join_clause, re.I)
        if on_match is None or not _has_exact_tenant_conjunct(join_clause[on_match.end():], alias):
            return f'企业范围的智能查询缺少 JOIN {alias} 的 tenant_id = :tenant_id 条件。'
    return None


def _has_exact_tenant_conjunct(fragment: str, alias: str) -> bool:
    return bool(re.search(
        rf'(?:^\s*|\band\s+){re.escape(alias)}\.tenant_id\s*=\s*:tenant_id'
        rf'(?=\s*(?:\band\b|$))',
        fragment,
        re.I,
    ))


def _top_level_from_clause_has_comma(sql: str) -> bool:
    """Detect legacy comma joins without confusing SELECT/GROUP commas.

    The tenant grammar already rejects subqueries. This scanner only needs to
    track quoted strings/identifiers and parenthesized function expressions so
    a depth-zero comma between FROM and the next clause is unambiguously a new
    table source.
    """

    in_from_clause = False
    depth = 0
    quote: Optional[str] = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote is not None:
            if char == '\\':
                index += 2
                continue
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in {"'", '"', '`'}:
            quote = char
            index += 1
            continue
        if char == '(':
            depth += 1
            index += 1
            continue
        if char == ')':
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0 and char == ',' and in_from_clause:
            return True
        if depth == 0 and (char.isalpha() or char == '_'):
            end = index + 1
            while end < len(sql) and (sql[end].isalnum() or sql[end] == '_'):
                end += 1
            token = sql[index:end].lower()
            if token == 'from':
                in_from_clause = True
            elif in_from_clause and token in {'where', 'group', 'order', 'having', 'limit'}:
                return False
            index = end
            continue
        index += 1
    return False


def get_readonly_engine() -> Optional[Engine]:
    """Return a dedicated read-only engine when DB_READONLY_* is configured.

    Tests and local SQLite fixtures can omit these variables; production Docker
    now provides them so smart SQL never uses the write application account.
    """
    global _READONLY_ENGINE
    if _READONLY_ENGINE is not None:
        return _READONLY_ENGINE

    uri = os.getenv('DB_READONLY_URI') or ''
    if not uri:
        user = os.getenv('DB_READONLY_USER') or ''
        password = os.getenv('DB_READONLY_PASSWORD') or ''
        host = os.getenv('DB_READONLY_HOST') or os.getenv('DB_HOST') or ''
        port = os.getenv('DB_READONLY_PORT') or os.getenv('DB_PORT') or '3306'
        name = os.getenv('DB_READONLY_NAME') or os.getenv('DB_NAME') or ''
        if not (user and password and host and name):
            return None
        uri = (
            f'mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}'
            f'@{host}:{port}/{name}?charset=utf8mb4'
        )
    engine_options: Dict[str, Any] = {'pool_pre_ping': True}
    if not uri.startswith('sqlite'):
        engine_options.update({
            'pool_recycle': 280,
            'pool_size': int(os.getenv('DB_READONLY_POOL_SIZE', '2')),
            'max_overflow': int(os.getenv('DB_READONLY_MAX_OVERFLOW', '4')),
        })
    _READONLY_ENGINE = create_engine(uri, **engine_options)
    return _READONLY_ENGINE


def _fetch_rows(result_proxy: Any, limit: int) -> List[Dict[str, Any]]:
    """Fetch rows from SQLAlchemy 1.x ResultProxy or 2.x Result."""
    if hasattr(result_proxy, 'mappings'):
        return [dict(row) for row in result_proxy.mappings().fetchmany(limit)]
    keys = list(result_proxy.keys())
    rows: List[Dict[str, Any]] = []
    for row in result_proxy.fetchmany(limit):
        rows.append({str(key): row[idx] for idx, key in enumerate(keys)})
    return rows


def _rejected_output(reason: str, question: str, sql: str) -> Dict[str, Any]:
    return {
        'entities': [],
        'widgets': [W.warning(reason, level='warning')],
        'facts': {
            'ok': False,
            'rejected': True,
            'question': question,
            'sql': sql,
            'reason': reason,
        },
        'rows_count': 0,
        'summary_hint': reason,
    }


def _columns_from_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    keys: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(str(key))
    return [{'key': key, 'label': _label_for_column(key)} for key in keys[:40]]


def _label_for_column(key: str) -> str:
    labels = {
        'cnt': '数量',
        'count': '数量',
        'total': '合计',
        'avg': '平均值',
        'name': '姓名',
        'title': '标题',
        'status': '状态',
        'department': '部门',
        'job_title': '岗位',
        'created_at': '创建时间',
        'updated_at': '更新时间',
    }
    return labels.get(key, key)


def _redact_row(row: Dict[str, Any], role: str) -> Dict[str, Any]:
    return {str(key): _redact_value(str(key), value, role) for key, value in row.items()}


def _redact_value(key: str, value: Any, role: str) -> Any:
    if value is None:
        return None
    lower = key.lower()
    plain = _to_plain(value)
    if role in PRIVILEGED_ROLES:
        return plain
    if any(token in lower for token in ('salary', 'payroll', 'wage', 'bonus', 'allowance', 'deduction', 'gross', 'net_salary', 'base_salary')):
        if role not in PAYROLL_AUTHORIZED_ROLES:
            return '***'
    if any(token in lower for token in ('phone', 'mobile', 'tel')):
        if role != ROLE_RECRUITER:
            return mask_phone(str(plain))
    if 'email' in lower or 'mail' == lower:
        if role != ROLE_RECRUITER:
            return mask_email(str(plain))
    if any(token in lower for token in ('id_no', 'idno', 'id_card', 'idcard', 'card_no', 'identity')):
        return mask_id_card(str(plain))
    if any(token in lower for token in ('address', 'bank', 'emergency')):
        return '***'
    return plain


def _to_plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    return value


def _extract_table_names(sql: str) -> List[str]:
    tables: List[str] = []
    for match in re.finditer(r'\b(?:from|join)\s+([`"\[]?)([A-Za-z_][A-Za-z0-9_]*)\1', sql, re.I):
        table = match.group(2)
        if table and table.lower() not in {'select'} and table not in tables:
            tables.append(table)
    return tables[:12]


def _summarize_result(question: str, sql: str, rows: Sequence[Dict[str, Any]], explanation: str, ctx=None) -> str:
    base = f'只读 SQL 查询返回 {len(rows)} 行。'
    deterministic = _deterministic_summary(question, rows)
    if deterministic:
        return deterministic
    if not rows:
        return base
    if not llm_client.is_available():
        return base
    try:
        payload = {
            'question': question,
            'sql': sql,
            'explanation': explanation,
            'rows_preview': list(rows[:20]),
            'instruction': '用中文给出 1-3 句业务总结，不要输出 SQL，不要编造未出现的数据。',
        }
        msg = llm_client.chat_profile(
            'standard',
            [
                {'role': 'system', 'content': '你是恒聘通 HRM 的数据分析摘要助手。'},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            temperature=0.2,
            max_tokens=350,
            timeout=_smart_sql_summary_timeout(),
            use_case='smart_sql_summary',
            retry_once=False,
            ctx=ctx,
        )
        text_out = llm_client.clean_text((msg or {}).get('content') or '')
        return text_out or base
    except Exception:  # noqa: BLE001
        logger.debug('smart_sql_summary_failed', exc_info=True)
        return base


def _deterministic_summary(question: str, rows: Sequence[Dict[str, Any]]) -> str:
    text_value = question or ''
    if not (_has_terms(text_value, ('低绩效', '绩效')) and _has_terms(text_value, ('考勤异常', '打卡异常', '迟到', '缺卡', '早退', '考勤'))):
        return ''
    if not rows:
        return '当前没有低绩效员工与考勤异常的交叉记录。'
    first = rows[0]
    name = first.get('employee_name') or first.get('name') or '排名最高员工'
    anomaly_count = first.get('attendance_anomaly_count')
    if anomaly_count is None:
        anomaly_count = first.get('cnt')
    return f'低绩效与考勤异常交叉统计返回 {len(rows)} 人，其中 {name} 的异常考勤次数最高，为 {anomaly_count or 0} 次。'


__all__ = [
    'build_schema_summary',
    'generate_sql_from_question',
    'validate_readonly_sql',
    'execute_smart_sql',
    'get_readonly_engine',
    'reset_readonly_engine_for_tests',
]
