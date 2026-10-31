import json
import hashlib
from pathlib import Path
import re
import subprocess
import sys

import pytest

from services import legacy_tenant_migration as migration
from scripts import restore_legacy_data as restore_cli

from services.legacy_tenant_migration import (
    MigrationPlanItem,
    MigrationSafetyError,
    TableMetadata,
    build_migration_plan,
    is_replaceable_seed_table,
    validate_candidate_database_names,
    validate_destination_tenant_rows,
)


def _copy_plan(*tables):
    return tuple(
        MigrationPlanItem(table=table, status='copy') for table in tables
    )


def _tenant_target_tables(*tables):
    return tuple(
        TableMetadata(name=table, columns=('id', 'tenant_id'))
        for table in tables
    )


class FakeMigrationCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = -1
        self._result = None
        self.closed = False

    @staticmethod
    def _table_after(sql, keyword):
        match = re.search(
            rf'{re.escape(keyword)} `[^`]+`\.`([^`]+)`',
            sql,
        )
        if match is None:
            raise AssertionError(f'could not identify table in SQL: {sql}')
        return match.group(1)

    def execute(self, sql, params=None):
        normalized_params = tuple(params or ())
        self.connection.statements.append((sql, normalized_params))
        self.connection.execute_begin_counts.append(self.connection.begin_count)
        self.rowcount = -1
        self._result = None

        if (
            sql == 'SET FOREIGN_KEY_CHECKS=1'
            and self.connection.foreign_key_restore_fail
        ):
            raise RuntimeError('simulated foreign key restoration failure')

        if sql.startswith('SET FOREIGN_KEY_CHECKS'):
            return

        if sql.startswith('DELETE FROM'):
            table = self._table_after(sql, 'DELETE FROM')
            self.rowcount = self.connection.deleted_counts.get(table, 0)
            return

        if sql.startswith('INSERT INTO'):
            table = self._table_after(sql, 'INSERT INTO')
            if table == self.connection.fail_insert_table:
                raise RuntimeError('simulated copy failure')
            self.rowcount = self.connection.inserted_counts.get(
                table,
                self.connection.source_counts.get(table, 0),
            )
            self.connection.inserted_tables.add(table)
            return

        table = self._table_after(sql, 'FROM')
        if 'WHERE `candidate_rows`.`tenant_id` IS NULL' in sql:
            count = self.connection.null_tenant_counts.get(table, 0)
        elif 'AS `stage_rows`' in sql:
            if '`candidate_rows`.`tenant_id` <> %s' in sql:
                count = self.connection.seed_collision_counts.get(table, 0)
            else:
                count = self.connection.collision_counts.get(table, 0)
        elif "NOT REGEXP_LIKE(`password_hash`, %s, 'c')" in sql:
            count = self.connection.invalid_bcrypt_counts.get(table, 0)
        elif '`role` = %s' in sql:
            count = self.connection.platform_admin_count
        elif 'LEFT JOIN' in sql:
            count = self.connection.orphan_counts.get(table, 0)
        elif 'AS `candidate_child` INNER JOIN' in sql:
            if '`candidate_parent`.`tenant_id` IS NULL' in sql:
                count = self.connection.parent_null_cross_tenant_counts.get(
                    table,
                    0,
                )
            else:
                count = self.connection.cross_tenant_counts.get(table, 0)
        elif '`tenant_id` IS NULL' in sql:
            count = self.connection.historical_null_tenant_counts.get(
                table,
                self.connection.null_tenant_counts.get(table, 0),
            )
        elif 'WHERE `tenant_id` = %s' in sql:
            if table in self.connection.inserted_tables:
                count = self.connection.candidate_counts.get(
                    table,
                    self.connection.source_counts.get(table, 0),
                )
            else:
                count = self.connection.destination_counts.get(table, 0)
        else:
            count = self.connection.source_counts.get(table, 0)
        self._result = (count,)

    def fetchone(self):
        if self._result is None:
            raise AssertionError('fetchone called without a result')
        return self._result

    def close(self):
        self.closed = True
        if self.connection.cursor_close_fail:
            raise RuntimeError('simulated cursor close failure')


class FakeMigrationConnection:
    def __init__(
        self,
        *,
        source_counts=None,
        inserted_counts=None,
        destination_counts=None,
        candidate_counts=None,
        collision_counts=None,
        seed_collision_counts=None,
        invalid_bcrypt_counts=None,
        platform_admin_count=0,
        null_tenant_counts=None,
        historical_null_tenant_counts=None,
        orphan_counts=None,
        cross_tenant_counts=None,
        parent_null_cross_tenant_counts=None,
        deleted_counts=None,
        fail_insert_table=None,
        foreign_key_restore_fail=False,
        cursor_close_fail=False,
        rollback_fail=False,
        commit_fail=False,
        close_fail=False,
    ):
        self.source_counts = dict(source_counts or {})
        self.inserted_counts = dict(inserted_counts or {})
        self.destination_counts = dict(destination_counts or {})
        self.candidate_counts = dict(candidate_counts or {})
        self.collision_counts = dict(collision_counts or {})
        self.seed_collision_counts = dict(seed_collision_counts or {})
        self.invalid_bcrypt_counts = dict(invalid_bcrypt_counts or {})
        self.platform_admin_count = platform_admin_count
        self.null_tenant_counts = dict(null_tenant_counts or {})
        self.historical_null_tenant_counts = dict(
            historical_null_tenant_counts or {}
        )
        self.orphan_counts = dict(orphan_counts or {})
        self.cross_tenant_counts = dict(cross_tenant_counts or {})
        self.parent_null_cross_tenant_counts = dict(
            parent_null_cross_tenant_counts or {}
        )
        self.deleted_counts = dict(deleted_counts or {})
        self.fail_insert_table = fail_insert_table
        self.foreign_key_restore_fail = foreign_key_restore_fail
        self.cursor_close_fail = cursor_close_fail
        self.rollback_fail = rollback_fail
        self.commit_fail = commit_fail
        self.close_fail = close_fail
        self.inserted_tables = set()
        self.statements = []
        self.execute_begin_counts = []
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.created_cursor = None

    def cursor(self):
        self.created_cursor = FakeMigrationCursor(self)
        return self.created_cursor

    def begin(self):
        self.begin_count += 1

    def commit(self):
        self.commit_count += 1
        if self.commit_fail:
            raise RuntimeError('simulated commit failure')

    def rollback(self):
        self.rollback_count += 1
        if self.rollback_fail:
            raise RuntimeError('simulated rollback failure')

    def close(self):
        self.close_count += 1
        if self.close_fail:
            raise RuntimeError('simulated connection close failure')


def _migration_metadata(
    table,
    columns=('id', 'value'),
    *,
    primary_key=('id',),
    foreign_keys=(),
):
    source = migration.TableMetadata(
        name=table,
        columns=columns,
        primary_key=primary_key,
    )
    target = migration.TableMetadata(
        name=table,
        columns=(*columns, 'tenant_id'),
        primary_key=primary_key,
        foreign_keys=foreign_keys,
    )
    plan = migration.build_migration_plan((source,), (target,))
    return source, target, plan


def _execute_single_table(
    connection,
    source,
    target,
    plan,
    *,
    target_tables=None,
    post_copy_hook=None,
):
    return migration.execute_transactional_migration(
        connection,
        stage_database='legacy_stage_20260715',
        candidate_database='hrm_candidate_20260715',
        tenant_id=17,
        migration_plan=plan,
        source_tables=(source,),
        target_tables=tuple(target_tables or (target,)),
        post_copy_hook=post_copy_hook,
    )


def _table_validation_result(**overrides):
    values = {
        'source_schema': 'legacy_stage_20260715',
        'candidate_schema': 'hrm_candidate_20260715',
        'table': 'employees',
        'source_rows': 2,
        'inserted_rows': 2,
        'candidate_tenant_rows': 2,
        'null_tenant_rows': 0,
        'orphan_rows': 0,
        'cross_tenant_rows': 0,
        'status': 'passed',
        'error_category': None,
    }
    values.update(overrides)
    return migration.TableValidationResult(**values)


