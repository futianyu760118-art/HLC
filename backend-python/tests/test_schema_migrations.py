from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from schema_migrations import (
    SQLITE_COLUMNS,
    _add_column_mysql,
    _add_column_sqlite,
    _fix_assistant_evaluation_runs_table,
    _fix_tenant_unique_indexes,
    _ensure_employee_oa_indexes,
    _ensure_enterprise_application_indexes,
    schema_migration_lock_for_connection,
)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _DuplicateColumnConn:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        if 'information_schema.COLUMNS' in str(statement):
            return _ScalarResult(0)
        raise OperationalError(
            statement=str(statement),
            params=None,
            orig=Exception("(1060, \"duplicate column name 'reopen_reason'\")"),
        )


def test_add_column_mysql_ignores_duplicate_column_errors_from_racing_workers():
    conn = _DuplicateColumnConn()

    _add_column_mysql(conn, 'feedbacks', 'reopen_reason', 'TEXT NULL')

    assert any('ALTER TABLE' in statement for statement in conn.statements)


def test_existing_sqlite_platform_operation_logs_gain_structured_audit_columns():
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text(
            'CREATE TABLE platform_operation_logs '
            '(id TEXT PRIMARY KEY, action TEXT NOT NULL, detail JSON)'
        ))
        for column_name, column_sql in SQLITE_COLUMNS['platform_operation_logs']:
            _add_column_sqlite(conn, 'platform_operation_logs', column_name, column_sql)

        columns = {
            row[1]: {'not_null': bool(row[3]), 'default': row[4]}
            for row in conn.execute(text('PRAGMA table_info(platform_operation_logs)')).fetchall()
        }

    assert {'result', 'request_id', 'error_code'} <= set(columns)
    assert columns['result'] == {'not_null': True, 'default': "'success'"}


def test_existing_sqlite_employee_table_gains_separate_oa_workcode_column():
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE employees (id TEXT PRIMARY KEY, employee_no TEXT)'))
        for column_name, column_sql in SQLITE_COLUMNS['employees']:
            _add_column_sqlite(conn, 'employees', column_name, column_sql)

        columns = {
            row[1]
            for row in conn.execute(text('PRAGMA table_info(employees)')).fetchall()
        }

    assert 'oa_workcode' in columns


