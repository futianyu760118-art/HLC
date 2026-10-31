from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json

import pytest

import services.legacy_tenant_files as legacy_files
from services.legacy_tenant_files import (
    rewrite_nested_file_references,
    rewrite_upload_reference,
    validate_tenant_segment,
)


@pytest.mark.parametrize(
    'tenant_id',
    (
        'a',
        'Tenant_01-prod',
        'A' * 64,
        '0' * 64,
    ),
)
def test_validate_tenant_segment_accepts_only_safe_segments(tenant_id):
    assert validate_tenant_segment(tenant_id) == tenant_id


@pytest.mark.parametrize(
    'tenant_id',
    (
        '',
        ' ',
        'a' * 65,
        'tenant.name',
        'tenant/name',
        'tenant\\name',
        'tenant name',
        '租户',
        None,
        123,
    ),
)
def test_validate_tenant_segment_rejects_unsafe_segments(tenant_id):
    with pytest.raises(ValueError, match='tenant'):
        validate_tenant_segment(tenant_id)


@pytest.mark.parametrize(
    'value',
    (
        'http://files.example.test/resume.pdf',
        'HTTPS://files.example.test/resume.pdf',
        'data:application/pdf;base64,AAAA',
        'blob:https://app.example.test/file-id',
        '/api/files/download/42',
    ),
)
def test_external_and_application_urls_are_not_rewritten(value):
    assert rewrite_upload_reference(value, 'tenant-a') == value


def test_upload_url_is_rewritten_under_destination_tenant():
    assert rewrite_upload_reference(
        '/uploads/resumes/candidate.pdf?download=1#page=2',
        'tenant-a',
    ) == '/uploads/tenants/tenant-a/resumes/candidate.pdf?download=1#page=2'


def test_video_object_key_is_rewritten_under_destination_tenant():
    assert rewrite_upload_reference(
        'courses/course-1/hour-1.mp4',
        'tenant-a',
        object_key=True,
    ) == 'tenants/tenant-a/courses/course-1/hour-1.mp4'


@pytest.mark.parametrize(
    ('value', 'object_key'),
    (
        ('/uploads/tenants/tenant-a/resumes/candidate.pdf', False),
        ('tenants/tenant-a/courses/hour.mp4', True),
    ),
)
def test_rewrite_is_idempotent_for_the_destination_tenant(value, object_key):
    assert rewrite_upload_reference(
        value,
        'tenant-a',
        object_key=object_key,
    ) == value


@pytest.mark.parametrize(
    ('value', 'object_key'),
    (
        ('/uploads/tenants/tenant-b/resumes/candidate.pdf', False),
        ('tenants/tenant-b/courses/hour.mp4', True),
    ),
)
def test_rewrite_blocks_references_owned_by_another_tenant(value, object_key):
    with pytest.raises(ValueError, match='another tenant'):
        rewrite_upload_reference(value, 'tenant-a', object_key=object_key)


@pytest.mark.parametrize(
    ('value', 'object_key'),
    (
        ('', False),
        ('   ', False),
        ('', True),
        ('C:\\legacy\\resume.pdf', False),
        ('C:/legacy/resume.pdf', True),
        ('/var/lib/hrm/resume.pdf', False),
        ('\\\\server\\share\\resume.pdf', True),
        ('/uploads/resumes\\candidate.pdf', False),
        ('courses\\hour.mp4', True),
        ('/uploads/./candidate.pdf', False),
        ('/uploads/resumes/../candidate.pdf', False),
        ('courses/./hour.mp4', True),
        ('courses/../hour.mp4', True),
        ('/uploads/', False),
        ('tenants/tenant-a/', True),
    ),
)
def test_rewrite_rejects_unsafe_local_paths(value, object_key):
    with pytest.raises(ValueError, match='path|reference'):
        rewrite_upload_reference(value, 'tenant-a', object_key=object_key)


@pytest.mark.parametrize(
    'value',
    ('hrm/employees/42',),
)
def test_ordinary_relative_page_and_link_urls_are_not_rewritten(value):
    assert rewrite_upload_reference(value, 'tenant-a') == value


@pytest.mark.parametrize(
    'value',
    (
        'mailto:owner@example.test',
        'javascript:alert(1)',
        'file:///var/lib/hrm/resume.pdf',
        'ftp://files.example.test/resume.pdf',
        '#employee-42',
        '?page=2',
    ),
)
def test_non_external_schemes_and_pathless_links_are_rejected(value):
    with pytest.raises(ValueError, match='scheme|path|reference'):
        rewrite_upload_reference(value, 'tenant-a')


