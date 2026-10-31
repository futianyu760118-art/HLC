"""Inspect or migrate a legacy HRM dump into a pre-created candidate.

This command never targets the configured live SaaS database. Operators must
pre-create a disposable staging schema and a full candidate clone, select one
existing destination tenant by slug, and preserve the previous live database
for rollback.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlsplit

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.legacy_tenant_files import (
    FileCopyReport,
    FileManifestEntry,
    FileReference,
    FileReferenceValidationReport,
    build_file_manifest,
    copy_file_manifest,
    merge_file_manifests,
    rollback_created_files,
    rewrite_nested_file_references,
    rewrite_upload_reference,
    validate_manifest_references,
)
from services.legacy_tenant_migration import (
    ForeignKeyMetadata,
    MigrationPlanItem,
    MigrationSafetyError,
    TableMetadata,
    build_migration_plan,
    execute_transactional_migration,
    quote_mysql_identifier,
    validate_candidate_database_names,
)


CONFIRM_PHRASE = 'MIGRATE_LEGACY_TO_CANDIDATE'
DEFAULT_DUMP = Path.home() / 'Desktop' / 'HRM' / 'mysql-20260611_030010.sql'
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = ROOT / '.env'
DEFAULT_REPORT = ROOT / 'artifacts' / 'db-restore' / 'legacy-candidate-report.json'
TENANT_SLUG_RE = re.compile(r'^[A-Za-z0-9_-]{1,80}$', re.ASCII)
SCALAR_UPLOAD_COLUMNS = frozenset(
    {
        'file_url',
        'feedback_file_url',
        'recording_url',
        'attachment_url',
        'cover_url',
        'image_url',
    }
)
OBJECT_KEY_COLUMNS = frozenset({'video_key'})
NESTED_FILE_JSON_COLUMNS = frozenset({'attachments', 'materials'})


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(
        encoding='utf-8',
        errors='ignore',
    ).splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def inspect_dump(path: Path) -> dict[str, list[str]]:
    """Return table and column names without parsing or logging row values."""

    tables: dict[str, list[str]] = {}
    current_table: str | None = None
    for raw_line in path.read_text(
        encoding='utf-8',
        errors='ignore',
    ).splitlines():
        line = raw_line.rstrip()
        if line.startswith('CREATE TABLE '):
            parts = line.split('`')
            current_table = parts[1] if len(parts) > 1 else None
            if current_table:
                tables[current_table] = []
            continue
        if current_table and line.startswith('  `'):
            parts = line.split('`')
            if len(parts) > 1:
                tables[current_table].append(parts[1])
            continue
        if current_table and line.startswith(')'):
            current_table = None
    return tables


def connect(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
):
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        charset='utf8mb4',
        autocommit=False,
        connect_timeout=5,
        read_timeout=60,
        write_timeout=60,
    )


def schema_exists(connection, database: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT COUNT(*) FROM information_schema.schemata '
            'WHERE schema_name = %s',
            (database,),
        )
        row = cursor.fetchone()
    count = row[0] if isinstance(row, (tuple, list)) and len(row) == 1 else None
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise MigrationSafetyError('schema existence query returned invalid data')
    return count == 1


def load_schema_metadata(
    connection,
    database: str,
) -> tuple[TableMetadata, ...]:
    """Load ordered base-table, key, and required-column metadata."""

    quote_mysql_identifier(database, label='metadata database name')
    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute(
            """
            SELECT
                columns.table_name AS table_name,
                columns.column_name AS column_name,
                columns.is_nullable AS is_nullable,
                columns.column_default AS column_default,
                columns.extra AS extra
            FROM information_schema.columns AS columns
            INNER JOIN information_schema.tables AS tables
              ON tables.table_schema = columns.table_schema
             AND tables.table_name = columns.table_name
             AND tables.table_type = 'BASE TABLE'
            WHERE columns.table_schema = %s
            ORDER BY columns.table_name, columns.ordinal_position
            """,
            (database,),
        )
        column_rows = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT
                table_name AS table_name,
                column_name AS column_name
            FROM information_schema.key_column_usage
            WHERE table_schema = %s AND constraint_name = 'PRIMARY'
            ORDER BY table_name, ordinal_position
            """,
            (database,),
        )
        primary_key_rows = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT
                table_name AS table_name,
                constraint_name AS constraint_name,
                column_name AS column_name,
                referenced_table_name AS referenced_table_name,
                referenced_column_name AS referenced_column_name
            FROM information_schema.key_column_usage
            WHERE table_schema = %s
              AND referenced_table_name IS NOT NULL
            ORDER BY table_name, constraint_name, ordinal_position
            """,
            (database,),
        )
        foreign_key_rows = list(cursor.fetchall())

    columns_by_table: dict[str, list[str]] = defaultdict(list)
    required_by_table: dict[str, list[str]] = defaultdict(list)
    for row in column_rows:
        table = str(row['table_name'])
        column = str(row['column_name'])
        columns_by_table[table].append(column)
        extra = str(row.get('extra') or '').casefold()
        if (
            str(row.get('is_nullable') or '').upper() == 'NO'
            and row.get('column_default') is None
            and 'auto_increment' not in extra
            and 'generated' not in extra
        ):
            required_by_table[table].append(column)

    primary_keys_by_table: dict[str, list[str]] = defaultdict(list)
    for row in primary_key_rows:
        primary_keys_by_table[str(row['table_name'])].append(
            str(row['column_name'])
        )

    grouped_foreign_keys: dict[
        tuple[str, str, str],
        tuple[list[str], list[str]],
    ] = {}
    for row in foreign_key_rows:
        group_key = (
            str(row['table_name']),
            str(row['constraint_name']),
            str(row['referenced_table_name']),
        )
        child_columns, parent_columns = grouped_foreign_keys.setdefault(
            group_key,
            ([], []),
        )
        child_columns.append(str(row['column_name']))
        parent_columns.append(str(row['referenced_column_name']))

    foreign_keys_by_table: dict[str, list[ForeignKeyMetadata]] = defaultdict(list)
    for (
        table,
        _constraint,
        referenced_table,
    ), (child_columns, parent_columns) in sorted(grouped_foreign_keys.items()):
        foreign_keys_by_table[table].append(
            ForeignKeyMetadata(
                columns=tuple(child_columns),
                referenced_table=referenced_table,
                referenced_columns=tuple(parent_columns),
            )
        )

    return tuple(
        TableMetadata(
            name=table,
            columns=tuple(columns),
            primary_key=tuple(primary_keys_by_table[table]),
            required_columns_without_default=tuple(required_by_table[table]),
            foreign_keys=tuple(foreign_keys_by_table[table]),
        )
        for table, columns in sorted(columns_by_table.items())
    )


def validate_dump_stage_shape(
    dump_tables: dict[str, list[str]],
    stage_tables: Iterable[TableMetadata],
) -> None:
    """Require the immutable dump declaration to match the loaded stage."""

    stage_by_name = {table.name: table for table in stage_tables}
    dump_names = set(dump_tables)
    stage_names = set(stage_by_name)
    if not dump_names or dump_names != stage_names:
        raise MigrationSafetyError('dump and stage shape mismatch')
    for table in sorted(dump_names):
        if tuple(dump_tables[table]) != stage_by_name[table].columns:
            raise MigrationSafetyError(
                f'dump and stage shape mismatch for table: {table}'
            )


def resolve_destination_tenant_id(
    connection,
    candidate_database: str,
    tenant_slug: str,
) -> object:
    quoted_candidate = quote_mysql_identifier(
        candidate_database,
        label='candidate database name',
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT `id` FROM {quoted_candidate}.`tenants` '
            'WHERE `slug` = %s',
            (tenant_slug,),
        )
        rows = list(cursor.fetchall())
    if len(rows) != 1:
        raise MigrationSafetyError(
            'tenant slug must resolve to exactly one candidate tenant'
        )
    row = rows[0]
    tenant_id = row[0] if isinstance(row, (tuple, list)) and len(row) == 1 else None
    if (
        isinstance(tenant_id, bool)
        or not isinstance(tenant_id, (str, int))
        or (isinstance(tenant_id, str) and not tenant_id.strip())
    ):
        raise MigrationSafetyError('candidate tenant id is invalid')
    return tenant_id


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _plan_item_to_dict(item: MigrationPlanItem) -> dict[str, object]:
    return {
        'table': item.table,
        'status': item.status,
        'columns': list(item.columns),
        'reason': item.reason,
        'source_only_columns': list(item.source_only_columns),
        'unmapped_required_columns': list(item.unmapped_required_columns),
        'source_primary_key': list(item.source_primary_key),
        'target_primary_key': list(item.target_primary_key),
    }


def _file_manifest_summary(
    manifest: Iterable[FileManifestEntry],
) -> dict[str, object]:
    """Return integrity evidence without exposing attachment paths or hashes."""

    entries = tuple(manifest)
    digest = hashlib.sha256()
    total_bytes = 0
    for entry in entries:
        canonical_entry = json.dumps(
            entry.to_dict(),
            ensure_ascii=True,
            separators=(',', ':'),
            sort_keys=True,
        ).encode('utf-8')
        digest.update(len(canonical_entry).to_bytes(8, 'big'))
        digest.update(canonical_entry)
        total_bytes += entry.size_bytes
    return {
        'file_count': len(entries),
        'total_bytes': total_bytes,
        'sha256': digest.hexdigest(),
    }


def _file_validation_summary(
    validation: FileReferenceValidationReport,
) -> dict[str, object]:
    """Keep only actionable missing keys in the operator-facing report."""

    return {
        'status': validation.status,
        'reference_count': validation.reference_count,
        'unique_reference_count': len(validation.referenced_keys),
        'missing_count': len(validation.missing_keys),
        'missing_keys': list(validation.missing_keys),
    }


def _file_copy_summary(copy_report: FileCopyReport) -> dict[str, int]:
    """Summarize prepared objects without exposing destination keys."""

    return {
        'created_count': len(copy_report.created_keys),
        'skipped_count': len(copy_report.skipped_keys),
        'total_bytes': copy_report.total_bytes,
    }


def _write_detailed_file_manifest(
    path: Path,
    *,
    manifest: Iterable[FileManifestEntry],
    references: Iterable[FileReference],
    validation: FileReferenceValidationReport,
) -> None:
    """Write explicitly requested, operator-controlled file evidence."""

    _write_json_report(
        path,
        {
            'file_manifest': [entry.to_dict() for entry in manifest],
            'file_references': [reference.to_dict() for reference in references],
            'file_validation': validation.to_dict(),
        },
    )


def _write_json_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f'.{path.name}.',
        suffix='.tmp',
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, 'w', encoding='utf-8') as output:
            file_descriptor = -1
            json.dump(
                report,
                output,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def _collect_tenant_destination_keys(value: object) -> tuple[str, ...]:
    keys: set[str] = set()

    def visit(current: object) -> None:
        if isinstance(current, dict):
            for child in current.values():
                visit(child)
            return
        if isinstance(current, list):
            for child in current:
                visit(child)
            return
        if not isinstance(current, str):
            return
        if current.startswith('/uploads/tenants/'):
            path = urlsplit(current).path
            keys.add(path[len('/uploads/'):])
        elif current.startswith('tenants/'):
            keys.add(current)

    visit(value)
    return tuple(sorted(keys))


def _rewrite_candidate_column_value(
    value: object,
    *,
    column: str,
    tenant_id: str,
) -> tuple[object, object, bool]:
    if column in NESTED_FILE_JSON_COLUMNS:
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (TypeError, ValueError) as exc:
                raise MigrationSafetyError(
                    'candidate file reference JSON is invalid'
                ) from exc
        elif isinstance(value, (dict, list)):
            decoded = value
        else:
            raise MigrationSafetyError(
                'candidate file reference JSON has an invalid type'
            )
        rewritten = rewrite_nested_file_references(decoded, tenant_id)
        return (
            json.dumps(
                rewritten,
                ensure_ascii=False,
                separators=(',', ':'),
            ),
            rewritten,
            rewritten != decoded,
        )

    if not isinstance(value, str):
        raise MigrationSafetyError(
            'candidate scalar file reference has an invalid type'
        )
    if column in OBJECT_KEY_COLUMNS:
        if value.startswith('/uploads/'):
            rewritten_upload = rewrite_upload_reference(value, tenant_id)
            rewritten = urlsplit(rewritten_upload).path[len('/uploads/'):]
        else:
            rewritten = rewrite_upload_reference(
                value,
                tenant_id,
                object_key=True,
            )
    else:
        rewritten = rewrite_upload_reference(value, tenant_id)
    return rewritten, rewritten, rewritten != value


def rewrite_candidate_file_references(
    *,
    cursor,
    stage_database: str,
    candidate_database: str,
    tenant_id: object,
    migration_plan: Iterable[MigrationPlanItem],
    source_tables: Iterable[TableMetadata],
    target_tables: Iterable[TableMetadata],
) -> tuple[FileReference, ...]:
    """Rewrite candidate file fields inside the migration transaction."""

    validate_candidate_database_names(
        stage_database=stage_database,
        candidate_database=candidate_database,
    )
    safe_tenant_id = str(tenant_id)
    plan_items = tuple(migration_plan)
    source_items = tuple(source_tables)
    target_items = tuple(target_tables)
    if plan_items != build_migration_plan(source_items, target_items):
        raise MigrationSafetyError(
            'file reference rewrite plan does not match schema metadata'
        )
    target_by_name = {table.name: table for table in target_items}
    quoted_candidate = quote_mysql_identifier(
        candidate_database,
        label='candidate database name',
    )
    references: set[FileReference] = set()

    for item in plan_items:
        target = target_by_name[item.table]
        file_columns = tuple(
            column
            for column in item.columns
            if column in SCALAR_UPLOAD_COLUMNS
            or column in OBJECT_KEY_COLUMNS
            or column in NESTED_FILE_JSON_COLUMNS
        )
        if not file_columns:
            continue
        quoted_table = quote_mysql_identifier(item.table, label='table name')
        quoted_primary_key = tuple(
            quote_mysql_identifier(column, label='primary key column')
            for column in target.primary_key
        )
        if not quoted_primary_key:
            raise MigrationSafetyError(
                'file reference rewrite requires a primary key'
            )

        for column in file_columns:
            quoted_column = quote_mysql_identifier(
                column,
                label='file reference column',
            )
            projection = ', '.join((*quoted_primary_key, quoted_column))
            order_by = ', '.join(quoted_primary_key)
            cursor.execute(
                f'SELECT {projection} FROM '
                f'{quoted_candidate}.{quoted_table} '
                'WHERE `tenant_id` = %s '
                f'AND {quoted_column} IS NOT NULL ORDER BY {order_by}',
                (tenant_id,),
            )
            rows = list(cursor.fetchall())
            for row in rows:
                if not isinstance(row, (tuple, list)) or len(row) != (
                    len(target.primary_key) + 1
                ):
                    raise MigrationSafetyError(
                        'file reference query returned an invalid row shape'
                    )
                primary_key_values = tuple(row[:-1])
                original_value = row[-1]
                update_value, reference_value, changed = (
                    _rewrite_candidate_column_value(
                        original_value,
                        column=column,
                        tenant_id=safe_tenant_id,
                    )
                )
                for destination_key in _collect_tenant_destination_keys(
                    reference_value
                ):
                    references.add(
                        FileReference(
                            source_table=item.table,
                            source_column=column,
                            destination_key=destination_key,
                        )
                    )
                if not changed:
                    continue

                primary_key_predicate = ' AND '.join(
                    f'{quoted_key} = %s' for quoted_key in quoted_primary_key
                )
                cursor.execute(
                    f'UPDATE {quoted_candidate}.{quoted_table} '
                    f'SET {quoted_column} = %s '
                    'WHERE `tenant_id` = %s AND '
                    f'{primary_key_predicate}',
                    (update_value, tenant_id, *primary_key_values),
                )
                if cursor.rowcount != 1:
                    raise MigrationSafetyError(
                        'file reference update affected an unexpected row count'
                    )

    return tuple(
        sorted(
            references,
            key=lambda item: (
                item.source_table,
                item.source_column,
                item.destination_key,
            ),
        )
    )


def collect_stage_file_references(
    *,
    connection,
    stage_database: str,
    candidate_database: str,
    tenant_id: object,
    migration_plan: Iterable[MigrationPlanItem],
    source_tables: Iterable[TableMetadata],
    target_tables: Iterable[TableMetadata],
) -> tuple[FileReference, ...]:
    """Preview rewritten file keys from the stage without modifying rows."""

    validate_candidate_database_names(
        stage_database=stage_database,
        candidate_database=candidate_database,
    )
    safe_tenant_id = str(tenant_id)
    plan_items = tuple(migration_plan)
    source_items = tuple(source_tables)
    target_items = tuple(target_tables)
    if plan_items != build_migration_plan(source_items, target_items):
        raise MigrationSafetyError(
            'stage file reference plan does not match schema metadata'
        )
    source_by_name = {table.name: table for table in source_items}
    quoted_stage = quote_mysql_identifier(
        stage_database,
        label='stage database name',
    )
    references: set[FileReference] = set()

    with connection.cursor() as cursor:
        for item in plan_items:
            source = source_by_name[item.table]
            file_columns = tuple(
                column
                for column in item.columns
                if column in SCALAR_UPLOAD_COLUMNS
                or column in OBJECT_KEY_COLUMNS
                or column in NESTED_FILE_JSON_COLUMNS
            )
            if not file_columns:
                continue
            quoted_table = quote_mysql_identifier(
                item.table,
                label='table name',
            )
            order_by = ', '.join(
                quote_mysql_identifier(column, label='primary key column')
                for column in source.primary_key
            )
            if not order_by:
                raise MigrationSafetyError(
                    'stage file reference scan requires a primary key'
                )

            for column in file_columns:
                quoted_column = quote_mysql_identifier(
                    column,
                    label='file reference column',
                )
                cursor.execute(
                    f'SELECT {quoted_column} FROM '
                    f'{quoted_stage}.{quoted_table} '
                    f'WHERE {quoted_column} IS NOT NULL '
                    f'ORDER BY {order_by}'
                )
                for row in cursor.fetchall():
                    if not isinstance(row, (tuple, list)) or len(row) != 1:
                        raise MigrationSafetyError(
                            'stage file reference query returned invalid data'
                        )
                    _update_value, reference_value, _changed = (
                        _rewrite_candidate_column_value(
                            row[0],
                            column=column,
                            tenant_id=safe_tenant_id,
                        )
                    )
                    for destination_key in _collect_tenant_destination_keys(
                        reference_value
                    ):
                        references.add(
                            FileReference(
                                source_table=item.table,
                                source_column=column,
                                destination_key=destination_key,
                            )
                        )

    return tuple(
        sorted(
            references,
            key=lambda item: (
                item.source_table,
                item.source_column,
                item.destination_key,
            ),
        )
    )


def prepare_file_roots(
    *,
    source_roots: Sequence[Path],
    manifests: Sequence[tuple],
    merged_manifest: tuple,
    destination_root: Path,
) -> FileCopyReport:
    """Copy multiple verified exports and roll back earlier roots on failure."""

    if len(source_roots) != len(manifests):
        raise MigrationSafetyError(
            'file roots and manifests must have matching lengths'
        )
    created_keys: set[str] = set()
    skipped_keys: set[str] = set()
    total_bytes = 0
    try:
        for source_root, manifest in zip(source_roots, manifests):
            partial = copy_file_manifest(
                manifest,
                source_root=source_root,
                destination_root=destination_root,
            )
            for key in partial.created_keys:
                created_keys.add(key)
                skipped_keys.discard(key)
            for key in partial.skipped_keys:
                if key not in created_keys:
                    skipped_keys.add(key)
            total_bytes += partial.total_bytes
    except Exception as copy_error:
        if created_keys:
            rollback_created_files(
                merged_manifest,
                FileCopyReport(
                    created_keys=tuple(sorted(created_keys)),
                    skipped_keys=tuple(sorted(skipped_keys)),
                    total_bytes=total_bytes,
                ),
                destination_root=destination_root,
            )
        raise MigrationSafetyError(
            'file preparation failed; created files were rolled back'
        ) from copy_error

    return FileCopyReport(
        created_keys=tuple(sorted(created_keys)),
        skipped_keys=tuple(sorted(skipped_keys)),
        total_bytes=total_bytes,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', type=Path, default=DEFAULT_ENV)
    parser.add_argument('--dump', type=Path, default=DEFAULT_DUMP)
    parser.add_argument('--host', help='migration MySQL host override')
    parser.add_argument('--port', type=int, help='migration MySQL port override')
    parser.add_argument('--user', help='migration MySQL user override')
    parser.add_argument(
        '--password-env',
        default='DB_PASSWORD',
        help='environment variable containing the migration DB password',
    )
    parser.add_argument('--stage-database')
    parser.add_argument('--candidate-database')
    parser.add_argument('--tenant-slug')
    parser.add_argument('--report', type=Path)
    parser.add_argument(
        '--file-manifest',
        type=Path,
        help=(
            'explicit path for detailed file keys/hashes; omitted from the '
            'normal report by default'
        ),
    )
    parser.add_argument(
        '--file-root',
        action='append',
        type=Path,
        default=[],
        help='immutable local-upload or object-export root; repeatable',
    )
    parser.add_argument(
        '--prepared-files-root',
        type=Path,
        help='existing destination root for the tenant-prefixed file package',
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='migrate the preloaded disposable stage into the candidate',
    )
    parser.add_argument(
        '--confirm',
        default='',
        help=f'required phrase for execute: {CONFIRM_PHRASE}',
    )
    parser.add_argument(
        '--inspect-dump-only',
        action='store_true',
        help='only print dump table/column summary',
    )
    return parser.parse_args(argv)


def _require_operation_inputs(args: argparse.Namespace) -> None:
    for option, value in (
        ('--stage-database', args.stage_database),
        ('--candidate-database', args.candidate_database),
        ('--tenant-slug', args.tenant_slug),
        ('--report', args.report),
    ):
        if value is None or (isinstance(value, str) and not value.strip()):
            raise MigrationSafetyError(
                f'candidate migration requires {option}'
            )


def _validate_preconnect_policy(
    args: argparse.Namespace,
    *,
    live_database: str | None,
) -> None:
    _require_operation_inputs(args)
    if not live_database:
        raise MigrationSafetyError(
            'configured live database name is required for isolation proof'
        )
    validate_candidate_database_names(
        stage_database=args.stage_database,
        candidate_database=args.candidate_database,
    )
    if args.candidate_database.casefold() == live_database.casefold():
        raise MigrationSafetyError(
            'candidate database must differ from the configured live database'
        )
    if TENANT_SLUG_RE.fullmatch(args.tenant_slug) is None:
        raise MigrationSafetyError('tenant slug is not a safe explicit slug')
    if args.file_manifest is not None:
        if args.file_manifest.resolve() == args.report.resolve():
            raise MigrationSafetyError(
                '--file-manifest must differ from --report'
            )
    if args.execute and args.confirm != CONFIRM_PHRASE:
        raise MigrationSafetyError(
            f'execute requires --confirm {CONFIRM_PHRASE}'
        )


def _print_dump_summary(dump_path: Path) -> None:
    tables = inspect_dump(dump_path)
    print(f'dump={dump_path}')
    print(f'table_count={len(tables)}')
    for table, columns in tables.items():
        print(f'{table}: {len(columns)} columns')


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    dump_path = args.dump.resolve()
    if not dump_path.is_file():
        raise MigrationSafetyError(f'legacy dump not found: {dump_path}')

    if args.inspect_dump_only:
        _print_dump_summary(dump_path)
        return 0

    env = read_env(args.env)
    live_database = (
        env.get('DB_NAME')
        or env.get('MYSQL_DATABASE')
        or os.getenv('DB_NAME')
        or os.getenv('MYSQL_DATABASE')
    )
    _validate_preconnect_policy(args, live_database=live_database)

    host = (
        args.host
        or env.get('DB_HOST')
        or os.getenv('DB_HOST')
        or '127.0.0.1'
    )
    port = args.port or int(
        env.get('DB_PORT') or os.getenv('DB_PORT') or 3306
    )
    user = (
        args.user
        or env.get('DB_USER')
        or env.get('MYSQL_USER')
        or os.getenv('DB_USER')
        or os.getenv('MYSQL_USER')
    )
    password = (
        os.getenv(args.password_env)
        or env.get('DB_PASSWORD')
        or env.get('MYSQL_PASSWORD')
    )
    if not user or not password:
        raise MigrationSafetyError(
            'migration DB user/password configuration is missing'
        )

    connection = connect(
        host=host,
        port=port,
        user=user,
        password=password,
    )
    try:
        if not schema_exists(connection, args.stage_database):
            raise MigrationSafetyError(
                'pre-created stage database does not exist'
            )
        if not schema_exists(connection, args.candidate_database):
            raise MigrationSafetyError(
                'pre-created candidate database does not exist'
            )

        source_tables = load_schema_metadata(
            connection,
            args.stage_database,
        )
        target_tables = load_schema_metadata(
            connection,
            args.candidate_database,
        )
        if not source_tables:
            raise MigrationSafetyError(
                'pre-created stage database has no loaded base tables'
            )
        if not target_tables:
            raise MigrationSafetyError(
                'pre-created candidate database has no base tables'
            )

        dump_tables = inspect_dump(dump_path)
        validate_dump_stage_shape(dump_tables, source_tables)
        migration_plan = build_migration_plan(source_tables, target_tables)
        if not migration_plan:
            raise MigrationSafetyError('candidate migration plan is empty')

        tenant_id = resolve_destination_tenant_id(
            connection,
            args.candidate_database,
            args.tenant_slug,
        )
        stage_file_references = collect_stage_file_references(
            connection=connection,
            stage_database=args.stage_database,
            candidate_database=args.candidate_database,
            tenant_id=tenant_id,
            migration_plan=migration_plan,
            source_tables=source_tables,
            target_tables=target_tables,
        )
        file_manifests = tuple(
            build_file_manifest(root, str(tenant_id))
            for root in args.file_root
        )
        file_manifest = merge_file_manifests(*file_manifests)
        file_validation = validate_manifest_references(
            file_manifest,
            stage_file_references,
        )
        blocked_tables = [
            item.table for item in migration_plan if item.status == 'blocked'
        ]
        report: dict[str, object] = {
            'status': (
                'blocked'
                if blocked_tables or file_validation.status == 'failed'
                else 'ready'
            ),
            'dry_run': not args.execute,
            'stage_database': args.stage_database,
            'candidate_database': args.candidate_database,
            'tenant_slug': args.tenant_slug,
            'dump': {
                'sha256': _sha256_file(dump_path),
                'table_count': len(dump_tables),
            },
            'stage_table_count': len(source_tables),
            'candidate_table_count': len(target_tables),
            'plan': [_plan_item_to_dict(item) for item in migration_plan],
            'blocked_tables': blocked_tables,
            'file_manifest': _file_manifest_summary(file_manifest),
            'file_validation': _file_validation_summary(file_validation),
        }
        if args.file_manifest is not None:
            _write_detailed_file_manifest(
                args.file_manifest,
                manifest=file_manifest,
                references=stage_file_references,
                validation=file_validation,
            )
        if blocked_tables:
            _write_json_report(args.report, report)
            raise MigrationSafetyError(
                'candidate migration plan contains blocked tables: '
                + ', '.join(blocked_tables)
            )
        if file_validation.status == 'failed':
            _write_json_report(args.report, report)
            raise MigrationSafetyError(
                'candidate migration has missing referenced files'
            )
        if args.execute and file_manifest and args.prepared_files_root is None:
            report['status'] = 'blocked'
            _write_json_report(args.report, report)
            raise MigrationSafetyError(
                'execute with files requires --prepared-files-root'
            )
        if args.execute and file_manifest and args.file_manifest is None:
            report['status'] = 'blocked'
            _write_json_report(args.report, report)
            raise MigrationSafetyError(
                'execute with files requires --file-manifest'
            )

        if not args.execute:
            _write_json_report(args.report, report)
            print(f'dry_run=true report={args.report.resolve()}')
            return 0

        if file_manifest:
            try:
                file_copy_report = prepare_file_roots(
                    source_roots=tuple(args.file_root),
                    manifests=file_manifests,
                    merged_manifest=file_manifest,
                    destination_root=args.prepared_files_root,
                )
            except Exception:
                report['status'] = 'failed'
                report['error_category'] = 'file_preparation_error'
                _write_json_report(args.report, report)
                raise
        else:
            file_copy_report = FileCopyReport(
                created_keys=(),
                skipped_keys=(),
                total_bytes=0,
            )
        report['file_copy'] = _file_copy_summary(file_copy_report)

        def rewrite_file_references_hook(**hook_args) -> None:
            references = rewrite_candidate_file_references(**hook_args)
            if references != stage_file_references:
                raise MigrationSafetyError(
                    'candidate file references differ from stage preview'
                )

        try:
            validation = execute_transactional_migration(
                connection,
                stage_database=args.stage_database,
                candidate_database=args.candidate_database,
                tenant_id=tenant_id,
                migration_plan=migration_plan,
                source_tables=source_tables,
                target_tables=target_tables,
                post_copy_hook=rewrite_file_references_hook,
            )
        except Exception as migration_error:
            report['status'] = 'failed'
            report['error_category'] = (
                'migration_safety_error'
                if isinstance(migration_error, MigrationSafetyError)
                else 'candidate_execution_error'
            )
            if file_copy_report.created_keys:
                try:
                    removed_keys = rollback_created_files(
                        file_manifest,
                        file_copy_report,
                        destination_root=args.prepared_files_root,
                    )
                except Exception as rollback_error:
                    report['error_category'] = 'file_rollback_error'
                    _write_json_report(args.report, report)
                    raise MigrationSafetyError(
                        'database migration failed and prepared file rollback '
                        'did not complete'
                    ) from rollback_error
                report['file_copy_rolled_back_count'] = len(removed_keys)
            _write_json_report(args.report, report)
            raise
        report['status'] = 'passed'
        report['validation'] = validation.to_dict()
        _write_json_report(args.report, report)
        print(f'migration_complete=true report={args.report.resolve()}')
        return 0
    finally:
        connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