def test_plan_blocks_source_only_columns_and_preserves_them_for_report():
    source_tables = (
        TableMetadata(
            name='employees',
            columns=('id', 'employee_no', 'legacy_note'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        TableMetadata(
            name='employees',
            columns=('id', 'tenant_id', 'employee_no'),
            primary_key=('id',),
        ),
        TableMetadata(
            name='platform_tenants',
            columns=('id', 'slug'),
            primary_key=('id',),
        ),
    )

    assert build_migration_plan(source_tables, target_tables) == (
        MigrationPlanItem(
            table='employees',
            status='blocked',
            columns=('id', 'employee_no'),
            reason='source_only_columns',
            source_only_columns=('legacy_note',),
        ),
    )


def test_plan_only_copies_source_tables_with_target_tenant_column():
    source_tables = (
        TableMetadata(
            name='employees',
            columns=('id', 'employee_no'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        TableMetadata(
            name='employees',
            columns=('id', 'tenant_id', 'employee_no'),
            primary_key=('id',),
        ),
    )

    assert build_migration_plan(source_tables, target_tables) == (
        MigrationPlanItem(
            table='employees',
            status='copy',
            columns=('id', 'employee_no'),
        ),
    )


def test_plan_blocks_source_only_or_control_plane_tables():
    source_tables = (
        TableMetadata(
            name='legacy_notes',
            columns=('id', 'body'),
            primary_key=('id',),
        ),
        TableMetadata(
            name='plans',
            columns=('id', 'name'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        TableMetadata(
            name='plans',
            columns=('id', 'name'),
            primary_key=('id',),
        ),
    )

    plan_by_table = {
        item.table: item
        for item in build_migration_plan(source_tables, target_tables)
    }

    assert plan_by_table['legacy_notes'].status == 'blocked'
    assert plan_by_table['legacy_notes'].reason == 'source_only'
    assert plan_by_table['plans'].status == 'blocked'
    assert plan_by_table['plans'].reason == 'target_missing_tenant_id'


def test_plan_blocks_source_tables_that_already_have_tenant_id():
    source_tables = (
        TableMetadata(
            name='employees',
            columns=('id', 'tenant_id', 'employee_no'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        TableMetadata(
            name='employees',
            columns=('id', 'tenant_id', 'employee_no'),
            primary_key=('id',),
        ),
    )

    plan = build_migration_plan(source_tables, target_tables)

    assert plan[0].status == 'blocked'
    assert plan[0].reason == 'source_contains_tenant_id'
    assert plan[0].columns == ()


def test_plan_blocks_tables_without_common_columns():
    source_tables = (
        TableMetadata(
            name='employees',
            columns=('legacy_employee_id',),
            primary_key=('legacy_employee_id',),
        ),
    )
    target_tables = (
        TableMetadata(
            name='employees',
            columns=('id', 'tenant_id'),
            primary_key=('id',),
        ),
    )

    plan = build_migration_plan(source_tables, target_tables)

    assert plan[0].status == 'blocked'
    assert plan[0].reason == 'no_common_columns'
    assert plan[0].columns == ()


def test_duplicate_source_table_metadata_is_blocked():
    source_tables = (
        TableMetadata(
            name='employees',
            columns=('id',),
            primary_key=('id',),
        ),
        TableMetadata(
            name='employees',
            columns=('id', 'employee_no'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        TableMetadata(
            name='employees',
            columns=('id', 'tenant_id'),
            primary_key=('id',),
        ),
    )

    with pytest.raises(
        MigrationSafetyError,
        match='duplicate source table metadata: employees',
    ):
        build_migration_plan(source_tables, target_tables)


def test_duplicate_target_table_metadata_is_blocked():
    source_tables = (
        TableMetadata(
            name='employees',
            columns=('id',),
            primary_key=('id',),
        ),
    )
    target_tables = (
        TableMetadata(
            name='employees',
            columns=('id', 'tenant_id'),
            primary_key=('id',),
        ),
        TableMetadata(
            name='employees',
            columns=('id', 'tenant_id', 'employee_no'),
            primary_key=('id',),
        ),
    )

    with pytest.raises(
        MigrationSafetyError,
        match='duplicate target table metadata: employees',
    ):
        build_migration_plan(source_tables, target_tables)


def test_target_database_must_be_a_candidate_and_differ_from_stage():
    validate_candidate_database_names(
        stage_database='legacy_stage_20260715',
        candidate_database='hrm_candidate_20260715',
    )

    with pytest.raises(MigrationSafetyError, match='candidate'):
        validate_candidate_database_names(
            stage_database='legacy_stage_20260715',
            candidate_database='hrm_production',
        )

    with pytest.raises(MigrationSafetyError, match='differ'):
        validate_candidate_database_names(
            stage_database='hrm_stage_candidate_20260715',
            candidate_database='HRM_STAGE_CANDIDATE_20260715',
        )


@pytest.mark.parametrize(
    ('stage_database', 'candidate_database'),
    (
        ('', 'hrm_candidate_20260715'),
        ('legacy-stage-20260715', 'hrm_candidate_20260715'),
        ('1legacy_stage_20260715', 'hrm_candidate_20260715'),
        ('legacy_stage_20260715', ''),
        ('legacy_stage_20260715', 'hrm_candidate_20260715;drop'),
        ('legacy_stage_20260715', 'a' * 50 + '_candidate_20260715'),
    ),
)
def test_stage_and_candidate_must_be_safe_mysql_identifiers(
    stage_database,
    candidate_database,
):
    with pytest.raises(MigrationSafetyError, match='safe MySQL identifier'):
        validate_candidate_database_names(
            stage_database=stage_database,
            candidate_database=candidate_database,
        )


@pytest.mark.parametrize(
    ('stage_database', 'candidate_database', 'required_marker'),
    (
        ('legacy_stage', 'hrm_candidate_20260715', '_stage_'),
        ('legacy_stage_20260715', 'hrm_candidate', '_candidate_'),
    ),
)
def test_database_names_require_explicit_stage_and_candidate_markers(
    stage_database,
    candidate_database,
    required_marker,
):
    with pytest.raises(MigrationSafetyError, match=required_marker):
        validate_candidate_database_names(
            stage_database=stage_database,
            candidate_database=candidate_database,
        )


@pytest.mark.parametrize('unsafe_marker', ('live', 'prod', 'production'))
@pytest.mark.parametrize('unsafe_database', ('stage', 'candidate'))
def test_stage_and_candidate_reject_live_database_markers(
    unsafe_marker,
    unsafe_database,
):
    stage_database = 'legacy_stage_20260715'
    candidate_database = 'hrm_candidate_20260715'
    if unsafe_database == 'stage':
        stage_database = f'legacy_{unsafe_marker}_stage_20260715'
    else:
        candidate_database = f'hrm_candidate_{unsafe_marker}_20260715'

    with pytest.raises(MigrationSafetyError, match='unsafe environment marker'):
        validate_candidate_database_names(
            stage_database=stage_database,
            candidate_database=candidate_database,
        )


def test_non_seed_destination_rows_block_execution():
    validate_destination_tenant_rows(
        {'employees': 0, 'roles': 2, 'settings': 1},
        migration_plan=_copy_plan('employees', 'roles', 'settings'),
        target_tables=_tenant_target_tables('employees', 'roles', 'settings'),
    )

    with pytest.raises(MigrationSafetyError, match='employees'):
        validate_destination_tenant_rows(
            {'employees': 1, 'roles': 2, 'settings': 1},
            migration_plan=_copy_plan('employees', 'roles', 'settings'),
            target_tables=_tenant_target_tables(
                'employees',
                'roles',
                'settings',
            ),
        )


@pytest.mark.parametrize(
    ('row_counts', 'message'),
    (
        ({'employees': 0, 'roles': 0}, 'missing expected tables: settings'),
        (
            {'employees': 0, 'roles': 0, 'settings': 0, 'plans': 0},
            'unknown tables: plans',
        ),
    ),
)
def test_destination_row_counts_must_exactly_cover_expected_tables(
    row_counts,
    message,
):
    with pytest.raises(MigrationSafetyError, match=message):
        validate_destination_tenant_rows(
            row_counts,
            migration_plan=_copy_plan('employees', 'roles', 'settings'),
            target_tables=_tenant_target_tables(
                'employees',
                'roles',
                'settings',
            ),
        )


@pytest.mark.parametrize('invalid_count', (-1, True, 1.5, '1'))
def test_destination_row_counts_must_be_non_bool_non_negative_integers(
    invalid_count,
):
    with pytest.raises(MigrationSafetyError, match='employees'):
        validate_destination_tenant_rows(
            {'employees': invalid_count, 'roles': 0, 'settings': 0},
            migration_plan=_copy_plan('employees', 'roles', 'settings'),
            target_tables=_tenant_target_tables(
                'employees',
                'roles',
                'settings',
            ),
        )


def test_destination_validation_rejects_empty_migration_plan():
    with pytest.raises(MigrationSafetyError, match='migration plan must not be empty'):
        validate_destination_tenant_rows(
            {},
            migration_plan=(),
            target_tables=_tenant_target_tables('employees'),
        )


def test_destination_validation_rejects_blocked_migration_plan_items():
    migration_plan = (
        MigrationPlanItem(
            table='employees',
            status='blocked',
            reason='source_only_columns',
        ),
    )

    with pytest.raises(
        MigrationSafetyError,
        match='migration plan contains blocked tables: employees',
    ):
        validate_destination_tenant_rows(
            {},
            migration_plan=migration_plan,
            target_tables=_tenant_target_tables('employees'),
        )


def test_destination_validation_rejects_duplicate_copy_tables():
    migration_plan = _copy_plan('employees', 'employees')

    with pytest.raises(
        MigrationSafetyError,
        match='duplicate copy table in migration plan: employees',
    ):
        validate_destination_tenant_rows(
            {},
            migration_plan=migration_plan,
            target_tables=_tenant_target_tables('employees'),
        )


def test_target_only_tenant_business_rows_block_execution():
    with pytest.raises(MigrationSafetyError, match='ai_usage_ledger'):
        validate_destination_tenant_rows(
            {'employees': 0, 'ai_usage_ledger': 1},
            migration_plan=_copy_plan('employees'),
            target_tables=_tenant_target_tables('employees', 'ai_usage_ledger'),
        )


def test_destination_counts_must_include_target_only_tenant_business_tables():
    with pytest.raises(
        MigrationSafetyError,
        match='missing expected tables: security_insight_snapshots',
    ):
        validate_destination_tenant_rows(
            {'employees': 0},
            migration_plan=_copy_plan('employees'),
            target_tables=_tenant_target_tables(
                'employees',
                'security_insight_snapshots',
            ),
        )


def test_existing_tenant_modules_rows_are_preserved_without_counting():
    validate_destination_tenant_rows(
        {'employees': 0},
        migration_plan=_copy_plan('employees'),
        target_tables=_tenant_target_tables('employees', 'tenant_modules'),
    )


@pytest.mark.parametrize(
    ('table', 'expected'),
    (
        ('roles', True),
        ('settings', True),
        ('users', False),
        ('platform_tenants', False),
        ('Roles', False),
    ),
)
def test_seed_roles_and_settings_are_the_only_replaceable_rows(table, expected):
    assert is_replaceable_seed_table(table) is expected


def test_metadata_expresses_primary_keys_required_columns_and_foreign_keys():
    foreign_key = migration.ForeignKeyMetadata(
        columns=('department_id',),
        referenced_table='departments',
        referenced_columns=('id',),
    )
    metadata = migration.TableMetadata(
        name='employees',
        columns=('id', 'department_id', 'tenant_id'),
        primary_key=('id',),
        required_columns_without_default=('id', 'tenant_id'),
        foreign_keys=(foreign_key,),
    )

    assert metadata.primary_key == ('id',)
    assert metadata.required_columns_without_default == ('id', 'tenant_id')
    assert metadata.foreign_keys == (foreign_key,)
    assert TableMetadata(name='legacy', columns=('id',)).primary_key == ()


def test_plan_blocks_unmapped_required_target_columns_except_tenant_id():
    source_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id',),
            primary_key=('id',),
        ),
    )
    target_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'employee_no', 'tenant_id'),
            primary_key=('id',),
            required_columns_without_default=(
                'id',
                'employee_no',
                'tenant_id',
            ),
        ),
    )

    assert migration.build_migration_plan(source_tables, target_tables) == (
        migration.MigrationPlanItem(
            table='employees',
            status='blocked',
            columns=('id',),
            reason='target_required_columns_unmapped',
            unmapped_required_columns=('employee_no',),
        ),
    )


@pytest.mark.parametrize(
    (
        'source_columns',
        'source_primary_key',
        'target_columns',
        'target_primary_key',
    ),
    (
        (('id', 'employee_no'), (), ('id', 'employee_no', 'tenant_id'), ('id',)),
        (('id', 'employee_no'), ('id',), ('id', 'employee_no', 'tenant_id'), ()),
        (
            ('id', 'employee_no'),
            ('missing_id',),
            ('id', 'employee_no', 'tenant_id'),
            ('id',),
        ),
        (
            ('id', 'employee_no'),
            ('id',),
            ('id', 'employee_no', 'tenant_id'),
            ('missing_id',),
        ),
    ),
)
def test_plan_blocks_missing_or_invalid_source_or_target_primary_key(
    source_columns,
    source_primary_key,
    target_columns,
    target_primary_key,
):
    source = migration.TableMetadata(
        name='employees',
        columns=source_columns,
        primary_key=source_primary_key,
    )
    target = migration.TableMetadata(
        name='employees',
        columns=target_columns,
        primary_key=target_primary_key,
    )

    assert migration.build_migration_plan((source,), (target,)) == (
        migration.MigrationPlanItem(
            table='employees',
            status='blocked',
            columns=('id', 'employee_no'),
            reason='missing_or_invalid_primary_key',
        ),
    )


def test_plan_blocks_primary_key_mismatch_and_reports_both_key_orders():
    source = migration.TableMetadata(
        name='employees',
        columns=('id', 'employee_no'),
        primary_key=('id', 'employee_no'),
    )
    target = migration.TableMetadata(
        name='employees',
        columns=('id', 'employee_no', 'tenant_id'),
        primary_key=('employee_no', 'id'),
    )

    assert migration.build_migration_plan((source,), (target,)) == (
        migration.MigrationPlanItem(
            table='employees',
            status='blocked',
            columns=('id', 'employee_no'),
            reason='primary_key_mismatch',
            source_primary_key=('id', 'employee_no'),
            target_primary_key=('employee_no', 'id'),
        ),
    )


def test_migration_plan_item_primary_key_report_fields_are_backward_compatible():
    item = migration.MigrationPlanItem(table='employees', status='copy')

    assert item.source_primary_key == ()
    assert item.target_primary_key == ()


def test_primary_key_collision_sql_uses_single_primary_key():
    sql = migration.build_primary_key_collision_sql(
        'legacy_stage_20260715',
        'hrm_candidate_20260715',
        migration.TableMetadata(
            name='users',
            columns=('id', 'email'),
            primary_key=('id',),
        ),
    )

    assert sql == (
        'SELECT COUNT(*) FROM `legacy_stage_20260715`.`users` '
        'AS `stage_rows` INNER JOIN `hrm_candidate_20260715`.`users` '
        'AS `candidate_rows` ON '
        '`candidate_rows`.`id` = `stage_rows`.`id`'
    )


def test_primary_key_collision_sql_joins_every_composite_primary_key_column():
    sql = migration.build_primary_key_collision_sql(
        'legacy_stage_20260715',
        'hrm_candidate_20260715',
        migration.TableMetadata(
            name='employee_assignments',
            columns=('employee_id', 'assignment_id', 'value'),
            primary_key=('employee_id', 'assignment_id'),
        ),
    )

    assert sql == (
        'SELECT COUNT(*) FROM '
        '`legacy_stage_20260715`.`employee_assignments` AS `stage_rows` '
        'INNER JOIN `hrm_candidate_20260715`.`employee_assignments` '
        'AS `candidate_rows` ON '
        '`candidate_rows`.`employee_id` = `stage_rows`.`employee_id` AND '
        '`candidate_rows`.`assignment_id` = `stage_rows`.`assignment_id`'
    )
    assert re.search(
        r'\b(INSERT|UPDATE|DELETE|TRUNCATE|REPLACE|DROP|ALTER|CREATE)\b',
        sql,
        re.IGNORECASE,
    ) is None


def test_primary_key_collision_sql_rejects_missing_primary_key():
    with pytest.raises(MigrationSafetyError, match='primary key'):
        migration.build_primary_key_collision_sql(
            'legacy_stage_20260715',
            'hrm_candidate_20260715',
            migration.TableMetadata(name='users', columns=('id',)),
        )


@pytest.mark.parametrize(
    'metadata',
    (
        migration.TableMetadata(
            name='users',
            columns=('id',),
            primary_key=('missing_id',),
        ),
        migration.TableMetadata(
            name='users',
            columns=('id;drop',),
            primary_key=('id;drop',),
        ),
        migration.TableMetadata(
            name='users',
            columns=('id',),
            primary_key=('id', 'id'),
        ),
    ),
)
def test_primary_key_collision_sql_rejects_invalid_primary_key(metadata):
    with pytest.raises(MigrationSafetyError, match='primary key'):
        migration.build_primary_key_collision_sql(
            'legacy_stage_20260715',
            'hrm_candidate_20260715',
            metadata,
        )


def test_insert_select_injects_tenant_id_without_changing_password_hash():
    sql = migration.build_insert_select_sql(
        stage_database='legacy_stage_20260715',
        candidate_database='hrm_candidate_20260715',
        plan_item=migration.MigrationPlanItem(
            table='users',
            status='copy',
            columns=('id', 'email', 'password_hash'),
        ),
    )

    assert sql == (
        'INSERT INTO `hrm_candidate_20260715`.`users` '
        '(`id`, `email`, `password_hash`, `tenant_id`) '
        'SELECT `id`, `email`, `password_hash`, %s '
        'FROM `legacy_stage_20260715`.`users`'
    )
    assert sql.count('`password_hash`') == 2


@pytest.mark.parametrize(
    'unsafe_name',
    ('users;drop', 'users`', '', '1users'),
)
def test_insert_select_rejects_unsafe_mysql_identifiers(unsafe_name):
    with pytest.raises(MigrationSafetyError, match='safe MySQL identifier'):
        migration.build_insert_select_sql(
            stage_database='legacy_stage_20260715',
            candidate_database='hrm_candidate_20260715',
            plan_item=migration.MigrationPlanItem(
                table=unsafe_name,
                status='copy',
                columns=('id',),
            ),
        )


def test_insert_select_sql_contains_no_destructive_or_upsert_keywords():
    sql = migration.build_insert_select_sql(
        stage_database='legacy_stage_20260715',
        candidate_database='hrm_candidate_20260715',
        plan_item=migration.MigrationPlanItem(
            table='employees',
            status='copy',
            columns=('id', 'employee_no'),
        ),
    )

    assert re.search(
        r'\b(TRUNCATE|REPLACE|ON\s+DUPLICATE\s+KEY|DROP)\b',
        sql,
        re.IGNORECASE,
    ) is None


@pytest.mark.parametrize(
    'value',
    (
        '$2a$04$' + '.' * 53,
        '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6Ttxwpc6kqJhMzBJD7VhQW1Q4xKGO',
        '$2y$31$' + '.' * 21 + 'u' + '.' * 30 + '6',
    ),
)
def test_compatible_bcrypt_hash_accepts_supported_strict_format(value):
    assert migration.is_compatible_bcrypt_hash(value) is True


@pytest.mark.parametrize('salt_tail', tuple('.Oeu'))
def test_compatible_bcrypt_hash_accepts_each_canonical_salt_tail(salt_tail):
    value = '$2b$12$' + '.' * 21 + salt_tail + '.' * 31

    assert migration.is_compatible_bcrypt_hash(value) is True


@pytest.mark.parametrize('digest_tail', tuple('.CGKOSWaeimquy26'))
def test_compatible_bcrypt_hash_accepts_each_canonical_digest_tail(digest_tail):
    value = '$2b$12$' + '.' * 22 + '.' * 30 + digest_tail

    assert migration.is_compatible_bcrypt_hash(value) is True


@pytest.mark.parametrize(
    'value',
    (
        None,
        True,
        b'$2b$12$' + b'A' * 53,
        '$2x$12$' + 'A' * 53,
        '$2b$03$' + 'A' * 53,
        '$2b$32$' + 'A' * 53,
        '$2b$4$' + 'A' * 53,
        '$2b$12$' + 'A' * 52,
        '$2b$12$' + 'A' * 54,
        '$2b$12$' + 'A' * 52 + '_',
        '$2b$12$' + 'A' * 53,
        '$2b$12$' + '.' * 21 + 'A' + '.' * 31,
        '$2b$12$' + '.' * 22 + '.' * 30 + 'A',
    ),
)
def test_compatible_bcrypt_hash_rejects_non_string_or_invalid_format(value):
    assert migration.is_compatible_bcrypt_hash(value) is False


def test_account_preflight_accepts_zero_counts():
    assert migration.validate_account_preflight(
        invalid_password_hashes=0,
        platform_admin_users=0,
    ) is None


@pytest.mark.parametrize(
    ('invalid_password_hashes', 'platform_admin_users'),
    ((1, 0), (0, 2), (3, 4)),
)
def test_account_preflight_blocks_invalid_hashes_or_platform_admin_users(
    invalid_password_hashes,
    platform_admin_users,
):
    with pytest.raises(MigrationSafetyError) as error:
        migration.validate_account_preflight(
            invalid_password_hashes=invalid_password_hashes,
            platform_admin_users=platform_admin_users,
        )

    assert str(error.value) == (
        'account preflight failed: '
        f'invalid_password_hashes={invalid_password_hashes}, '
        f'platform_admin_users={platform_admin_users}'
    )


@pytest.mark.parametrize(
    ('field', 'value'),
    (
        ('invalid_password_hashes', True),
        ('invalid_password_hashes', -1),
        ('invalid_password_hashes', 1.5),
        ('invalid_password_hashes', '1'),
        ('platform_admin_users', True),
        ('platform_admin_users', -1),
        ('platform_admin_users', 1.5),
        ('platform_admin_users', '1'),
    ),
)
def test_account_preflight_rejects_invalid_counts(field, value):
    counts = {
        'invalid_password_hashes': 0,
        'platform_admin_users': 0,
    }
    counts[field] = value

    with pytest.raises(MigrationSafetyError, match=field):
        migration.validate_account_preflight(**counts)


@pytest.mark.parametrize(
    ('counts', 'error_category'),
    (
        (
            {
                'source_rows': 2,
                'inserted_rows': 1,
                'candidate_tenant_rows': 1,
            },
            'count_mismatch',
        ),
        ({'null_tenant_rows': 1}, 'null_tenant_id'),
        ({'orphan_rows': 1}, 'foreign_key_orphan'),
        ({'cross_tenant_rows': 1}, 'cross_tenant_foreign_key'),
    ),
)
def test_table_validation_result_categorizes_unsafe_counts(
    counts,
    error_category,
):
    values = {
        'source_rows': 2,
        'inserted_rows': 2,
        'candidate_tenant_rows': 2,
        'null_tenant_rows': 0,
        'orphan_rows': 0,
        'cross_tenant_rows': 0,
    }
    values.update(counts)

    result = migration.build_table_validation_result(
        source_schema='legacy_stage_20260715',
        candidate_schema='hrm_candidate_20260715',
        table='employees',
        **values,
    )

    assert result.status == 'failed'
    assert result.error_category == error_category


@pytest.mark.parametrize(
    'field',
    (
        'source_rows',
        'inserted_rows',
        'candidate_tenant_rows',
        'null_tenant_rows',
        'orphan_rows',
        'cross_tenant_rows',
    ),
)
@pytest.mark.parametrize('value', (True, -1, 1.5, '1'))
def test_table_validation_result_rejects_invalid_counts(field, value):
    counts = {
        'source_rows': 2,
        'inserted_rows': 2,
        'candidate_tenant_rows': 2,
        'null_tenant_rows': 0,
        'orphan_rows': 0,
        'cross_tenant_rows': 0,
    }
    counts[field] = value

    with pytest.raises(MigrationSafetyError, match=field):
        migration.build_table_validation_result(
            source_schema='legacy_stage_20260715',
            candidate_schema='hrm_candidate_20260715',
            table='employees',
            **counts,
        )


@pytest.mark.parametrize(
    ('status', 'error_category'),
    (
        ('passed', 'count_mismatch'),
        ('failed', None),
        ('failed', 'unknown_validation_error'),
        ('unknown', None),
    ),
)
def test_table_validation_result_rejects_invalid_status_category_state(
    status,
    error_category,
):
    with pytest.raises(MigrationSafetyError):
        _table_validation_result(
            status=status,
            error_category=error_category,
        )


@pytest.mark.parametrize(
    'field',
    (
        'source_rows',
        'inserted_rows',
        'candidate_tenant_rows',
        'null_tenant_rows',
        'orphan_rows',
        'cross_tenant_rows',
    ),
)
@pytest.mark.parametrize('value', (True, -1, 1.5, '1'))
def test_table_validation_result_constructor_rejects_invalid_counts(
    field,
    value,
):
    values = {
        'source_schema': 'legacy_stage_20260715',
        'candidate_schema': 'hrm_candidate_20260715',
        'table': 'employees',
        'source_rows': 2,
        'inserted_rows': 2,
        'candidate_tenant_rows': 2,
        'null_tenant_rows': 0,
        'orphan_rows': 0,
        'cross_tenant_rows': 0,
        'status': 'passed',
        'error_category': None,
    }
    values[field] = value

    with pytest.raises(MigrationSafetyError, match=field):
        migration.TableValidationResult(**values)


@pytest.mark.parametrize(
    'count_overrides',
    (
        {'inserted_rows': 1},
        {'orphan_rows': 1},
    ),
)
def test_table_validation_result_constructor_rejects_passed_unsafe_counts(
    count_overrides,
):
    with pytest.raises(MigrationSafetyError, match='count-derived'):
        _table_validation_result(**count_overrides)


def test_validation_report_rejects_empty_table_results():
    with pytest.raises(MigrationSafetyError, match='at least one table result'):
        migration.build_migration_validation_report(
            source_schema='legacy_stage_20260715',
            candidate_schema='hrm_candidate_20260715',
            table_results=(),
        )


def test_migration_validation_report_constructor_rejects_empty_table_results():
    with pytest.raises(MigrationSafetyError, match='at least one table result'):
        migration.MigrationValidationReport(
            source_schema='legacy_stage_20260715',
            candidate_schema='hrm_candidate_20260715',
            status='passed',
            error_category=None,
            table_results=(),
        )


@pytest.mark.parametrize(
    ('schema_field', 'mismatched_schema'),
    (
        ('source_schema', 'other_stage_20260715'),
        ('candidate_schema', 'other_candidate_20260715'),
    ),
)
def test_validation_report_rejects_table_result_schema_mismatch(
    schema_field,
    mismatched_schema,
):
    result = _table_validation_result(**{schema_field: mismatched_schema})

    with pytest.raises(MigrationSafetyError, match=schema_field):
        migration.build_migration_validation_report(
            source_schema='legacy_stage_20260715',
            candidate_schema='hrm_candidate_20260715',
            table_results=(result,),
        )


@pytest.mark.parametrize(
    ('schema_field', 'mismatched_schema'),
    (
        ('source_schema', 'other_stage_20260715'),
        ('candidate_schema', 'other_candidate_20260715'),
    ),
)
def test_migration_validation_report_constructor_rejects_schema_mismatch(
    schema_field,
    mismatched_schema,
):
    result = _table_validation_result(**{schema_field: mismatched_schema})

    with pytest.raises(MigrationSafetyError, match=schema_field):
        migration.MigrationValidationReport(
            source_schema='legacy_stage_20260715',
            candidate_schema='hrm_candidate_20260715',
            status='passed',
            error_category=None,
            table_results=(result,),
        )


def test_migration_validation_report_constructor_rejects_passed_failed_table():
    failed_result = _table_validation_result(
        orphan_rows=1,
        status='failed',
        error_category='foreign_key_orphan',
    )

    with pytest.raises(MigrationSafetyError, match='table-derived'):
        migration.MigrationValidationReport(
            source_schema='legacy_stage_20260715',
            candidate_schema='hrm_candidate_20260715',
            status='passed',
            error_category=None,
            table_results=(failed_result,),
        )


def test_migration_validation_report_constructor_rejects_wrong_error_priority():
    orphan_result = _table_validation_result(
        orphan_rows=1,
        status='failed',
        error_category='foreign_key_orphan',
    )
    mismatch_result = _table_validation_result(
        table='users',
        inserted_rows=1,
        status='failed',
        error_category='count_mismatch',
    )

    with pytest.raises(MigrationSafetyError, match='table-derived'):
        migration.MigrationValidationReport(
            source_schema='legacy_stage_20260715',
            candidate_schema='hrm_candidate_20260715',
            status='failed',
            error_category='foreign_key_orphan',
            table_results=(orphan_result, mismatch_result),
        )


@pytest.mark.parametrize(
    ('status', 'error_category'),
    (
        ('passed', 'count_mismatch'),
        ('failed', None),
        ('failed', 'unknown_validation_error'),
        ('unknown', None),
    ),
)
def test_migration_validation_report_rejects_invalid_status_category_state(
    status,
    error_category,
):
    with pytest.raises(MigrationSafetyError):
        migration.MigrationValidationReport(
            source_schema='legacy_stage_20260715',
            candidate_schema='hrm_candidate_20260715',
            status=status,
            error_category=error_category,
            table_results=(_table_validation_result(),),
        )


def test_validation_report_is_json_safe_and_contains_no_row_values():
    result = migration.build_table_validation_result(
        source_schema='legacy_stage_20260715',
        candidate_schema='hrm_candidate_20260715',
        table='users',
        source_rows=2,
        inserted_rows=2,
        candidate_tenant_rows=2,
        null_tenant_rows=0,
        orphan_rows=0,
        cross_tenant_rows=0,
    )
    report = migration.build_migration_validation_report(
        source_schema='legacy_stage_20260715',
        candidate_schema='hrm_candidate_20260715',
        table_results=(result,),
    )

    payload = report.to_dict()
    serialized = json.dumps(payload)

    assert payload == {
        'source_schema': 'legacy_stage_20260715',
        'candidate_schema': 'hrm_candidate_20260715',
        'status': 'passed',
        'error_category': None,
        'tables': [
            {
                'source_schema': 'legacy_stage_20260715',
                'candidate_schema': 'hrm_candidate_20260715',
                'table': 'users',
                'source_rows': 2,
                'inserted_rows': 2,
                'candidate_tenant_rows': 2,
                'null_tenant_rows': 0,
                'orphan_rows': 0,
                'cross_tenant_rows': 0,
                'status': 'passed',
                'error_category': None,
            },
        ],
    }
    for secret_or_row_value in (
        '$2b$12$not-for-a-report',
        'person@example.com',
        'Legacy Person',
    ):
        assert secret_or_row_value not in serialized


def test_transactional_migration_commits_only_after_successful_validation():
    source, target, plan = _migration_metadata('employees')
    connection = FakeMigrationConnection(source_counts={'employees': 2})

    report = _execute_single_table(connection, source, target, plan)

    assert report.status == 'passed'
    assert report.table_results == (
        migration.TableValidationResult(
            source_schema='legacy_stage_20260715',
            candidate_schema='hrm_candidate_20260715',
            table='employees',
            source_rows=2,
            inserted_rows=2,
            candidate_tenant_rows=2,
            null_tenant_rows=0,
            orphan_rows=0,
            cross_tenant_rows=0,
            status='passed',
            error_category=None,
        ),
    )
    assert connection.begin_count == 1
    assert connection.commit_count == 1
    assert connection.rollback_count == 0
    assert connection.created_cursor.closed is True
    assert connection.statements[-1] == ('SET FOREIGN_KEY_CHECKS=1', ())
    assert set(connection.execute_begin_counts) == {1}

    users_source, users_target, users_plan = _migration_metadata(
        'users',
        columns=('id', 'password_hash', 'role'),
    )
    users_connection = FakeMigrationConnection(
        source_counts={'users': 1},
        null_tenant_counts={'users': 0},
        historical_null_tenant_counts={'users': 1},
    )

    users_report = _execute_single_table(
        users_connection,
        users_source,
        users_target,
        users_plan,
    )

    null_check = next(
        statement
        for statement in users_connection.statements
        if '`candidate_rows`.`tenant_id` IS NULL' in statement[0]
    )
    assert users_report.status == 'passed'
    assert 'AS `candidate_rows` INNER JOIN' in null_check[0]
    assert '`candidate_rows`.`id` = `stage_rows`.`id`' in null_check[0]
    assert null_check[1] == ()


def test_transactional_migration_replaces_only_planned_seed_rows():
    source_tables = []
    target_tables = []
    plan_items = []
    for table in ('employees', 'roles', 'settings'):
        source, target, plan = _migration_metadata(table)
        source_tables.append(source)
        target_tables.append(target)
        plan_items.extend(plan)
    connection = FakeMigrationConnection(
        source_counts={'employees': 1, 'roles': 2, 'settings': 1},
        destination_counts={'employees': 0, 'roles': 4, 'settings': 3},
        candidate_counts={'employees': 1, 'roles': 2, 'settings': 1},
        deleted_counts={'roles': 4, 'settings': 3},
    )

    report = migration.execute_transactional_migration(
        connection,
        stage_database='legacy_stage_20260715',
        candidate_database='hrm_candidate_20260715',
        tenant_id=17,
        migration_plan=tuple(plan_items),
        source_tables=tuple(source_tables),
        target_tables=tuple(target_tables),
    )

    delete_statements = [
        statement
        for statement in connection.statements
        if statement[0].startswith('DELETE FROM')
    ]
    assert report.status == 'passed'
    assert delete_statements == [
        (
            'DELETE FROM `hrm_candidate_20260715`.`roles` '
            'WHERE `tenant_id` = %s',
            (17,),
        ),
        (
            'DELETE FROM `hrm_candidate_20260715`.`settings` '
            'WHERE `tenant_id` = %s',
            (17,),
        ),
    ]
    assert not any(
        sql.startswith('DELETE FROM `hrm_candidate_20260715`.`employees`')
        for sql, _params in connection.statements
    )


def test_transactional_migration_applies_primary_key_collision_policy():
    source, target, plan = _migration_metadata('employees')
    connection = FakeMigrationConnection(
        source_counts={'employees': 1},
        collision_counts={'employees': 1},
    )

    with pytest.raises(MigrationSafetyError, match='primary key collision'):
        _execute_single_table(connection, source, target, plan)

    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    assert not any(
        sql.startswith(('DELETE FROM', 'INSERT INTO'))
        for sql, _params in connection.statements
    )

    roles_source, roles_target, roles_plan = _migration_metadata('roles')
    same_tenant_connection = FakeMigrationConnection(
        source_counts={'roles': 1},
        destination_counts={'roles': 1},
        collision_counts={'roles': 1},
        seed_collision_counts={'roles': 0},
    )

    same_tenant_report = _execute_single_table(
        same_tenant_connection,
        roles_source,
        roles_target,
        roles_plan,
    )

    seed_collision_check = next(
        statement
        for statement in same_tenant_connection.statements
        if 'AS `stage_rows`' in statement[0]
    )
    assert same_tenant_report.status == 'passed'
    assert '`candidate_rows`.`tenant_id` IS NULL' in seed_collision_check[0]
    assert '`candidate_rows`.`tenant_id` <> %s' in seed_collision_check[0]
    assert seed_collision_check[1] == (17,)

    cross_tenant_connection = FakeMigrationConnection(
        source_counts={'roles': 1},
        collision_counts={'roles': 1},
        seed_collision_counts={'roles': 1},
    )

    with pytest.raises(MigrationSafetyError, match='primary key collision'):
        _execute_single_table(
            cross_tenant_connection,
            roles_source,
            roles_target,
            roles_plan,
        )

    assert cross_tenant_connection.commit_count == 0
    assert cross_tenant_connection.rollback_count == 1
    assert not any(
        sql.startswith(('DELETE FROM', 'INSERT INTO'))
        for sql, _params in cross_tenant_connection.statements
    )


@pytest.mark.parametrize(
    ('table', 'connection_kwargs', 'message'),
    (
        (
            'users',
            {'invalid_bcrypt_counts': {'users': 1}},
            'invalid_password_hashes=1',
        ),
        (
            'employee_portal_accounts',
            {'invalid_bcrypt_counts': {'employee_portal_accounts': 1}},
            'invalid_password_hashes=1',
        ),
        (
            'users',
            {'platform_admin_count': 1},
            'platform_admin_users=1',
        ),
    ),
)
def test_transactional_migration_blocks_unsafe_accounts(
    table,
    connection_kwargs,
    message,
):
    source, target, plan = _migration_metadata(
        table,
        columns=('id', 'password_hash', 'role'),
    )
    connection = FakeMigrationConnection(
        source_counts={table: 1},
        **connection_kwargs,
    )

    with pytest.raises(MigrationSafetyError, match=message):
        _execute_single_table(connection, source, target, plan)

    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    assert not any(
        sql.startswith(('DELETE FROM', 'INSERT INTO'))
        for sql, _params in connection.statements
    )


def test_transactional_migration_rolls_back_when_insert_fails_mid_copy():
    source_tables = []
    target_tables = []
    plan_items = []
    for table in ('departments', 'employees'):
        source, target, plan = _migration_metadata(table)
        source_tables.append(source)
        target_tables.append(target)
        plan_items.extend(plan)
    connection = FakeMigrationConnection(
        source_counts={'departments': 1, 'employees': 1},
        fail_insert_table='employees',
    )

    with pytest.raises(RuntimeError, match='simulated copy failure'):
        migration.execute_transactional_migration(
            connection,
            stage_database='legacy_stage_20260715',
            candidate_database='hrm_candidate_20260715',
            tenant_id=17,
            migration_plan=tuple(plan_items),
            source_tables=tuple(source_tables),
            target_tables=tuple(target_tables),
        )

    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    assert connection.close_count == 0
    assert connection.created_cursor.closed is True
    assert connection.statements[-1] == ('SET FOREIGN_KEY_CHECKS=1', ())

    rollback_failure_connection = FakeMigrationConnection(
        source_counts={'departments': 1, 'employees': 1},
        fail_insert_table='employees',
        rollback_fail=True,
        close_fail=True,
    )

    with pytest.raises(
        MigrationSafetyError,
        match='rollback failed; candidate transaction state is unknown',
    ) as rollback_failure:
        migration.execute_transactional_migration(
            rollback_failure_connection,
            stage_database='legacy_stage_20260715',
            candidate_database='hrm_candidate_20260715',
            tenant_id=17,
            migration_plan=tuple(plan_items),
            source_tables=tuple(source_tables),
            target_tables=tuple(target_tables),
        )

    assert str(rollback_failure.value.__cause__) == 'simulated rollback failure'
    assert rollback_failure_connection.commit_count == 0
    assert rollback_failure_connection.rollback_count == 1
    assert rollback_failure_connection.close_count == 1

    commit_failure_connection = FakeMigrationConnection(
        source_counts={'departments': 1, 'employees': 1},
        commit_fail=True,
        rollback_fail=True,
    )

    with pytest.raises(
        MigrationSafetyError,
        match='rollback failed; candidate transaction state is unknown',
    ) as commit_rollback_failure:
        migration.execute_transactional_migration(
            commit_failure_connection,
            stage_database='legacy_stage_20260715',
            candidate_database='hrm_candidate_20260715',
            tenant_id=17,
            migration_plan=tuple(plan_items),
            source_tables=tuple(source_tables),
            target_tables=tuple(target_tables),
        )

    assert (
        str(commit_rollback_failure.value.__cause__)
        == 'simulated rollback failure'
    )
    assert commit_failure_connection.commit_count == 1
    assert commit_failure_connection.rollback_count == 1
    assert commit_failure_connection.close_count == 1


def test_transactional_migration_rolls_back_on_foreign_key_orphan():
    foreign_key = migration.ForeignKeyMetadata(
        columns=('department_id',),
        referenced_table='departments',
        referenced_columns=('id',),
    )
    source, target, plan = _migration_metadata(
        'employees',
        columns=('id', 'department_id'),
        foreign_keys=(foreign_key,),
    )
    parent_target = migration.TableMetadata(
        name='departments',
        columns=('id', 'tenant_id'),
        primary_key=('id',),
    )
    connection = FakeMigrationConnection(
        source_counts={'employees': 1},
        orphan_counts={'employees': 1},
    )

    with pytest.raises(MigrationSafetyError, match='foreign_key_orphan'):
        _execute_single_table(
            connection,
            source,
            target,
            plan,
            target_tables=(target, parent_target),
        )

    assert connection.commit_count == 0
    assert connection.rollback_count == 1


def test_transactional_migration_rolls_back_on_cross_tenant_foreign_key():
    foreign_key = migration.ForeignKeyMetadata(
        columns=('department_id',),
        referenced_table='departments',
        referenced_columns=('id',),
    )
    source, target, plan = _migration_metadata(
        'employees',
        columns=('id', 'department_id'),
        foreign_keys=(foreign_key,),
    )
    parent_target = migration.TableMetadata(
        name='departments',
        columns=('id', 'tenant_id'),
        primary_key=('id',),
    )
    connection = FakeMigrationConnection(
        source_counts={'employees': 1},
        parent_null_cross_tenant_counts={'employees': 1},
    )

    with pytest.raises(
        MigrationSafetyError,
        match='cross_tenant_foreign_key',
    ):
        _execute_single_table(
            connection,
            source,
            target,
            plan,
            target_tables=(target, parent_target),
        )

    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    cross_tenant_sql, cross_tenant_params = next(
        statement
        for statement in connection.statements
        if 'AS `candidate_child` INNER JOIN' in statement[0]
    )
    assert (
        'AND (`candidate_parent`.`tenant_id` IS NULL '
        'OR `candidate_parent`.`tenant_id` <> %s)'
        in cross_tenant_sql
    )
    assert cross_tenant_params == (17, 17)


@pytest.mark.parametrize(
    'unsafe_target',
    (
        migration.TableMetadata(
            name='unsafe-table',
            columns=('id', 'tenant_id'),
            primary_key=('id',),
        ),
        migration.TableMetadata(
            name='audit_rows',
            columns=('id', 'tenant-id'),
            primary_key=('id',),
        ),
    ),
)
def test_transactional_migration_validates_all_identifiers_before_begin(
    unsafe_target,
):
    source, target, plan = _migration_metadata('employees')
    connection = FakeMigrationConnection()

    with pytest.raises(MigrationSafetyError, match='identifier'):
        _execute_single_table(
            connection,
            source,
            target,
            plan,
            target_tables=(target, unsafe_target),
        )

    assert connection.begin_count == 0
    assert connection.commit_count == 0
    assert connection.rollback_count == 0
    assert connection.statements == []


def test_transactional_migration_validates_foreign_key_metadata_before_begin():
    foreign_key = migration.ForeignKeyMetadata(
        columns=(),
        referenced_table='departments',
        referenced_columns=(),
    )
    source, target, plan = _migration_metadata(
        'employees',
        foreign_keys=(foreign_key,),
    )
    parent_target = migration.TableMetadata(
        name='departments',
        columns=('id', 'tenant_id'),
        primary_key=('id',),
    )
    connection = FakeMigrationConnection()

    with pytest.raises(MigrationSafetyError, match='foreign key metadata'):
        _execute_single_table(
            connection,
            source,
            target,
            plan,
            target_tables=(target, parent_target),
        )

    assert connection.begin_count == 0
    assert connection.statements == []


def test_transactional_migration_rolls_back_if_foreign_keys_cannot_be_restored():
    source, target, plan = _migration_metadata('employees')
    connection = FakeMigrationConnection(
        source_counts={'employees': 1},
        foreign_key_restore_fail=True,
    )

    with pytest.raises(
        MigrationSafetyError,
        match='failed to restore foreign key checks; connection closed',
    ) as restore_failure:
        _execute_single_table(connection, source, target, plan)

    assert str(restore_failure.value.__cause__) == (
        'simulated foreign key restoration failure'
    )
    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    assert connection.close_count == 1
    assert connection.created_cursor.closed is True

    cursor_close_connection = FakeMigrationConnection(
        source_counts={'employees': 1},
        cursor_close_fail=True,
    )

    with pytest.raises(
        MigrationSafetyError,
        match='migration cleanup failed; connection closed',
    ) as cursor_close_failure:
        _execute_single_table(
            cursor_close_connection,
            source,
            target,
            plan,
        )

    assert str(cursor_close_failure.value.__cause__) == (
        'simulated cursor close failure'
    )
    assert cursor_close_connection.commit_count == 0
    assert cursor_close_connection.rollback_count == 1
    assert cursor_close_connection.close_count == 1

    rollback_failure_connection = FakeMigrationConnection(
        source_counts={'employees': 1},
        foreign_key_restore_fail=True,
        rollback_fail=True,
    )

    with pytest.raises(
        MigrationSafetyError,
        match='rollback failed; candidate transaction state is unknown',
    ) as rollback_failure:
        _execute_single_table(
            rollback_failure_connection,
            source,
            target,
            plan,
        )

    assert str(rollback_failure.value.__cause__) == 'simulated rollback failure'
    assert rollback_failure_connection.commit_count == 0
    assert rollback_failure_connection.rollback_count == 1
    assert rollback_failure_connection.close_count == 1


def test_foreign_key_restore_failure_supersedes_insert_failure():
    source, target, plan = _migration_metadata('employees')
    connection = FakeMigrationConnection(
        source_counts={'employees': 1},
        fail_insert_table='employees',
        foreign_key_restore_fail=True,
    )

    with pytest.raises(
        MigrationSafetyError,
        match='failed to restore foreign key checks; connection closed',
    ) as restore_failure:
        _execute_single_table(connection, source, target, plan)

    assert str(restore_failure.value.__cause__) == (
        'simulated foreign key restoration failure'
    )
    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    assert connection.close_count == 1
    assert connection.created_cursor.closed is True


def test_transactional_migration_blocked_plan_has_zero_database_activity():
    source = migration.TableMetadata(
        name='employees',
        columns=('id', 'legacy_value'),
        primary_key=('id',),
    )
    target = migration.TableMetadata(
        name='employees',
        columns=('id', 'tenant_id'),
        primary_key=('id',),
    )
    plan = migration.build_migration_plan((source,), (target,))
    connection = FakeMigrationConnection()

    with pytest.raises(MigrationSafetyError, match='blocked tables: employees'):
        _execute_single_table(connection, source, target, plan)

    assert connection.begin_count == 0
    assert connection.commit_count == 0
    assert connection.rollback_count == 0
    assert connection.created_cursor is None
    assert connection.statements == []


@pytest.mark.parametrize('tenant_id', (None, '', '   ', True, [], {}))
def test_transactional_migration_rejects_empty_or_non_scalar_tenant_id(
    tenant_id,
):
    source, target, plan = _migration_metadata('employees')
    connection = FakeMigrationConnection()

    with pytest.raises(MigrationSafetyError, match='non-empty scalar'):
        migration.execute_transactional_migration(
            connection,
            stage_database='legacy_stage_20260715',
            candidate_database='hrm_candidate_20260715',
            tenant_id=tenant_id,
            migration_plan=plan,
            source_tables=(source,),
            target_tables=(target,),
        )

    assert connection.begin_count == 0
    assert connection.statements == []


def test_transactional_migration_rejects_incomplete_plan_before_begin():
    source, target, _plan = _migration_metadata('employees')
    connection = FakeMigrationConnection()

    with pytest.raises(MigrationSafetyError, match='does not match complete'):
        _execute_single_table(
            connection,
            source,
            target,
            (
                migration.MigrationPlanItem(
                    table='employees',
                    status='copy',
                    columns=('id',),
                ),
            ),
        )

    assert connection.begin_count == 0
    assert connection.statements == []


def test_transactional_migration_checks_target_only_business_tables():
    source, target, plan = _migration_metadata('employees')
    target_only = migration.TableMetadata(
        name='security_insight_snapshots',
        columns=('id', 'tenant_id'),
        primary_key=('id',),
    )
    control_table = migration.TableMetadata(
        name='tenant_modules',
        columns=('id', 'tenant_id'),
        primary_key=('id',),
    )
    connection = FakeMigrationConnection(
        destination_counts={
            'employees': 0,
            'security_insight_snapshots': 1,
            'tenant_modules': 9,
        },
    )

    with pytest.raises(
        MigrationSafetyError,
        match='security_insight_snapshots',
    ):
        _execute_single_table(
            connection,
            source,
            target,
            plan,
            target_tables=(target, target_only, control_table),
        )

    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    assert not any(
        sql.startswith(('DELETE FROM', 'INSERT INTO'))
        for sql, _params in connection.statements
    )
    assert not any(
        '.`tenant_modules`' in sql for sql, _params in connection.statements
    )


def test_transactional_migration_bcrypt_and_role_checks_are_parameterized():
    source, target, plan = _migration_metadata(
        'users',
        columns=('id', 'password_hash', 'role'),
    )
    connection = FakeMigrationConnection(source_counts={'users': 1})

    _execute_single_table(connection, source, target, plan)

    bcrypt_statement = next(
        statement
        for statement in connection.statements
        if 'REGEXP' in statement[0]
    )
    role_statement = next(
        statement
        for statement in connection.statements
        if '`role` = %s' in statement[0]
    )
    assert bcrypt_statement[1][0].startswith('^')
    assert bcrypt_statement[1][0].endswith('$')
    assert (
        "NOT REGEXP_LIKE(`password_hash`, %s, 'c')"
        in bcrypt_statement[0]
    )
    assert '$2b$12$row-value-must-not-appear' not in repr(connection.statements)
    assert role_statement[1] == ('platform_admin',)
    assert 'platform_admin' not in role_statement[0]


@pytest.mark.parametrize(
    ('connection_kwargs', 'message'),
    (
        ({'inserted_counts': {'employees': -1}}, 'insert rowcount is invalid'),
        ({'inserted_counts': {'employees': 1}}, 'count_mismatch'),
        ({'null_tenant_counts': {'employees': 1}}, 'null_tenant_id'),
    ),
)
def test_transactional_migration_rolls_back_on_invalid_table_counts(
    connection_kwargs,
    message,
):
    source, target, plan = _migration_metadata('employees')
    connection = FakeMigrationConnection(
        source_counts={'employees': 2},
        **connection_kwargs,
    )

    with pytest.raises(MigrationSafetyError, match=message):
        _execute_single_table(connection, source, target, plan)

    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    assert connection.created_cursor.closed is True
    assert connection.statements[-1] == ('SET FOREIGN_KEY_CHECKS=1', ())


def test_transactional_migration_runs_post_copy_hook_before_validation_commit():
    source, target, plan = _migration_metadata('employees')
    connection = FakeMigrationConnection(source_counts={'employees': 1})
    captured = {}

    def post_copy_hook(**kwargs):
        captured.update(kwargs)
        assert connection.inserted_tables == {'employees'}
        assert connection.commit_count == 0

    _execute_single_table(
        connection,
        source,
        target,
        plan,
        post_copy_hook=post_copy_hook,
    )

    assert captured == {
        'cursor': connection.created_cursor,
        'stage_database': 'legacy_stage_20260715',
        'candidate_database': 'hrm_candidate_20260715',
        'tenant_id': 17,
        'migration_plan': plan,
        'source_tables': (source,),
        'target_tables': (target,),
    }
    assert connection.commit_count == 1


def test_transactional_migration_rolls_back_when_post_copy_hook_fails():
    source, target, plan = _migration_metadata('employees')
    connection = FakeMigrationConnection(source_counts={'employees': 1})

    def fail_hook(**_kwargs):
        raise MigrationSafetyError('simulated reference rewrite failure')

    with pytest.raises(MigrationSafetyError, match='reference rewrite'):
        _execute_single_table(
            connection,
            source,
            target,
            plan,
            post_copy_hook=fail_hook,
        )

    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    assert connection.created_cursor.closed is True


def test_candidate_restore_cli_source_contains_no_full_database_clear_path():
    source = Path(restore_cli.__file__).read_text(encoding='utf-8')

    assert 'TRUNCATE TABLE' not in source
    assert 'DROP DATABASE' not in source
    assert 'CLEAR_TARGET_AND_RESTORE' not in source
    assert restore_cli.CONFIRM_PHRASE == 'MIGRATE_LEGACY_TO_CANDIDATE'


def test_candidate_restore_cli_direct_script_entrypoint_loads_services():
    completed = subprocess.run(
        [sys.executable, str(Path(restore_cli.__file__)), '--help'],
        cwd=Path(restore_cli.__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert '--candidate-database' in completed.stdout
    assert '--stage-database' in completed.stdout


def test_candidate_restore_cli_parses_explicit_candidate_only_inputs(tmp_path):
    args = restore_cli.parse_args(
        [
            '--dump',
            str(tmp_path / 'legacy.sql'),
            '--stage-database',
            'legacy_stage_20260715',
            '--candidate-database',
            'hrm_candidate_20260715',
            '--tenant-slug',
            'HPT-00000001',
            '--report',
            str(tmp_path / 'report.json'),
            '--prepared-files-root',
            str(tmp_path / 'prepared'),
        ]
    )

    assert args.execute is False
    assert args.stage_database == 'legacy_stage_20260715'
    assert args.candidate_database == 'hrm_candidate_20260715'
    assert args.tenant_slug == 'HPT-00000001'
    assert args.report == tmp_path / 'report.json'
    assert args.prepared_files_root == tmp_path / 'prepared'
    assert not hasattr(args, 'database')
    assert not hasattr(args, 'keep_temp')
    assert not hasattr(args, 'backup_dir')


def test_candidate_restore_cli_inspects_dump_without_database_inputs(
    tmp_path,
    monkeypatch,
    capsys,
):
    dump_path = tmp_path / 'legacy.sql'
    dump_path.write_text(
        'CREATE TABLE `employees` (\n'
        '  `id` int NOT NULL,\n'
        '  `name` varchar(80) DEFAULT NULL\n'
        ');\n',
        encoding='utf-8',
    )

    def unexpected_connect(**_kwargs):
        raise AssertionError('inspect-only mode must not connect to MySQL')

    monkeypatch.setattr(restore_cli, 'connect', unexpected_connect)

    assert restore_cli.main(
        ['--dump', str(dump_path), '--inspect-dump-only']
    ) == 0
    output = capsys.readouterr().out
    assert 'table_count=1' in output
    assert 'employees: 2 columns' in output


def test_candidate_restore_cli_requires_all_non_inspection_safety_inputs(
    tmp_path,
):
    dump_path = tmp_path / 'legacy.sql'
    dump_path.write_text('-- empty test dump\n', encoding='utf-8')

    with pytest.raises(MigrationSafetyError, match='stage-database'):
        restore_cli.main(['--dump', str(dump_path)])


def test_candidate_restore_cli_rejects_live_database_before_connecting(
    tmp_path,
    monkeypatch,
):
    dump_path = tmp_path / 'legacy.sql'
    env_path = tmp_path / '.env'
    report_path = tmp_path / 'report.json'
    dump_path.write_text('-- test dump\n', encoding='utf-8')
    env_path.write_text(
        'DB_NAME=hrm_candidate_20260715\n'
        'DB_USER=migration\n'
        'DB_PASSWORD=not-used\n',
        encoding='utf-8',
    )

    def unexpected_connect(**_kwargs):
        raise AssertionError('unsafe candidate must be rejected before connect')

    monkeypatch.setattr(restore_cli, 'connect', unexpected_connect)

    with pytest.raises(MigrationSafetyError, match='configured live database'):
        restore_cli.main(
            [
                '--env',
                str(env_path),
                '--dump',
                str(dump_path),
                '--stage-database',
                'legacy_stage_20260715',
                '--candidate-database',
                'hrm_candidate_20260715',
                '--tenant-slug',
                'HPT-00000001',
                '--report',
                str(report_path),
            ]
        )


def test_candidate_restore_cli_validates_confirmation_before_connecting(
    tmp_path,
    monkeypatch,
):
    dump_path = tmp_path / 'legacy.sql'
    env_path = tmp_path / '.env'
    dump_path.write_text('-- test dump\n', encoding='utf-8')
    env_path.write_text(
        'DB_NAME=hrm_live\nDB_USER=migration\nDB_PASSWORD=not-used\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(
        restore_cli,
        'connect',
        lambda **_kwargs: pytest.fail('must reject confirmation first'),
    )

    with pytest.raises(MigrationSafetyError, match='MIGRATE_LEGACY_TO_CANDIDATE'):
        restore_cli.main(
            [
                '--env',
                str(env_path),
                '--dump',
                str(dump_path),
                '--stage-database',
                'legacy_stage_20260715',
                '--candidate-database',
                'hrm_candidate_20260715',
                '--tenant-slug',
                'HPT-00000001',
                '--report',
                str(tmp_path / 'report.json'),
                '--execute',
                '--confirm',
                'wrong phrase',
            ]
        )


class FakeMetadataCursor:
    def __init__(self, result_sets):
        self.result_sets = result_sets
        self.rows = []
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=()):
        normalized = ' '.join(sql.split())
        self.statements.append((normalized, params))
        if 'information_schema.columns' in normalized:
            self.rows = self.result_sets['columns']
        elif "constraint_name = 'PRIMARY'" in normalized:
            self.rows = self.result_sets['primary_keys']
        elif 'referenced_table_name IS NOT NULL' in normalized:
            self.rows = self.result_sets['foreign_keys']
        else:
            raise AssertionError(f'unexpected metadata SQL: {normalized}')

    def fetchall(self):
        return list(self.rows)


class FakeMetadataConnection:
    def __init__(self, result_sets):
        self.cursor_instance = FakeMetadataCursor(result_sets)

    def cursor(self, *_args, **_kwargs):
        return self.cursor_instance


def test_candidate_restore_cli_loads_complete_schema_metadata():
    connection = FakeMetadataConnection(
        {
            'columns': [
                {
                    'table_name': 'departments',
                    'column_name': 'id',
                    'is_nullable': 'NO',
                    'column_default': None,
                    'extra': '',
                },
                {
                    'table_name': 'employees',
                    'column_name': 'id',
                    'is_nullable': 'NO',
                    'column_default': None,
                    'extra': 'auto_increment',
                },
                {
                    'table_name': 'employees',
                    'column_name': 'department_id',
                    'is_nullable': 'YES',
                    'column_default': None,
                    'extra': '',
                },
                {
                    'table_name': 'employees',
                    'column_name': 'tenant_id',
                    'is_nullable': 'NO',
                    'column_default': None,
                    'extra': '',
                },
            ],
            'primary_keys': [
                {'table_name': 'departments', 'column_name': 'id'},
                {'table_name': 'employees', 'column_name': 'id'},
            ],
            'foreign_keys': [
                {
                    'table_name': 'employees',
                    'constraint_name': 'fk_employee_department',
                    'column_name': 'department_id',
                    'referenced_table_name': 'departments',
                    'referenced_column_name': 'id',
                },
            ],
        }
    )

    metadata = restore_cli.load_schema_metadata(
        connection,
        'hrm_candidate_20260715',
    )

    assert metadata == (
        migration.TableMetadata(
            name='departments',
            columns=('id',),
            primary_key=('id',),
            required_columns_without_default=('id',),
        ),
        migration.TableMetadata(
            name='employees',
            columns=('id', 'department_id', 'tenant_id'),
            primary_key=('id',),
            required_columns_without_default=('tenant_id',),
            foreign_keys=(
                migration.ForeignKeyMetadata(
                    columns=('department_id',),
                    referenced_table='departments',
                    referenced_columns=('id',),
                ),
            ),
        ),
    )
    assert all(
        params == ('hrm_candidate_20260715',)
        for _sql, params in connection.cursor_instance.statements
    )
    primary_key_sql = connection.cursor_instance.statements[1][0]
    foreign_key_sql = connection.cursor_instance.statements[2][0]
    assert 'table_name AS table_name' in primary_key_sql
    assert 'column_name AS column_name' in primary_key_sql
    assert 'table_name AS table_name' in foreign_key_sql
    assert 'constraint_name AS constraint_name' in foreign_key_sql
    assert 'referenced_table_name AS referenced_table_name' in foreign_key_sql


def test_candidate_restore_cli_requires_dump_and_stage_shapes_to_match():
    stage = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name'),
            primary_key=('id',),
        ),
    )

    restore_cli.validate_dump_stage_shape(
        {'employees': ['id', 'name']},
        stage,
    )
    with pytest.raises(MigrationSafetyError, match='shape mismatch'):
        restore_cli.validate_dump_stage_shape(
            {'employees': ['id', 'legacy_name']},
            stage,
        )
    with pytest.raises(MigrationSafetyError, match='shape mismatch'):
        restore_cli.validate_dump_stage_shape(
            {'employees': ['id', 'name'], 'users': ['id']},
            stage,
        )


class FakeCliConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _write_candidate_cli_inputs(tmp_path):
    dump_path = tmp_path / 'legacy.sql'
    env_path = tmp_path / '.env'
    report_path = tmp_path / 'report.json'
    dump_path.write_text(
        'CREATE TABLE `employees` (\n'
        '  `id` int NOT NULL,\n'
        '  `name` varchar(80) DEFAULT NULL\n'
        ');\n',
        encoding='utf-8',
    )
    env_path.write_text(
        'DB_NAME=hrm_live\nDB_USER=migration\nDB_PASSWORD=test-only\n',
        encoding='utf-8',
    )
    return dump_path, env_path, report_path


def _candidate_cli_argv(
    dump_path,
    env_path,
    report_path,
    *extra,
):
    return [
        '--env',
        str(env_path),
        '--dump',
        str(dump_path),
        '--stage-database',
        'legacy_stage_20260715',
        '--candidate-database',
        'hrm_candidate_20260715',
        '--tenant-slug',
        'HPT-00000001',
        '--report',
        str(report_path),
        *extra,
    ]


def _patch_candidate_cli_database_boundaries(
    monkeypatch,
    connection,
    source_tables,
    target_tables,
):
    monkeypatch.setattr(restore_cli, 'connect', lambda **_kwargs: connection)
    monkeypatch.setattr(
        restore_cli,
        'schema_exists',
        lambda _connection, _database: True,
    )
    monkeypatch.setattr(
        restore_cli,
        'load_schema_metadata',
        lambda _connection, database: (
            source_tables
            if database == 'legacy_stage_20260715'
            else target_tables
        ),
    )
    monkeypatch.setattr(
        restore_cli,
        'resolve_destination_tenant_id',
        lambda _connection, _database, _slug: 'tenant-1',
    )
    monkeypatch.setattr(
        restore_cli,
        'collect_stage_file_references',
        lambda **_kwargs: (),
    )


def test_candidate_restore_cli_dry_run_writes_plan_without_migrating(
    tmp_path,
    monkeypatch,
):
    dump_path, env_path, report_path = _write_candidate_cli_inputs(tmp_path)
    connection = FakeCliConnection()
    source_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name', 'tenant_id'),
            primary_key=('id',),
        ),
    )
    _patch_candidate_cli_database_boundaries(
        monkeypatch,
        connection,
        source_tables,
        target_tables,
    )
    monkeypatch.setattr(
        restore_cli,
        'execute_transactional_migration',
        lambda *_args, **_kwargs: pytest.fail('dry run must not migrate'),
    )

    result = restore_cli.main(
        _candidate_cli_argv(dump_path, env_path, report_path)
    )

    assert result == 0
    assert connection.closed is True
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['status'] == 'ready'
    assert report['dry_run'] is True
    assert report['stage_database'] == 'legacy_stage_20260715'
    assert report['candidate_database'] == 'hrm_candidate_20260715'
    assert report['tenant_slug'] == 'HPT-00000001'
    assert report['dump']['table_count'] == 1
    assert re.fullmatch(r'[0-9a-f]{64}', report['dump']['sha256'])
    assert report['plan'] == [
        {
            'table': 'employees',
            'status': 'copy',
            'columns': ['id', 'name'],
            'reason': None,
            'source_only_columns': [],
            'unmapped_required_columns': [],
            'source_primary_key': [],
            'target_primary_key': [],
        }
    ]
    assert 'test-only' not in report_path.read_text(encoding='utf-8')


def test_candidate_restore_cli_uses_compose_process_environment(
    tmp_path,
    monkeypatch,
):
    dump_path, env_path, report_path = _write_candidate_cli_inputs(tmp_path)
    env_path.unlink()
    connection = FakeCliConnection()
    source_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name', 'tenant_id'),
            primary_key=('id',),
        ),
    )
    _patch_candidate_cli_database_boundaries(
        monkeypatch,
        connection,
        source_tables,
        target_tables,
    )
    captured_connection = {}

    def capture_connect(**kwargs):
        captured_connection.update(kwargs)
        return connection

    monkeypatch.setattr(restore_cli, 'connect', capture_connect)
    monkeypatch.setenv('DB_NAME', 'hrm_live')
    monkeypatch.setenv('DB_HOST', 'mysql')
    monkeypatch.setenv('DB_PORT', '3307')
    monkeypatch.setenv('DB_USER', 'migration')
    monkeypatch.setenv('DB_PASSWORD', 'compose-secret')

    assert restore_cli.main(
        _candidate_cli_argv(dump_path, env_path, report_path)
    ) == 0
    assert captured_connection == {
        'host': 'mysql',
        'port': 3307,
        'user': 'migration',
        'password': 'compose-secret',
    }
    assert 'compose-secret' not in report_path.read_text(encoding='utf-8')


