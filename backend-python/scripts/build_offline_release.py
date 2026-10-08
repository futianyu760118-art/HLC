"""Build a data-free Linux/amd64 offline SaaS release package."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Sequence

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ops.operation_common import OperationSafetyError, SubprocessCommandRunner
from ops.release_bundle import (
    DEFAULT_RELEASE_SOURCE_ALLOWLIST,
    ReleaseManifest,
    assert_workspace_unchanged,
    build_release_archive,
    build_release_plan,
    capture_workspace_files,
    execute_release_build,
)


CONFIRMATION = 'BUILD_OFFLINE_SAAS_RELEASE'
REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm')
    parser.add_argument(
        '--release-id',
        default=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
    )
    parser.add_argument('--output-root', type=Path)
    return parser.parse_args(argv)


def _discover_build_inputs(root: Path) -> tuple[str, ...]:
    explicit = (
        'Dockerfile.python',
        'docker-compose.yml',
        'docker-compose.saas-preview.yml',
        'docker-compose.release.yml',
        'eslint.config.js',
        'index.html',
        'package-lock.json',
        'package.json',
        'tsconfig.app.json',
        'tsconfig.json',
        'tsconfig.node.json',
        'vite.config.ts',
    )
    paths = set()
    for relative in explicit:
        if (root / relative).is_file():
            paths.add(relative)
    roots = (
        ('src', {'.css', '.html', '.js', '.jsx', '.json', '.ts', '.tsx'}),
        ('public', None),
        ('backend-python', {'.py', '.txt'}),
        ('scripts', {'.js', '.mjs', '.ps1', '.py', '.sh'}),
    )
    for dirname, suffixes in roots:
        directory = root / dirname
        if not directory.is_dir():
            continue
        for path in directory.rglob('*'):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            lowered = f'/{relative.lower()}/'
            if any(
                marker in lowered
                for marker in ('/__pycache__/', '/uploads/', '/node_modules/', '/artifacts/')
            ):
                continue
            if suffixes is None or path.suffix.lower() in suffixes:
                paths.add(relative)
    return tuple(sorted(paths))


class LocalReleaseBuildActions:
    def __init__(
        self,
        *,
        release_id: str,
        output_root: Path,
        runner,
        docker_command: str,
    ) -> None:
        self.plan = build_release_plan(release_id)
        self.output_dir = Path(output_root) / release_id
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.staging_root = self.output_dir / '.staging'
        self.staging_root.mkdir()
        self.runner = runner
        self.docker_command = docker_command
        self.node_command = shutil.which('node') or 'node'
        self.npm_command = shutil.which('npm') or 'npm'
        self.npx_command = shutil.which('npx') or 'npx'
        self.build_inputs = _discover_build_inputs(REPO_ROOT)
        self.captured_inputs = capture_workspace_files(
            REPO_ROOT,
            self.build_inputs,
        )
        self.backend_digest: str | None = None
        self.archive_result = None

    def _run(self, argv, *, timeout=3600):
        result = self.runner.run(
            tuple(argv),
            cwd=REPO_ROOT,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise OperationSafetyError(
                f'release build command failed with code {result.returncode}'
            )
        return result

    def _copy_release_sources(self) -> None:
        app_root = self.staging_root / 'app'
        for relative in DEFAULT_RELEASE_SOURCE_ALLOWLIST:
            source = REPO_ROOT.joinpath(*relative.split('/'))
            if source.is_symlink() or not source.is_file():
                raise OperationSafetyError(
                    f'release source is missing or unsafe: {relative}'
                )
            target = app_root.joinpath(*relative.split('/'))
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open('rb') as input_file, target.open('xb') as output:
                shutil.copyfileobj(input_file, output, length=1024 * 1024)

    def run_release_build_step(self, step) -> None:
        handler = getattr(self, f'_step_{step.name}')
        handler()

    def _step_target_guard(self):
        self._run((self.node_command, 'scripts/verify-saas-target-guard.mjs'))

    def _step_operation_tests(self):
        self._run(
            (
                sys.executable,
                '-m',
                'pytest',
                '-q',
                'backend-python/tests/test_operation_common.py',
                'backend-python/tests/test_release_bundle.py',
                'backend-python/tests/test_release_manager.py',
                'backend-python/tests/test_release_transport.py',
                'backend-python/tests/test_server_first_tenant_migration.py',
                'backend-python/tests/test_server_prepare.py',
            ),
            timeout=3600,
        )

    def _step_typescript(self):
        self._run((self.npx_command, 'tsc', '-b', '--pretty', 'false'))

    def _step_lint(self):
        self._run((self.npm_command, 'run', 'lint', '--', '--max-warnings=0'))

    def _step_frontend_build(self):
        destination = self.staging_root / 'app' / 'dist-prod'
        self._run(
            (
                self.npx_command,
                'vite',
                'build',
                '--outDir',
                str(destination),
            ),
            timeout=1800,
        )

    def _step_linux_image_build(self):
        buildx = self.runner.run(
            (self.docker_command, 'buildx', 'version'),
            cwd=REPO_ROOT,
            timeout=60,
        )
        if buildx.returncode == 0:
            command = (
                self.docker_command,
                'buildx',
                'build',
                '--platform',
                'linux/amd64',
                '--build-arg',
                'DEBIAN_MIRROR=https://mirrors.cloud.tencent.com/debian',
                '--build-arg',
                'DEBIAN_SECURITY_MIRROR=https://mirrors.cloud.tencent.com/debian-security',
                '--build-arg',
                'PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple',
                '--load',
                '--file',
                'Dockerfile.python',
                '--tag',
                self.plan.backend_image,
                '.',
            )
        else:
            daemon = self._run(
                (
                    self.docker_command,
                    'version',
                    '--format',
                    '{{.Server.Os}}/{{.Server.Arch}}',
                )
            )
            if daemon.stdout.strip() != 'linux/amd64':
                raise OperationSafetyError(
                    'Buildx is unavailable and Docker daemon is not linux/amd64'
                )
            command = (
                self.docker_command,
                'build',
                '--platform',
                'linux/amd64',
                '--build-arg',
                'DEBIAN_MIRROR=https://mirrors.cloud.tencent.com/debian',
                '--build-arg',
                'DEBIAN_SECURITY_MIRROR=https://mirrors.cloud.tencent.com/debian-security',
                '--build-arg',
                'PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple',
                '--file',
                'Dockerfile.python',
                '--tag',
                self.plan.backend_image,
                '.',
            )
        self._run(command, timeout=7200)

    def _step_image_inspect(self):
        result = self._run(
            (
                self.docker_command,
                'image',
                'inspect',
                '--format',
                '{{.Id}}|{{.Os}}|{{.Architecture}}',
                self.plan.backend_image,
            )
        )
        fields = result.stdout.strip().split('|')
        if (
            len(fields) != 3
            or fields[1:] != ['linux', 'amd64']
            or not fields[0].startswith('sha256:')
        ):
            raise OperationSafetyError('built backend image architecture is invalid')
        self.backend_digest = fields[0]

    def _step_image_save(self):
        image_root = self.staging_root / 'images'
        image_root.mkdir()
        result = self.runner.run_to_file(
            (self.docker_command, 'save', self.plan.backend_image),
            image_root / 'backend-image.tar',
            cwd=REPO_ROOT,
            timeout=7200,
        )
        if result.returncode != 0:
            raise OperationSafetyError('backend image save failed')

    def _step_workspace_drift_check(self):
        assert_workspace_unchanged(REPO_ROOT, self.captured_inputs)

    def _step_archive_publish(self):
        if self.backend_digest is None:
            raise OperationSafetyError('backend image digest is unavailable')
        self._copy_release_sources()
        payload_paths = tuple(
            sorted(
                path.relative_to(self.staging_root).as_posix()
                for path in self.staging_root.rglob('*')
                if path.is_file() and not path.is_symlink()
            )
        )
        payload = capture_workspace_files(self.staging_root, payload_paths)
        manifest = ReleaseManifest(
            release_id=self.plan.release_id,
            architecture='linux/amd64',
            backend_image=self.plan.backend_image,
            backend_digest=self.backend_digest,
            payload=payload,
        )
        archive_path = self.output_dir / (
            f'HRM-saas-offline-release-{self.plan.release_id}.zip'
        )
        self.archive_result = build_release_archive(
            staging_root=self.staging_root,
            archive_path=archive_path,
            manifest=manifest,
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    plan = build_release_plan(args.release_id)
    print(
        json.dumps(
            {
                'confirmationRequired': CONFIRMATION,
                'execute': args.execute,
                'releaseId': plan.release_id,
                'steps': [step.name for step in plan.steps],
            },
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    if not args.execute:
        return 0
    if args.confirm != CONFIRMATION:
        raise OperationSafetyError(
            f'--execute requires --confirm {CONFIRMATION}'
        )
    docker_command = shutil.which('docker')
    if docker_command is None:
        candidate = Path(
            r'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
        )
        if candidate.is_file():
            docker_command = str(candidate)
    if docker_command is None:
        raise OperationSafetyError('Docker CLI is unavailable')
    output_root = (
        Path(args.output_root)
        if args.output_root is not None
        else REPO_ROOT / 'artifacts' / 'releases'
    )
    actions = LocalReleaseBuildActions(
        release_id=plan.release_id,
        output_root=output_root,
        runner=SubprocessCommandRunner(),
        docker_command=docker_command,
    )
    result = execute_release_build(actions, plan)
    print(
        json.dumps(
            {
                'archive': str(actions.archive_result.archive_path),
                'sha256': actions.archive_result.sha256,
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