@pytest.mark.parametrize(
    'value',
    (
        '/api/files\\private',
        '/api/../private',
        '/api/%2e%2e/private',
        '/api//etc/passwd',
        '/api/%2Fetc/passwd',
        '/api/C:/Windows/System32',
        '/api/C:%5CWindows/System32',
    ),
)
def test_application_urls_are_path_safety_checked(value):
    with pytest.raises(ValueError, match='path|reference'):
        rewrite_upload_reference(value, 'tenant-a')


@pytest.mark.parametrize(
    ('value', 'object_key'),
    (
        ('/uploads/%252e%252e/private.pdf', False),
        ('/uploads/files%252Fprivate.pdf', False),
        ('/uploads/files%255Cprivate.pdf', False),
        ('courses/%252e%252e/private.mp4', True),
        ('courses/files%252Fprivate.mp4', True),
        ('courses/files%255Cprivate.mp4', True),
    ),
)
def test_recursively_encoded_traversal_and_separators_are_rejected(
    value,
    object_key,
):
    with pytest.raises(ValueError, match='path|reference'):
        rewrite_upload_reference(value, 'tenant-a', object_key=object_key)


def test_percent_decoding_that_does_not_stabilize_is_rejected():
    encoded = '%2e%2e'
    for _ in range(12):
        encoded = encoded.replace('%', '%25')

    with pytest.raises(ValueError, match='encoding|path|reference'):
        rewrite_upload_reference(
            f'/uploads/{encoded}/private.pdf',
            'tenant-a',
        )


@pytest.mark.parametrize(
    'value',
    (
        '/uploads//etc/passwd',
        '/uploads/C:/Windows/System32/config',
        '/uploads/%43%3A/Windows/System32/config',
        '/uploads/%2Fetc/passwd',
        '/uploads/files//private.pdf',
    ),
)
def test_upload_relative_path_cannot_hide_absolute_or_empty_segments(value):
    with pytest.raises(ValueError, match='path|reference'):
        rewrite_upload_reference(value, 'tenant-a')


@pytest.mark.parametrize(
    ('value', 'object_key'),
    (
        ('/uploads/C:escape/file', False),
        ('C:escape/file', True),
    ),
)
def test_windows_drive_relative_paths_are_rejected(value, object_key):
    with pytest.raises(ValueError, match='path|reference|scheme'):
        rewrite_upload_reference(value, 'tenant-a', object_key=object_key)


ATTACHMENT_URL_KEYS = (
    'url',
    'fileUrl',
    'file_url',
    'attachmentUrl',
    'attachment_url',
    'imageUrl',
    'image_url',
    'coverUrl',
    'cover_url',
    'recordingUrl',
    'recording_url',
    'feedbackFileUrl',
    'feedback_file_url',
)


@pytest.mark.parametrize('key', ATTACHMENT_URL_KEYS)
def test_nested_rewrite_handles_every_attachment_url_key(key):
    payload = {key: '/uploads/files/attachment.pdf'}

    assert rewrite_nested_file_references(payload, 'tenant-a') == {
        key: '/uploads/tenants/tenant-a/files/attachment.pdf'
    }


@pytest.mark.parametrize('key', ('videoKey', 'video_key'))
def test_nested_rewrite_uses_object_key_mode_for_video_keys(key):
    payload = {key: 'courses/course-1/hour.mp4'}

    assert rewrite_nested_file_references(payload, 'tenant-a') == {
        key: 'tenants/tenant-a/courses/course-1/hour.mp4'
    }


def test_nested_json_attachment_urls_are_rewritten_recursively():
    payload = {
        'sections': [
            {
                'name': 'profile',
                'assets': [
                    '/uploads/avatars/alice.png',
                    {'unlistedKey': '/uploads/documents/offer.pdf'},
                ],
            },
            {'url': 'https://cdn.example.test/external.pdf'},
        ],
        'count': 2,
        'enabled': True,
        'empty': None,
    }

    assert rewrite_nested_file_references(payload, 'tenant-a') == {
        'sections': [
            {
                'name': 'profile',
                'assets': [
                    '/uploads/tenants/tenant-a/avatars/alice.png',
                    {
                        'unlistedKey':
                            '/uploads/tenants/tenant-a/documents/offer.pdf'
                    },
                ],
            },
            {'url': 'https://cdn.example.test/external.pdf'},
        ],
        'count': 2,
        'enabled': True,
        'empty': None,
    }


