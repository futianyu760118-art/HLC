"""Safety contracts shared by platform evaluation request handling."""

from __future__ import annotations

import json
import copy
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from flask import g
from sqlalchemy import Delete, Insert, Update, event, inspect as sqlalchemy_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.pool.base import _ConnectionFairy
from sqlalchemy.sql import visitors
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BindParameter, BinaryExpression, ColumnClause, TextClause
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.orm import Session

from models import (
    AIUsageLedger,
    AssistantAuditLog,
    AssistantEvaluationRun,
    AssistantSession,
    Tenant,
    User,
    db,
)


_EXECUTION_USER_ID_OVERRIDE: ContextVar[Optional[str]] = ContextVar(
    'evaluation_execution_user_id_override',
    default=None,
)
@dataclass
class _ReadOnlyEvaluationState:
    tenant_id: str
    run_user_id: str
    metadata_identities: set[tuple[type, str]] = field(default_factory=set)


_READ_ONLY_EVALUATION_SCOPE: ContextVar[Optional[_ReadOnlyEvaluationState]] = ContextVar(
    'read_only_evaluation_scope',
    default=None,
)
_RUN_AS_VALUE_UNSET = object()

_ALLOWED_METADATA_TYPES = (
    AssistantSession,
    AssistantAuditLog,
    AssistantEvaluationRun,
    AIUsageLedger,
)
_ALLOWED_DIRTY_FIELDS = {
    AssistantSession: {'title', 'messages', 'is_active', 'message_count', 'updated_at'},
    AssistantAuditLog: {'session_id', 'response_meta'},
    AssistantEvaluationRun: {
        'session_id',
        'actual_modules',
        'actual_render_blocks',
        'used_tools',
        'evidence_sources',
        'entity_summary',
        'time_range',
        'response_summary',
        'pass_status',
        'failure_categories',
        'missing_expectations',
        'root_cause_notes',
        'fix_plan',
        'response_payload',
    },
    AIUsageLedger: set(),
}
_ALLOWED_METADATA_TABLES = frozenset(
    model.__table__.name for model in _ALLOWED_METADATA_TYPES
)
_MUTATING_SQL_RE = re.compile(
    r'^\s*(?:insert|update|delete|replace|truncate|alter|drop|create)\b',
    re.IGNORECASE,
)
_MUTATING_SQL_ANYWHERE_RE = re.compile(
    r'\b(?:insert|update|delete|replace|truncate|alter|drop|create|merge|upsert|'
    r'grant|revoke|attach|detach|pragma|vacuum|analyze|call|execute|exec|load|'
    r'rename|set|use|optimize|repair|install|uninstall|import|clone|flush|reset|'
    r'purge|shutdown|kill|outfile|dumpfile|lock|unlock)\b',
    re.IGNORECASE,
)
_LEADING_SQL_IGNORABLE_RE = re.compile(
    r'\A(?:\s+|--[^\r\n]*(?:\r?\n|\Z)|#[^\r\n]*(?:\r?\n|\Z)|/\*.*?\*/)*',
    re.DOTALL,
)
_COMPILED_CURSOR_ALLOWANCE_KEY = '_evaluation_compiled_cursor_allowance'
_TENANT_CHECKED_ORM_SELECT_KEY = '_evaluation_tenant_checked_orm_select'
_DIRECT_READ_QUERY_RE = re.compile(r'^\s*(?:select|with)\b', re.IGNORECASE)
_RAW_TABLE_REFERENCE_RE = re.compile(r'\b(?:from|join)\b', re.IGNORECASE)
_FOR_UPDATE_RE = re.compile(r'\bfor\s+update\b', re.IGNORECASE)
_DANGEROUS_READ_SQL_RE = re.compile(
    r'\b(?:for\s+share|lock\s+in\s+share\s+mode)\b|'
    r'\b(?:load_file|sleep|benchmark|get_lock|release_lock|is_free_lock|is_used_lock|'
    r'master_pos_wait|wait_for_executed_gtid_set)\s*\(',
    re.IGNORECASE,
)
_READ_ONLY_TRANSACTION_RE = re.compile(
    r'^\s*(?:savepoint\s+[A-Za-z0-9_$]+|'
    r'release\s+savepoint\s+[A-Za-z0-9_$]+|'
    r'rollback\s+to(?:\s+savepoint)?\s+[A-Za-z0-9_$]+)\s*;?\s*$',
    re.IGNORECASE,
)
_SAFE_COMPILED_READ_FUNCTIONS = frozenset({
    'abs', 'avg', 'coalesce', 'concat', 'count', 'date', 'datetime',
    'group_concat', 'ifnull', 'json_extract', 'json_unquote', 'length',
    'lower', 'ltrim', 'max', 'min', 'nullif', 'round', 'rtrim', 'strftime',
    'sum', 'trim', 'upper',
})


