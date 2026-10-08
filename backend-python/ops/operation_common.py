"""Small safety primitives for privileged operational commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Mapping, Protocol, Sequence


RUNTIME_ID_RE = re.compile(r'^\d{8}T\d{6}Z$', re.ASCII)
WINDOWS_ABSOLUTE_RE = re.compile(r'^[A-Za-z]:[/\\]')
FILE_CHUNK_SIZE = 1024 * 1024


class OperationSafetyError(RuntimeError):
    """Raised when an operational precondition cannot be proved safe."""


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: int = 300,
    ) -> CommandResult: ...


class SubprocessCommandRunner:
    """Run argv directly and provide non-overwriting file streaming helpers."""

    @staticmethod
    def _environment(env: Mapping[str, str] | None) -> dict[str, str] | None:
        if env is None:
            return None
        merged = dict(os.environ)
        merged.update(env)
        return merged

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        safe_argv = tuple(str(item) for item in argv)
        completed = subprocess.run(
            safe_argv,
            cwd=str(cwd) if cwd is not None else None,
            env=self._environment(env),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            check=False,
            shell=False,
        )
        return CommandResult(
            argv=safe_argv,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def run_to_file(
        self,
        argv: Sequence[str],
        destination: Path,
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: int = 3600,
    ) -> CommandResult:
        target = Path(destination)
        if target.is_symlink():
            raise OperationSafetyError('stream destination must not be a symlink')
        if target.exists():
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f'.{target.name}.',
            suffix='.tmp',
            dir=target.parent,
        )
        temporary = Path(temporary_name)
        safe_argv = tuple(str(item) for item in argv)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                descriptor = -1
                completed = subprocess.run(
                    safe_argv,
                    cwd=str(cwd) if cwd is not None else None,
                    env=self._environment(env),
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                    check=False,
                    shell=False,
                )
                output.flush()
                os.fsync(output.fileno())
            if completed.returncode == 0:
                os.link(temporary, target)
                temporary.unlink()
            else:
                temporary.unlink()
            return CommandResult(
                argv=safe_argv,
                returncode=completed.returncode,
                stdout='',
                stderr=completed.stderr.decode('utf-8', errors='replace'),
            )
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise

    def run_from_file(
        self,
        argv: Sequence[str],
        source: Path,
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: int = 3600,
    ) -> CommandResult:
        input_path = Path(source)
        if input_path.is_symlink() or not input_path.is_file():
            raise OperationSafetyError('stream source must be a regular file')
        safe_argv = tuple(str(item) for item in argv)
        with input_path.open('rb') as input_file:
            completed = subprocess.run(
                safe_argv,
                cwd=str(cwd) if cwd is not None else None,
                env=self._environment(env),
                stdin=input_file,
                capture_output=True,
                text=False,
                timeout=timeout,
                check=False,
                shell=False,
            )
        return CommandResult(
            argv=safe_argv,
            returncode=completed.returncode,
            stdout=completed.stdout.decode(
                'utf-8', errors='replace'
            ).replace('\r\n', '\n'),
            stderr=completed.stderr.decode(
                'utf-8', errors='replace'
            ).replace('\r\n', '\n'),
        )


def validate_runtime_id(value: object) -> str:
    if not isinstance(value, str) or RUNTIME_ID_RE.fullmatch(value) is None:
        raise OperationSafetyError(
            'runtime ID must use strict UTC form YYYYMMDDTHHMMSSZ'
        )
    try:
        datetime.strptime(value, '%Y%m%dT%H%M%SZ')
    except ValueError as exc:
        raise OperationSafetyError('runtime ID contains an invalid UTC time') from exc
    return value


def ensure_relative_member(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise OperationSafetyError('archive member must be a non-empty string')
    if '\\' in value or value.startswith('/') or WINDOWS_ABSOLUTE_RE.match(value):
        raise OperationSafetyError('archive member must be a relative POSIX path')
    segments = value.split('/')
    if any(segment in ('', '.', '..') for segment in segments):
        raise OperationSafetyError(
            'archive member must not contain empty or traversal segments'
        )
    return value


def write_atomic_json(path: Path, value: object, *, overwrite: bool) -> None:
    target = Path(path)
    if target.is_symlink():
        raise OperationSafetyError('atomic JSON target must not be a symlink')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and target.exists():
        raise FileExistsError(target)

    payload = (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + '\n'
    ).encode('utf-8')
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f'.{target.name}.',
        suffix='.tmp',
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        with os.fdopen(descriptor, 'wb') as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if overwrite:
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
            linked = True
            temporary.unlink()
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()
        if linked and target.exists():
            target.unlink()
        raise


def sha256_file(path: Path) -> str:
    source = Path(path)
    metadata = source.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise OperationSafetyError('SHA-256 source must be a regular file')
    digest = hashlib.sha256()
    with source.open('rb') as handle:
        while chunk := handle.read(FILE_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def summarize_command_failure(result: CommandResult) -> dict[str, object]:
    return {
        'category': 'command_failed',
        'returncode': result.returncode,
    }