def test_nested_rewrite_does_not_mutate_the_input():
    payload = {'items': [{'file_url': '/uploads/files/a.pdf'}]}
    original = deepcopy(payload)

    result = rewrite_nested_file_references(payload, 'tenant-a')

    assert payload == original
    assert result is not payload
    assert result['items'] is not payload['items']
    assert result['items'][0] is not payload['items'][0]


def test_nested_rewrite_preserves_page_and_link_url_fields():
    payload = {
        'page_url': '/uploads/pages/legacy-preview.html',
        'link_url': '/uploads/documents/legacy-link.pdf',
        'nested': [
            {'page_url': '/hrm/employees'},
            {'link_url': 'https://example.test/uploads/file.pdf'},
        ],
    }

    assert rewrite_nested_file_references(payload, 'tenant-a') == payload


def test_nested_rewrite_validates_tenant_even_without_file_references():
    with pytest.raises(ValueError, match='tenant'):
        rewrite_nested_file_references({'page_url': '/hrm/home'}, '../tenant')


def test_nested_rewrite_rejects_dict_cycles():
    payload = {}
    payload['self'] = payload

    with pytest.raises(ValueError, match='cycle'):
        rewrite_nested_file_references(payload, 'tenant-a')


def test_nested_rewrite_rejects_list_cycles():
    payload = []
    payload.append(payload)

    with pytest.raises(ValueError, match='cycle'):
        rewrite_nested_file_references(payload, 'tenant-a')


@pytest.mark.parametrize('key', ('page_url', 'link_url'))
def test_page_and_link_containers_cannot_bypass_cycle_detection(key):
    cyclic_value = []
    cyclic_value.append(cyclic_value)

    with pytest.raises(ValueError, match='cycle'):
        rewrite_nested_file_references(
            {key: cyclic_value},
            'tenant-a',
        )


def test_nested_rewrite_rejects_values_beyond_the_depth_limit():
    payload = 'leaf'
    for _ in range(5):
        payload = [payload]

    with pytest.raises(ValueError, match='depth'):
        rewrite_nested_file_references(
            payload,
            'tenant-a',
            max_depth=3,
        )


def test_nested_rewrite_rejects_values_beyond_the_node_limit():
    payload = {'items': [1, 2]}

    with pytest.raises(ValueError, match='node'):
        rewrite_nested_file_references(
            payload,
            'tenant-a',
            max_nodes=3,
        )


def test_file_manifest_entry_is_frozen_and_json_safe():
    entry = legacy_files.FileManifestEntry(
        source_relative_path='resumes/candidate.pdf',
        destination_key='tenants/tenant-a/resumes/candidate.pdf',
        size_bytes=7,
        sha256='a' * 64,
    )

    assert json.loads(json.dumps(entry.to_dict())) == {
        'source_relative_path': 'resumes/candidate.pdf',
        'destination_key': 'tenants/tenant-a/resumes/candidate.pdf',
        'size_bytes': 7,
        'sha256': 'a' * 64,
    }
    with pytest.raises(FrozenInstanceError):
        entry.size_bytes = 8


@pytest.mark.parametrize(
    'overrides',
    (
        {'source_relative_path': ''},
        {'source_relative_path': '/absolute.pdf'},
        {'source_relative_path': 'C:drive-relative.pdf'},
        {'source_relative_path': 'resumes//candidate.pdf'},
        {'source_relative_path': 'resumes/../candidate.pdf'},
        {'source_relative_path': 'resumes\\candidate.pdf'},
        {'destination_key': 'uploads/tenant-a/resumes/candidate.pdf'},
        {'destination_key': 'tenants/../resumes/candidate.pdf'},
        {'destination_key': 'tenants/tenant-a/other.pdf'},
        {'size_bytes': -1},
        {'size_bytes': True},
        {'sha256': 'A' * 64},
        {'sha256': 'a' * 63},
    ),
)
def test_file_manifest_entry_direct_construction_fails_closed(overrides):
    values = {
        'source_relative_path': 'resumes/candidate.pdf',
        'destination_key': 'tenants/tenant-a/resumes/candidate.pdf',
        'size_bytes': 7,
        'sha256': 'a' * 64,
    }
    values.update(overrides)

    with pytest.raises((ValueError, legacy_files.MigrationSafetyError)):
        legacy_files.FileManifestEntry(**values)


