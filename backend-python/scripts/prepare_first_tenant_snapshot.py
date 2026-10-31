"""Plan or execute a consistent first-tenant snapshot capture."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Sequence

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ops.legacy_snapshot_runtime import (
    LegacySnapshotActions,
    LocalSnapshotPaths,
    run_consistent_snapshot,
)
from ops.operation_common import (
    OperationSafetyError,
    SubprocessCommandRunner,
    validate_runtime_id,
)


EXECUTION_CONFIRMATION = 'CAPTURE_HENGPINTONG_NEXT'
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT.parent / 'HRM'
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / 'artifacts' / 'first-tenant-snapshots'


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Prepare the legacy HRM first-tenant snapshot package.',
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        '--plan',
        dest='execute',
        action='store_false',
        help='Print the operation plan without changing source services.',
    )
    mode.add_argument(
        '--execute',
        dest='execute',
        action='store_true',
        help='Capture the snapshot after validating the confirmation phrase.',
    )
    parser.set_defaults(execute=False)
    parser.add_argument('--confirm')
    parser.add_argument('--source-root', type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument('--output-root', type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        '--snapshot-id',
        default=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
    )
    return parser.parse_args(argv)


def validate_execution_policy(args: argparse.Namespace) -> None:
    validate_runtime_id(args.snapshot_id)
    source_root = Path(args.source_root).resolve(strict=False)
    output_root = Path(args.output_root).resolve(strict=False)
    if source_root == output_root or source_root in output_root.parents:
        raise OperationSafetyError(
            'snapshot output root must be outside the legacy source root'
        )
    if args.execute and args.confirm != EXECUTION_CONFIRMATION:
        raise OperationSafetyError(
            f'--execute requires --confirm {EXECUTION_CONFIRMATION}'
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_execution_policy(args)
    plan = {
        'confirmationRequired': EXECUTION_CONFIRMATION,
        'execute': args.execute,
        'outputRoot': str(Path(args.output_root).resolve(strict=False)),
        'snapshotId': args.snapshot_id,
        'sourceProject': 'hengpintong-next',
        'sourceRoot': str(Path(args.source_root).resolve(strict=False)),
    }
    print(json.dumps(plan, ensure_ascii=True, indent=2, sort_keys=True))
    if not args.execute:
        return 0

    docker_command = shutil.which('docker')
    if docker_command is None:
        windows_docker = Path(
            r'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
        )
        if windows_docker.is_file():
            docker_command = str(windows_docker)
    if docker_command is None:
        raise OperationSafetyError('Docker CLI is unavailable')

    paths = LocalSnapshotPaths.build(args.output_root, args.snapshot_id)
    actions = LegacySnapshotActions(
        runner=SubprocessCommandRunner(),
        source_root=args.source_root,
        repo_root=REPOSITORY_ROOT,
        paths=paths,
        snapshot_id=args.snapshot_id,
        docker_command=docker_command,
    )
    result = run_consistent_snapshot(actions)
    print(
        json.dumps(
            {
                'archive': str(paths.archive_path),
                'archiveSha256': paths.archive_sha256_path.read_text(
                    encoding='ascii'
                ).split()[0],
                'snapshotId': args.snapshot_id,
                'status': result.status,
            },
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