def test_candidate_restore_cli_execute_calls_transactional_service(
    tmp_path,
    monkeypatch,
):
    dump_path, env_path, report_path = _write_candidate_cli_inputs(tmp_path)
    connection = FakeCliConnection()
    source_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name', 'tenant_id'),
            primary_key=('id',),
        ),
    )
    _patch_candidate_cli_database_boundaries(
        monkeypatch,
        connection,
        source_tables,
        target_tables,
    )
    captured = {}
    validation = migration.build_migration_validation_report(
        source_schema='legacy_stage_20260715',
        candidate_schema='hrm_candidate_20260715',
        table_results=(
            migration.build_table_validation_result(
                source_schema='legacy_stage_20260715',
                candidate_schema='hrm_candidate_20260715',
                table='employees',
                source_rows=1,
                inserted_rows=1,
                candidate_tenant_rows=1,
                null_tenant_rows=0,
                orphan_rows=0,
                cross_tenant_rows=0,
            ),
        ),
    )

    def capture_execute(connection_arg, **kwargs):
        captured['connection'] = connection_arg
        captured.update(kwargs)
        return validation

    monkeypatch.setattr(
        restore_cli,
        'execute_transactional_migration',
        capture_execute,
    )

    result = restore_cli.main(
        _candidate_cli_argv(
            dump_path,
            env_path,
            report_path,
            '--execute',
            '--confirm',
            restore_cli.CONFIRM_PHRASE,
        )
    )

    assert result == 0
    assert connection.closed is True
    post_copy_hook = captured.pop('post_copy_hook')
    assert callable(post_copy_hook)
    assert captured == {
        'connection': connection,
        'stage_database': 'legacy_stage_20260715',
        'candidate_database': 'hrm_candidate_20260715',
        'tenant_id': 'tenant-1',
        'migration_plan': migration.build_migration_plan(
            source_tables,
            target_tables,
        ),
        'source_tables': source_tables,
        'target_tables': target_tables,
    }
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['status'] == 'passed'
    assert report['dry_run'] is False
    assert report['validation'] == validation.to_dict()
    assert 'file_references' not in report