def test_file_copy_report_is_frozen_and_json_safe():
    report = legacy_files.FileCopyReport(
        created_keys=('tenants/tenant-a/a.txt',),
        skipped_keys=('tenants/tenant-a/b.txt',),
        total_bytes=3,
    )

    assert json.loads(json.dumps(report.to_dict())) == {
        'created_keys': ['tenants/tenant-a/a.txt'],
        'skipped_keys': ['tenants/tenant-a/b.txt'],
        'total_bytes': 3,
    }
    with pytest.raises(FrozenInstanceError):
        report.total_bytes = 4


@pytest.mark.parametrize(
    'overrides',
    (
        {'created_keys': ['tenants/tenant-a/a.txt']},
        {
            'created_keys': (
                'tenants/tenant-a/b.txt',
                'tenants/tenant-a/a.txt',
            )
        },
        {
            'created_keys': (
                'tenants/tenant-a/a.txt',
                'tenants/tenant-a/a.txt',
            )
        },
        {
            'created_keys': ('tenants/tenant-a/a.txt',),
            'skipped_keys': ('tenants/tenant-a/a.txt',),
        },
        {'created_keys': ('../tenant-a/a.txt',)},
        {'total_bytes': -1},
        {'total_bytes': True},
    ),
)
def test_file_copy_report_direct_construction_fails_closed(overrides):
    values = {
        'created_keys': (),
        'skipped_keys': (),
        'total_bytes': 0,
    }
    values.update(overrides)

    with pytest.raises((ValueError, legacy_files.MigrationSafetyError)):
        legacy_files.FileCopyReport(**values)


def test_build_file_manifest_hashes_files_in_stable_relative_path_order(
    tmp_path,
):
    source_root = tmp_path / 'legacy-uploads'
    (source_root / 'resumes').mkdir(parents=True)
    (source_root / 'z-last.bin').write_bytes(
        b'z' * (legacy_files.FILE_CHUNK_SIZE + 7)
    )
    (source_root / 'resumes' / 'candidate.pdf').write_bytes(b'pdf-data')

    manifest = legacy_files.build_file_manifest(source_root, 'tenant-a')

    assert [entry.to_dict() for entry in manifest] == [
        {
            'source_relative_path': 'resumes/candidate.pdf',
            'destination_key': (
                'tenants/tenant-a/resumes/candidate.pdf'
            ),
            'size_bytes': 8,
            'sha256': hashlib.sha256(b'pdf-data').hexdigest(),
        },
        {
            'source_relative_path': 'z-last.bin',
            'destination_key': 'tenants/tenant-a/z-last.bin',
            'size_bytes': legacy_files.FILE_CHUNK_SIZE + 7,
            'sha256': hashlib.sha256(
                b'z' * (legacy_files.FILE_CHUNK_SIZE + 7)
            ).hexdigest(),
        },
    ]


def test_build_file_manifest_rejects_a_missing_or_non_directory_root(tmp_path):
    regular_file = tmp_path / 'source.txt'
    regular_file.write_text('not a directory', encoding='utf-8')

    with pytest.raises(legacy_files.MigrationSafetyError, match='directory'):
        legacy_files.build_file_manifest(tmp_path / 'missing', 'tenant-a')
    with pytest.raises(legacy_files.MigrationSafetyError, match='directory'):
        legacy_files.build_file_manifest(regular_file, 'tenant-a')


def test_build_file_manifest_rejects_symlinks_without_following_them(tmp_path):
    source_root = tmp_path / 'legacy-uploads'
    outside_file = tmp_path / 'outside.txt'
    source_root.mkdir()
    outside_file.write_text('outside', encoding='utf-8')
    link = source_root / 'linked.txt'
    try:
        link.symlink_to(outside_file)
    except OSError as exc:
        pytest.skip(f'symlink creation unavailable: {exc}')

    with pytest.raises(legacy_files.MigrationSafetyError, match='symlink'):
        legacy_files.build_file_manifest(source_root, 'tenant-a')