class EvaluationSafetyError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        case_ids: Optional[Iterable[str]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.case_ids = list(case_ids or [])


def _raise_read_only_violation(model_name: str) -> None:
    raise EvaluationSafetyError(
        'AI_EVALUATION_READ_ONLY_VIOLATION',
        f'只读评估禁止修改业务数据：{model_name}',
        status_code=409,
    )


_METADATA_IDENTITIES_IN_TRANSACTION_KEY = '_evaluation_metadata_identities_in_transaction'
_METADATA_PENDING_INSERT_IDENTITIES_KEY = '_evaluation_metadata_pending_insert_identities'
_METADATA_FLUSH_PERMISSIONS_KEY = '_evaluation_metadata_flush_permissions'
_VALIDATED_METADATA_DML_KEY = '_evaluation_validated_metadata_dml'


@dataclass
class _MetadataFlushPermissions:
    inserts: dict[str, set[str]] = field(default_factory=dict)
    updates: dict[tuple[str, str], set[str]] = field(default_factory=dict)


def _read_only_scope_state() -> Optional[_ReadOnlyEvaluationState]:
    return _READ_ONLY_EVALUATION_SCOPE.get()


def _assert_metadata_ownership(
    obj,
    *,
    tenant_id: str,
    run_user_id: str,
    bind_missing_user: bool,
) -> None:
    if hasattr(obj, 'tenant_id'):
        object_tenant_id = getattr(obj, 'tenant_id', None)
        if object_tenant_id is None:
            obj.tenant_id = tenant_id
        elif str(object_tenant_id) != tenant_id:
            _raise_read_only_violation(type(obj).__name__)
    if hasattr(obj, 'user_id'):
        object_user_id = getattr(obj, 'user_id', None)
        if object_user_id is None and bind_missing_user:
            obj.user_id = run_user_id
        elif object_user_id is None or str(object_user_id) != run_user_id:
            _raise_read_only_violation(type(obj).__name__)


def _metadata_identity(obj) -> tuple[type, str]:
    object_id = getattr(obj, 'id', None)
    if object_id is None or not str(object_id).strip():
        _raise_read_only_violation(type(obj).__name__)
    return type(obj), str(object_id)


@event.listens_for(Session, 'before_flush')
def _enforce_read_only_evaluation_flush(session, _flush_context, _instances):
    scope_state = _read_only_scope_state()
    if scope_state is None:
        return
    tenant_id = scope_state.tenant_id
    run_user_id = scope_state.run_user_id
    transaction_identities = session.info.setdefault(
        _METADATA_IDENTITIES_IN_TRANSACTION_KEY,
        set(),
    )
    pending_insert_identities = session.info.setdefault(
        _METADATA_PENDING_INSERT_IDENTITIES_KEY,
        set(),
    )
    flush_permissions = _MetadataFlushPermissions()

    if session.deleted:
        _raise_read_only_violation(type(next(iter(session.deleted))).__name__)

    for obj in session.new:
        if not isinstance(obj, _ALLOWED_METADATA_TYPES):
            _raise_read_only_violation(type(obj).__name__)
        _assert_metadata_ownership(
            obj,
            tenant_id=tenant_id,
            run_user_id=run_user_id,
            bind_missing_user=True,
        )
        identity = _metadata_identity(obj)
        pending_insert_identities.add(identity)
        flush_permissions.inserts.setdefault(obj.__table__.name, set()).add(identity[1])

    for obj in session.dirty:
        if obj in session.new:
            continue
        if not isinstance(obj, _ALLOWED_METADATA_TYPES):
            _raise_read_only_violation(type(obj).__name__)
        identity = _metadata_identity(obj)
        if (
            identity not in scope_state.metadata_identities
            and identity not in transaction_identities
        ):
            _raise_read_only_violation(type(obj).__name__)
        _assert_metadata_ownership(
            obj,
            tenant_id=tenant_id,
            run_user_id=run_user_id,
            bind_missing_user=False,
        )
        state = sqlalchemy_inspect(obj)
        changed_fields = {
            attr.key
            for attr in state.mapper.column_attrs
            if state.attrs[attr.key].history.has_changes()
        }
        allowed_fields = _ALLOWED_DIRTY_FIELDS.get(type(obj), set())
        if changed_fields - allowed_fields:
            _raise_read_only_violation(type(obj).__name__)
        if changed_fields:
            flush_permissions.updates[(obj.__table__.name, identity[1])] = set(changed_fields)

    # ``Session.before_flush`` runs immediately before SQLAlchemy emits the
    # INSERT/UPDATE statements for the explicitly allowlisted metadata rows.
    # Mark that connection briefly so the engine-level Core-DML guard below can
    # distinguish those statements from an evaluation body bypassing the ORM.
    try:
        connection = session.connection()
        connection.info[_METADATA_FLUSH_PERMISSIONS_KEY] = flush_permissions
        session.info['_evaluation_metadata_flush_connection'] = connection
    except Exception:
        # The ORM guard above remains authoritative if the connection cannot be
        # inspected (for example, a test double session).
        pass


def _discard_read_only_metadata_flush_marker(session) -> None:
    connection = session.info.pop('_evaluation_metadata_flush_connection', None)
    if connection is not None:
        try:
            connection.info.pop(_METADATA_FLUSH_PERMISSIONS_KEY, None)
            connection.info.pop(_VALIDATED_METADATA_DML_KEY, None)
        except Exception:
            # Cleanup must never replace the original flush/rollback failure
            # when SQLAlchemy has already invalidated or closed the connection.
            pass


@event.listens_for(Session, 'after_flush')
def _clear_read_only_metadata_flush_marker(session, _flush_context):
    pending_identities = session.info.pop(_METADATA_PENDING_INSERT_IDENTITIES_KEY, set())
    if pending_identities:
        session.info.setdefault(_METADATA_IDENTITIES_IN_TRANSACTION_KEY, set()).update(
            pending_identities
        )
    _discard_read_only_metadata_flush_marker(session)


@event.listens_for(Session, 'after_commit')
def _commit_read_only_metadata_identities(session):
    identities = session.info.pop(_METADATA_IDENTITIES_IN_TRANSACTION_KEY, set())
    scope_state = _read_only_scope_state()
    if scope_state is not None:
        scope_state.metadata_identities.update(identities)


@event.listens_for(Session, 'after_rollback')
def _clear_read_only_metadata_flush_marker_after_rollback(session):
    _discard_read_only_metadata_flush_marker(session)
    session.info.pop(_METADATA_IDENTITIES_IN_TRANSACTION_KEY, None)
    session.info.pop(_METADATA_PENDING_INSERT_IDENTITIES_KEY, None)


@event.listens_for(Session, 'do_orm_execute')
def _enforce_read_only_evaluation_statement(execute_state):
    scope_state = _read_only_scope_state()
    if scope_state is None:
        return
    if (
        str(getattr(g, 'tenant_id', '') or '') != scope_state.tenant_id
        or bool(getattr(g, 'is_platform_admin', False))
    ):
        _raise_read_only_violation('tenant_context_override')
    if execute_state.execution_options.get('skip_tenant_criteria'):
        _raise_read_only_violation('tenant_filter_opt_out')
    if any(
        bool(getattr(execute_state, flag, False))
        for flag in ('is_insert', 'is_update', 'is_delete')
    ):
        _raise_read_only_violation('bulk_statement')
    if bool(getattr(execute_state, 'is_select', False)):
        execute_state.update_execution_options(**{
            _TENANT_CHECKED_ORM_SELECT_KEY: scope_state,
        })


def _execution_parameter_sets(multiparams, params) -> list[dict[str, Any]]:
    if isinstance(multiparams, (list, tuple)) and multiparams:
        return [item for item in multiparams if isinstance(item, dict)]
    if isinstance(params, dict) and params:
        return [params]
    return []


def _update_primary_key_bind_key(statement, table_name: str) -> Optional[str]:
    for criterion in getattr(statement, '_where_criteria', ()):
        for node in visitors.iterate(criterion):
            if not isinstance(node, BinaryExpression) or node.operator is not operators.eq:
                continue
            for column, bound in ((node.left, node.right), (node.right, node.left)):
                if (
                    getattr(column, 'name', None) == 'id'
                    and getattr(getattr(column, 'table', None), 'name', None) == table_name
                    and isinstance(bound, BindParameter)
                ):
                    return str(bound.key)
    return None


def _metadata_dml_matches_current_flush(conn, statement, multiparams, params) -> bool:
    """Authorize only DML represented by the current ORM flush inventory."""

    permissions = conn.info.get(_METADATA_FLUSH_PERMISSIONS_KEY)
    table = getattr(statement, 'table', None)
    table_name = str(getattr(table, 'name', '') or '')
    if not isinstance(permissions, _MetadataFlushPermissions):
        return False
    if table_name not in _ALLOWED_METADATA_TABLES or table is None:
        return False
    parameter_sets = _execution_parameter_sets(multiparams, params)
    if not parameter_sets:
        return False

    if isinstance(statement, Insert):
        allowed_ids = permissions.inserts.get(table_name, set())
        return bool(allowed_ids) and all(
            str(item.get('id') or '') in allowed_ids
            for item in parameter_sets
        )
    if not isinstance(statement, Update):
        return False

    primary_key_bind = _update_primary_key_bind_key(statement, table_name)
    if not primary_key_bind:
        return False
    column_names = {str(column.name) for column in table.columns}
    for item in parameter_sets:
        object_id = str(item.get(primary_key_bind) or '')
        allowed_fields = permissions.updates.get((table_name, object_id))
        changed_fields = (set(item) & column_names) - {'id'}
        if not allowed_fields or not changed_fields or not changed_fields <= allowed_fields:
            return False
    return True


def _coerce_driver_sql_text(statement) -> Optional[str]:
    if isinstance(statement, str):
        return statement
    if isinstance(statement, (bytes, bytearray, memoryview)):
        # SQL verbs are ASCII; latin-1 preserves every byte one-to-one so a
        # non-UTF8 connection encoding cannot hide the leading operation.
        return bytes(statement).decode('latin-1')
    return None


def _normalize_single_sql_text(statement) -> Optional[str]:
    sql = _coerce_driver_sql_text(statement)
    if sql is None:
        return None
    prefix = _LEADING_SQL_IGNORABLE_RE.match(sql)
    if prefix is not None:
        sql = sql[prefix.end():]
    stripped = sql.strip()
    without_final_semicolon = stripped[:-1].rstrip() if stripped.endswith(';') else stripped
    if ';' in without_final_semicolon:
        return None
    return without_final_semicolon


def _is_read_only_sql_text(statement) -> bool:
    """Fail closed unless raw SQL is a simple, function-free read.

    Compiled SQLAlchemy SELECT statements receive a one-statement cursor
    allowance in ``_enforce_read_only_driver_sql``.  Raw DB-API text cannot
    safely distinguish a harmless built-in from a user-defined stored
    function that mutates business rows, so any parenthesized expression is
    rejected here.
    """
    sql = _normalize_single_sql_text(statement)
    if not sql:
        return False
    if _READ_ONLY_TRANSACTION_RE.fullmatch(sql):
        return True
    if not _DIRECT_READ_QUERY_RE.match(sql):
        return False
    if '(' in sql or ')' in sql:
        return False
    if (
        _RAW_TABLE_REFERENCE_RE.search(sql)
        or _MUTATING_SQL_ANYWHERE_RE.search(sql)
        or _FOR_UPDATE_RE.search(sql)
        or _DANGEROUS_READ_SQL_RE.search(sql)
    ):
        return False
    return not re.match(r'^\s*with\b', sql, re.IGNORECASE) or bool(
        re.search(r'\bselect\b', sql, re.IGNORECASE)
    )


def _is_mutating_sql_text(sql: str) -> bool:
    # The historical name is kept for the event hooks, but the decision is
    # intentionally fail-closed: unknown textual statements are not read-only.
    return not _is_read_only_sql_text(sql)


def _is_direct_read_query(statement) -> bool:
    """Allow only an unambiguous single SELECT/CTE on a driver ``query`` API."""
    sql = _normalize_single_sql_text(statement)
    return bool(
        sql
        and _DIRECT_READ_QUERY_RE.match(sql)
        and _is_read_only_sql_text(sql)
    )


def _is_mutating_text_statement(statement: TextClause) -> bool:
    return _is_mutating_sql_text(str(statement.text or ''))


def _compiled_select_is_read_only(statement) -> bool:
    """Accept only structurally read-only SQLAlchemy SELECT statements."""
    if not bool(getattr(statement, 'is_select', False)):
        return False
    if (
        statement.get_final_froms()
        and getattr(statement, '_propagate_attrs', {}).get('compile_state_plugin') != 'orm'
    ):
        # Tenant criteria are attached by the ORM execution path. Core table
        # selects bypass those criteria and therefore cannot be tenant-safe.
        return False
    if getattr(statement, '_for_update_arg', None) is not None:
        return False
    if getattr(statement, '_into', None) is not None:
        return False
    if any(
        bool(getattr(statement, attribute, None))
        for attribute in ('_statement_hints', '_hints', '_prefixes', '_suffixes')
    ):
        # Dialect hints and arbitrary prefixes/suffixes can render locking,
        # file-output, or vendor-specific side-effect clauses even though the
        # SQLAlchemy node still reports ``is_select``.
        return False
    for node in visitors.iterate(statement):
        if isinstance(node, TextClause):
            return False
        if (
            isinstance(node, ColumnClause)
            and bool(getattr(node, 'is_literal', False))
            and str(getattr(node, 'name', '')) != '*'
        ):
            return False
        if isinstance(node, FunctionElement):
            function_name = str(getattr(node, 'name', '') or '').lower()
            if function_name not in _SAFE_COMPILED_READ_FUNCTIONS:
                return False
    return True


_DRIVER_DML_TARGET_RE = re.compile(
    r'^\s*(?:insert\s+into|update|delete\s+from)\s+[`"\[]?([A-Za-z0-9_]+)[`"\]]?',
    re.IGNORECASE,
)


def _driver_sql_targets_metadata(sql: str) -> bool:
    """Accept only one simple DML statement for an evaluation table."""

    if not isinstance(sql, str) or ';' in sql:
        return False
    match = _DRIVER_DML_TARGET_RE.match(sql)
    return bool(match and match.group(1) in _ALLOWED_METADATA_TABLES)


@event.listens_for(Engine, 'before_execute', retval=True)
def _enforce_read_only_connection_dml(
    conn,
    clauseelement,
    multiparams,
    params,
    execution_options,
):
    """Close the connection-level Core SQL escape hatch.

    ``Session.do_orm_execute`` protects ``Session.execute(update(...))`` but
    does not see ``Session.connection().execute(...)`` or textual SQL.  During
    a read-only evaluation, only the four explicitly allowlisted metadata
    tables may be written, and only while SQLAlchemy is flushing those rows.
    """
    if _read_only_scope_state() is None:
        return clauseelement, multiparams, params

    is_dml = isinstance(clauseelement, (Insert, Update, Delete))
    is_mutating_text = (
        isinstance(clauseelement, TextClause)
        and _is_mutating_text_statement(clauseelement)
    )
    is_select = bool(getattr(clauseelement, 'is_select', False))
    is_unsafe_select = is_select and (
        not _compiled_select_is_read_only(clauseelement)
        or (
            bool(clauseelement.get_final_froms())
            and execution_options.get(_TENANT_CHECKED_ORM_SELECT_KEY)
            is not _read_only_scope_state()
        )
    )
    if not (is_dml or is_mutating_text or is_unsafe_select):
        return clauseelement, multiparams, params

    if (
        is_dml
        and _metadata_dml_matches_current_flush(
            conn,
            clauseelement,
            multiparams,
            params,
        )
    ):
        conn.info[_VALIDATED_METADATA_DML_KEY] = clauseelement
        return clauseelement, multiparams, params

    _raise_read_only_violation('connection_dml')
    return clauseelement, multiparams, params


@event.listens_for(Engine, 'before_cursor_execute', retval=True)
def _enforce_read_only_driver_sql(
    conn,
    _cursor,
    statement,
    parameters,
    _context,
    _executemany,
):
    """Guard the raw DB-API path used by ``Connection.exec_driver_sql``.

    SQLAlchemy's ``before_execute`` event does not run for driver-level SQL.
    ORM metadata flushes have already been table-checked by the higher-level
    listener. A marker alone is not sufficient: a later ``before_flush``
    listener can otherwise call ``exec_driver_sql`` while it is set. Only a
    compiled ORM DML statement for an allowlisted table may pass.
    """
    if _read_only_scope_state() is None:
        return statement, parameters
    compiled_statement = getattr(getattr(_context, 'compiled', None), 'statement', None)
    if (
        getattr(_context, 'compiled', None) is not None
        and _compiled_select_is_read_only(compiled_statement)
    ):
        # The higher-level SQLAlchemy statement is structurally a SELECT.
        # Allow only this exact rendered cursor call; direct raw SQL never
        # receives the allowance and remains function-free/fail-closed.
        conn.info[_COMPILED_CURSOR_ALLOWANCE_KEY] = (statement, parameters)
        return statement, parameters
    validated_metadata_dml = conn.info.pop(_VALIDATED_METADATA_DML_KEY, None)
    if validated_metadata_dml is not None and compiled_statement is validated_metadata_dml:
        # This allowance is consumed by the DB-API cursor proxy.  It is
        # deliberately tied to the exact DML node whose parameter records were
        # matched against the current ORM flush inventory.
        conn.info[_COMPILED_CURSOR_ALLOWANCE_KEY] = (statement, parameters)
        return statement, parameters
    if isinstance(statement, str) and _is_mutating_sql_text(statement):
        _raise_read_only_violation('driver_sql')
    return statement, parameters


class _ReadOnlyCursorProxy:
    """DB-API cursor guard for the raw connection path.

    SQLAlchemy execution events cannot observe ``raw_connection().cursor()``.
    Wrapping the pool fairy's cursor keeps normal metadata sessions working,
    while still rejecting business DML even when a caller bypasses Engine.
    """

    def __init__(self, cursor, guard_info):
        self.__cursor = cursor
        self._guard_info = guard_info

    def _info(self):
        """Return the shared SQLAlchemy connection-info mapping."""
        info = getattr(self._guard_info, 'info', None)
        return info if info is not None else self._guard_info

    def _guard_connection(self, connection):
        if connection is None:
            return None
        if isinstance(connection, _ReadOnlyConnectionProxy):
            connection._guard_info = self._guard_info
            return connection
        return _ReadOnlyConnectionProxy(connection, self._guard_info)

    @property
    def connection(self):
        """Keep the driver's public cursor-to-connection path guarded."""
        return self._guard_connection(getattr(self.__cursor, 'connection', None))

    def _get_db(self):
        """Guard PyMySQL's cursor helper for recovering its connection."""
        getter = getattr(self.__cursor, '_get_db', None)
        connection = getter() if callable(getter) else getattr(self.__cursor, 'connection', None)
        return self._guard_connection(connection)

    def _query(self, statement):
        """Guard PyMySQL's cursor-level direct query helper."""
        self._check_statement(statement)
        return self._wrap_result(self.__cursor._query(statement))

    def _check_statement(self, statement, parameters=None):
        if _read_only_scope_state() is None:
            return
        allowance = self._info().pop(_COMPILED_CURSOR_ALLOWANCE_KEY, None)
        allowance_matches = False
        if isinstance(allowance, tuple) and len(allowance) == 2:
            try:
                allowance_matches = (
                    allowance[0] == statement
                    and allowance[1] == parameters
                )
            except Exception:
                allowance_matches = False
        if not _is_read_only_sql_text(statement) and not allowance_matches:
            _raise_read_only_violation('raw_cursor_sql')

    def _wrap_result(self, result):
        if result is self.__cursor:
            return self
        if result is None or isinstance(result, _ReadOnlyCursorProxy):
            return result
        return result

    def execute(self, statement, parameters=None):
        self._check_statement(statement, parameters)
        if parameters is None:
            return self._wrap_result(self.__cursor.execute(statement))
        return self._wrap_result(self.__cursor.execute(statement, parameters))

    def executemany(self, statement, parameters):
        self._check_statement(statement, parameters)
        return self._wrap_result(self.__cursor.executemany(statement, parameters))

    def executescript(self, script):
        self._check_statement(script)
        if _read_only_scope_state() is not None:
            _raise_read_only_violation('raw_cursor_script')
        return self._wrap_result(self.__cursor.executescript(script))

    def callproc(self, *args, **kwargs):
        if _read_only_scope_state() is not None:
            _raise_read_only_violation('raw_cursor_proc')
        return self._wrap_result(self.__cursor.callproc(*args, **kwargs))

    def __getattr__(self, name):
        if name == '_cursor':
            if _read_only_scope_state() is not None:
                _raise_read_only_violation('raw_cursor_attribute')
            return self.__cursor
        return getattr(self.__cursor, name)

    def __iter__(self):
        return iter(self.__cursor)

    def __enter__(self):
        self.__cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self.__cursor.__exit__(*args)


class _ReadOnlyConnectionProxy:
    """Proxy the fairy's deprecated/current DB-API connection aliases."""

    def __init__(self, connection, guard_info):
        self.__connection = connection
        self._guard_info = guard_info

    def cursor(self, *args, **kwargs):
        return _ReadOnlyCursorProxy(
            self.__connection.cursor(*args, **kwargs),
            self._guard_info,
        )

    def execute(self, statement, parameters=None):
        cursor = self.cursor()
        if parameters is None:
            return cursor.execute(statement)
        return cursor.execute(statement, parameters)

    def executemany(self, statement, parameters):
        cursor = self.cursor()
        return cursor.executemany(statement, parameters)

    def executescript(self, script):
        cursor = self.cursor()
        return cursor.executescript(script)

    def callproc(self, *args, **kwargs):
        cursor = self.cursor()
        return cursor.callproc(*args, **kwargs)

    def query(self, statement, *args, **kwargs):
        """Guard PyMySQL's direct COM_QUERY entry point."""
        if (
            _read_only_scope_state() is not None
            and not _is_direct_read_query(statement)
        ):
            _raise_read_only_violation('raw_connection_query')
        return self.__connection.query(statement, *args, **kwargs)

    def write_packet(self, *args, **kwargs):
        # A caller can encode COM_QUERY in a raw MySQL packet, so the payload
        # cannot be safely classified at this layer.
        if _read_only_scope_state() is not None:
            _raise_read_only_violation('raw_connection_packet')
        return self.__connection.write_packet(*args, **kwargs)

    def _execute_command(self, *args, **kwargs):
        if _read_only_scope_state() is not None:
            _raise_read_only_violation('raw_connection_command')
        return self.__connection._execute_command(*args, **kwargs)

    def _write_bytes(self, *args, **kwargs):
        if _read_only_scope_state() is not None:
            _raise_read_only_violation('raw_connection_bytes')
        return self.__connection._write_bytes(*args, **kwargs)

    def __getattr__(self, name):
        if name == '_connection':
            # Return the proxy even outside an evaluation scope.  A caller can
            # acquire ``fairy._connection`` before the scope starts; exposing
            # the native object here would leave an unrevocable write-capable
            # reference that bypasses the dynamic ContextVar guard.
            return self
        return getattr(self.__connection, name)


def _guard_fairy_dbapi_connection(fairy):
    """Replace a fairy's direct DB-API slot with the scope-aware proxy."""
    raw = fairy.dbapi_connection
    guard_info = fairy.info
    if isinstance(raw, _ReadOnlyConnectionProxy):
        raw._guard_info = guard_info
        return raw
    guarded = _ReadOnlyConnectionProxy(raw, guard_info)
    fairy.dbapi_connection = guarded
    if fairy._connection_record is not None:
        fairy._connection_record.dbapi_connection = guarded
    return guarded


if not getattr(_ConnectionFairy, '_hpt_evaluation_cursor_guard', False):
    _ORIGINAL_FAIRY_CURSOR = _ConnectionFairy.cursor

    def _guarded_fairy_cursor(self, *args, **kwargs):
        cursor = _ORIGINAL_FAIRY_CURSOR(self, *args, **kwargs)
        if isinstance(cursor, _ReadOnlyCursorProxy):
            return cursor
        return _ReadOnlyCursorProxy(cursor, self.info)

    _ConnectionFairy.cursor = _guarded_fairy_cursor
    _ConnectionFairy._hpt_evaluation_cursor_guard = True

if not getattr(_ConnectionFairy, '_hpt_evaluation_connection_guard', False):
    _ORIGINAL_FAIRY_CONNECTION = _ConnectionFairy.connection
    _ORIGINAL_FAIRY_DRIVER_CONNECTION = _ConnectionFairy.driver_connection

    def _guarded_fairy_connection(self):
        # Read the slot directly instead of invoking SQLAlchemy's deprecated
        # property getter (which would emit a warning on every guarded access).
        connection = self.dbapi_connection
        if isinstance(connection, _ReadOnlyConnectionProxy):
            connection._guard_info = self.info
            return connection
        return _ReadOnlyConnectionProxy(connection, self.info)

    def _guarded_fairy_driver_connection(self):
        connection = _ORIGINAL_FAIRY_DRIVER_CONNECTION.fget(self)
        if isinstance(connection, _ReadOnlyConnectionProxy):
            connection._guard_info = self.info
            return connection
        return _ReadOnlyConnectionProxy(connection, self.info)

    _ConnectionFairy.connection = property(
        _guarded_fairy_connection,
        doc=_ORIGINAL_FAIRY_CONNECTION.__doc__,
    )
    _ConnectionFairy.driver_connection = property(
        _guarded_fairy_driver_connection,
        doc=_ORIGINAL_FAIRY_DRIVER_CONNECTION.__doc__,
    )
    _ConnectionFairy._hpt_evaluation_connection_guard = True

if not getattr(_ConnectionFairy, '_hpt_evaluation_checkout_guard', False):
    _ORIGINAL_FAIRY_CHECKOUT = _ConnectionFairy._checkout

    def _guarded_fairy_checkout(cls, pool, threadconns=None, fairy=None):
        result = _ORIGINAL_FAIRY_CHECKOUT(
            pool,
            threadconns=threadconns,
            fairy=fairy,
        )
        # A cursor/connection can be acquired before the evaluation scope
        # starts.  Wrap every checkout so the proxy can enforce the dynamic
        # ContextVar at execution time.
        _guard_fairy_dbapi_connection(result)
        return result

    _ConnectionFairy._checkout = classmethod(_guarded_fairy_checkout)
    _ConnectionFairy._hpt_evaluation_checkout_guard = True


def _guard_current_evaluation_session_connection() -> None:
    """Guard a connection the scoped session checked out before the scope."""
    with db.session.no_autoflush:
        fairy = db.session.connection().connection
    _guard_fairy_dbapi_connection(fairy)


@contextmanager
def evaluation_execution_scope(*, tenant: Tenant, run_user: User, read_only: bool):
    request_globals = g._get_current_object()
    original_context = {
        name: (name in request_globals.__dict__, request_globals.__dict__.get(name))
        for name in ('tenant_id', 'tenant', 'is_platform_admin')
    }
    reservations_present = '_ai_actual_call_reservations' in request_globals.__dict__
    original_reservations = copy.deepcopy(
        request_globals.__dict__.get('_ai_actual_call_reservations')
    )
    execution_user_token = _EXECUTION_USER_ID_OVERRIDE.set(run_user.id)
    read_only_token = _READ_ONLY_EVALUATION_SCOPE.set(
        _ReadOnlyEvaluationState(str(tenant.id), str(run_user.id)) if read_only else None
    )
    g.tenant_id = tenant.id
    g.tenant = tenant
    g.is_platform_admin = False
    try:
        if read_only:
            _guard_current_evaluation_session_connection()
        yield
    except BaseException:
        db.session.rollback()
        db.session.expire_all()
        raise
    finally:
        if reservations_present:
            g._ai_actual_call_reservations = copy.deepcopy(original_reservations)
        else:
            request_globals.__dict__.pop('_ai_actual_call_reservations', None)
        _READ_ONLY_EVALUATION_SCOPE.reset(read_only_token)
        _EXECUTION_USER_ID_OVERRIDE.reset(execution_user_token)
        for name, (was_present, value) in original_context.items():
            if was_present:
                setattr(g, name, value)
            else:
                request_globals.__dict__.pop(name, None)


def current_evaluation_execution_user_id() -> Optional[str]:
    return _EXECUTION_USER_ID_OVERRIDE.get()


def assert_evaluation_safe(
    cases,
    *,
    tenant: Optional[Tenant],
    allow_writes,
) -> None:
    if tenant is None:
        raise EvaluationSafetyError(
            'AI_EVALUATION_TENANT_REQUIRED',
            '必须显式指定评估目标企业',
        )

    write_case_ids = []
    for case in cases:
        side_effect = case.get('side_effect') if isinstance(case, dict) else None
        if side_effect not in {'read_only', 'business_write'}:
            case_id = case.get('id') if isinstance(case, dict) else None
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
                f'evaluation case side_effect is invalid: {case_id or "<unknown>"}',
                status_code=500,
                case_ids=[case_id] if case_id else None,
            )
        if side_effect == 'business_write':
            write_case_ids.append(str(case.get('id') or ''))

    if not write_case_ids:
        return
    if allow_writes is not True:
        raise EvaluationSafetyError(
            'AI_EVALUATION_WRITES_NOT_ALLOWED',
            '写入型评估必须显式启用 allowWrites',
            status_code=409,
            case_ids=write_case_ids,
        )

    settings = tenant.settings_json
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except (TypeError, ValueError):
            settings = {}
    if not isinstance(settings, dict):
        settings = {}
    disposable = (
        str(tenant.slug or '').startswith('e2e-platform-')
        and settings.get('disposableTestTenant') is True
    )
    if not disposable:
        raise EvaluationSafetyError(
            'AI_EVALUATION_REQUIRES_DISPOSABLE_TENANT',
            '写入型评估只能在双重标记的一次性测试企业运行',
            status_code=409,
            case_ids=write_case_ids,
        )


