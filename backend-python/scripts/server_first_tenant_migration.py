"""Prepare, promote, inspect, or roll back the first tenant migration."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Sequence

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ops.operation_common import (
    OperationSafetyError,
    SubprocessCommandRunner,
    sha256_file,
    write_atomic_json,
)
from ops.server_migration import (
    DockerSwitchActions,
    OperationLock,
    PrepareConfig,
    build_prepare_plan,
    clear_stale_operation_lock,
    execute_prepare,
    load_prepared_state,
    peek_snapshot_id,
    promote_candidate,
    rollback_candidate,
    verify_outer_package_hash,
)
from ops.server_prepare import ServerPrepareActions


DEFAULT_DEPLOYMENT_ROOT = Path('/home/ubuntu/apps/hrm-saas')


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--deployment-root',
        type=Path,
        default=DEFAULT_DEPLOYMENT_ROOT,
    )
    parser.add_argument('--app-root', type=Path)
    subparsers = parser.add_subparsers(dest='command', required=True)

    prepare = subparsers.add_parser('prepare')
    prepare.add_argument('--package', type=Path)
    prepare.add_argument('--sidecar', type=Path)
    prepare.add_argument('--plan', action='store_true')

    cutover = subparsers.add_parser('cutover')
    cutover.add_argument('--snapshot-id')
    cutover.add_argument('--confirm')

    rollback = subparsers.add_parser('rollback')
    rollback.add_argument('--snapshot-id')

    status = subparsers.add_parser('status')
    status.add_argument('--snapshot-id')

    unlock = subparsers.add_parser('unlock')
    unlock.add_argument('--confirm')
    return parser.parse_args(argv)


def resolve_snapshot_package(args: argparse.Namespace) -> tuple[Path, Path]:
    deployment_root = Path(args.deployment_root).resolve(strict=False)
    requested_package = getattr(args, 'package', None)
    requested_sidecar = getattr(args, 'sidecar', None)
    if requested_package is not None:
        package = Path(requested_package).resolve(strict=False)
    else:
        incoming = deployment_root / 'shared' / 'incoming'
        packages = sorted(incoming.glob('*.zip')) if incoming.is_dir() else []
        if len(packages) != 1:
            raise OperationSafetyError(
                'prepare requires exactly one snapshot ZIP in shared/incoming'
            )
        package = packages[0]
    sidecar = (
        Path(requested_sidecar).resolve(strict=False)
        if requested_sidecar is not None
        else package.with_name(package.name + '.sha256')
    )
    if package.is_symlink() or not package.is_file():
        raise OperationSafetyError('snapshot package is missing or unsafe')
    if sidecar.is_symlink() or not sidecar.is_file():
        raise OperationSafetyError('snapshot package sidecar is missing or unsafe')
    return package, sidecar


def _deployment_root(args: argparse.Namespace) -> Path:
    root = Path(args.deployment_root)
    if root.is_symlink() or not root.is_dir():
        raise OperationSafetyError('deployment root is missing or unsafe')
    return root.resolve(strict=True)


def _app_root(args: argparse.Namespace, deployment_root: Path) -> Path:
    candidate = (
        Path(args.app_root)
        if args.app_root is not None
        else deployment_root / 'current'
    )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise OperationSafetyError('active application root is missing') from exc
    if not resolved.is_dir():
        raise OperationSafetyError('active application root is invalid')
    return resolved


def _operation_root(deployment_root: Path, snapshot_id: str) -> Path:
    return deployment_root / 'shared' / 'migrations' / snapshot_id


def _lock_path(deployment_root: Path) -> Path:
    return deployment_root / 'shared' / 'locks' / 'first-tenant.lock'


def _build_config(
    *,
    snapshot_id: str,
    app_root: Path,
    operation_root: Path,
    package: Path,
    sidecar: Path,
    environment_path: Path,
    uploads_path: Path,
    certs_path: Path,
) -> PrepareConfig:
    return PrepareConfig(
        snapshot_id=snapshot_id,
        project='hengpintong-saas-preview',
        app_root=app_root,
        operation_root=operation_root,
        package_path=package,
        sidecar_path=sidecar,
        environment_path=environment_path,
        uploads_path=uploads_path,
        certs_path=certs_path,
    )


def _resolve_state_operation(
    args: argparse.Namespace,
    deployment_root: Path,
) -> tuple[Path, Path]:
    migrations_root = deployment_root / 'shared' / 'migrations'
    if args.snapshot_id:
        operation_root = _operation_root(deployment_root, args.snapshot_id)
        state_path = operation_root / 'prepared.json'
        if not state_path.is_file():
            raise OperationSafetyError('prepared state does not exist')
        return operation_root, state_path
    candidates = sorted(migrations_root.glob('*/prepared.json'))
    if len(candidates) != 1:
        raise OperationSafetyError(
            'command requires exactly one prepared migration or --snapshot-id'
        )
    return candidates[0].parent, candidates[0]


def _run_prepare(args: argparse.Namespace) -> int:
    deployment_root = _deployment_root(args)
    app_root = _app_root(args, deployment_root)
    package, sidecar = resolve_snapshot_package(args)
    snapshot_id = peek_snapshot_id(package)
    operation_root = _operation_root(deployment_root, snapshot_id)
    config = _build_config(
        snapshot_id=snapshot_id,
        app_root=app_root,
        operation_root=operation_root,
        package=package,
        sidecar=sidecar,
        environment_path=deployment_root / 'shared' / '.env',
        uploads_path=deployment_root / 'shared' / 'uploads',
        certs_path=deployment_root / 'shared' / 'certs',
    )
    plan = build_prepare_plan(config)
    if args.plan:
        print(
            json.dumps(
                {
                    'activeEnvironmentWrite': False,
                    'package': str(package),
                    'project': plan.project,
                    'snapshotId': snapshot_id,
                    'steps': [step.name for step in plan.steps],
                },
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    runner = SubprocessCommandRunner()
    actions = ServerPrepareActions(
        runner=runner,
        config=config,
        plan=plan,
        code_root=Path(__file__).resolve().parents[2],
    )
    try:
        with OperationLock(
            _lock_path(deployment_root),
            operation='prepare',
            runtime_id=snapshot_id,
        ):
            result = execute_prepare(actions, plan)
    except BaseException as exc:
        if operation_root.is_dir():
            failure_path = operation_root / 'prepare-failure.json'
            if not failure_path.exists():
                write_atomic_json(
                    failure_path,
                    {
                        'errorCategory': type(exc).__name__,
                        'snapshotId': snapshot_id,
                        'status': 'failed',
                    },
                    overwrite=False,
                )
        raise
    print(
        json.dumps(
            {
                'completedSteps': list(result.completed_steps),
                'preparedState': str(operation_root / 'prepared.json'),
                'snapshotId': snapshot_id,
                'status': result.status,
            },
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _run_cutover(args: argparse.Namespace) -> int:
    deployment_root = _deployment_root(args)
    app_root = _app_root(args, deployment_root)
    operation_root, state_path = _resolve_state_operation(args, deployment_root)
    package, sidecar = resolve_snapshot_package(args)
    package_hash = verify_outer_package_hash(package, sidecar)
    state = load_prepared_state(
        state_path,
        expected_package_sha256=package_hash,
    )
    config = _build_config(
        snapshot_id=state.snapshot_id,
        app_root=app_root,
        operation_root=operation_root,
        package=package,
        sidecar=sidecar,
        environment_path=deployment_root / 'shared' / '.env',
        uploads_path=deployment_root / 'shared' / 'uploads',
        certs_path=deployment_root / 'shared' / 'certs',
    )
    plan = build_prepare_plan(config)
    actions = DockerSwitchActions(
        runner=SubprocessCommandRunner(),
        plan=plan,
    )
    with OperationLock(
        _lock_path(deployment_root),
        operation='cutover',
        runtime_id=state.snapshot_id,
    ):
        result = promote_candidate(
            state,
            environment_path=plan.active_environment_path,
            backup_path=operation_root / 'before-cutover.env',
            actions=actions,
            expected_package_sha256=package_hash,
            confirm=args.confirm,
            now=datetime.now(timezone.utc),
        )
        write_atomic_json(
            operation_root / 'cutover.json',
            {
                'activeBucket': result.active_bucket,
                'activeDatabase': result.active_database,
                'snapshotId': state.snapshot_id,
                'status': result.status,
            },
            overwrite=False,
        )
    print(json.dumps({'status': result.status, 'snapshotId': state.snapshot_id}))
    return 0


def _run_rollback(args: argparse.Namespace) -> int:
    deployment_root = _deployment_root(args)
    app_root = _app_root(args, deployment_root)
    operation_root, state_path = _resolve_state_operation(args, deployment_root)
    state_value = json.loads(state_path.read_text(encoding='utf-8'))
    package_hash = state_value.get('packageSha256')
    state = load_prepared_state(
        state_path,
        expected_package_sha256=package_hash,
    )
    package = deployment_root / 'shared' / 'incoming' / 'placeholder.zip'
    config = _build_config(
        snapshot_id=state.snapshot_id,
        app_root=app_root,
        operation_root=operation_root,
        package=package,
        sidecar=package.with_name(package.name + '.sha256'),
        environment_path=deployment_root / 'shared' / '.env',
        uploads_path=deployment_root / 'shared' / 'uploads',
        certs_path=deployment_root / 'shared' / 'certs',
    )
    plan = build_prepare_plan(config)
    actions = DockerSwitchActions(
        runner=SubprocessCommandRunner(),
        plan=plan,
    )
    with OperationLock(
        _lock_path(deployment_root),
        operation='rollback',
        runtime_id=state.snapshot_id,
    ):
        result = rollback_candidate(
            state,
            environment_path=plan.active_environment_path,
            backup_path=operation_root / 'before-cutover.env',
            actions=actions,
        )
        write_atomic_json(
            operation_root / 'rollback.json',
            {
                'activeBucket': result.active_bucket,
                'activeDatabase': result.active_database,
                'retainedCandidateBucket': result.retained_candidate_bucket,
                'retainedCandidateDatabase': result.retained_candidate_database,
                'snapshotId': state.snapshot_id,
                'status': result.status,
            },
            overwrite=False,
        )
    print(json.dumps({'status': result.status, 'snapshotId': state.snapshot_id}))
    return 0


def _run_status(args: argparse.Namespace) -> int:
    deployment_root = _deployment_root(args)
    operation_root, state_path = _resolve_state_operation(args, deployment_root)
    value = json.loads(state_path.read_text(encoding='utf-8'))
    output = {
        'cutoverRecorded': (operation_root / 'cutover.json').is_file(),
        'rollbackRecorded': (operation_root / 'rollback.json').is_file(),
        'snapshotId': value.get('snapshotId'),
        'status': value.get('status'),
        'validationResults': value.get('validationResults'),
    }
    print(json.dumps(output, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if os.name != 'nt' and os.geteuid() != 0:
        raise OperationSafetyError('server migration commands require root')
    if args.command == 'prepare':
        return _run_prepare(args)
    if args.command == 'cutover':
        return _run_cutover(args)
    if args.command == 'rollback':
        return _run_rollback(args)
    if args.command == 'status':
        return _run_status(args)
    if args.command == 'unlock':
        clear_stale_operation_lock(
            _lock_path(_deployment_root(args)),
            confirm=args.confirm,
        )
        print('status=unlocked')
        return 0
    raise AssertionError(f'unhandled command: {args.command}')


if __name__ == '__main__':
    raise SystemExit(main())