def test_merge_file_manifests_deduplicates_identical_entries_in_key_order():
    entry_a = legacy_files.FileManifestEntry(
        source_relative_path='a.txt',
        destination_key='tenants/tenant-a/a.txt',
        size_bytes=1,
        sha256=hashlib.sha256(b'a').hexdigest(),
    )
    entry_b = legacy_files.FileManifestEntry(
        source_relative_path='b.txt',
        destination_key='tenants/tenant-a/b.txt',
        size_bytes=1,
        sha256=hashlib.sha256(b'b').hexdigest(),
    )

    assert legacy_files.merge_file_manifests(
        (entry_b, entry_a),
        (entry_a,),
    ) == (entry_a, entry_b)


def test_merge_file_manifests_blocks_conflicts_before_copying():
    original = legacy_files.FileManifestEntry(
        source_relative_path='a.txt',
        destination_key='tenants/tenant-a/a.txt',
        size_bytes=1,
        sha256=hashlib.sha256(b'a').hexdigest(),
    )
    conflict = legacy_files.FileManifestEntry(
        source_relative_path='a.txt',
        destination_key='tenants/tenant-a/a.txt',
        size_bytes=1,
        sha256=hashlib.sha256(b'b').hexdigest(),
    )

    with pytest.raises(legacy_files.MigrationSafetyError, match='conflict'):
        legacy_files.merge_file_manifests((original,), (conflict,))


def test_merge_file_manifests_rejects_mixed_destination_tenants():
    tenant_a = legacy_files.FileManifestEntry(
        source_relative_path='a.txt',
        destination_key='tenants/tenant-a/a.txt',
        size_bytes=1,
        sha256=hashlib.sha256(b'a').hexdigest(),
    )
    tenant_b = legacy_files.FileManifestEntry(
        source_relative_path='b.txt',
        destination_key='tenants/tenant-b/b.txt',
        size_bytes=1,
        sha256=hashlib.sha256(b'b').hexdigest(),
    )

    with pytest.raises(legacy_files.MigrationSafetyError, match='tenant'):
        legacy_files.merge_file_manifests((tenant_a,), (tenant_b,))


def test_file_reference_is_frozen_and_contains_no_business_row_value():
    reference = legacy_files.FileReference(
        source_table='resumes',
        source_column='file_url',
        destination_key='tenants/tenant-a/resumes/candidate.pdf',
    )

    assert reference.to_dict() == {
        'source_table': 'resumes',
        'source_column': 'file_url',
        'destination_key': 'tenants/tenant-a/resumes/candidate.pdf',
    }
    with pytest.raises(FrozenInstanceError):
        reference.source_table = 'users'


@pytest.mark.parametrize(
    'overrides',
    (
        {'source_table': ''},
        {'source_table': 'resume-items'},
        {'source_column': '../file_url'},
        {'destination_key': 'resumes/candidate.pdf'},
    ),
)
def test_file_reference_direct_construction_fails_closed(overrides):
    values = {
        'source_table': 'resumes',
        'source_column': 'file_url',
        'destination_key': 'tenants/tenant-a/resumes/candidate.pdf',
    }
    values.update(overrides)

    with pytest.raises(legacy_files.MigrationSafetyError):
        legacy_files.FileReference(**values)


def test_validate_manifest_references_reports_missing_hash_free_keys():
    manifest = (
        legacy_files.FileManifestEntry(
            source_relative_path='resumes/present.pdf',
            destination_key='tenants/tenant-a/resumes/present.pdf',
            size_bytes=7,
            sha256=hashlib.sha256(b'present').hexdigest(),
        ),
    )
    references = (
        legacy_files.FileReference(
            source_table='resumes',
            source_column='file_url',
            destination_key='tenants/tenant-a/resumes/present.pdf',
        ),
        legacy_files.FileReference(
            source_table='course_hours',
            source_column='video_key',
            destination_key='tenants/tenant-a/courses/missing.mp4',
        ),
    )

    report = legacy_files.validate_manifest_references(manifest, references)

    assert report.to_dict() == {
        'status': 'failed',
        'reference_count': 2,
        'referenced_keys': [
            'tenants/tenant-a/courses/missing.mp4',
            'tenants/tenant-a/resumes/present.pdf',
        ],
        'missing_keys': ['tenants/tenant-a/courses/missing.mp4'],
    }
    assert 'sha256' not in json.dumps(report.to_dict())


def test_validate_manifest_references_passes_for_an_empty_reference_set():
    report = legacy_files.validate_manifest_references((), ())

    assert report.to_dict() == {
        'status': 'passed',
        'reference_count': 0,
        'referenced_keys': [],
        'missing_keys': [],
    }