def test_candidate_restore_cli_requires_both_precreated_schemas(
    tmp_path,
    monkeypatch,
):
    dump_path, env_path, report_path = _write_candidate_cli_inputs(tmp_path)
    connection = FakeCliConnection()
    monkeypatch.setattr(restore_cli, 'connect', lambda **_kwargs: connection)
    monkeypatch.setattr(
        restore_cli,
        'schema_exists',
        lambda _connection, database: database != 'legacy_stage_20260715',
    )

    with pytest.raises(MigrationSafetyError, match='pre-created stage'):
        restore_cli.main(
            _candidate_cli_argv(dump_path, env_path, report_path)
        )

    assert connection.closed is True


class FakeTenantCursor:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=()):
        self.statement = (' '.join(sql.split()), params)

    def fetchall(self):
        return list(self.rows)


class FakeTenantConnection:
    def __init__(self, rows):
        self.cursor_instance = FakeTenantCursor(rows)

    def cursor(self):
        return self.cursor_instance


def test_candidate_restore_cli_resolves_exactly_one_tenant_parameterized():
    connection = FakeTenantConnection([('tenant-1',)])

    tenant_id = restore_cli.resolve_destination_tenant_id(
        connection,
        'hrm_candidate_20260715',
        'HPT-00000001',
    )

    assert tenant_id == 'tenant-1'
    sql, params = connection.cursor_instance.statement
    assert 'HPT-00000001' not in sql
    assert params == ('HPT-00000001',)


