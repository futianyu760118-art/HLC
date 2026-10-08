from __future__ import annotations

import importlib
import json
import sys

import pytest


def _common():
    return importlib.import_module('ops.operation_common')


@pytest.mark.parametrize(
    'value',
    (
        '',
        '20260715',
        '20260715T102030',
        '20260715T102030+0800',
        '../20260715T102030Z',
        '20260715t102030z',
        None,
        True,
    ),
)
def test_runtime_id_accepts_only_strict_utc_identifiers(value):
    common = _common()

    with pytest.raises(common.OperationSafetyError, match='runtime ID'):
        common.validate_runtime_id(value)

    assert common.validate_runtime_id('20260715T102030Z') == (
        '20260715T102030Z'
    )


@pytest.mark.parametrize(
    'value',
    (
        '',
        '.',
        '..',
        '../secret',
        'folder/../secret',
        '/absolute/file',
        'C:/absolute/file',
        'folder\\file',
        'folder//file',
        None,
    ),
)
def test_archive_member_accepts_only_safe_relative_posix_paths(value):
    common = _common()

    with pytest.raises(common.OperationSafetyError, match='archive member'):
        common.ensure_relative_member(value)

    assert common.ensure_relative_member('folder/file.txt') == (
        'folder/file.txt'
    )


def test_atomic_json_refuses_overwrite_and_is_json_safe(tmp_path):
    common = _common()
    target = tmp_path / 'state' / 'operation.json'

    common.write_atomic_json(
        target,
        {'status': 'ready', 'count': 3},
        overwrite=False,
    )

    assert json.loads(target.read_text(encoding='utf-8')) == {
        'count': 3,
        'status': 'ready',
    }
    with pytest.raises(FileExistsError):
        common.write_atomic_json(
            target,
            {'status': 'changed'},
            overwrite=False,
        )


def test_atomic_json_overwrite_replaces_complete_document(tmp_path):
    common = _common()
    target = tmp_path / 'operation.json'
    common.write_atomic_json(target, {'version': 1}, overwrite=False)

    common.write_atomic_json(target, {'version': 2}, overwrite=True)

    assert target.read_text(encoding='utf-8') == '{\n  "version": 2\n}\n'


def test_command_failure_summary_never_contains_process_output():
    common = _common()
    result = common.CommandResult(
        argv=('docker', 'exec', 'mysql'),
        returncode=1,
        stdout='DB_PASSWORD=top-secret',
        stderr='password=another-secret',
    )

    summary = common.summarize_command_failure(result)

    assert summary == {
        'category': 'command_failed',
        'returncode': 1,
    }
    serialized = json.dumps(summary)
    assert 'top-secret' not in serialized
    assert 'another-secret' not in serialized


def test_sha256_file_streams_known_content(tmp_path):
    common = _common()
    payload = tmp_path / 'payload.bin'
    payload.write_bytes(b'hello')

    assert common.sha256_file(payload) == (
        '2cf24dba5fb0a30e26e83b2ac5b9e29e'
        '1b161e5c1fa7425e73043362938b9824'
    )


def test_subprocess_runner_never_uses_shell_and_streams_files(tmp_path):
    common = _common()
    runner = common.SubprocessCommandRunner()

    result = runner.run(
        [sys.executable, '-c', "print('safe-output')"],
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout == 'safe-output\n'

    streamed = tmp_path / 'streamed.bin'
    to_file = runner.run_to_file(
        [sys.executable, '-c', "import sys; sys.stdout.buffer.write(b'payload')"],
        streamed,
        timeout=30,
    )
    assert to_file.returncode == 0
    assert to_file.stdout == ''
    assert streamed.read_bytes() == b'payload'

    from_file = runner.run_from_file(
        [
            sys.executable,
            '-c',
            'import sys; print(len(sys.stdin.buffer.read()))',
        ],
        streamed,
        timeout=30,
    )
    assert from_file.returncode == 0
    assert from_file.stdout == '7\n'


def test_subprocess_stream_failure_removes_partial_output(tmp_path):
    common = _common()
    runner = common.SubprocessCommandRunner()
    destination = tmp_path / 'partial.bin'

    result = runner.run_to_file(
        [
            sys.executable,
            '-c',
            "import sys; sys.stdout.write('partial'); sys.exit(7)",
        ],
        destination,
        timeout=30,
    )

    assert result.returncode == 7
    assert not destination.exists()