def test_copy_file_manifest_creates_files_and_reports_streamed_bytes(tmp_path):
    source_root = tmp_path / 'source'
    destination_root = tmp_path / 'destination'
    (source_root / 'docs').mkdir(parents=True)
    destination_root.mkdir()
    (source_root / 'a.txt').write_bytes(b'a')
    (source_root / 'docs' / 'b.txt').write_bytes(b'bbb')
    manifest = legacy_files.build_file_manifest(source_root, 'tenant-a')

    report = legacy_files.copy_file_manifest(
        manifest,
        source_root=source_root,
        destination_root=destination_root,
    )

    assert report.to_dict() == {
        'created_keys': [
            'tenants/tenant-a/a.txt',
            'tenants/tenant-a/docs/b.txt',
        ],
        'skipped_keys': [],
        'total_bytes': 4,
    }
    assert (
        destination_root / 'tenants' / 'tenant-a' / 'a.txt'
    ).read_bytes() == b'a'
    assert (
        destination_root / 'tenants' / 'tenant-a' / 'docs' / 'b.txt'
    ).read_bytes() == b'bbb'
    assert not list(destination_root.rglob('.legacy-migration-*.tmp'))


def test_copy_file_manifest_skips_an_existing_identical_hash(tmp_path):
    source_root = tmp_path / 'source'
    destination_root = tmp_path / 'destination'
    source_root.mkdir()
    existing = destination_root / 'tenants' / 'tenant-a' / 'a.txt'
    existing.parent.mkdir(parents=True)
    (source_root / 'a.txt').write_bytes(b'same')
    existing.write_bytes(b'same')
    manifest = legacy_files.build_file_manifest(source_root, 'tenant-a')

    report = legacy_files.copy_file_manifest(
        manifest,
        source_root=source_root,
        destination_root=destination_root,
    )

    assert report.to_dict() == {
        'created_keys': [],
        'skipped_keys': ['tenants/tenant-a/a.txt'],
        'total_bytes': 0,
    }
    assert existing.read_bytes() == b'same'


def test_copy_file_manifest_preflights_all_conflicts_before_any_write(
    tmp_path,
):
    source_root = tmp_path / 'source'
    destination_root = tmp_path / 'destination'
    source_root.mkdir()
    conflict = destination_root / 'tenants' / 'tenant-a' / 'z.txt'
    conflict.parent.mkdir(parents=True)
    (source_root / 'a.txt').write_bytes(b'new')
    (source_root / 'z.txt').write_bytes(b'wanted')
    conflict.write_bytes(b'existing-different')
    manifest = legacy_files.build_file_manifest(source_root, 'tenant-a')

    with pytest.raises(legacy_files.MigrationSafetyError, match='conflict'):
        legacy_files.copy_file_manifest(
            manifest,
            source_root=source_root,
            destination_root=destination_root,
        )

    assert not (
        destination_root / 'tenants' / 'tenant-a' / 'a.txt'
    ).exists()
    assert conflict.read_bytes() == b'existing-different'


def test_copy_file_manifest_preflights_source_hashes_before_any_write(tmp_path):
    source_root = tmp_path / 'source'
    destination_root = tmp_path / 'destination'
    source_root.mkdir()
    destination_root.mkdir()
    (source_root / 'a.txt').write_bytes(b'a')
    (source_root / 'z.txt').write_bytes(b'z')
    manifest = legacy_files.build_file_manifest(source_root, 'tenant-a')
    (source_root / 'z.txt').write_bytes(b'changed')

    with pytest.raises(legacy_files.MigrationSafetyError, match='source'):
        legacy_files.copy_file_manifest(
            manifest,
            source_root=source_root,
            destination_root=destination_root,
        )

    assert not list(destination_root.rglob('*'))


@pytest.mark.parametrize('destination_kind', ('same', 'child', 'parent'))
def test_copy_file_manifest_rejects_overlapping_source_and_destination_roots(
    tmp_path,
    destination_kind,
):
    parent_root = tmp_path / 'parent'
    source_root = parent_root / 'source'
    source_root.mkdir(parents=True)
    (source_root / 'a.txt').write_bytes(b'a')
    manifest = legacy_files.build_file_manifest(source_root, 'tenant-a')
    if destination_kind == 'same':
        destination_root = source_root
    elif destination_kind == 'child':
        destination_root = source_root / 'prepared'
        destination_root.mkdir()
    else:
        destination_root = parent_root

    with pytest.raises(legacy_files.MigrationSafetyError, match='overlap'):
        legacy_files.copy_file_manifest(
            manifest,
            source_root=source_root,
            destination_root=destination_root,
        )

    assert not (source_root / 'tenants').exists()


