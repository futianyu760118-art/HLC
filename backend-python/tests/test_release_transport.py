from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ops.operation_common import OperationSafetyError
from ops.release_transport import (
    APPLY_STATE_CONTRACT,
    OfflineReleaseTransport,
    TcrReleaseTransport,
)


def test_offline_transport_returns_verified_local_archive(tmp_path):
    archive = tmp_path / 'release.zip'
    archive.write_bytes(b'release')
    digest = hashlib.sha256(b'release').hexdigest()
    sidecar = tmp_path / 'release.zip.sha256'
    sidecar.write_text(f'{digest}  release.zip\n', encoding='ascii')

    verified = OfflineReleaseTransport().fetch(str(archive))

    assert verified.transport == 'offline'
    assert verified.archive_path == archive.resolve()
    assert verified.sha256 == digest
    assert verified.state_contract == APPLY_STATE_CONTRACT


@pytest.mark.parametrize(
    'image',
    (
        'ccr.ccs.tencentyun.com/hpt/backend:latest',
        'ccr.ccs.tencentyun.com/hpt/backend:release-1',
        'backend@sha256:not-a-digest',
    ),
)
def test_tcr_transport_requires_digest_pinned_images_and_never_latest(image):
    with pytest.raises(OperationSafetyError, match='digest'):
        TcrReleaseTransport().fetch(image)


def test_transport_choice_does_not_change_apply_or_rollback_state_contract(
    tmp_path,
):
    archive = tmp_path / 'release.zip'
    archive.write_bytes(b'release')
    digest = hashlib.sha256(b'release').hexdigest()
    archive.with_name('release.zip.sha256').write_text(
        f'{digest}  release.zip\n',
        encoding='ascii',
    )
    offline = OfflineReleaseTransport().fetch(str(archive))
    tcr = TcrReleaseTransport().fetch(
        'ccr.ccs.tencentyun.com/hpt/backend@sha256:' + 'a' * 64
    )

    assert offline.state_contract == tcr.state_contract == APPLY_STATE_CONTRACT
    assert tcr.pull_command == (
        'docker',
        'pull',
        'ccr.ccs.tencentyun.com/hpt/backend@sha256:' + 'a' * 64,
    )