@pytest.mark.parametrize('rows', ([], [('tenant-1',), ('tenant-2',)]))
def test_candidate_restore_cli_rejects_missing_or_duplicate_tenant(rows):
    connection = FakeTenantConnection(rows)

    with pytest.raises(MigrationSafetyError, match='exactly one'):
        restore_cli.resolve_destination_tenant_id(
            connection,
            'hrm_candidate_20260715',
            'HPT-00000001',
        )


def test_candidate_restore_cli_writes_sanitized_failure_report(
    tmp_path,
    monkeypatch,
):
    dump_path, env_path, report_path = _write_candidate_cli_inputs(tmp_path)
    connection = FakeCliConnection()
    source_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name', 'tenant_id'),
            primary_key=('id',),
        ),
    )
    _patch_candidate_cli_database_boundaries(
        monkeypatch,
        connection,
        source_tables,
        target_tables,
    )

    def fail_migration(*_args, **_kwargs):
        raise MigrationSafetyError(
            'simulated private row value must not reach the report'
        )

    monkeypatch.setattr(
        restore_cli,
        'execute_transactional_migration',
        fail_migration,
    )

    with pytest.raises(MigrationSafetyError, match='simulated private'):
        restore_cli.main(
            _candidate_cli_argv(
                dump_path,
                env_path,
                report_path,
                '--execute',
                '--confirm',
                restore_cli.CONFIRM_PHRASE,
            )
        )

    serialized = report_path.read_text(encoding='utf-8')
    report = json.loads(serialized)
    assert report['status'] == 'failed'
    assert report['error_category'] == 'migration_safety_error'
    assert 'simulated private' not in serialized
    assert 'test-only' not in serialized
    assert connection.closed is True