def test_copy_file_manifest_rejects_a_symlinked_destination_parent(tmp_path):
    source_root = tmp_path / 'source'
    destination_root = tmp_path / 'destination'
    outside_root = tmp_path / 'outside'
    (source_root / 'linked').mkdir(parents=True)
    tenant_root = destination_root / 'tenants' / 'tenant-a'
    tenant_root.mkdir(parents=True)
    outside_root.mkdir()
    (source_root / 'linked' / 'file.txt').write_bytes(b'private')
    link = tenant_root / 'linked'
    try:
        link.symlink_to(outside_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f'symlink creation unavailable: {exc}')
    manifest = legacy_files.build_file_manifest(source_root, 'tenant-a')

    with pytest.raises(legacy_files.MigrationSafetyError, match='symlink'):
        legacy_files.copy_file_manifest(
            manifest,
            source_root=source_root,
            destination_root=destination_root,
        )

    assert not (outside_root / 'file.txt').exists()


def test_copy_file_manifest_rolls_back_created_files_on_mid_copy_failure(
    tmp_path,
    monkeypatch,
):
    source_root = tmp_path / 'source'
    destination_root = tmp_path / 'destination'
    source_root.mkdir()
    destination_root.mkdir()
    (source_root / 'a.txt').write_bytes(b'a')
    (source_root / 'b.txt').write_bytes(b'b')
    manifest = legacy_files.build_file_manifest(source_root, 'tenant-a')
    real_link = legacy_files.os.link

    def fail_second_link(source, destination):
        if str(destination).endswith('b.txt'):
            raise OSError('simulated destination failure')
        return real_link(source, destination)

    monkeypatch.setattr(legacy_files.os, 'link', fail_second_link)

    with pytest.raises(legacy_files.MigrationSafetyError, match='copy'):
        legacy_files.copy_file_manifest(
            manifest,
            source_root=source_root,
            destination_root=destination_root,
        )

    assert not [path for path in destination_root.rglob('*') if path.is_file()]


def test_rollback_created_files_removes_only_hash_matching_created_keys(
    tmp_path,
):
    source_root = tmp_path / 'source'
    destination_root = tmp_path / 'destination'
    source_root.mkdir()
    existing = destination_root / 'tenants' / 'tenant-a' / 'b.txt'
    existing.parent.mkdir(parents=True)
    (source_root / 'a.txt').write_bytes(b'a')
    (source_root / 'b.txt').write_bytes(b'b')
    existing.write_bytes(b'b')
    manifest = legacy_files.build_file_manifest(source_root, 'tenant-a')
    report = legacy_files.copy_file_manifest(
        manifest,
        source_root=source_root,
        destination_root=destination_root,
    )

    removed = legacy_files.rollback_created_files(
        manifest,
        report,
        destination_root=destination_root,
    )

    assert removed == ('tenants/tenant-a/a.txt',)
    assert not (
        destination_root / 'tenants' / 'tenant-a' / 'a.txt'
    ).exists()
    assert existing.read_bytes() == b'b'


def test_rollback_created_files_preflights_tampering_before_any_delete(
    tmp_path,
):
    source_root = tmp_path / 'source'
    destination_root = tmp_path / 'destination'
    source_root.mkdir()
    destination_root.mkdir()
    (source_root / 'a.txt').write_bytes(b'a')
    (source_root / 'z.txt').write_bytes(b'z')
    manifest = legacy_files.build_file_manifest(source_root, 'tenant-a')
    report = legacy_files.copy_file_manifest(
        manifest,
        source_root=source_root,
        destination_root=destination_root,
    )
    created_a = destination_root / 'tenants' / 'tenant-a' / 'a.txt'
    created_z = destination_root / 'tenants' / 'tenant-a' / 'z.txt'
    created_z.write_bytes(b'tampered')

    with pytest.raises(legacy_files.MigrationSafetyError, match='changed'):
        legacy_files.rollback_created_files(
            manifest,
            report,
            destination_root=destination_root,
        )

    assert created_a.read_bytes() == b'a'
    assert created_z.read_bytes() == b'tampered'
