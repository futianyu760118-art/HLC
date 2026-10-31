"""Transport-neutral release references for offline ZIP and future TCR."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Protocol

from ops.operation_common import OperationSafetyError, sha256_file


APPLY_STATE_CONTRACT = (
    'verify',
    'install',
    'switch_current',
    'recreate_backend_nginx',
    'health_gate',
    'record_or_rollback',
)
TCR_DIGEST_RE = re.compile(
    r'^[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}$',
    re.ASCII,
)


@dataclass(frozen=True)
class VerifiedRelease:
    transport: str
    state_contract: tuple[str, ...]
    archive_path: Path | None = None
    sha256: str | None = None
    image_reference: str | None = None
    pull_command: tuple[str, ...] | None = None


class ReleaseTransport(Protocol):
    def fetch(self, release_ref: str) -> VerifiedRelease: ...


class OfflineReleaseTransport:
    def fetch(self, release_ref: str) -> VerifiedRelease:
        archive = Path(release_ref).resolve(strict=False)
        sidecar = archive.with_name(archive.name + '.sha256')
        if archive.is_symlink() or not archive.is_file():
            raise OperationSafetyError('offline release archive is missing')
        if sidecar.is_symlink() or not sidecar.is_file():
            raise OperationSafetyError('offline release checksum is missing')
        try:
            value = sidecar.read_text(encoding='ascii')
        except (OSError, UnicodeError) as exc:
            raise OperationSafetyError('offline release checksum is invalid') from exc
        match = re.fullmatch(
            r'([0-9a-f]{64})  ([^\r\n]+)\r?\n?',
            value,
            re.ASCII,
        )
        if match is None or match.group(2) != archive.name:
            raise OperationSafetyError('offline release checksum is invalid')
        actual = sha256_file(archive)
        if actual != match.group(1):
            raise OperationSafetyError('offline release checksum mismatch')
        return VerifiedRelease(
            transport='offline',
            archive_path=archive,
            sha256=actual,
            state_contract=APPLY_STATE_CONTRACT,
        )


class TcrReleaseTransport:
    def fetch(self, release_ref: str) -> VerifiedRelease:
        if (
            not isinstance(release_ref, str)
            or TCR_DIGEST_RE.fullmatch(release_ref) is None
        ):
            raise OperationSafetyError(
                'TCR release must use an immutable digest-pinned image'
            )
        return VerifiedRelease(
            transport='tcr',
            image_reference=release_ref,
            pull_command=('docker', 'pull', release_ref),
            state_contract=APPLY_STATE_CONTRACT,
        )