class FakeReferenceRewriteCursor:
    def __init__(self, rows_by_column):
        self.rows_by_column = rows_by_column
        self.rows = []
        self.rowcount = -1
        self.statements = []

    def execute(self, sql, params=()):
        normalized = ' '.join(sql.split())
        normalized_params = tuple(params)
        self.statements.append((normalized, normalized_params))
        self.rowcount = -1
        table_match = re.search(r'`hrm_candidate_20260715`\.`([^`]+)`', sql)
        if table_match is None:
            raise AssertionError(f'missing candidate table: {sql}')
        table = table_match.group(1)
        if normalized.startswith('SELECT'):
            selected = normalized.split(' FROM ', 1)[0]
            selected_columns = re.findall(r'`([^`]+)`', selected)
            column = selected_columns[-1]
            self.rows = list(self.rows_by_column.get((table, column), ()))
            return
        if normalized.startswith('UPDATE'):
            self.rowcount = 1
            self.rows = []
            return
        raise AssertionError(f'unexpected reference SQL: {sql}')

    def fetchall(self):
        return list(self.rows)


def test_candidate_reference_hook_rewrites_scalar_object_and_nested_json():
    cursor = FakeReferenceRewriteCursor(
        {
            ('resumes', 'file_url'): [
                ('resume-1', '/uploads/resumes/candidate.pdf'),
            ],
            ('interviews', 'recording_url'): [
                ('interview-1', 'https://meeting.example.test/recording'),
            ],
            ('course_hours', 'video_key'): [
                ('hour-1', 'courses/course-1/hour-1.mp4'),
            ],
            ('employees', 'attachments'): [
                (
                    'employee-1',
                    json.dumps(
                        {
                            'items': [
                                {'url': '/uploads/employees/id-card.pdf'},
                                {'page_url': '/uploads/hrm/profile'},
                            ]
                        }
                    ),
                ),
            ],
        }
    )
    source_tables = (
        migration.TableMetadata(
            name='resumes',
            columns=('id', 'file_url'),
            primary_key=('id',),
        ),
        migration.TableMetadata(
            name='interviews',
            columns=('id', 'recording_url'),
            primary_key=('id',),
        ),
        migration.TableMetadata(
            name='course_hours',
            columns=('id', 'video_key'),
            primary_key=('id',),
        ),
        migration.TableMetadata(
            name='employees',
            columns=('id', 'attachments'),
            primary_key=('id',),
        ),
    )
    target_tables = tuple(
        migration.TableMetadata(
            name=table.name,
            columns=(*table.columns, 'tenant_id'),
            primary_key=table.primary_key,
        )
        for table in source_tables
    )
    plan = migration.build_migration_plan(source_tables, target_tables)

    references = restore_cli.rewrite_candidate_file_references(
        cursor=cursor,
        stage_database='legacy_stage_20260715',
        candidate_database='hrm_candidate_20260715',
        tenant_id='tenant-a',
        migration_plan=plan,
        source_tables=source_tables,
        target_tables=target_tables,
    )

    assert [reference.to_dict() for reference in references] == [
        {
            'source_table': 'course_hours',
            'source_column': 'video_key',
            'destination_key': (
                'tenants/tenant-a/courses/course-1/hour-1.mp4'
            ),
        },
        {
            'source_table': 'employees',
            'source_column': 'attachments',
            'destination_key': (
                'tenants/tenant-a/employees/id-card.pdf'
            ),
        },
        {
            'source_table': 'resumes',
            'source_column': 'file_url',
            'destination_key': (
                'tenants/tenant-a/resumes/candidate.pdf'
            ),
        },
    ]
    updates = [
        (sql, params)
        for sql, params in cursor.statements
        if sql.startswith('UPDATE')
    ]
    assert len(updates) == 3
    assert all('`tenant_id` = %s AND `id` = %s' in sql for sql, _ in updates)
    assert all('candidate.pdf' not in sql for sql, _ in updates)
    rewritten_values = [params[0] for _sql, params in updates]
    assert '/uploads/tenants/tenant-a/resumes/candidate.pdf' in rewritten_values
    assert 'tenants/tenant-a/courses/course-1/hour-1.mp4' in rewritten_values
    nested = next(value for value in rewritten_values if value.startswith('{'))
    assert json.loads(nested) == {
        'items': [
            {'url': '/uploads/tenants/tenant-a/employees/id-card.pdf'},
            {'page_url': '/uploads/hrm/profile'},
        ]
    }