def test_existing_sqlite_performance_tables_gain_tenant_and_review_columns():
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE performance_reviews (id TEXT PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE performance_cycles (id TEXT PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE performance_templates (id TEXT PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE employees (id TEXT PRIMARY KEY, employee_no TEXT)'))
        for table in ('performance_reviews', 'performance_cycles', 'performance_templates', 'employees'):
            for column_name, column_sql in SQLITE_COLUMNS[table]:
                _add_column_sqlite(conn, table, column_name, column_sql)

        review_cols = {
            row[1] for row in conn.execute(text('PRAGMA table_info(performance_reviews)')).fetchall()
        }
        employee_cols = {
            row[1] for row in conn.execute(text('PRAGMA table_info(employees)')).fetchall()
        }

    assert {
        'tenant_id', 'manager_id', 'auto_score',
        'self_submitted_at', 'manager_scored_at', 'confirmed_at',
    } <= review_cols
    assert {'employee_type', 'performance_participant'} <= employee_cols


class _ColumnExistsConn:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        if 'information_schema.COLUMNS' in str(statement):
            return _ScalarResult(1)
        return _ScalarResult(0)


def test_assistant_evaluation_retest_reference_accepts_request_ids():
    conn = _ColumnExistsConn()

    _fix_assistant_evaluation_runs_table(conn, 'mysql')

    assert any('MODIFY COLUMN `retest_of` VARCHAR(64) NULL' in statement for statement in conn.statements)


class _RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def scalar(self):
        return 1


class _IndexConn:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if 'information_schema.STATISTICS' in sql:
            if params['table'] == 'users':
                return _RowsResult([
                    ('PRIMARY', 'id', 1, 0),
                    ('email', 'email', 1, 0),
                ])
            if params['table'] == 'roles':
                return _RowsResult([
                    ('PRIMARY', 'id', 1, 0),
                    ('code', 'code', 1, 0),
                ])
        return _RowsResult([])


def test_mysql_unique_indexes_are_scoped_by_tenant():
    conn = _IndexConn()

    _fix_tenant_unique_indexes(conn, 'mysql')

    sql = '\n'.join(conn.statements)
    assert 'DROP INDEX `email`' in sql
    assert 'ADD CONSTRAINT `uq_users_tenant_email` UNIQUE (`tenant_id`, `email`)' in sql
    assert 'DROP INDEX `code`' in sql
    assert 'ADD CONSTRAINT `uq_roles_tenant_code` UNIQUE (`tenant_id`, `code`)' in sql


class _EmployeeOaIndexConn:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if 'information_schema.TABLES' in sql:
            return _ScalarResult(1)
        if 'information_schema.STATISTICS' in sql:
            return _RowsResult([('PRIMARY', 'id', 1, 0)])
        return _RowsResult([])


def test_existing_mysql_employee_table_gains_oa_identity_indexes():
    conn = _EmployeeOaIndexConn()

    _ensure_employee_oa_indexes(conn, 'mysql')

    sql = '\n'.join(conn.statements)
    assert (
        'ADD UNIQUE INDEX `uq_employees_tenant_oa_person_id` '
        '(`tenant_id`, `oa_person_id`)' in sql
    )
    assert 'ADD INDEX `ix_employees_oa_login_id` (`oa_login_id`)' in sql
    assert 'ADD INDEX `ix_employees_source_system` (`source_system`)' in sql


class _WrongEnterpriseIndexConn:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if 'information_schema.TABLES' in sql:
            return _ScalarResult(1)
        if 'information_schema.STATISTICS' in sql:
            return _RowsResult([
                ('PRIMARY', 'id', 1, 0),
                ('idx_enterprise_application_status_created', 'status', 1, 1),
            ])
        return _RowsResult([])


def test_mysql_wrong_shape_enterprise_index_is_repaired_instead_of_silently_skipped():
    conn = _WrongEnterpriseIndexConn()

    _ensure_enterprise_application_indexes(conn, 'mysql')

    sql = '\n'.join(conn.statements)
    assert 'DROP INDEX `idx_enterprise_application_status_created`' in sql
    assert (
        'ADD INDEX `idx_enterprise_application_status_created` (`status`, `created_at`)' in sql
    )


class _EnterpriseForeignKeyConn:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if 'information_schema.TABLES' in sql:
            return _ScalarResult(1)
        if 'information_schema.KEY_COLUMN_USAGE' in sql:
            return _RowsResult([])
        return _RowsResult([])


def test_mysql_existing_application_table_gains_owner_and_converted_tenant_foreign_keys():
    from schema_migrations import _ensure_enterprise_application_foreign_keys

    conn = _EnterpriseForeignKeyConn()

    _ensure_enterprise_application_foreign_keys(conn, 'mysql')

    sql = '\n'.join(conn.statements)
    assert (
        'FOREIGN KEY (`owner_user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL' in sql
    )
    assert (
        'FOREIGN KEY (`converted_tenant_id`) REFERENCES `tenants` (`id`) ON DELETE SET NULL' in sql
    )


class _WrongEnterpriseForeignKeyConn(_EnterpriseForeignKeyConn):
    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if 'information_schema.TABLES' in sql:
            return _ScalarResult(1)
        if 'information_schema.KEY_COLUMN_USAGE' in sql:
            return _RowsResult([
                ('legacy_owner_fk', 'owner_user_id', 'users', 'id', 'CASCADE'),
                ('legacy_tenant_fk', 'converted_tenant_id', 'tenants', 'id', 'RESTRICT'),
            ])
        return _RowsResult([])


def test_mysql_wrong_application_foreign_keys_are_replaced_by_set_null_constraints():
    from schema_migrations import _ensure_enterprise_application_foreign_keys

    conn = _WrongEnterpriseForeignKeyConn()

    _ensure_enterprise_application_foreign_keys(conn, 'mysql')

    sql = '\n'.join(conn.statements)
    assert 'DROP FOREIGN KEY `legacy_owner_fk`' in sql
    assert 'DROP FOREIGN KEY `legacy_tenant_fk`' in sql
    assert (
        'FOREIGN KEY (`owner_user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL' in sql
    )
    assert (
        'FOREIGN KEY (`converted_tenant_id`) REFERENCES `tenants` (`id`) ON DELETE SET NULL' in sql
    )


class _LockConn:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if 'GET_LOCK' in sql:
            return _ScalarResult(1)
        return _ScalarResult(1)


def test_mysql_schema_work_is_serialized_with_advisory_lock():
    conn = _LockConn()

    with schema_migration_lock_for_connection(conn, 'mysql'):
        conn.statements.append('MIGRATION_BODY')

    assert 'GET_LOCK' in conn.statements[0]
    assert conn.statements[-1].find('RELEASE_LOCK') >= 0


def test_bootstrap_sql_uses_compose_selected_database_and_tenant_email_key():
    init_sql = Path(__file__).resolve().parents[2].joinpath('init.sql').read_text(encoding='utf-8')

    assert 'USE hengpintong_saas' not in init_sql
    assert 'email VARCHAR(255) UNIQUE' not in init_sql
    assert 'UNIQUE KEY uq_users_tenant_email (tenant_id, email)' in init_sql