def resolve_evaluation_run_user(
    *,
    tenant: Tenant,
    run_as_user_id: Any = _RUN_AS_VALUE_UNSET,
    run_as_user_email: Any = _RUN_AS_VALUE_UNSET,
) -> User:
    query = User.query.execution_options(skip_tenant_criteria=True).filter(
        User.tenant_id == tenant.id,
        User.status == 'active',
    )

    def normalize_explicit(value: Any) -> Optional[str]:
        if value is _RUN_AS_VALUE_UNSET:
            return None
        if not isinstance(value, str) or not value.strip():
            raise EvaluationSafetyError(
                'AI_EVALUATION_RUN_USER_INVALID',
                '指定的评估执行账号标识必须是非空字符串',
                status_code=409,
            )
        return value.strip()

    explicit_id = normalize_explicit(run_as_user_id)
    explicit_email = normalize_explicit(run_as_user_email)
    if run_as_user_id is not _RUN_AS_VALUE_UNSET or run_as_user_email is not _RUN_AS_VALUE_UNSET:
        if explicit_id:
            query = query.filter(User.id == explicit_id)
        if explicit_email:
            query = query.filter(User.email == explicit_email)
        user = query.filter(User.role.in_(('admin', 'hr_admin'))).order_by(User.id.asc()).first()
        if user is None:
            raise EvaluationSafetyError(
                'AI_EVALUATION_RUN_USER_INVALID',
                '指定的评估执行账号不属于目标企业、未启用或角色不允许',
                status_code=409,
            )
        return user

    for role in ('admin', 'hr_admin'):
        user = query.filter(User.role == role).order_by(User.id.asc()).first()
        if user is not None:
            return user
    raise EvaluationSafetyError(
        'AI_EVALUATION_RUN_USER_REQUIRED',
        '目标企业没有可用的管理员评估执行账号',
        status_code=409,
    )