def test_candidate_reference_hook_rejects_invalid_json_before_commit():
    cursor = FakeReferenceRewriteCursor(
        {('employees', 'attachments'): [('employee-1', '{invalid-json')]}
    )
    source = migration.TableMetadata(
        name='employees',
        columns=('id', 'attachments'),
        primary_key=('id',),
    )
    target = migration.TableMetadata(
        name='employees',
        columns=('id', 'attachments', 'tenant_id'),
        primary_key=('id',),
    )
    plan = migration.build_migration_plan((source,), (target,))

    with pytest.raises(MigrationSafetyError, match='JSON'):
        restore_cli.rewrite_candidate_file_references(
            cursor=cursor,
            stage_database='legacy_stage_20260715',
            candidate_database='hrm_candidate_20260715',
            tenant_id='tenant-a',
            migration_plan=plan,
            source_tables=(source,),
            target_tables=(target,),
        )

    assert not any(
        sql.startswith('UPDATE') for sql, _params in cursor.statements
    )


class FakeStageReferenceCursor:
    def __init__(self, rows_by_column):
        self.rows_by_column = rows_by_column
        self.rows = []
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=()):
        normalized = ' '.join(sql.split())
        self.statements.append((normalized, tuple(params)))
        table_match = re.search(r'`legacy_stage_20260715`\.`([^`]+)`', sql)
        if table_match is None:
            raise AssertionError(f'missing stage table: {sql}')
        selected = normalized.split(' FROM ', 1)[0]
        selected_columns = re.findall(r'`([^`]+)`', selected)
        self.rows = list(
            self.rows_by_column.get(
                (table_match.group(1), selected_columns[-1]),
                (),
            )
        )

    def fetchall(self):
        return list(self.rows)


