"""Install, inspect, or roll back immutable Hengpintong SaaS releases."""

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

from ops.operation_common import OperationSafetyError, SubprocessCommandRunner
from ops.release_manager import (
    DockerReleaseActions,
    ServerLayout,
    apply_installed_release,
    bootstrap_legacy_layout,
    read_release_status,
    rollback_release,
    verify_and_install_release,
)
from ops.release_transport import OfflineReleaseTransport
from ops.server_migration import OperationLock


DEFAULT_ROOT = Path('/home/ubuntu/apps/hrm-saas')


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment-root', type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest='command', required=True)
    bootstrap = commands.add_parser('bootstrap')
    bootstrap.add_argument('legacy_app_root', type=Path)
    apply = commands.add_parser('apply')
    apply.add_argument('archive', type=Path)
    commands.add_parser('status')
    commands.add_parser('rollback')
    return parser.parse_args(argv)


def _runtime_id() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if os.name != 'nt' and os.geteuid() != 0:
        raise OperationSafetyError('release commands require root')
    layout = ServerLayout(Path(args.deployment_root).resolve(strict=False))
    layout.ensure_directories()
    runner = SubprocessCommandRunner()
    lock_path = layout.locks_root / 'release.lock'
    if args.command == 'bootstrap':
        with OperationLock(
            lock_path,
            operation='release-bootstrap',
            runtime_id=_runtime_id(),
        ):
            state = bootstrap_legacy_layout(
                layout,
                legacy_app_root=args.legacy_app_root,
                release_override_source=Path(__file__).resolve().parents[2]
                / 'docker-compose.release.yml',
                runner=runner,
            )
        print(json.dumps({'status': 'bootstrapped', 'current': state.current.release_id}))
        return 0
    actions = DockerReleaseActions(layout=layout, runner=runner)
    if args.command == 'apply':
        verified = OfflineReleaseTransport().fetch(str(args.archive))
        state_value = json.loads(layout.release_state_path.read_text(encoding='utf-8'))
        current_id = state_value['current']['releaseId']
        with OperationLock(
            lock_path,
            operation='release-apply',
            runtime_id=_runtime_id(),
        ):
            installed = verify_and_install_release(
                layout,
                archive_path=verified.archive_path,
                sidecar_path=verified.archive_path.with_name(
                    verified.archive_path.name + '.sha256'
                ),
                runner=runner,
                current_release_id=current_id,
            )
            state = apply_installed_release(layout, installed, actions=actions)
        print(json.dumps({'status': 'applied', 'current': state.current.release_id}))
        return 0
    if args.command == 'rollback':
        with OperationLock(
            lock_path,
            operation='release-rollback',
            runtime_id=_runtime_id(),
        ):
            state = rollback_release(layout, actions=actions)
        print(json.dumps({'status': 'rolled_back', 'current': state.current.release_id}))
        return 0
    if args.command == 'status':
        print(
            json.dumps(
                read_release_status(layout, actions=actions),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    raise AssertionError(args.command)


if __name__ == '__main__':
    raise SystemExit(main())
