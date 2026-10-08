"""Pure planning and safety checks for legacy tenant migration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping


REPLACEABLE_SEED_TABLES = frozenset({'roles', 'settings'})
PRESERVED_TENANT_CONTROL_TABLES = frozenset(
    {
        'tenant_modules',
        'tenant_onboarding_items',
        'tenant_subscriptions',
        'tenant_orders',
        'tenant_invoices',
        'tenant_billing_events',
        'tenant_data_requests',
        'tenant_ai_entitlements',
        'platform_operation_logs',
    }
)
UNSAFE_DATABASE_MARKERS = frozenset({'live', 'prod', 'production'})
MYSQL_IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
BCRYPT_HASH_RE = re.compile(
    r'\$2[aby]\$(?:0[4-9]|[12][0-9]|3[01])\$'
    r'[./A-Za-z0-9]{21}[.Oeu]'
    r'[./A-Za-z0-9]{30}[.CGKOSWaeimquy26]'
)
VALIDATION_ERROR_PRIORITY = (
    'count_mismatch',
    'null_tenant_id',
    'foreign_key_orphan',
    'cross_tenant_foreign_key',
)


class MigrationSafetyError(RuntimeError):
    """Raised when a migration precondition would make execution unsafe."""


def _validate_status_error_category(
    *,
    owner: str,
    status: object,
    error_category: object,
) -> None:
    if status not in ('passed', 'failed'):
        raise MigrationSafetyError(f'{owner} has unknown status: {status!r}')
    if (
        error_category is not None
        and error_category not in VALIDATION_ERROR_PRIORITY
    ):
        raise MigrationSafetyError(
            f'{owner} has unknown error category: {error_category!r}'
        )
    if (status == 'passed') != (error_category is None):
        raise MigrationSafetyError(
            f'{owner} status and error category are inconsistent'
        )


def _classify_table_validation_counts(
    *,
    source_rows: int,
    inserted_rows: int,
    candidate_tenant_rows: int,
    null_tenant_rows: int,
    orphan_rows: int,
    cross_tenant_rows: int,
) -> tuple[Literal['passed', 'failed'], str | None]:
    error_category = None
    if source_rows != inserted_rows or source_rows != candidate_tenant_rows:
        error_category = 'count_mismatch'
    elif null_tenant_rows:
        error_category = 'null_tenant_id'
    elif orphan_rows:
        error_category = 'foreign_key_orphan'
    elif cross_tenant_rows:
        error_category = 'cross_tenant_foreign_key'

    return ('failed' if error_category else 'passed', error_category)


@dataclass(frozen=True)
class ForeignKeyMetadata:
    columns: tuple[str, ...]
    referenced_table: str
    referenced_columns: tuple[str, ...]


@dataclass(frozen=True)
class TableMetadata:
    name: str
    columns: tuple[str, ...]
    primary_key: tuple[str, ...] = ()
    required_columns_without_default: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKeyMetadata, ...] = ()


@dataclass(frozen=True)
class MigrationPlanItem:
    table: str
    status: Literal['copy', 'blocked']
    columns: tuple[str, ...] = ()
    reason: str | None = None
    source_only_columns: tuple[str, ...] = ()
    unmapped_required_columns: tuple[str, ...] = ()
    source_primary_key: tuple[str, ...] = ()
    target_primary_key: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableValidationResult:
    source_schema: str
    candidate_schema: str
    table: str
    source_rows: int
    inserted_rows: int
    candidate_tenant_rows: int
    null_tenant_rows: int
    orphan_rows: int
    cross_tenant_rows: int
    status: Literal['passed', 'failed']
    error_category: str | None

    def __post_init__(self) -> None:
        for field, count in (
            ('source_rows', self.source_rows),
            ('inserted_rows', self.inserted_rows),
            ('candidate_tenant_rows', self.candidate_tenant_rows),
            ('null_tenant_rows', self.null_tenant_rows),
            ('orphan_rows', self.orphan_rows),
            ('cross_tenant_rows', self.cross_tenant_rows),
        ):
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
            ):
                raise MigrationSafetyError(
                    f'{field} must be a non-bool non-negative int'
                )
        _validate_status_error_category(
            owner='table validation result',
            status=self.status,
            error_category=self.error_category,
        )
        expected_status, expected_error_category = (
            _classify_table_validation_counts(
                source_rows=self.source_rows,
                inserted_rows=self.inserted_rows,
                candidate_tenant_rows=self.candidate_tenant_rows,
                null_tenant_rows=self.null_tenant_rows,
                orphan_rows=self.orphan_rows,
                cross_tenant_rows=self.cross_tenant_rows,
            )
        )
        if (
            self.status != expected_status
            or self.error_category != expected_error_category
        ):
            raise MigrationSafetyError(
                'table validation result does not match count-derived '
                'status and error category'
            )

    def to_dict(self) -> dict[str, object]:
        return {
            'source_schema': self.source_schema,
            'candidate_schema': self.candidate_schema,
            'table': self.table,
            'source_rows': self.source_rows,
            'inserted_rows': self.inserted_rows,
            'candidate_tenant_rows': self.candidate_tenant_rows,
            'null_tenant_rows': self.null_tenant_rows,
            'orphan_rows': self.orphan_rows,
            'cross_tenant_rows': self.cross_tenant_rows,
            'status': self.status,
            'error_category': self.error_category,
        }


def _classify_migration_validation_results(
    results: tuple[TableValidationResult, ...],
) -> tuple[Literal['passed', 'failed'], str | None]:
    error_categories = {
        result.error_category
        for result in results
        if result.error_category is not None
    }
    error_category = next(
        (
            category
            for category in VALIDATION_ERROR_PRIORITY
            if category in error_categories
        ),
        None,
    )
    status = 'failed' if any(
        result.status == 'failed' for result in results
    ) else 'passed'
    return status, error_category


@dataclass(frozen=True)
class MigrationValidationReport:
    source_schema: str
    candidate_schema: str
    status: Literal['passed', 'failed']
    error_category: str | None
    table_results: tuple[TableValidationResult, ...]

    def __post_init__(self) -> None:
        if not self.table_results:
            raise MigrationSafetyError(
                'validation report requires at least one table result'
            )
        for result in self.table_results:
            if result.source_schema != self.source_schema:
                raise MigrationSafetyError(
                    f'table result source_schema mismatch: {result.table}'
                )
            if result.candidate_schema != self.candidate_schema:
                raise MigrationSafetyError(
                    f'table result candidate_schema mismatch: {result.table}'
                )

        _validate_status_error_category(
            owner='migration validation report',
            status=self.status,
            error_category=self.error_category,
        )
        expected_status, expected_error_category = (
            _classify_migration_validation_results(self.table_results)
        )
        if (
            self.status != expected_status
            or self.error_category != expected_error_category
        ):
            raise MigrationSafetyError(
                'migration validation report does not match table-derived '
                'status and error category'
            )

    def to_dict(self) -> dict[str, object]:
        return {
            'source_schema': self.source_schema,
            'candidate_schema': self.candidate_schema,
            'status': self.status,
            'error_category': self.error_category,
            'tables': [result.to_dict() for result in self.table_results],
        }


def _validate_unique_table_metadata(
    tables: tuple[TableMetadata, ...],
    source: str,
) -> None:
    seen: set[str] = set()
    for table in tables:
        if table.name in seen:
            raise MigrationSafetyError(
                f'duplicate {source} table metadata: {table.name}'
            )
        seen.add(table.name)


def _has_valid_primary_key(table: TableMetadata) -> bool:
    if not table.primary_key:
        return False

    seen: set[str] = set()
    for column in table.primary_key:
        if (
            not isinstance(column, str)
            or MYSQL_IDENTIFIER_RE.fullmatch(column) is None
            or column not in table.columns
            or column in seen
        ):
            return False
        seen.add(column)
    return True


def build_migration_plan(
    source_tables: Iterable[TableMetadata],
    target_tables: Iterable[TableMetadata],
) -> tuple[MigrationPlanItem, ...]:
    """Classify each source table without reading or changing row data."""

    source_table_list = tuple(source_tables)
    target_table_list = tuple(target_tables)
    _validate_unique_table_metadata(source_table_list, 'source')
    _validate_unique_table_metadata(target_table_list, 'target')

    target_by_name = {table.name: table for table in target_table_list}
    plan: list[MigrationPlanItem] = []

    for source in source_table_list:
        target = target_by_name.get(source.name)
        if target is None:
            plan.append(
                MigrationPlanItem(
                    table=source.name,
                    status='blocked',
                    reason='source_only',
                )
            )
            continue

        if 'tenant_id' in source.columns:
            plan.append(
                MigrationPlanItem(
                    table=source.name,
                    status='blocked',
                    reason='source_contains_tenant_id',
                )
            )
            continue

        if 'tenant_id' not in target.columns:
            plan.append(
                MigrationPlanItem(
                    table=source.name,
                    status='blocked',
                    reason='target_missing_tenant_id',
                )
            )
            continue

        target_columns = set(target.columns)
        common_columns = tuple(
            column for column in source.columns if column in target_columns
        )
        source_only_columns = tuple(
            column for column in source.columns if column not in target_columns
        )
        if not common_columns:
            plan.append(
                MigrationPlanItem(
                    table=source.name,
                    status='blocked',
                    reason='no_common_columns',
                    source_only_columns=source_only_columns,
                )
            )
            continue

        if source_only_columns:
            plan.append(
                MigrationPlanItem(
                    table=source.name,
                    status='blocked',
                    columns=common_columns,
                    reason='source_only_columns',
                    source_only_columns=source_only_columns,
                )
            )
            continue

        common_column_set = set(common_columns)
        unmapped_required_columns = tuple(
            column
            for column in target.required_columns_without_default
            if column != 'tenant_id' and column not in common_column_set
        )
        if unmapped_required_columns:
            plan.append(
                MigrationPlanItem(
                    table=source.name,
                    status='blocked',
                    columns=common_columns,
                    reason='target_required_columns_unmapped',
                    unmapped_required_columns=unmapped_required_columns,
                )
            )
            continue

        if not (
            _has_valid_primary_key(source)
            and _has_valid_primary_key(target)
        ):
            plan.append(
                MigrationPlanItem(
                    table=source.name,
                    status='blocked',
                    columns=common_columns,
                    reason='missing_or_invalid_primary_key',
                )
            )
            continue

        if source.primary_key != target.primary_key:
            plan.append(
                MigrationPlanItem(
                    table=source.name,
                    status='blocked',
                    columns=common_columns,
                    reason='primary_key_mismatch',
                    source_primary_key=source.primary_key,
                    target_primary_key=target.primary_key,
                )
            )
            continue

        plan.append(
            MigrationPlanItem(
                table=source.name,
                status='copy',
                columns=common_columns,
            )
        )

    return tuple(plan)


def quote_mysql_identifier(name: str, *, label: str = 'identifier') -> str:
    """Quote an identifier only after strict MySQL identifier validation."""

    if not isinstance(name, str) or MYSQL_IDENTIFIER_RE.fullmatch(name) is None:
        raise MigrationSafetyError(
            f'{label} must be a non-empty safe MySQL identifier'
        )
    return f'`{name}`'


def build_primary_key_collision_sql(
    stage_database: str,
    candidate_database: str,
    table_metadata: TableMetadata,
) -> str:
    """Build a read-only count query for source/candidate PK collisions."""

    validate_candidate_database_names(
        stage_database=stage_database,
        candidate_database=candidate_database,
    )
    if not _has_valid_primary_key(table_metadata):
        raise MigrationSafetyError(
            'table metadata must define a valid primary key'
        )

    quoted_stage = quote_mysql_identifier(
        stage_database,
        label='stage database name',
    )
    quoted_candidate = quote_mysql_identifier(
        candidate_database,
        label='candidate database name',
    )
    quoted_table = quote_mysql_identifier(
        table_metadata.name,
        label='table name',
    )
    quoted_primary_key = tuple(
        quote_mysql_identifier(column, label='primary key column')
        for column in table_metadata.primary_key
    )
    join_condition = ' AND '.join(
        f'`candidate_rows`.{column} = `stage_rows`.{column}'
        for column in quoted_primary_key
    )

    return (
        f'SELECT COUNT(*) FROM {quoted_stage}.{quoted_table} '
        f'AS `stage_rows` INNER JOIN {quoted_candidate}.{quoted_table} '
        f'AS `candidate_rows` ON {join_condition}'
    )


def _build_seed_primary_key_collision_sql(
    *,
    stage_database: str,
    candidate_database: str,
    table_metadata: TableMetadata,
) -> str:
    return (
        build_primary_key_collision_sql(
            stage_database,
            candidate_database,
            table_metadata,
        )
        + ' WHERE (`candidate_rows`.`tenant_id` IS NULL '
        'OR `candidate_rows`.`tenant_id` <> %s)'
    )


def _build_null_tenant_validation_sql(
    *,
    stage_database: str,
    candidate_database: str,
    table_metadata: TableMetadata,
) -> str:
    validate_candidate_database_names(
        stage_database=stage_database,
        candidate_database=candidate_database,
    )
    if not _has_valid_primary_key(table_metadata):
        raise MigrationSafetyError(
            'table metadata must define a valid primary key'
        )

    quoted_stage = quote_mysql_identifier(
        stage_database,
        label='stage database name',
    )
    quoted_candidate = quote_mysql_identifier(
        candidate_database,
        label='candidate database name',
    )
    quoted_table = quote_mysql_identifier(
        table_metadata.name,
        label='table name',
    )
    quoted_primary_key = tuple(
        quote_mysql_identifier(column, label='primary key column')
        for column in table_metadata.primary_key
    )
    join_condition = ' AND '.join(
        f'`candidate_rows`.{column} = `stage_rows`.{column}'
        for column in quoted_primary_key
    )
    return (
        f'SELECT COUNT(*) FROM {quoted_candidate}.{quoted_table} '
        f'AS `candidate_rows` INNER JOIN {quoted_stage}.{quoted_table} '
        f'AS `stage_rows` ON {join_condition} '
        'WHERE `candidate_rows`.`tenant_id` IS NULL'
    )


def is_compatible_bcrypt_hash(value: object) -> bool:
    """Return whether a value is a supported, strictly formatted bcrypt hash."""

    return (
        isinstance(value, str)
        and BCRYPT_HASH_RE.fullmatch(value) is not None
    )


def validate_account_preflight(
    *,
    invalid_password_hashes: int,
    platform_admin_users: int,
) -> None:
    """Block unsafe account rows using aggregate counts only."""

    for category, count in (
        ('invalid_password_hashes', invalid_password_hashes),
        ('platform_admin_users', platform_admin_users),
    ):
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise MigrationSafetyError(
                f'{category} must be a non-bool non-negative int'
            )

    if invalid_password_hashes > 0 or platform_admin_users > 0:
        raise MigrationSafetyError(
            'account preflight failed: '
            f'invalid_password_hashes={invalid_password_hashes}, '
            f'platform_admin_users={platform_admin_users}'
        )


def build_insert_select_sql(
    *,
    stage_database: str,
    candidate_database: str,
    plan_item: MigrationPlanItem,
) -> str:
    """Build a parameterized candidate-only INSERT SELECT statement."""

    validate_candidate_database_names(
        stage_database=stage_database,
        candidate_database=candidate_database,
    )
    if plan_item.status != 'copy':
        raise MigrationSafetyError('INSERT SELECT requires a copy plan item')
    if not plan_item.columns:
        raise MigrationSafetyError('INSERT SELECT requires at least one column')
    if 'tenant_id' in plan_item.columns:
        raise MigrationSafetyError('tenant_id must be injected, not copied')

    quoted_stage = quote_mysql_identifier(
        stage_database,
        label='stage database name',
    )
    quoted_candidate = quote_mysql_identifier(
        candidate_database,
        label='candidate database name',
    )
    quoted_table = quote_mysql_identifier(plan_item.table, label='table name')
    quoted_columns = tuple(
        quote_mysql_identifier(column, label='column name')
        for column in plan_item.columns
    )
    projection = ', '.join(quoted_columns)

    return (
        f'INSERT INTO {quoted_candidate}.{quoted_table} '
        f'({projection}, `tenant_id`) '
        f'SELECT {projection}, %s '
        f'FROM {quoted_stage}.{quoted_table}'
    )


def build_table_validation_result(
    *,
    source_schema: str,
    candidate_schema: str,
    table: str,
    source_rows: int,
    inserted_rows: int,
    candidate_tenant_rows: int,
    null_tenant_rows: int,
    orphan_rows: int,
    cross_tenant_rows: int,
) -> TableValidationResult:
    """Classify table-level count validation using deterministic priority."""

    for field, count in (
        ('source_rows', source_rows),
        ('inserted_rows', inserted_rows),
        ('candidate_tenant_rows', candidate_tenant_rows),
        ('null_tenant_rows', null_tenant_rows),
        ('orphan_rows', orphan_rows),
        ('cross_tenant_rows', cross_tenant_rows),
    ):
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise MigrationSafetyError(
                f'{field} must be a non-bool non-negative int'
            )

    status, error_category = _classify_table_validation_counts(
        source_rows=source_rows,
        inserted_rows=inserted_rows,
        candidate_tenant_rows=candidate_tenant_rows,
        null_tenant_rows=null_tenant_rows,
        orphan_rows=orphan_rows,
        cross_tenant_rows=cross_tenant_rows,
    )

    return TableValidationResult(
        source_schema=source_schema,
        candidate_schema=candidate_schema,
        table=table,
        source_rows=source_rows,
        inserted_rows=inserted_rows,
        candidate_tenant_rows=candidate_tenant_rows,
        null_tenant_rows=null_tenant_rows,
        orphan_rows=orphan_rows,
        cross_tenant_rows=cross_tenant_rows,
        status=status,
        error_category=error_category,
    )


def build_migration_validation_report(
    *,
    source_schema: str,
    candidate_schema: str,
    table_results: Iterable[TableValidationResult],
) -> MigrationValidationReport:
    """Aggregate table validation results without exposing row values."""

    results = tuple(table_results)
    if not results:
        raise MigrationSafetyError(
            'validation report requires at least one table result'
        )
    for result in results:
        if result.source_schema != source_schema:
            raise MigrationSafetyError(
                f'table result source_schema mismatch: {result.table}'
            )
        if result.candidate_schema != candidate_schema:
            raise MigrationSafetyError(
                f'table result candidate_schema mismatch: {result.table}'
            )

    status, error_category = _classify_migration_validation_results(results)
    return MigrationValidationReport(
        source_schema=source_schema,
        candidate_schema=candidate_schema,
        status=status,
        error_category=error_category,
        table_results=results,
    )


def _normalize_database_identifier(label: str, name: str) -> str:
    if not isinstance(name, str) or MYSQL_IDENTIFIER_RE.fullmatch(name) is None:
        raise MigrationSafetyError(
            f'{label} database name must be a non-empty safe MySQL identifier'
        )
    return name.casefold()


def validate_candidate_database_names(
    *,
    stage_database: str,
    candidate_database: str,
) -> None:
    """Require distinct, explicitly staged candidate database identifiers."""

    normalized_stage = _normalize_database_identifier('stage', stage_database)
    normalized_candidate = _normalize_database_identifier(
        'candidate', candidate_database
    )
    if '_stage_' not in normalized_stage:
        raise MigrationSafetyError("stage database name must contain '_stage_'")
    if '_candidate_' not in normalized_candidate:
        raise MigrationSafetyError(
            "candidate database name must contain '_candidate_'"
        )
    if normalized_stage == normalized_candidate:
        raise MigrationSafetyError('stage and candidate database names must differ')

    for label, normalized_name in (
        ('stage', normalized_stage),
        ('candidate', normalized_candidate),
    ):
        unsafe_markers = UNSAFE_DATABASE_MARKERS.intersection(
            normalized_name.split('_')
        )
        if unsafe_markers:
            markers = ', '.join(sorted(unsafe_markers))
            raise MigrationSafetyError(
                f'{label} database name contains unsafe environment marker: {markers}'
            )


def is_replaceable_seed_table(table: str) -> bool:
    """Return whether destination-tenant seed rows may be replaced."""

    return table in REPLACEABLE_SEED_TABLES


def validate_destination_tenant_rows(
    row_counts: Mapping[str, int],
    *,
    migration_plan: Iterable[MigrationPlanItem],
    target_tables: Iterable[TableMetadata],
) -> None:
    """Validate complete counts and block occupied non-seed tables."""

    target_table_items = tuple(target_tables)
    if not target_table_items:
        raise MigrationSafetyError('target table metadata must not be empty')
    _validate_unique_table_metadata(target_table_items, 'target')

    expected_table_set = {
        table.name
        for table in target_table_items
        if 'tenant_id' in table.columns
        and table.name not in PRESERVED_TENANT_CONTROL_TABLES
    }

    migration_plan_items = tuple(migration_plan)
    if not migration_plan_items:
        raise MigrationSafetyError('migration plan must not be empty')

    blocked_tables = sorted(
        item.table for item in migration_plan_items if item.status == 'blocked'
    )
    if blocked_tables:
        tables = ', '.join(blocked_tables)
        raise MigrationSafetyError(
            f'migration plan contains blocked tables: {tables}'
        )

    copy_table_set: set[str] = set()
    for item in migration_plan_items:
        if item.status != 'copy':
            continue
        if item.table in copy_table_set:
            raise MigrationSafetyError(
                f'duplicate copy table in migration plan: {item.table}'
            )
        copy_table_set.add(item.table)

    unexpected_copy_tables = sorted(copy_table_set - expected_table_set)
    if unexpected_copy_tables:
        tables = ', '.join(unexpected_copy_tables)
        raise MigrationSafetyError(
            f'migration plan copy tables are not tenant target tables: {tables}'
        )

    reported_table_set = set(row_counts)
    missing_tables = sorted(expected_table_set - reported_table_set)
    if missing_tables:
        tables = ', '.join(missing_tables)
        raise MigrationSafetyError(
            f'destination row counts missing expected tables: {tables}'
        )
    unknown_tables = sorted(reported_table_set - expected_table_set)
    if unknown_tables:
        tables = ', '.join(unknown_tables)
        raise MigrationSafetyError(
            f'destination row counts contain unknown tables: {tables}'
        )

    for table in sorted(expected_table_set):
        row_count = row_counts[table]
        if (
            isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or row_count < 0
        ):
            raise MigrationSafetyError(
                f'destination row count for {table} must be a non-bool '
                'non-negative int'
            )

    occupied_tables = sorted(
        table
        for table, row_count in row_counts.items()
        if row_count > 0 and not is_replaceable_seed_table(table)
    )
    if occupied_tables:
        tables = ', '.join(occupied_tables)
        raise MigrationSafetyError(
            f'destination tenant already has non-seed rows in: {tables}'
        )


def _fetch_aggregate_count(cursor, sql: str, params: tuple[object, ...] = ()) -> int:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    count = row[0] if isinstance(row, (tuple, list)) and len(row) == 1 else None
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise MigrationSafetyError('aggregate query returned an invalid count')
    return count


def _close_connection_quietly(connection) -> None:
    try:
        connection.close()
    except BaseException:
        pass


def _rollback_or_raise_unknown(connection) -> None:
    try:
        connection.rollback()
    except BaseException as rollback_error:
        _close_connection_quietly(connection)
        raise MigrationSafetyError(
            'rollback failed; candidate transaction state is unknown'
        ) from rollback_error


def _validate_transaction_inputs(
    *,
    stage_database: str,
    candidate_database: str,
    tenant_id: object,
    migration_plan: tuple[MigrationPlanItem, ...],
    source_tables: tuple[TableMetadata, ...],
    target_tables: tuple[TableMetadata, ...],
) -> None:
    validate_candidate_database_names(
        stage_database=stage_database,
        candidate_database=candidate_database,
    )
    if (
        isinstance(tenant_id, bool)
        or not isinstance(tenant_id, (str, int))
        or (isinstance(tenant_id, str) and not tenant_id.strip())
    ):
        raise MigrationSafetyError('tenant_id must be a non-empty scalar')
    if not source_tables:
        raise MigrationSafetyError('source table metadata must not be empty')
    if not target_tables:
        raise MigrationSafetyError('target table metadata must not be empty')
    if not migration_plan:
        raise MigrationSafetyError('migration plan must not be empty')

    expected_plan = build_migration_plan(source_tables, target_tables)
    if migration_plan != expected_plan:
        raise MigrationSafetyError(
            'migration plan does not match complete source/target metadata'
        )
    blocked_tables = sorted(
        item.table for item in migration_plan if item.status == 'blocked'
    )
    if blocked_tables:
        raise MigrationSafetyError(
            'migration plan contains blocked tables: '
            + ', '.join(blocked_tables)
        )

    for metadata_label, tables in (
        ('source', source_tables),
        ('target', target_tables),
    ):
        for table in tables:
            quote_mysql_identifier(
                table.name,
                label=f'{metadata_label} table identifier',
            )
            if not table.columns or len(set(table.columns)) != len(table.columns):
                raise MigrationSafetyError(
                    f'{metadata_label} table columns must be complete and unique'
                )
            for column in table.columns:
                quote_mysql_identifier(
                    column,
                    label=f'{metadata_label} column identifier',
                )
            for column in (
                *table.primary_key,
                *table.required_columns_without_default,
            ):
                quote_mysql_identifier(column, label='metadata column identifier')
                if column not in table.columns:
                    raise MigrationSafetyError(
                        'metadata column must exist in its table columns'
                    )

    target_by_name = {table.name: table for table in target_tables}
    for table in target_tables:
        for foreign_key in table.foreign_keys:
            if (
                not foreign_key.columns
                or len(foreign_key.columns)
                != len(foreign_key.referenced_columns)
            ):
                raise MigrationSafetyError(
                    'foreign key metadata requires matching non-empty columns'
                )
            quote_mysql_identifier(
                foreign_key.referenced_table,
                label='referenced table identifier',
            )
            parent = target_by_name.get(foreign_key.referenced_table)
            if parent is None:
                raise MigrationSafetyError(
                    'foreign key metadata references missing target table'
                )
            for child_column, parent_column in zip(
                foreign_key.columns,
                foreign_key.referenced_columns,
            ):
                quote_mysql_identifier(
                    child_column,
                    label='foreign key column identifier',
                )
                quote_mysql_identifier(
                    parent_column,
                    label='referenced column identifier',
                )
                if (
                    child_column not in table.columns
                    or parent_column not in parent.columns
                ):
                    raise MigrationSafetyError(
                        'foreign key metadata columns must exist in target tables'
                    )

    source_by_name = {table.name: table for table in source_tables}
    for account_table in ('users', 'employee_portal_accounts'):
        source = source_by_name.get(account_table)
        if source is not None and 'password_hash' not in source.columns:
            raise MigrationSafetyError(
                f'{account_table} metadata must include password_hash'
            )
    users = source_by_name.get('users')
    if users is not None and 'role' not in users.columns:
        raise MigrationSafetyError('users metadata must include role')


def _build_foreign_key_orphan_sql(
    *,
    candidate_database: str,
    child_table: str,
    foreign_key: ForeignKeyMetadata,
) -> str:
    quoted_candidate = quote_mysql_identifier(
        candidate_database,
        label='candidate database name',
    )
    quoted_child = quote_mysql_identifier(child_table, label='table name')
    quoted_parent = quote_mysql_identifier(
        foreign_key.referenced_table,
        label='referenced table name',
    )
    child_columns = tuple(
        quote_mysql_identifier(column, label='foreign key column')
        for column in foreign_key.columns
    )
    parent_columns = tuple(
        quote_mysql_identifier(column, label='referenced column')
        for column in foreign_key.referenced_columns
    )
    join_condition = ' AND '.join(
        f'`candidate_child`.{child_column} = '
        f'`candidate_parent`.{parent_column}'
        for child_column, parent_column in zip(child_columns, parent_columns)
    )
    populated_condition = ' AND '.join(
        f'`candidate_child`.{column} IS NOT NULL' for column in child_columns
    )
    return (
        f'SELECT COUNT(*) FROM {quoted_candidate}.{quoted_child} '
        f'AS `candidate_child` LEFT JOIN {quoted_candidate}.{quoted_parent} '
        f'AS `candidate_parent` ON {join_condition} '
        'WHERE `candidate_child`.`tenant_id` = %s '
        f'AND {populated_condition} '
        f'AND `candidate_parent`.{parent_columns[0]} IS NULL'
    )


def _build_cross_tenant_foreign_key_sql(
    *,
    candidate_database: str,
    child_table: str,
    foreign_key: ForeignKeyMetadata,
) -> str:
    quoted_candidate = quote_mysql_identifier(
        candidate_database,
        label='candidate database name',
    )
    quoted_child = quote_mysql_identifier(child_table, label='table name')
    quoted_parent = quote_mysql_identifier(
        foreign_key.referenced_table,
        label='referenced table name',
    )
    child_columns = tuple(
        quote_mysql_identifier(column, label='foreign key column')
        for column in foreign_key.columns
    )
    parent_columns = tuple(
        quote_mysql_identifier(column, label='referenced column')
        for column in foreign_key.referenced_columns
    )
    join_condition = ' AND '.join(
        f'`candidate_child`.{child_column} = '
        f'`candidate_parent`.{parent_column}'
        for child_column, parent_column in zip(child_columns, parent_columns)
    )
    return (
        f'SELECT COUNT(*) FROM {quoted_candidate}.{quoted_child} '
        f'AS `candidate_child` INNER JOIN '
        f'{quoted_candidate}.{quoted_parent} AS `candidate_parent` '
        f'ON {join_condition} '
        'WHERE `candidate_child`.`tenant_id` = %s '
        'AND (`candidate_parent`.`tenant_id` IS NULL '
        'OR `candidate_parent`.`tenant_id` <> %s)'
    )


def execute_transactional_migration(
    connection,
    *,
    stage_database: str,
    candidate_database: str,
    tenant_id: object,
    migration_plan: Iterable[MigrationPlanItem],
    source_tables: Iterable[TableMetadata],
    target_tables: Iterable[TableMetadata],
    post_copy_hook=None,
) -> MigrationValidationReport:
    """Copy a validated legacy plan and commit only after aggregate checks pass."""

    plan_items = tuple(migration_plan)
    source_table_items = tuple(source_tables)
    target_table_items = tuple(target_tables)
    _validate_transaction_inputs(
        stage_database=stage_database,
        candidate_database=candidate_database,
        tenant_id=tenant_id,
        migration_plan=plan_items,
        source_tables=source_table_items,
        target_tables=target_table_items,
    )
    if post_copy_hook is not None and not callable(post_copy_hook):
        raise MigrationSafetyError('post_copy_hook must be callable')

    quoted_stage = quote_mysql_identifier(
        stage_database,
        label='stage database name',
    )
    quoted_candidate = quote_mysql_identifier(
        candidate_database,
        label='candidate database name',
    )
    source_by_name = {table.name: table for table in source_table_items}
    target_by_name = {table.name: table for table in target_table_items}
    cursor = None
    report = None
    pending_error = None
    pending_traceback = None
    foreign_key_restore_error = None
    cursor_close_error = None

    try:
        connection.begin()
        cursor = connection.cursor()

        destination_counts: dict[str, int] = {}
        for target in target_table_items:
            if (
                'tenant_id' not in target.columns
                or target.name in PRESERVED_TENANT_CONTROL_TABLES
            ):
                continue
            quoted_table = quote_mysql_identifier(target.name, label='table name')
            destination_counts[target.name] = _fetch_aggregate_count(
                cursor,
                f'SELECT COUNT(*) FROM {quoted_candidate}.{quoted_table} '
                'WHERE `tenant_id` = %s',
                (tenant_id,),
            )
        validate_destination_tenant_rows(
            destination_counts,
            migration_plan=plan_items,
            target_tables=target_table_items,
        )

        source_counts: dict[str, int] = {}
        invalid_password_hashes = 0
        platform_admin_users = 0
        for item in plan_items:
            source = source_by_name[item.table]
            quoted_table = quote_mysql_identifier(item.table, label='table name')
            source_counts[item.table] = _fetch_aggregate_count(
                cursor,
                f'SELECT COUNT(*) FROM {quoted_stage}.{quoted_table}',
            )
            if is_replaceable_seed_table(item.table):
                collision_sql = _build_seed_primary_key_collision_sql(
                    stage_database=stage_database,
                    candidate_database=candidate_database,
                    table_metadata=source,
                )
                collision_params = (tenant_id,)
            else:
                collision_sql = build_primary_key_collision_sql(
                    stage_database,
                    candidate_database,
                    source,
                )
                collision_params = ()
            collision_count = _fetch_aggregate_count(
                cursor,
                collision_sql,
                collision_params,
            )
            if collision_count:
                raise MigrationSafetyError(
                    f'primary key collision detected for table: {item.table}'
                )

            if item.table in {'users', 'employee_portal_accounts'}:
                invalid_password_hashes += _fetch_aggregate_count(
                    cursor,
                    f'SELECT COUNT(*) FROM {quoted_stage}.{quoted_table} '
                    'WHERE `password_hash` IS NULL '
                    "OR NOT REGEXP_LIKE(`password_hash`, %s, 'c')",
                    (f'^{BCRYPT_HASH_RE.pattern}$',),
                )
            if item.table == 'users':
                platform_admin_users = _fetch_aggregate_count(
                    cursor,
                    f'SELECT COUNT(*) FROM {quoted_stage}.{quoted_table} '
                    'WHERE `role` = %s',
                    ('platform_admin',),
                )

        validate_account_preflight(
            invalid_password_hashes=invalid_password_hashes,
            platform_admin_users=platform_admin_users,
        )

        for item in plan_items:
            if is_replaceable_seed_table(item.table):
                quoted_table = quote_mysql_identifier(item.table, label='table name')
                cursor.execute(
                    f'DELETE FROM {quoted_candidate}.{quoted_table} '
                    'WHERE `tenant_id` = %s',
                    (tenant_id,),
                )

        cursor.execute('SET FOREIGN_KEY_CHECKS=0')
        inserted_counts: dict[str, int] = {}
        for item in plan_items:
            cursor.execute(
                build_insert_select_sql(
                    stage_database=stage_database,
                    candidate_database=candidate_database,
                    plan_item=item,
                ),
                (tenant_id,),
            )
            inserted_count = cursor.rowcount
            if (
                isinstance(inserted_count, bool)
                or not isinstance(inserted_count, int)
                or inserted_count < 0
            ):
                raise MigrationSafetyError(
                    f'insert rowcount is invalid for table: {item.table}'
                )
            inserted_counts[item.table] = inserted_count

        if post_copy_hook is not None:
            post_copy_hook(
                cursor=cursor,
                stage_database=stage_database,
                candidate_database=candidate_database,
                tenant_id=tenant_id,
                migration_plan=plan_items,
                source_tables=source_table_items,
                target_tables=target_table_items,
            )

        table_results: list[TableValidationResult] = []
        for item in plan_items:
            target = target_by_name[item.table]
            quoted_table = quote_mysql_identifier(target.name, label='table name')
            candidate_tenant_rows = _fetch_aggregate_count(
                cursor,
                f'SELECT COUNT(*) FROM {quoted_candidate}.{quoted_table} '
                'WHERE `tenant_id` = %s',
                (tenant_id,),
            )
            null_tenant_rows = _fetch_aggregate_count(
                cursor,
                _build_null_tenant_validation_sql(
                    stage_database=stage_database,
                    candidate_database=candidate_database,
                    table_metadata=target,
                ),
            )
            orphan_rows = 0
            cross_tenant_rows = 0
            for foreign_key in target.foreign_keys:
                orphan_rows += _fetch_aggregate_count(
                    cursor,
                    _build_foreign_key_orphan_sql(
                        candidate_database=candidate_database,
                        child_table=target.name,
                        foreign_key=foreign_key,
                    ),
                    (tenant_id,),
                )
                parent = target_by_name[foreign_key.referenced_table]
                if 'tenant_id' in parent.columns:
                    cross_tenant_rows += _fetch_aggregate_count(
                        cursor,
                        _build_cross_tenant_foreign_key_sql(
                            candidate_database=candidate_database,
                            child_table=target.name,
                            foreign_key=foreign_key,
                        ),
                        (tenant_id, tenant_id),
                    )
            result = build_table_validation_result(
                source_schema=stage_database,
                candidate_schema=candidate_database,
                table=item.table,
                source_rows=source_counts[item.table],
                inserted_rows=inserted_counts[item.table],
                candidate_tenant_rows=candidate_tenant_rows,
                null_tenant_rows=null_tenant_rows,
                orphan_rows=orphan_rows,
                cross_tenant_rows=cross_tenant_rows,
            )
            if result.status == 'failed':
                raise MigrationSafetyError(
                    f'table validation failed for {item.table}: '
                    f'{result.error_category}'
                )
            table_results.append(result)

        report = build_migration_validation_report(
            source_schema=stage_database,
            candidate_schema=candidate_database,
            table_results=table_results,
        )
    except BaseException as exc:
        pending_error = exc
        pending_traceback = exc.__traceback__
    finally:
        if cursor is not None:
            try:
                cursor.execute('SET FOREIGN_KEY_CHECKS=1')
            except BaseException as exc:
                foreign_key_restore_error = exc
            finally:
                try:
                    cursor.close()
                except BaseException as exc:
                    cursor_close_error = exc

    if foreign_key_restore_error is not None or cursor_close_error is not None:
        _rollback_or_raise_unknown(connection)
        _close_connection_quietly(connection)
        if foreign_key_restore_error is not None:
            raise MigrationSafetyError(
                'failed to restore foreign key checks; connection closed'
            ) from foreign_key_restore_error
        raise MigrationSafetyError(
            'migration cleanup failed; connection closed'
        ) from cursor_close_error

    if pending_error is not None:
        _rollback_or_raise_unknown(connection)
        raise pending_error.with_traceback(pending_traceback)

    try:
        connection.commit()
    except BaseException:
        _rollback_or_raise_unknown(connection)
        raise
    return report