class FakeStageReferenceConnection:
    def __init__(self, rows_by_column):
        self.cursor_instance = FakeStageReferenceCursor(rows_by_column)

    def cursor(self):
        return self.cursor_instance


def test_candidate_restore_cli_collects_stage_file_references_read_only():
    connection = FakeStageReferenceConnection(
        {
            ('resumes', 'file_url'): [
                ('/uploads/resumes/candidate.pdf',),
                ('https://cdn.example.test/external.pdf',),
            ],
            ('course_hours', 'video_key'): [
                ('courses/course-1/hour-1.mp4',),
            ],
        }
    )
    source_tables = (
        migration.TableMetadata(
            name='resumes',
            columns=('id', 'file_url'),
            primary_key=('id',),
        ),
        migration.TableMetadata(
            name='course_hours',
            columns=('id', 'video_key'),
            primary_key=('id',),
        ),
    )
    target_tables = tuple(
        migration.TableMetadata(
            name=table.name,
            columns=(*table.columns, 'tenant_id'),
            primary_key=table.primary_key,
        )
        for table in source_tables
    )
    plan = migration.build_migration_plan(source_tables, target_tables)

    references = restore_cli.collect_stage_file_references(
        connection=connection,
        stage_database='legacy_stage_20260715',
        candidate_database='hrm_candidate_20260715',
        tenant_id='tenant-a',
        migration_plan=plan,
        source_tables=source_tables,
        target_tables=target_tables,
    )

    assert [item.to_dict() for item in references] == [
        {
            'source_table': 'course_hours',
            'source_column': 'video_key',
            'destination_key': (
                'tenants/tenant-a/courses/course-1/hour-1.mp4'
            ),
        },
        {
            'source_table': 'resumes',
            'source_column': 'file_url',
            'destination_key': (
                'tenants/tenant-a/resumes/candidate.pdf'
            ),
        },
    ]
    assert all(
        sql.startswith('SELECT') and params == ()
        for sql, params in connection.cursor_instance.statements
    )


def test_candidate_restore_cli_blocks_missing_referenced_files_in_dry_run(
    tmp_path,
    monkeypatch,
):
    dump_path, env_path, report_path = _write_candidate_cli_inputs(tmp_path)
    connection = FakeCliConnection()
    source_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name', 'tenant_id'),
            primary_key=('id',),
        ),
    )
    _patch_candidate_cli_database_boundaries(
        monkeypatch,
        connection,
        source_tables,
        target_tables,
    )
    monkeypatch.setattr(
        restore_cli,
        'collect_stage_file_references',
        lambda **_kwargs: (
            restore_cli.FileReference(
                source_table='resumes',
                source_column='file_url',
                destination_key='tenants/tenant-1/resumes/missing.pdf',
            ),
        ),
    )

    with pytest.raises(MigrationSafetyError, match='missing referenced files'):
        restore_cli.main(
            _candidate_cli_argv(dump_path, env_path, report_path)
        )

    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['status'] == 'blocked'
    assert report['file_validation']['missing_keys'] == [
        'tenants/tenant-1/resumes/missing.pdf'
    ]
    assert connection.closed is True


def test_candidate_restore_cli_accepts_hash_verified_file_roots(tmp_path, monkeypatch):
    dump_path, env_path, report_path = _write_candidate_cli_inputs(tmp_path)
    file_manifest_report_path = tmp_path / 'file-manifest.json'
    source_root = tmp_path / 'legacy-uploads'
    (source_root / 'resumes').mkdir(parents=True)
    (source_root / 'resumes' / 'candidate.pdf').write_bytes(b'pdf')
    connection = FakeCliConnection()
    source_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name', 'tenant_id'),
            primary_key=('id',),
        ),
    )
    _patch_candidate_cli_database_boundaries(
        monkeypatch,
        connection,
        source_tables,
        target_tables,
    )
    monkeypatch.setattr(
        restore_cli,
        'collect_stage_file_references',
        lambda **_kwargs: (
            restore_cli.FileReference(
                source_table='resumes',
                source_column='file_url',
                destination_key='tenants/tenant-1/resumes/candidate.pdf',
            ),
        ),
    )

    result = restore_cli.main(
        _candidate_cli_argv(
            dump_path,
            env_path,
            report_path,
            '--file-root',
            str(source_root),
            '--file-manifest',
            str(file_manifest_report_path),
        )
    )

    assert result == 0
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['status'] == 'ready'
    assert report['file_validation'] == {
        'status': 'passed',
        'reference_count': 1,
        'unique_reference_count': 1,
        'missing_count': 0,
        'missing_keys': [],
    }
    assert report['file_manifest']['file_count'] == 1
    assert report['file_manifest']['total_bytes'] == 3
    assert re.fullmatch(
        r'[0-9a-f]{64}',
        report['file_manifest']['sha256'],
    )
    assert 'file_references' not in report
    report_text = report_path.read_text(encoding='utf-8')
    assert 'candidate.pdf' not in report_text
    assert hashlib.sha256(b'pdf').hexdigest() not in report_text
    detailed_manifest = json.loads(
        file_manifest_report_path.read_text(encoding='utf-8')
    )
    assert detailed_manifest['file_manifest'][0]['destination_key'].endswith(
        '/candidate.pdf'
    )
    assert detailed_manifest['file_manifest'][0]['sha256'] == (
        hashlib.sha256(b'pdf').hexdigest()
    )


def _validation_for_single_employee():
    return migration.build_migration_validation_report(
        source_schema='legacy_stage_20260715',
        candidate_schema='hrm_candidate_20260715',
        table_results=(
            migration.build_table_validation_result(
                source_schema='legacy_stage_20260715',
                candidate_schema='hrm_candidate_20260715',
                table='employees',
                source_rows=1,
                inserted_rows=1,
                candidate_tenant_rows=1,
                null_tenant_rows=0,
                orphan_rows=0,
                cross_tenant_rows=0,
            ),
        ),
    )


def _patch_file_prepare_cli(tmp_path, monkeypatch):
    dump_path, env_path, report_path = _write_candidate_cli_inputs(tmp_path)
    source_root = tmp_path / 'legacy-uploads'
    prepared_root = tmp_path / 'prepared-objects'
    (source_root / 'resumes').mkdir(parents=True)
    prepared_root.mkdir()
    (source_root / 'resumes' / 'candidate.pdf').write_bytes(b'pdf')
    connection = FakeCliConnection()
    source_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name'),
            primary_key=('id',),
        ),
    )
    target_tables = (
        migration.TableMetadata(
            name='employees',
            columns=('id', 'name', 'tenant_id'),
            primary_key=('id',),
        ),
    )
    _patch_candidate_cli_database_boundaries(
        monkeypatch,
        connection,
        source_tables,
        target_tables,
    )
    monkeypatch.setattr(
        restore_cli,
        'collect_stage_file_references',
        lambda **_kwargs: (
            restore_cli.FileReference(
                source_table='resumes',
                source_column='file_url',
                destination_key='tenants/tenant-1/resumes/candidate.pdf',
            ),
        ),
    )
    argv = _candidate_cli_argv(
        dump_path,
        env_path,
        report_path,
        '--file-root',
        str(source_root),
        '--prepared-files-root',
        str(prepared_root),
        '--file-manifest',
        str(tmp_path / 'file-manifest.json'),
        '--execute',
        '--confirm',
        restore_cli.CONFIRM_PHRASE,
    )
    return connection, report_path, prepared_root, argv


def test_candidate_restore_cli_execute_prepares_tenant_prefixed_files(
    tmp_path,
    monkeypatch,
):
    connection, report_path, prepared_root, argv = _patch_file_prepare_cli(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(
        restore_cli,
        'execute_transactional_migration',
        lambda *_args, **_kwargs: _validation_for_single_employee(),
    )

    assert restore_cli.main(argv) == 0

    prepared_file = (
        prepared_root
        / 'tenants'
        / 'tenant-1'
        / 'resumes'
        / 'candidate.pdf'
    )
    assert prepared_file.read_bytes() == b'pdf'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['file_copy'] == {
        'created_count': 1,
        'skipped_count': 0,
        'total_bytes': 3,
    }
    assert 'candidate.pdf' not in report_path.read_text(encoding='utf-8')
    assert connection.closed is True


def test_candidate_restore_cli_rolls_back_prepared_files_on_db_failure(
    tmp_path,
    monkeypatch,
):
    connection, report_path, prepared_root, argv = _patch_file_prepare_cli(
        tmp_path,
        monkeypatch,
    )

    def fail_migration(*_args, **_kwargs):
        raise MigrationSafetyError('simulated database validation failure')

    monkeypatch.setattr(
        restore_cli,
        'execute_transactional_migration',
        fail_migration,
    )

    with pytest.raises(MigrationSafetyError, match='database validation'):
        restore_cli.main(argv)

    assert not [path for path in prepared_root.rglob('*') if path.is_file()]
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['status'] == 'failed'
    assert report['file_copy_rolled_back_count'] == 1
    assert 'candidate.pdf' not in report_path.read_text(encoding='utf-8')
    assert connection.closed is True
