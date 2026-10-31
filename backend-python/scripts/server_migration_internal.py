"""Fixed helper commands run only inside migration/backend containers."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ops.legacy_snapshot import export_minio_objects
from ops.operation_common import write_atomic_json
from ops.server_internal import (
    bootstrap_candidate_controls_from_profile,
    bootstrap_candidate_from_profile,
    delete_restore_proof_bucket,
    import_minio_tree,
    minio_client_from_environment,
    remove_candidate_admin,
    validate_candidate_runtime,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)

    export = commands.add_parser('minio-export')
    export.add_argument('--bucket', required=True)
    export.add_argument('--output-root', type=Path, required=True)
    export.add_argument('--replace-changed', action='store_true')
    export.add_argument('--prune', action='store_true')

    import_command = commands.add_parser('minio-import')
    import_command.add_argument('--bucket', required=True)
    import_command.add_argument('--source-root', type=Path, required=True)
    import_command.add_argument('--report', type=Path, required=True)

    delete = commands.add_parser('minio-delete-bucket')
    delete.add_argument('--bucket', required=True)

    bootstrap = commands.add_parser('bootstrap-candidate')
    bootstrap.add_argument('--candidate-database', required=True)
    bootstrap.add_argument('--active-database', required=True)
    bootstrap.add_argument('--snapshot-id', required=True)
    bootstrap.add_argument('--tenant-profile', type=Path, required=True)
    bootstrap.add_argument('--credential-path', type=Path, required=True)
    bootstrap.add_argument('--result-path', type=Path, required=True)

    controls = commands.add_parser('bootstrap-candidate-controls')
    controls.add_argument('--candidate-database', required=True)
    controls.add_argument('--active-database', required=True)
    controls.add_argument('--snapshot-id', required=True)
    controls.add_argument('--tenant-profile', type=Path, required=True)
    controls.add_argument('--result-path', type=Path, required=True)

    remove = commands.add_parser('remove-candidate-admin')
    remove.add_argument('--candidate-database', required=True)
    remove.add_argument('--bootstrap-result', type=Path, required=True)
    remove.add_argument('--report', type=Path, required=True)

    validate = commands.add_parser('validate-candidate')
    validate.add_argument('--credential-path', type=Path, required=True)
    validate.add_argument('--candidate-database', required=True)
    validate.add_argument('--candidate-bucket', required=True)
    validate.add_argument('--report', type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == 'minio-export':
        report = export_minio_objects(
            minio_client_from_environment(),
            bucket=args.bucket,
            destination_root=args.output_root,
            replace_changed=args.replace_changed,
            prune=args.prune,
        )
        report_path = args.output_root.parent / 'minio-export-report.json'
        write_atomic_json(
            report_path,
            {'bucket': args.bucket, 'status': 'passed', **report.to_dict()},
            overwrite=False,
        )
        return 0
    if args.command == 'minio-import':
        report = import_minio_tree(
            minio_client_from_environment(),
            bucket=args.bucket,
            source_root=args.source_root,
        )
        write_atomic_json(args.report, report, overwrite=False)
        return 0
    if args.command == 'minio-delete-bucket':
        delete_restore_proof_bucket(
            minio_client_from_environment(),
            bucket=args.bucket,
        )
        return 0
    if args.command == 'bootstrap-candidate':
        bootstrap_candidate_from_profile(
            candidate_database=args.candidate_database,
            active_database=args.active_database,
            snapshot_id=args.snapshot_id,
            tenant_profile_path=args.tenant_profile,
            credential_path=args.credential_path,
            result_path=args.result_path,
        )
        return 0
    if args.command == 'bootstrap-candidate-controls':
        bootstrap_candidate_controls_from_profile(
            candidate_database=args.candidate_database,
            active_database=args.active_database,
            snapshot_id=args.snapshot_id,
            tenant_profile_path=args.tenant_profile,
            result_path=args.result_path,
        )
        return 0
    if args.command == 'remove-candidate-admin':
        remove_candidate_admin(
            candidate_database=args.candidate_database,
            bootstrap_result_path=args.bootstrap_result,
            report_path=args.report,
        )
        return 0
    if args.command == 'validate-candidate':
        report = validate_candidate_runtime(
            credential_path=args.credential_path,
            candidate_database=args.candidate_database,
            candidate_bucket=args.candidate_bucket,
        )
        write_atomic_json(args.report, report, overwrite=False)
        return 0
    raise AssertionError(f'unhandled command: {args.command}')


if __name__ == '__main__':
    raise SystemExit(main())