def resolve_evaluation_case_run_user(*, case, tenant: Tenant, default_user: User) -> User:
    required_role = str(case.get('run_as_role') or '').strip() if isinstance(case, dict) else ''
    if not required_role:
        if (
            not isinstance(default_user, User)
            or str(default_user.tenant_id or '') != str(tenant.id)
            or default_user.status != 'active'
            or default_user.role not in {'admin', 'hr_admin'}
        ):
            raise EvaluationSafetyError(
                'AI_EVALUATION_RUN_USER_INVALID',
                '评估执行账号不属于目标企业、未启用或角色不允许',
                status_code=409,
            )
        return default_user
    if case.get('side_effect') != 'read_only' or required_role != 'employee':
        raise EvaluationSafetyError(
            'AI_EVALUATION_RUN_USER_INVALID',
            '评估用例声明了不允许的执行角色',
            status_code=409,
            case_ids=[case.get('id')] if case.get('id') else None,
        )
    user = (
        User.query.execution_options(skip_tenant_criteria=True)
        .filter(
            User.tenant_id == tenant.id,
            User.status == 'active',
            User.role == required_role,
        )
        .order_by(User.id.asc())
        .first()
    )
    if user is None:
        raise EvaluationSafetyError(
            'AI_EVALUATION_RUN_USER_REQUIRED',
            '目标企业没有评估用例要求的可用执行账号',
            status_code=409,
            case_ids=[case.get('id')] if case.get('id') else None,
        )
    return user
