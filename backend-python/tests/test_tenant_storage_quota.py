from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from flask import g
from sqlalchemy.dialects import mysql

from models import (
    Certificate,
    Contract,
    Course,
    CourseAttachment,
    CourseChapter,
    CourseHour,
    Employee,
    Feedback,
    Interview,
    Job,
    LearningPath,
    Resume,
    Tenant,
    db,
)
from services import storage
from services.storage import StoredObject
from services.tenant_storage_quota import (
    StorageQuotaExceeded,
    StorageUsageUnavailable,
    enforce_storage_quota,
    tenant_storage_usage_bytes,
)
from tests.test_saas_tenancy import _client, saas_app


def test_storage_usage_includes_local_and_minio_bytes(monkeypatch, tmp_path):
    legacy_file = tmp_path / 'tenant-alpha' / 'legacy.bin'
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_bytes(b'1234')
    tenant_file = tmp_path / 'tenants' / 'tenant-alpha' / 'current.bin'
    tenant_file.parent.mkdir(parents=True)
    tenant_file.write_bytes(b'12')

    monkeypatch.setattr(
        storage,
        'list_tenant_objects',
        lambda tenant_id: [StoredObject(f'tenants/{tenant_id}/object.bin', 6)],
    )

    assert tenant_storage_usage_bytes('tenant-alpha', local_root=tmp_path) == 12


def test_list_tenant_objects_filters_out_other_tenant_prefixes(monkeypatch):
    class FakeClient:
        def list_objects(self, _bucket, *, prefix, recursive):
            assert prefix == 'tenants/tenant-alpha/'
            assert recursive is True
            return [
                SimpleNamespace(object_name='tenants/tenant-alpha/a.bin', size=6),
                SimpleNamespace(object_name='tenants/tenant-alpha/nested/b.bin', size=7),
                SimpleNamespace(object_name='tenants/tenant-beta/private.bin', size=1000),
                SimpleNamespace(object_name='tenants/tenant-alpha-malicious/private.bin', size=1000),
            ]

    monkeypatch.setattr(storage, '_get_client', lambda: FakeClient())

    assert storage.list_tenant_objects('tenant-alpha') == [
        StoredObject('tenants/tenant-alpha/a.bin', 6),
        StoredObject('tenants/tenant-alpha/nested/b.bin', 7),
    ]


def test_configured_object_storage_outage_fails_usage_measurement_closed(monkeypatch):
    monkeypatch.setattr(storage, '_MINIO_ENDPOINT', 'minio.internal:9000')
    monkeypatch.setattr(storage, '_MINIO_ACCESS_KEY', 'configured')
    monkeypatch.setattr(storage, '_MINIO_SECRET_KEY', 'configured')
    monkeypatch.setattr(storage, '_get_client', lambda: None)

    with pytest.raises(StorageUsageUnavailable) as caught:
        tenant_storage_usage_bytes('tenant-alpha')

    assert caught.value.code == 'STORAGE_USAGE_UNAVAILABLE'
    assert caught.value.status_code == 503


def test_upload_preflight_allows_exact_limit_and_rejects_one_byte_above(monkeypatch):
    tenant = SimpleNamespace(id='tenant-alpha', max_storage_mb=1)
    monkeypatch.setattr(
        'services.tenant_storage_quota.tenant_storage_usage_bytes',
        lambda *_args, **_kwargs: 1024 * 1024 - 1,
    )

    allowed = enforce_storage_quota(tenant, incoming_bytes=1)
    assert allowed.projected_bytes == 1024 * 1024

    with pytest.raises(StorageQuotaExceeded) as caught:
        enforce_storage_quota(tenant, incoming_bytes=2)

    assert caught.value.code == 'STORAGE_QUOTA_EXCEEDED'
    assert caught.value.status_code == 413
    assert caught.value.limit_bytes == 1024 * 1024
    assert caught.value.projected_bytes == 1024 * 1024 + 1


def test_same_tenant_concurrent_uploads_are_serialized_before_quota_measurement(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    measurement_barrier = threading.Barrier(2)
    start_barrier = threading.Barrier(2)
    object_lock = threading.Lock()
    objects = {}
    outcomes = []

    class FakeClient:
        def stat_object(self, _bucket, key):
            with object_lock:
                if key not in objects:
                    raise KeyError(key)
                return SimpleNamespace(size=len(objects[key]))

        def put_object(self, _bucket, key, data, *, length, content_type):
            payload = data.read()
            assert len(payload) == length
            with object_lock:
                objects[key] = payload

    def measured_usage(requested_tenant_id):
        with object_lock:
            used = sum(
                len(payload)
                for key, payload in objects.items()
                if key.startswith(f'tenants/{requested_tenant_id}/')
            )
        try:
            measurement_barrier.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass
        return used

    monkeypatch.setattr(storage, '_get_client', lambda: FakeClient())
    monkeypatch.setattr(
        storage,
        '_bound_tenant',
        lambda requested_tenant_id: SimpleNamespace(id=requested_tenant_id, max_storage_mb=1),
    )
    monkeypatch.setattr(
        'services.tenant_storage_quota.tenant_storage_usage_bytes',
        measured_usage,
    )

    def upload(index):
        with app.app_context():
            start_barrier.wait(timeout=2)
            try:
                storage.upload_file(
                    BytesIO(b'x' * (600 * 1024)),
                    f'concurrent/{index}.bin',
                    tenant_id=tenant_id,
                )
                db.session.commit()
                outcomes.append('stored')
            except StorageQuotaExceeded:
                db.session.rollback()
                outcomes.append('quota')
            finally:
                db.session.remove()

    threads = [threading.Thread(target=upload, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ['quota', 'stored']
    assert sum(len(payload) for payload in objects.values()) == 600 * 1024


def test_tenant_storage_write_lock_uses_mysql_row_lock_contract():
    statement = storage._tenant_write_lock_statement('tenant-alpha')
    sql = str(statement.compile(
        dialect=mysql.dialect(),
        compile_kwargs={'literal_binds': True},
    ))

    assert 'FROM tenants' in sql
    assert "WHERE tenants.id = 'tenant-alpha'" in sql
    assert sql.rstrip().endswith('FOR UPDATE')


def test_different_tenant_uploads_remain_concurrent(monkeypatch, saas_app):
    app, tokens = saas_app
    measurement_barrier = threading.Barrier(2)
    start_barrier = threading.Barrier(2)
    outcomes = []

    class FakeClient:
        def stat_object(self, _bucket, key):
            raise KeyError(key)

        def put_object(self, _bucket, key, data, *, length, content_type):
            assert len(data.read()) == length

    def measured_usage(_tenant_id):
        measurement_barrier.wait(timeout=1)
        return 0

    monkeypatch.setattr(storage, '_get_client', lambda: FakeClient())
    monkeypatch.setattr(
        storage,
        '_bound_tenant',
        lambda tenant_id: SimpleNamespace(id=tenant_id, max_storage_mb=1),
    )
    monkeypatch.setattr(
        'services.tenant_storage_quota.tenant_storage_usage_bytes',
        measured_usage,
    )

    def upload(tenant_id):
        with app.app_context():
            start_barrier.wait(timeout=2)
            try:
                storage.upload_file(
                    BytesIO(b'concurrent'),
                    'concurrent/object.bin',
                    tenant_id=tenant_id,
                )
                db.session.commit()
                outcomes.append(tenant_id)
            finally:
                db.session.remove()

    threads = [
        threading.Thread(target=upload, args=(tokens['alpha_id'],)),
        threading.Thread(target=upload, args=(tokens['beta_id'],)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert sorted(outcomes) == sorted([tokens['alpha_id'], tokens['beta_id']])
    assert not measurement_barrier.broken


def test_feedback_upload_without_business_commit_releases_tenant_write_lease_at_teardown(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    monkeypatch.setattr(storage, '_get_client', lambda: None)
    monkeypatch.setattr(storage, '_object_storage_configured', lambda: False)

    response = _client(app, tokens['alpha']).post(
        '/api/hrm/feedback-attachments',
        data={'file': (BytesIO(b'feedback'), 'feedback.txt')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 201, response.get_json()
    local_lock = storage._local_tenant_write_lock(tokens['alpha_id'])
    assert local_lock.acquire(blocking=False)
    local_lock.release()


def test_replacement_upload_subtracts_existing_object_size(monkeypatch):
    tenant = SimpleNamespace(id='tenant-alpha', max_storage_mb=1)
    monkeypatch.setattr(
        'services.tenant_storage_quota.tenant_storage_usage_bytes',
        lambda *_args, **_kwargs: 1024 * 1024,
    )

    snapshot = enforce_storage_quota(
        tenant,
        incoming_bytes=256,
        replacing_bytes=256,
    )

    assert snapshot.used_bytes == 1024 * 1024
    assert snapshot.projected_bytes == 1024 * 1024


def test_storage_upload_preflight_uses_stream_size_and_existing_object(monkeypatch, saas_app):
    app, tokens = saas_app
    calls = []

    class FakeClient:
        def stat_object(self, _bucket, key):
            assert key == f"tenants/{tokens['alpha_id']}/same.bin"
            return SimpleNamespace(size=4)

        def put_object(self, _bucket, key, data, *, length, content_type):
            calls.append((key, data.read(), length, content_type))

    monkeypatch.setattr(storage, '_get_client', lambda: FakeClient())
    monkeypatch.setattr(
        'services.tenant_storage_quota.enforce_storage_quota',
        lambda tenant, *, incoming_bytes, replacing_bytes=0: calls.append(
            ('quota', tenant.id, incoming_bytes, replacing_bytes)
        ),
    )

    with app.app_context(), app.test_request_context('/'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        g.tenant_id = tenant.id
        g.tenant = tenant
        stream = BytesIO(b'new-value')
        key = storage.upload_file(stream, 'same.bin', content_type='application/test')

    assert key == f"tenants/{tokens['alpha_id']}/same.bin"
    assert calls == [
        ('quota', tokens['alpha_id'], 9, 4),
        (f"tenants/{tokens['alpha_id']}/same.bin", b'new-value', 9, 'application/test'),
    ]


def test_versioned_upload_accounts_for_replaced_object_size(monkeypatch, saas_app):
    app, tokens = saas_app
    calls = []
    old_key = f"tenants/{tokens['alpha_id']}/courses/hour-old.mp4"

    class FakeClient:
        def stat_object(self, _bucket, key):
            assert key == old_key
            return SimpleNamespace(size=4)

        def put_object(self, _bucket, key, data, *, length, content_type):
            calls.append((key, data.read(), length, content_type))

    monkeypatch.setattr(storage, '_get_client', lambda: FakeClient())
    monkeypatch.setattr(
        'services.tenant_storage_quota.enforce_storage_quota',
        lambda tenant, *, incoming_bytes, replacing_bytes=0: calls.append(
            ('quota', tenant.id, incoming_bytes, replacing_bytes)
        ),
    )

    with app.app_context(), app.test_request_context('/'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        g.tenant_id = tenant.id
        g.tenant = tenant
        key = storage.upload_file(
            BytesIO(b'new-value'),
            'courses/hour-versioned.mp4',
            content_type='video/mp4',
            replacing_object_key=old_key,
        )

    new_key = f"tenants/{tokens['alpha_id']}/courses/hour-versioned.mp4"
    assert key == new_key
    assert calls == [
        ('quota', tokens['alpha_id'], 9, 4),
        (new_key, b'new-value', 9, 'video/mp4'),
    ]


@pytest.mark.parametrize(
    ('case', 'expected_replacing_bytes'),
    [
        ('shared-versioned', 0),
        ('legacy-unprefixed', 0),
        ('same-key-overwrite', 4),
    ],
)
def test_replacement_quota_credit_requires_counted_unreferenced_old_object(
    monkeypatch,
    saas_app,
    case,
    expected_replacing_bytes,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    if case == 'legacy-unprefixed':
        old_key = 'legacy/quota/old.mp4'
        target_key = 'courses/quota/versioned.mp4'
    elif case == 'same-key-overwrite':
        old_key = f'tenants/{tenant_id}/same-key-overwrite.bin'
        target_key = 'same-key-overwrite.bin'
    else:
        old_key = f'tenants/{tenant_id}/courses/quota/shared-old.mp4'
        target_key = 'courses/quota/versioned.mp4'

    with app.app_context():
        course = Course(id=f'quota-credit-course-{case}', tenant_id=tenant_id, title=f'配额抵扣 {case}')
        first = CourseHour(
            id=f'quota-credit-first-{case}',
            tenant_id=tenant_id,
            course_id=course.id,
            title='配额抵扣课时一',
            video_key=old_key,
        )
        rows = [course, first]
        if case in {'shared-versioned', 'same-key-overwrite'}:
            rows.append(CourseHour(
                id=f'quota-credit-second-{case}',
                tenant_id=tenant_id,
                course_id=course.id,
                title='配额抵扣课时二',
                video_key=old_key,
            ))
        db.session.add_all(rows)
        db.session.commit()

    calls = []

    class FakeClient:
        def stat_object(self, _bucket, key):
            calls.append(('stat', key))
            return SimpleNamespace(size=4)

        def put_object(self, _bucket, key, data, *, length, content_type):
            calls.append(('write', key, data.read(), length, content_type))

    monkeypatch.setattr(storage, '_get_client', lambda: FakeClient())
    monkeypatch.setattr(
        'services.tenant_storage_quota.enforce_storage_quota',
        lambda tenant, *, incoming_bytes, replacing_bytes=0: calls.append(
            ('quota', tenant.id, incoming_bytes, replacing_bytes)
        ),
    )
    with app.app_context(), app.test_request_context('/'):
        tenant = db.session.get(Tenant, tenant_id)
        g.tenant_id = tenant.id
        g.tenant = tenant
        storage.upload_file(
            BytesIO(b'new-value'),
            target_key,
            replacing_object_key=old_key,
        )

    quota_call = next(call for call in calls if call[0] == 'quota')
    assert quota_call == ('quota', tenant_id, 9, expected_replacing_bytes)


def test_rejected_upload_preserves_stream_position_and_does_not_write(monkeypatch, saas_app):
    app, tokens = saas_app
    put_calls = []

    class FakeClient:
        def stat_object(self, _bucket, _key):
            raise KeyError('missing')

        def put_object(self, *_args, **_kwargs):
            put_calls.append((_args, _kwargs))

    def reject(*_args, **_kwargs):
        raise StorageQuotaExceeded(limit_bytes=10, used_bytes=10, projected_bytes=13)

    monkeypatch.setattr(storage, '_get_client', lambda: FakeClient())
    monkeypatch.setattr('services.tenant_storage_quota.enforce_storage_quota', reject)

    with app.app_context(), app.test_request_context('/'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        g.tenant_id = tenant.id
        g.tenant = tenant
        stream = BytesIO(b'012345')
        stream.seek(2)
        with pytest.raises(StorageQuotaExceeded):
            storage.upload_file(stream, 'rejected.bin')

    assert stream.tell() == 2
    assert put_calls == []


def test_storage_write_rejects_cross_tenant_prefixed_key_without_exposing_key(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    writes = []

    class FakeClient:
        def put_object(self, *_args, **_kwargs):
            writes.append((_args, _kwargs))

    monkeypatch.setattr(storage, '_get_client', lambda: FakeClient())
    with app.app_context(), app.test_request_context('/'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        g.tenant_id = tenant.id
        g.tenant = tenant
        foreign_key = f"tenants/{tokens['beta_id']}/secret.pdf"
        with pytest.raises(ValueError) as caught:
            storage.upload_file(BytesIO(b'private'), foreign_key)

    assert getattr(caught.value, 'code', None) == 'STORAGE_CROSS_TENANT_KEY'
    assert tokens['alpha_id'] not in str(caught.value)
    assert tokens['beta_id'] not in str(caught.value)
    assert 'secret.pdf' not in str(caught.value)
    assert writes == []


def test_storage_write_rejects_windows_separator_traversal():
    with pytest.raises(ValueError, match='非法 object key'):
        storage.tenant_object_key(
            r'courses\..\..\tenant-beta\secret.pdf',
            tenant_id='tenant-alpha',
        )


def test_local_storage_write_cannot_escape_tenant_directory_with_backslashes(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(storage, '_upload_folder', lambda: tmp_path)
    monkeypatch.setattr(storage, '_enforce_tenant_quota', lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match='非法 object key'):
        storage.save_local_upload(
            SimpleNamespace(save=lambda destination: Path(destination).write_bytes(b'private')),
            r'courses\..\..\tenant-beta\secret.pdf',
            tenant_id='tenant-alpha',
        )

    assert not (tmp_path / 'tenants' / 'tenant-beta' / 'secret.pdf').exists()


def test_non_request_storage_write_requires_explicit_tenant_binding(monkeypatch, saas_app):
    app, _tokens = saas_app
    writes = []

    class FakeClient:
        def put_object(self, *_args, **_kwargs):
            writes.append((_args, _kwargs))

    monkeypatch.setattr(storage, '_get_client', lambda: FakeClient())
    with app.app_context():
        with pytest.raises(ValueError) as caught:
            storage.upload_file(BytesIO(b'unscoped'), 'imports/unscoped.bin')

    assert getattr(caught.value, 'code', None) == 'STORAGE_TENANT_BINDING_REQUIRED'
    assert writes == []


def test_non_request_storage_write_accepts_explicit_existing_tenant(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    calls = []

    class FakeClient:
        def stat_object(self, _bucket, _key):
            raise KeyError('missing')

        def put_object(self, _bucket, key, data, *, length, content_type):
            calls.append(('write', key, data.read(), length, content_type))

    monkeypatch.setattr(storage, '_get_client', lambda: FakeClient())
    monkeypatch.setattr(
        'services.tenant_storage_quota.enforce_storage_quota',
        lambda tenant, *, incoming_bytes, replacing_bytes=0: calls.append(
            ('quota', tenant.id, incoming_bytes, replacing_bytes)
        ),
    )
    with app.app_context():
        key = storage.upload_file(
            BytesIO(b'bound'),
            'imports/bound.bin',
            tenant_id=tokens['alpha_id'],
        )

    expected = f"tenants/{tokens['alpha_id']}/imports/bound.bin"
    assert key == expected
    assert calls == [
        ('quota', tokens['alpha_id'], 5, 0),
        ('write', expected, b'bound', 5, 'application/octet-stream'),
    ]


def test_unscoped_storage_write_requires_explicit_controlled_bypass(monkeypatch, saas_app):
    app, _tokens = saas_app
    writes = []

    class FakeClient:
        def stat_object(self, _bucket, _key):
            raise KeyError('missing')

        def put_object(self, _bucket, key, data, *, length, content_type):
            writes.append((key, data.read(), length, content_type))

    monkeypatch.setattr(storage, '_get_client', lambda: FakeClient())
    with app.app_context():
        key = storage.upload_file(
            BytesIO(b'controlled'),
            'controlled/system.bin',
            allow_unscoped=True,
        )

    assert key == 'controlled/system.bin'
    assert writes == [('controlled/system.bin', b'controlled', 10, 'application/octet-stream')]


def test_spc_import_requires_tenant_and_passes_it_to_storage(monkeypatch, tmp_path):
    from scripts import import_spc_course

    with pytest.raises(SystemExit):
        import_spc_course.parse_args([])

    args = import_spc_course.parse_args(['--tenant-id', 'tenant-alpha'])
    assert args.tenant_id == 'tenant-alpha'

    video = tmp_path / 'lesson.mp4'
    video.write_bytes(b'video')
    calls = []
    monkeypatch.setattr(
        import_spc_course.storage,
        'upload_video',
        lambda stream, key, *, content_type, tenant_id: calls.append(
            (stream.read(), key, content_type, tenant_id)
        ) or f'tenants/{tenant_id}/{key}',
    )

    stored_key = import_spc_course.upload_training_video(
        str(video),
        'courses/course/hour.mp4',
        tenant_id=args.tenant_id,
    )

    assert stored_key == 'tenants/tenant-alpha/courses/course/hour.mp4'
    assert calls == [
        (b'video', 'courses/course/hour.mp4', 'video/mp4', 'tenant-alpha'),
    ]


def test_spc_import_final_commit_failure_deletes_all_new_staged_objects(
    monkeypatch,
    saas_app,
):
    from scripts import import_spc_course

    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    staged_keys = [
        f'tenants/{tenant_id}/courses/import/hour-a.mp4',
        f'tenants/{tenant_id}/courses/import/hour-b.mp4',
    ]
    deleted = []
    monkeypatch.setattr(storage, 'delete_object', deleted.append)
    with app.app_context():
        monkeypatch.setattr(
            db.session,
            'commit',
            lambda: (_ for _ in ()).throw(RuntimeError('SPC final commit failed')),
        )
        with pytest.raises(RuntimeError, match='SPC final commit failed'):
            import_spc_course.commit_import(
                staged_keys,
                tenant_id=tenant_id,
            )

    assert deleted == staged_keys


def test_generated_certificate_cannot_bypass_tenant_storage_quota(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']

    monkeypatch.setattr(storage, '_get_client', lambda: None)
    monkeypatch.setattr(
        'services.certificate.render_certificate_png',
        lambda path, **_kwargs: Path(path).write_bytes(b'certificate'),
    )

    with app.app_context(), app.test_request_context('/'):
        tenant = db.session.get(Tenant, tenant_id)
        tenant.max_storage_mb = 1
        employee = Employee(
            id='quota-certificate-employee',
            tenant_id=tenant_id,
            employee_no='CERT-EMP-1',
            name='证书配额员工',
        )
        course = Course(
            id='quota-certificate-course',
            tenant_id=tenant_id,
            title='证书配额课程',
        )
        db.session.add_all([employee, course])
        used = Path(app.config['UPLOAD_FOLDER']) / 'tenants' / tenant_id / 'used.bin'
        used.parent.mkdir(parents=True, exist_ok=True)
        used.write_bytes(b'x' * (1024 * 1024))
        db.session.commit()
        g.tenant_id = tenant.id
        g.tenant = tenant

        from services.certificate import generate_certificate

        with pytest.raises(StorageQuotaExceeded):
            generate_certificate(employee.id, course.id)

        assert Certificate.query.filter_by(employee_id=employee.id, course_id=course.id).count() == 0
        certificate_root = Path(app.config['UPLOAD_FOLDER']) / 'tenants' / tenant_id / 'certificates'
        assert not certificate_root.exists() or not any(certificate_root.iterdir())


def test_generated_certificate_uses_employee_tenant_outside_request_context(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    monkeypatch.setattr(storage, '_get_client', lambda: None)
    monkeypatch.setattr(
        'services.certificate.render_certificate_png',
        lambda path, **_kwargs: Path(path).write_bytes(b'certificate'),
    )

    with app.app_context():
        employee = Employee(
            id='bound-certificate-employee',
            tenant_id=tenant_id,
            employee_no='BOUND-CERT-1',
            name='显式企业证书员工',
        )
        course = Course(
            id='bound-certificate-course',
            tenant_id=tenant_id,
            title='显式企业证书课程',
        )
        db.session.add_all([employee, course])
        db.session.commit()

        from services.certificate import generate_certificate

        certificate = generate_certificate(employee.id, course.id)

        assert certificate.tenant_id == tenant_id
        assert certificate.image_url.startswith(f'/uploads/tenants/{tenant_id}/certificates/')


def test_certificate_commit_failure_deletes_new_staged_object(monkeypatch, saas_app):
    from services import certificate as certificate_service

    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    staged_key = f'tenants/{tenant_id}/certificates/staged-certificate.png'
    employee_id = 'certificate-compensation-employee'
    course_id = 'certificate-compensation-course'
    with app.app_context():
        employee = Employee(
            id=employee_id,
            tenant_id=tenant_id,
            employee_no='CERT-COMPENSATION',
            name='证书补偿员工',
        )
        course = Course(
            id=course_id,
            tenant_id=tenant_id,
            title='证书补偿课程',
        )
        db.session.add_all([employee, course])
        db.session.commit()

    deleted = []
    monkeypatch.setattr(
        certificate_service,
        'render_certificate_png',
        lambda path, **_kwargs: Path(path).write_bytes(b'certificate'),
    )
    monkeypatch.setattr(storage, 'upload_file', lambda *_args, **_kwargs: staged_key)
    monkeypatch.setattr(storage, 'delete_object', deleted.append)
    with app.app_context():
        monkeypatch.setattr(
            db.session,
            'commit',
            lambda: (_ for _ in ()).throw(RuntimeError('certificate commit failed')),
        )
        with pytest.raises(RuntimeError, match='certificate commit failed'):
            certificate_service.generate_certificate(employee_id, course_id)
        db.session.rollback()
        assert Certificate.query.filter_by(
            employee_id=employee_id,
            course_id=course_id,
        ).count() == 0

    assert deleted == [staged_key]


def test_upload_route_returns_stable_413_when_tenant_quota_is_exceeded(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    with app.app_context():
        tenant = db.session.get(Tenant, tenant_id)
        tenant.max_storage_mb = 1
        used = Path(app.config['UPLOAD_FOLDER']) / 'tenants' / tenant_id / 'used.bin'
        used.parent.mkdir(parents=True, exist_ok=True)
        used.write_bytes(b'x' * (1024 * 1024))
        db.session.commit()

    monkeypatch.setattr(storage, '_get_client', lambda: None)
    response = _client(app, tokens['alpha']).post(
        '/api/hrm/feedback-attachments',
        data={'file': (BytesIO(b'x'), 'quota.txt')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 413, response.get_json()
    assert response.get_json() == {
        'code': 'STORAGE_QUOTA_EXCEEDED',
        'error': '企业存储空间已达上限，请删除文件或联系平台管理员扩容',
        'limitBytes': 1024 * 1024,
        'projectedBytes': 1024 * 1024 + 1,
        'usedBytes': 1024 * 1024,
    }


def test_upload_route_returns_stable_503_when_configured_storage_usage_is_unavailable(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    monkeypatch.setattr(storage, '_MINIO_ENDPOINT', 'minio.internal:9000')
    monkeypatch.setattr(storage, '_MINIO_ACCESS_KEY', 'configured')
    monkeypatch.setattr(storage, '_MINIO_SECRET_KEY', 'configured')
    monkeypatch.setattr(storage, '_get_client', lambda: None)

    response = _client(app, tokens['alpha']).post(
        '/api/hrm/feedback-attachments',
        data={'file': (BytesIO(b'x'), 'storage-down.txt')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 503
    assert response.get_json() == {
        'code': 'STORAGE_USAGE_UNAVAILABLE',
        'error': '对象存储用量暂时无法校验，本次上传已安全阻止',
    }


def _quota_error() -> StorageQuotaExceeded:
    return StorageQuotaExceeded(limit_bytes=10, used_bytes=10, projected_bytes=11)


def _usage_error() -> StorageUsageUnavailable:
    return StorageUsageUnavailable()


def test_course_video_does_not_translate_storage_quota_error_to_500(monkeypatch, saas_app):
    app, tokens = saas_app
    with app.app_context():
        course = Course(
            id='quota-video-course',
            tenant_id=tokens['alpha_id'],
            title='配额视频课程',
        )
        hour = CourseHour(
            id='quota-video-hour',
            tenant_id=tokens['alpha_id'],
            course_id=course.id,
            title='配额视频课时',
        )
        db.session.add_all([course, hour])
        db.session.commit()

    monkeypatch.setattr(
        storage,
        'upload_video',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_quota_error()),
    )
    response = _client(app, tokens['alpha']).post(
        '/api/hrm/course-hours/quota-video-hour/upload-video',
        data={'file': (BytesIO(b'v'), 'course.mp4')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 413, response.get_json()
    assert response.get_json()['code'] == 'STORAGE_QUOTA_EXCEEDED'


def test_course_video_does_not_translate_storage_usage_outage_to_500(monkeypatch, saas_app):
    app, tokens = saas_app
    with app.app_context():
        course = Course(
            id='unavailable-video-course',
            tenant_id=tokens['alpha_id'],
            title='存储不可用视频课程',
        )
        hour = CourseHour(
            id='unavailable-video-hour',
            tenant_id=tokens['alpha_id'],
            course_id=course.id,
            title='存储不可用视频课时',
        )
        db.session.add_all([course, hour])
        db.session.commit()

    monkeypatch.setattr(
        storage,
        'upload_video',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_usage_error()),
    )
    response = _client(app, tokens['alpha']).post(
        '/api/hrm/course-hours/unavailable-video-hour/upload-video',
        data={'file': (BytesIO(b'v'), 'course.mp4')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 503, response.get_json()
    assert response.get_json()['code'] == 'STORAGE_USAGE_UNAVAILABLE'


def test_resume_batch_does_not_swallow_storage_quota_error(monkeypatch, saas_app):
    app, tokens = saas_app
    app.config['ALLOWED_EXTENSIONS'] = {'pdf'}
    with app.app_context():
        db.session.add(Job(
            id='quota-resume-job',
            tenant_id=tokens['alpha_id'],
            title='配额简历岗位',
            status='open',
        ))
        db.session.commit()

    monkeypatch.setattr(
        'routes.resumes._require_resume_ai',
        lambda _use_case: SimpleNamespace(resource_domain='resume_ai'),
    )
    monkeypatch.setattr('routes.resumes.is_minio_enabled', lambda: True)
    monkeypatch.setattr(
        'routes.resumes.upload_file',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_quota_error()),
    )
    response = _client(app, tokens['alpha']).post(
        '/api/resumes/upload',
        data={
            'jobId': 'quota-resume-job',
            'file': (BytesIO(b'%PDF'), 'candidate.pdf'),
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 413
    assert response.get_json()['code'] == 'STORAGE_QUOTA_EXCEEDED'


def test_resume_batch_does_not_swallow_storage_usage_outage(monkeypatch, saas_app):
    app, tokens = saas_app
    app.config['ALLOWED_EXTENSIONS'] = {'pdf'}
    with app.app_context():
        db.session.add(Job(
            id='unavailable-resume-job',
            tenant_id=tokens['alpha_id'],
            title='存储不可用简历岗位',
            status='open',
        ))
        db.session.commit()

    monkeypatch.setattr(
        'routes.resumes._require_resume_ai',
        lambda _use_case: SimpleNamespace(resource_domain='resume_ai'),
    )
    monkeypatch.setattr('routes.resumes.is_minio_enabled', lambda: True)
    monkeypatch.setattr(
        'routes.resumes.upload_file',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_usage_error()),
    )
    response = _client(app, tokens['alpha']).post(
        '/api/resumes/upload',
        data={
            'jobId': 'unavailable-resume-job',
            'file': (BytesIO(b'%PDF'), 'candidate.pdf'),
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 503, response.get_json()
    assert response.get_json()['code'] == 'STORAGE_USAGE_UNAVAILABLE'


@pytest.mark.parametrize('failure_point', ['parse', 'ai'])
def test_resume_post_upload_failure_deletes_only_new_staged_object(
    monkeypatch,
    saas_app,
    failure_point,
):
    from routes import resumes as resumes_route

    app, tokens = saas_app
    app.config['ALLOWED_EXTENSIONS'] = {'pdf'}
    tenant_id = tokens['alpha_id']
    with app.app_context():
        db.session.add(Job(
            id=f'resume-compensation-job-{failure_point}',
            tenant_id=tenant_id,
            title='简历补偿岗位',
            status='open',
        ))
        db.session.commit()

    staged = []
    deleted = []

    def fake_upload(_stream, key, **_kwargs):
        staged_key = f'tenants/{tenant_id}/{key}'
        staged.append(staged_key)
        return staged_key

    def fake_download(_key, path):
        Path(path).write_bytes(b'%PDF')
        return Path(path)

    monkeypatch.setattr(resumes_route, '_require_resume_ai', lambda _use: SimpleNamespace(resource_domain='resume'))
    monkeypatch.setattr(resumes_route, 'is_minio_enabled', lambda: True)
    monkeypatch.setattr(resumes_route, 'upload_file', fake_upload)
    monkeypatch.setattr(resumes_route, 'download_to_file', fake_download)
    monkeypatch.setattr(resumes_route, 'delete_object', deleted.append, raising=False)
    if failure_point == 'parse':
        monkeypatch.setattr(
            resumes_route,
            'extract_text_from_file',
            lambda _path: (_ for _ in ()).throw(RuntimeError('parse failed')),
        )
    else:
        monkeypatch.setattr(resumes_route, 'extract_text_from_file', lambda _path: 'resume text')
        monkeypatch.setattr(
            resumes_route,
            'analyze_resume',
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('ai failed')),
        )

    response = _client(app, tokens['alpha']).post(
        '/api/resumes/upload',
        data={
            'jobId': f'resume-compensation-job-{failure_point}',
            'file': (BytesIO(b'%PDF'), f'{failure_point}.pdf'),
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 400, response.get_json()
    assert len(staged) == 1
    assert deleted == staged
    with app.app_context():
        assert Resume.query.filter_by(job_id=f'resume-compensation-job-{failure_point}').count() == 0


def test_interview_recording_does_not_translate_storage_quota_error_to_500(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    with app.app_context():
        job = Job(
            id='quota-interview-job',
            tenant_id=tokens['alpha_id'],
            title='配额面试岗位',
            status='open',
        )
        resume = Resume(
            id='quota-interview-resume',
            tenant_id=tokens['alpha_id'],
            candidate_name='配额候选人',
            file_url='/uploads/quota.pdf',
        )
        interview = Interview(
            id='quota-interview',
            tenant_id=tokens['alpha_id'],
            job_id=job.id,
            resume_id=resume.id,
            scheduled_at=datetime.utcnow(),
            status='scheduled',
        )
        db.session.add_all([job, resume, interview])
        db.session.commit()

    monkeypatch.setattr(
        'routes.interviews.save_local_upload',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_quota_error()),
    )
    response = _client(app, tokens['alpha']).post(
        '/api/interviews/quota-interview/recording',
        data={'file': (BytesIO(b'audio'), 'recording.mp3')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 413
    assert response.get_json()['code'] == 'STORAGE_QUOTA_EXCEEDED'


@pytest.mark.parametrize(
    ('route_suffix', 'use_case'),
    [
        ('analyze/media', 'interview_analysis'),
        ('recording', None),
    ],
)
def test_interview_uploads_do_not_translate_storage_usage_outage_to_500(
    monkeypatch,
    saas_app,
    route_suffix,
    use_case,
):
    app, tokens = saas_app
    with app.app_context():
        job = Job(
            id=f'unavailable-interview-job-{route_suffix.replace("/", "-")}',
            tenant_id=tokens['alpha_id'],
            title='存储不可用面试岗位',
            status='open',
        )
        resume = Resume(
            id=f'unavailable-interview-resume-{route_suffix.replace("/", "-")}',
            tenant_id=tokens['alpha_id'],
            candidate_name='存储不可用候选人',
            file_url='/uploads/unavailable.pdf',
        )
        interview = Interview(
            id=f'unavailable-interview-{route_suffix.replace("/", "-")}',
            tenant_id=tokens['alpha_id'],
            job_id=job.id,
            resume_id=resume.id,
            scheduled_at=datetime.utcnow(),
            status='scheduled',
        )
        db.session.add_all([job, resume, interview])
        db.session.commit()
        interview_id = interview.id

    if use_case:
        monkeypatch.setattr(
            'routes.interviews._require_interview_ai',
            lambda requested: SimpleNamespace(resource_domain=requested),
        )
    monkeypatch.setattr(
        'routes.interviews.save_local_upload',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_usage_error()),
    )
    response = _client(app, tokens['alpha']).post(
        f'/api/interviews/{interview_id}/{route_suffix}',
        data={'file': (BytesIO(b'audio'), 'recording.mp3')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 503, response.get_json()
    assert response.get_json()['code'] == 'STORAGE_USAGE_UNAVAILABLE'


def test_course_cover_replacement_deletes_old_object_only_after_commit(monkeypatch, saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    old_key = f'tenants/{tenant_id}/courses/release-cover/old.png'
    new_key = f'tenants/{tenant_id}/courses/release-cover/new.png'
    with app.app_context():
        db.session.add(Course(
            id='release-cover-course',
            tenant_id=tenant_id,
            title='替换封面课程',
            cover_url=f'/uploads/{old_key}',
        ))
        db.session.commit()

    events = []
    monkeypatch.setattr(storage, 'save_local_upload', lambda *_args, **_kwargs: new_key)
    monkeypatch.setattr(storage, 'delete_object', lambda key: events.append(('delete', key)))
    with app.app_context():
        original_commit = db.session.commit

        def tracked_commit():
            result = original_commit()
            events.append(('commit', None))
            return result

        monkeypatch.setattr(db.session, 'commit', tracked_commit)
        response = _client(app, tokens['alpha']).post(
            '/api/hrm/courses/release-cover-course/upload-cover',
            data={'file': (BytesIO(b'new'), 'cover.png')},
            content_type='multipart/form-data',
        )

    assert response.status_code == 200, response.get_json()
    assert events == [('commit', None), ('delete', old_key)]


@pytest.mark.parametrize('upload_kind', ['cover', 'material'])
def test_course_file_commit_failure_deletes_only_new_staged_object(
    monkeypatch,
    saas_app,
    upload_kind,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    old_key = f'tenants/{tenant_id}/courses/commit-failure/{upload_kind}-old.bin'
    staged_key = f'tenants/{tenant_id}/courses/commit-failure/{upload_kind}-new.bin'
    with app.app_context():
        course = Course(
            id=f'commit-failure-course-{upload_kind}',
            tenant_id=tenant_id,
            title='课程文件提交补偿',
            cover_url=f'/uploads/{old_key}' if upload_kind == 'cover' else None,
        )
        rows = [course]
        if upload_kind == 'material':
            chapter = CourseChapter(
                id='commit-failure-material-chapter',
                tenant_id=tenant_id,
                course_id=course.id,
                name='课程资料提交补偿',
                materials=[{'title': '旧资料', 'url': f'/uploads/{old_key}', 'ext': 'pdf'}],
            )
            rows.append(chapter)
        db.session.add_all(rows)
        db.session.commit()

    deleted = []
    monkeypatch.setattr(storage, 'save_local_upload', lambda *_args, **_kwargs: staged_key)
    monkeypatch.setattr(storage, 'delete_object', deleted.append)
    with app.app_context():
        monkeypatch.setattr(
            db.session,
            'commit',
            lambda: (_ for _ in ()).throw(RuntimeError(f'{upload_kind} commit failed')),
        )
        if upload_kind == 'cover':
            path = f'/api/hrm/courses/commit-failure-course-{upload_kind}/upload-cover'
            data = {'file': (BytesIO(b'image'), 'cover.png')}
        else:
            path = '/api/hrm/course-chapters/commit-failure-material-chapter/upload-material'
            data = {'file': (BytesIO(b'material'), 'material.pdf'), 'title': '新资料'}
        with pytest.raises(RuntimeError, match=f'{upload_kind} commit failed'):
            _client(app, tokens['alpha']).post(
                path,
                data=data,
                content_type='multipart/form-data',
            )
        db.session.rollback()
        if upload_kind == 'cover':
            assert db.session.get(Course, f'commit-failure-course-{upload_kind}').cover_url == f'/uploads/{old_key}'
        else:
            assert db.session.get(CourseChapter, 'commit-failure-material-chapter').materials == [
                {'title': '旧资料', 'url': f'/uploads/{old_key}', 'ext': 'pdf'},
            ]

    assert deleted == [staged_key]


def test_removed_chapter_material_releases_storage_and_retained_material_does_not(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    removed_key = f'tenants/{tenant_id}/chapters/materials/remove.pdf'
    retained_key = f'tenants/{tenant_id}/chapters/materials/keep.pdf'
    with app.app_context():
        course = Course(id='materials-course', tenant_id=tenant_id, title='资料课程')
        chapter = CourseChapter(
            id='materials-chapter',
            tenant_id=tenant_id,
            course_id=course.id,
            name='资料章节',
            materials=[
                {'title': '移除', 'url': f'/uploads/{removed_key}', 'ext': 'pdf'},
                {'title': '保留', 'url': f'/uploads/{retained_key}', 'ext': 'pdf'},
            ],
        )
        db.session.add_all([course, chapter])
        db.session.commit()

    deleted = []
    monkeypatch.setattr(storage, 'delete_object', deleted.append)
    response = _client(app, tokens['alpha']).put(
        '/api/hrm/course-chapters/materials-chapter/materials',
        json={
            'materials': [
                {'title': '保留', 'url': f'/uploads/{retained_key}', 'ext': 'pdf'},
            ],
        },
    )

    assert response.status_code == 200, response.get_json()
    assert deleted == [removed_key]


def test_course_hour_video_key_change_releases_old_object(monkeypatch, saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    old_key = f'tenants/{tenant_id}/courses/video-change/old.webm'
    new_key = f'tenants/{tenant_id}/courses/video-change/new.mp4'
    with app.app_context():
        course = Course(id='video-change-course', tenant_id=tenant_id, title='换视频课程')
        hour = CourseHour(
            id='video-change-hour',
            tenant_id=tenant_id,
            course_id=course.id,
            title='换视频课时',
            video_key=old_key,
        )
        db.session.add_all([course, hour])
        db.session.commit()

    deleted = []
    monkeypatch.setattr(storage, 'delete_object', deleted.append)
    response = _client(app, tokens['alpha']).put(
        '/api/hrm/course-hours/video-change-hour',
        json={'videoKey': new_key},
    )

    assert response.status_code == 200, response.get_json()
    assert deleted == [old_key]


def test_course_hour_delete_releases_video_after_record_is_committed(monkeypatch, saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    old_key = f'tenants/{tenant_id}/courses/delete-hour/video.mp4'
    with app.app_context():
        course = Course(id='delete-hour-course', tenant_id=tenant_id, title='删除课时课程')
        hour = CourseHour(
            id='delete-hour',
            tenant_id=tenant_id,
            course_id=course.id,
            title='删除课时',
            video_key=old_key,
        )
        db.session.add_all([course, hour])
        db.session.commit()

    events = []
    monkeypatch.setattr(storage, 'delete_object', lambda key: events.append(('delete', key)))
    with app.app_context():
        original_commit = db.session.commit

        def tracked_commit():
            result = original_commit()
            events.append(('commit', None))
            return result

        monkeypatch.setattr(db.session, 'commit', tracked_commit)
        response = _client(app, tokens['alpha']).delete('/api/hrm/course-hours/delete-hour')

    assert response.status_code == 200, response.get_json()
    assert events == [('commit', None), ('delete', old_key)]


def test_course_attachment_generic_delete_releases_file(monkeypatch, saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    old_key = f'tenants/{tenant_id}/courses/attachments/handbook.pdf'
    with app.app_context():
        course = Course(id='attachment-course', tenant_id=tenant_id, title='附件课程')
        attachment = CourseAttachment(
            id='delete-course-attachment',
            tenant_id=tenant_id,
            course_id=course.id,
            title='课程手册',
            file_url=f'/uploads/{old_key}',
            ext='pdf',
        )
        db.session.add_all([course, attachment])
        db.session.commit()

    deleted = []
    monkeypatch.setattr(storage, 'delete_object', deleted.append)
    response = _client(app, tokens['alpha']).delete(
        '/api/hrm/course-attachments/delete-course-attachment',
    )

    assert response.status_code == 200, response.get_json()
    assert deleted == [old_key]


@pytest.mark.parametrize(
    ('resource', 'model', 'attribute', 'payload'),
    [
        ('courses', Course, 'cover_url', {'coverUrl': 'FOREIGN_URL'}),
        ('course-chapters', CourseChapter, 'materials', {
            'materials': [{'title': '越权资料', 'url': 'FOREIGN_URL', 'ext': 'pdf'}],
        }),
        ('course-hours', CourseHour, 'video_key', {'videoKey': 'FOREIGN_KEY'}),
        ('course-attachments', CourseAttachment, 'file_url', {'fileUrl': 'FOREIGN_URL'}),
    ],
    ids=['course-cover', 'chapter-materials', 'hour-video', 'course-attachment'],
)
def test_generic_course_storage_fields_reject_cross_tenant_references(
    saas_app,
    resource,
    model,
    attribute,
    payload,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    foreign_key = f"tenants/{tokens['beta_id']}/private/foreign.bin"
    foreign_url = f'/uploads/{foreign_key}'
    payload = {
        key: (
            value.replace('FOREIGN_URL', foreign_url).replace('FOREIGN_KEY', foreign_key)
            if isinstance(value, str)
            else [
                {
                    nested_key: (
                        nested_value.replace('FOREIGN_URL', foreign_url)
                        if isinstance(nested_value, str)
                        else nested_value
                    )
                    for nested_key, nested_value in item.items()
                }
                for item in value
            ]
        )
        for key, value in payload.items()
    }
    with app.app_context():
        course = Course(
            id='cross-reference-course',
            tenant_id=tenant_id,
            title='跨企业引用防护课程',
            cover_url=f'/uploads/tenants/{tenant_id}/safe/cover.png',
        )
        db.session.add(course)
        if model is Course:
            obj = course
            initial_value = course.cover_url
        elif model is CourseChapter:
            obj = CourseChapter(
                id='cross-reference-chapter',
                tenant_id=tenant_id,
                course_id=course.id,
                name='跨企业引用防护章节',
                materials=[{
                    'title': '安全资料',
                    'url': f'/uploads/tenants/{tenant_id}/safe/material.pdf',
                    'ext': 'pdf',
                }],
            )
            initial_value = list(obj.materials)
            db.session.add(obj)
        elif model is CourseHour:
            obj = CourseHour(
                id='cross-reference-hour',
                tenant_id=tenant_id,
                course_id=course.id,
                title='跨企业引用防护课时',
                video_key=f'tenants/{tenant_id}/safe/video.mp4',
            )
            initial_value = obj.video_key
            db.session.add(obj)
        else:
            obj = CourseAttachment(
                id='cross-reference-attachment',
                tenant_id=tenant_id,
                course_id=course.id,
                title='跨企业引用防护附件',
                file_url=f'/uploads/tenants/{tenant_id}/safe/attachment.pdf',
                ext='pdf',
            )
            initial_value = obj.file_url
            db.session.add(obj)
        db.session.commit()
        object_id = obj.id

    response = _client(app, tokens['alpha']).put(
        f'/api/hrm/{resource}/{object_id}',
        json=payload,
    )

    assert response.status_code == 400, response.get_json()
    assert response.get_json()['code'] == 'STORAGE_CROSS_TENANT_KEY'
    with app.app_context():
        assert getattr(db.session.get(model, object_id), attribute) == initial_value


@pytest.mark.parametrize(
    ('resource', 'model', 'marker_field', 'marker', 'payload'),
    [
        (
            'courses',
            Course,
            'title',
            '跨企业创建课程',
            {'title': '跨企业创建课程', 'coverUrl': 'FOREIGN_URL'},
        ),
        (
            'course-chapters',
            CourseChapter,
            'name',
            '跨企业创建章节',
            {
                'courseId': 'cross-create-parent-course',
                'name': '跨企业创建章节',
                'materials': [{'title': '越权资料', 'url': 'FOREIGN_URL', 'ext': 'pdf'}],
            },
        ),
        (
            'course-hours',
            CourseHour,
            'title',
            '跨企业创建课时',
            {
                'courseId': 'cross-create-parent-course',
                'title': '跨企业创建课时',
                'videoKey': 'FOREIGN_KEY',
            },
        ),
        (
            'course-attachments',
            CourseAttachment,
            'title',
            '跨企业创建附件',
            {
                'courseId': 'cross-create-parent-course',
                'title': '跨企业创建附件',
                'fileUrl': 'FOREIGN_URL',
            },
        ),
    ],
    ids=['course-cover', 'chapter-materials', 'hour-video', 'course-attachment'],
)
def test_generic_course_create_rejects_cross_tenant_storage_references(
    saas_app,
    resource,
    model,
    marker_field,
    marker,
    payload,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    foreign_key = f"tenants/{tokens['beta_id']}/private/create-foreign.bin"
    foreign_url = f'/uploads/{foreign_key}'

    def replace_foreign(value):
        if isinstance(value, str):
            return value.replace('FOREIGN_URL', foreign_url).replace('FOREIGN_KEY', foreign_key)
        if isinstance(value, list):
            return [replace_foreign(item) for item in value]
        if isinstance(value, dict):
            return {key: replace_foreign(item) for key, item in value.items()}
        return value

    with app.app_context():
        db.session.add(Course(
            id='cross-create-parent-course',
            tenant_id=tenant_id,
            title='跨企业创建防护父课程',
        ))
        db.session.commit()

    response = _client(app, tokens['alpha']).post(
        f'/api/hrm/{resource}',
        json=replace_foreign(payload),
    )

    assert response.status_code == 400, response.get_json()
    assert response.get_json()['code'] == 'STORAGE_CROSS_TENANT_KEY'
    with app.app_context():
        assert model.query.filter(
            model.tenant_id == tenant_id,
            getattr(model, marker_field) == marker,
        ).count() == 0


@pytest.mark.parametrize(
    'resource',
    ['employees', 'contracts', 'learning-paths', 'feedbacks'],
)
def test_generic_non_course_storage_fields_reject_cross_tenant_create_and_update(
    saas_app,
    resource,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    foreign_url = f"/uploads/tenants/{tokens['beta_id']}/private/{resource}.bin"
    safe_url = f'/uploads/tenants/{tenant_id}/safe/{resource}.bin'
    with app.app_context():
        employee = Employee(
            id=f'{resource}-owner-employee',
            tenant_id=tenant_id,
            employee_no=f'OWNER-{resource}',
            name=f'{resource} 归属员工',
        )
        db.session.add(employee)
        if resource == 'employees':
            obj = Employee(
                id='generic-storage-existing-employee',
                tenant_id=tenant_id,
                employee_no='GEN-STORAGE-EMP',
                name='通用存储已有员工',
                attachments=[{'url': safe_url}],
            )
            create_payload = {
                'name': '通用存储越权新员工',
                'employeeNo': 'GEN-STORAGE-NEW',
                'attachments': [{'url': foreign_url}],
            }
            update_payload = {'attachments': [{'url': foreign_url}]}
            marker_field, marker = Employee.name, '通用存储越权新员工'
            initial_value = list(obj.attachments)
            attribute = 'attachments'
        elif resource == 'contracts':
            obj = Contract(
                id='generic-storage-existing-contract',
                tenant_id=tenant_id,
                employee_id=employee.id,
                contract_no='GEN-STORAGE-CONTRACT',
                attachment_url=safe_url,
            )
            create_payload = {
                'employeeId': employee.id,
                'contractNo': 'GEN-STORAGE-NEW-CONTRACT',
                'attachmentUrl': foreign_url,
            }
            update_payload = {'attachmentUrl': foreign_url}
            marker_field, marker = Contract.contract_no, 'GEN-STORAGE-NEW-CONTRACT'
            initial_value = obj.attachment_url
            attribute = 'attachment_url'
        elif resource == 'learning-paths':
            obj = LearningPath(
                id='generic-storage-existing-learning-path',
                tenant_id=tenant_id,
                name='通用存储已有学习路径',
                cover_url=safe_url,
            )
            create_payload = {'name': '通用存储越权新学习路径', 'coverUrl': foreign_url}
            update_payload = {'coverUrl': foreign_url}
            marker_field, marker = LearningPath.name, '通用存储越权新学习路径'
            initial_value = obj.cover_url
            attribute = 'cover_url'
        else:
            obj = Feedback(
                id='generic-storage-existing-feedback',
                tenant_id=tenant_id,
                user_id='alpha-admin',
                feedback_type='bug',
                severity='medium',
                title='通用存储已有反馈',
                content='已有反馈内容',
                attachments=[{'url': safe_url}],
            )
            create_payload = {
                'feedbackType': 'bug',
                'title': '通用存储越权新反馈',
                'content': '越权反馈内容',
                'attachments': [{'url': foreign_url}],
            }
            update_payload = {'attachments': [{'url': foreign_url}]}
            marker_field, marker = Feedback.title, '通用存储越权新反馈'
            initial_value = list(obj.attachments)
            attribute = 'attachments'
        db.session.add(obj)
        db.session.commit()
        object_id = obj.id
        model = type(obj)

    created = _client(app, tokens['alpha']).post(f'/api/hrm/{resource}', json=create_payload)
    assert created.status_code == 400, created.get_json()
    assert created.get_json()['code'] == 'STORAGE_CROSS_TENANT_KEY'

    updated = _client(app, tokens['alpha']).put(
        f'/api/hrm/{resource}/{object_id}',
        json=update_payload,
    )
    assert updated.status_code == 400, updated.get_json()
    assert updated.get_json()['code'] == 'STORAGE_CROSS_TENANT_KEY'
    with app.app_context():
        assert model.query.filter(model.tenant_id == tenant_id, marker_field == marker).count() == 0
        assert getattr(db.session.get(model, object_id), attribute) == initial_value


@pytest.mark.parametrize(
    'resource',
    ['employees', 'contracts', 'learning-paths', 'feedbacks'],
)
def test_generic_non_course_delete_releases_unreferenced_storage(
    monkeypatch,
    saas_app,
    resource,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    object_key = f'tenants/{tenant_id}/generic-delete/{resource}.bin'
    storage_url = f'/uploads/{object_key}'
    with app.app_context():
        employee = Employee(
            id=f'{resource}-delete-owner',
            tenant_id=tenant_id,
            employee_no=f'DELETE-{resource}',
            name=f'{resource} 删除归属员工',
        )
        if resource == 'employees':
            obj = employee
            obj.attachments = [{'url': storage_url}]
        elif resource == 'contracts':
            db.session.add(employee)
            obj = Contract(
                id='generic-delete-contract',
                tenant_id=tenant_id,
                employee_id=employee.id,
                contract_no='GEN-DELETE-CONTRACT',
                attachment_url=storage_url,
            )
        elif resource == 'learning-paths':
            obj = LearningPath(
                id='generic-delete-learning-path',
                tenant_id=tenant_id,
                name='通用删除学习路径',
                cover_url=storage_url,
            )
        else:
            obj = Feedback(
                id='generic-delete-feedback',
                tenant_id=tenant_id,
                user_id='alpha-admin',
                feedback_type='bug',
                severity='medium',
                title='通用删除反馈',
                content='通用删除反馈内容',
                attachments=[{'url': storage_url}],
            )
        db.session.add(obj)
        db.session.commit()
        object_id = obj.id

    deleted = []
    monkeypatch.setattr(storage, 'delete_object', deleted.append)
    response = _client(app, tokens['alpha']).delete(f'/api/hrm/{resource}/{object_id}')

    assert response.status_code == 200, response.get_json()
    assert deleted == [object_key]


def test_bespoke_chapter_materials_update_rejects_cross_tenant_reference(saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    safe_materials = [{
        'title': '安全资料',
        'url': f'/uploads/tenants/{tenant_id}/safe/chapter.pdf',
        'ext': 'pdf',
    }]
    with app.app_context():
        course = Course(id='bespoke-material-course', tenant_id=tenant_id, title='专用资料防护课程')
        chapter = CourseChapter(
            id='bespoke-material-chapter',
            tenant_id=tenant_id,
            course_id=course.id,
            name='专用资料防护章节',
            materials=safe_materials,
        )
        db.session.add_all([course, chapter])
        db.session.commit()

    response = _client(app, tokens['alpha']).put(
        '/api/hrm/course-chapters/bespoke-material-chapter/materials',
        json={'materials': [{
            'title': '越权资料',
            'url': f"/uploads/tenants/{tokens['beta_id']}/private/chapter.pdf",
            'ext': 'pdf',
        }]},
    )

    assert response.status_code == 400, response.get_json()
    assert response.get_json()['code'] == 'STORAGE_CROSS_TENANT_KEY'
    with app.app_context():
        assert db.session.get(CourseChapter, 'bespoke-material-chapter').materials == safe_materials


def test_course_video_commit_failure_preserves_old_object_and_cleans_only_staged_object(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    old_key = f'tenants/{tenant_id}/courses/atomic-video-course/atomic-video-hour.mp4'
    with app.app_context():
        course = Course(id='atomic-video-course', tenant_id=tenant_id, title='原子视频课程')
        hour = CourseHour(
            id='atomic-video-hour',
            tenant_id=tenant_id,
            course_id=course.id,
            title='原子视频课时',
            video_key=old_key,
        )
        db.session.add_all([course, hour])
        db.session.commit()

    objects = {old_key: b'old-content'}
    written_keys = []
    deleted_keys = []

    def fake_upload(stream, key, **_kwargs):
        bound_key = key if key.startswith('tenants/') else f'tenants/{tenant_id}/{key}'
        objects[bound_key] = stream.read()
        written_keys.append(bound_key)
        return bound_key

    def fake_delete(key):
        deleted_keys.append(key)
        objects.pop(key, None)

    monkeypatch.setattr(storage, 'upload_video', fake_upload)
    monkeypatch.setattr(storage, 'delete_object', fake_delete)
    with app.app_context():
        monkeypatch.setattr(
            db.session,
            'commit',
            lambda: (_ for _ in ()).throw(RuntimeError('commit failed')),
        )
        with pytest.raises(RuntimeError, match='commit failed'):
            _client(app, tokens['alpha']).post(
                '/api/hrm/course-hours/atomic-video-hour/upload-video',
                data={'file': (BytesIO(b'new-content'), 'replacement.mp4')},
                content_type='multipart/form-data',
            )
        db.session.rollback()
        assert db.session.get(CourseHour, 'atomic-video-hour').video_key == old_key

    assert len(written_keys) == 1
    assert written_keys[0] != old_key
    assert deleted_keys == [written_keys[0]]
    assert objects == {old_key: b'old-content'}


def test_repeated_interview_media_releases_previous_object(monkeypatch, saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    old_key = f'tenants/{tenant_id}/interviews/repeated/old.mp3'
    new_key = f'tenants/{tenant_id}/interviews/repeated/new.mp3'
    with app.app_context():
        job = Job(id='repeated-media-job', tenant_id=tenant_id, title='重复媒体岗位', status='open')
        resume = Resume(
            id='repeated-media-resume',
            tenant_id=tenant_id,
            candidate_name='重复媒体候选人',
            file_url='/uploads/resume.pdf',
        )
        interview = Interview(
            id='repeated-media-interview',
            tenant_id=tenant_id,
            job_id=job.id,
            resume_id=resume.id,
            scheduled_at=datetime.utcnow(),
            feedback_file_url=f'/uploads/{old_key}',
            feedback_file_type='audio',
        )
        db.session.add_all([job, resume, interview])
        db.session.commit()

    monkeypatch.setattr(
        'routes.interviews._require_interview_ai',
        lambda requested: SimpleNamespace(resource_domain=requested),
    )
    monkeypatch.setattr('routes.interviews.save_local_upload', lambda *_args, **_kwargs: new_key)
    monkeypatch.setattr(
        'routes.interviews.analyze_interview_audio',
        lambda **_kwargs: {'status': 'not_implemented', 'message': '待实现'},
    )
    deleted = []
    monkeypatch.setattr(storage, 'delete_object', deleted.append)
    response = _client(app, tokens['alpha']).post(
        '/api/interviews/repeated-media-interview/analyze/media',
        data={'file': (BytesIO(b'audio'), 'media.mp3')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 202, response.get_json()
    assert deleted == [old_key]


def test_repeated_interview_recording_deletes_shared_previous_object_once(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    old_key = f'tenants/{tenant_id}/recordings/repeated/old.mp3'
    new_key = f'tenants/{tenant_id}/recordings/repeated/new.mp3'
    with app.app_context():
        job = Job(id='repeated-recording-job', tenant_id=tenant_id, title='重复录音岗位', status='open')
        resume = Resume(
            id='repeated-recording-resume',
            tenant_id=tenant_id,
            candidate_name='重复录音候选人',
            file_url='/uploads/resume.pdf',
        )
        interview = Interview(
            id='repeated-recording-interview',
            tenant_id=tenant_id,
            job_id=job.id,
            resume_id=resume.id,
            scheduled_at=datetime.utcnow(),
            recording_url=f'/uploads/{old_key}',
            feedback_file_url=f'/uploads/{old_key}',
            feedback_file_type='audio',
        )
        db.session.add_all([job, resume, interview])
        db.session.commit()

    monkeypatch.setattr('routes.interviews.save_local_upload', lambda *_args, **_kwargs: new_key)
    monkeypatch.setattr(
        'routes.interviews.transcribe_audio',
        lambda *_args, **_kwargs: {'success': True, 'text': '短录音', 'error': ''},
    )
    deleted = []
    monkeypatch.setattr(storage, 'delete_object', deleted.append)
    response = _client(app, tokens['alpha']).post(
        '/api/interviews/repeated-recording-interview/recording',
        data={'file': (BytesIO(b'audio'), 'recording.mp3')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 200, response.get_json()
    assert deleted == [old_key]


@pytest.mark.parametrize('upload_kind', ['media', 'recording'])
def test_interview_post_upload_failure_deletes_only_new_staged_object(
    monkeypatch,
    saas_app,
    upload_kind,
):
    from routes import interviews as interviews_route

    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    old_key = f'tenants/{tenant_id}/interviews/compensation/{upload_kind}-old.mp3'
    staged_key = f'tenants/{tenant_id}/interviews/compensation/{upload_kind}-new.mp3'
    with app.app_context():
        job = Job(
            id=f'interview-compensation-job-{upload_kind}',
            tenant_id=tenant_id,
            title='面试补偿岗位',
            status='open',
        )
        resume = Resume(
            id=f'interview-compensation-resume-{upload_kind}',
            tenant_id=tenant_id,
            candidate_name='面试补偿候选人',
            file_url='/uploads/resume.pdf',
        )
        interview = Interview(
            id=f'interview-compensation-{upload_kind}',
            tenant_id=tenant_id,
            job_id=job.id,
            resume_id=resume.id,
            scheduled_at=datetime.utcnow(),
            feedback_file_url=f'/uploads/{old_key}' if upload_kind == 'media' else None,
            recording_url=f'/uploads/{old_key}' if upload_kind == 'recording' else None,
        )
        db.session.add_all([job, resume, interview])
        db.session.commit()

    deleted = []
    monkeypatch.setattr(interviews_route, 'save_local_upload', lambda *_args, **_kwargs: staged_key)
    monkeypatch.setattr(interviews_route, 'delete_object', deleted.append, raising=False)
    if upload_kind == 'media':
        monkeypatch.setattr(
            interviews_route,
            '_require_interview_ai',
            lambda requested: SimpleNamespace(resource_domain=requested),
        )
        monkeypatch.setattr(
            interviews_route,
            'analyze_interview_audio',
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError('media analysis failed')),
        )
        suffix = 'analyze/media'
    else:
        monkeypatch.setattr(
            interviews_route,
            'transcribe_audio',
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('transcription failed')),
        )
        suffix = 'recording'

    response = _client(app, tokens['alpha']).post(
        f'/api/interviews/interview-compensation-{upload_kind}/{suffix}',
        data={'file': (BytesIO(b'audio'), 'failure.mp3')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 500, response.get_json()
    assert deleted == [staged_key]
    with app.app_context():
        interview = db.session.get(Interview, f'interview-compensation-{upload_kind}')
        persisted = interview.feedback_file_url if upload_kind == 'media' else interview.recording_url
        assert persisted == f'/uploads/{old_key}'


def test_shared_persistent_reference_prevents_object_deletion(monkeypatch, saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    shared_key = f'tenants/{tenant_id}/courses/shared/cover.png'
    with app.app_context():
        db.session.add_all([
            Course(
                id='shared-cover-a',
                tenant_id=tenant_id,
                title='共享封面 A',
                cover_url=f'/uploads/{shared_key}',
            ),
            Course(
                id='shared-cover-b',
                tenant_id=tenant_id,
                title='共享封面 B',
                cover_url=f'/uploads/{shared_key}',
            ),
        ])
        db.session.commit()

        deleted = []
        monkeypatch.setattr(storage, 'delete_object', deleted.append)
        assert storage.delete_object_if_unreferenced(shared_key, tenant_id=tenant_id) is False

    assert deleted == []


def test_unprefixed_legacy_key_is_not_deleted_while_another_tenant_references_it(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    shared_key = 'legacy/shared-cover.pdf'
    with app.app_context():
        alpha_course = Course(
            id='legacy-shared-alpha',
            tenant_id=tokens['alpha_id'],
            title='旧版共享引用 A',
            cover_url=f'/uploads/{shared_key}',
        )
        beta_course = Course(
            id='legacy-shared-beta',
            tenant_id=tokens['beta_id'],
            title='旧版共享引用 B',
            cover_url=f'/uploads/{shared_key}',
        )
        db.session.add_all([alpha_course, beta_course])
        db.session.commit()

        alpha_course.cover_url = None
        db.session.commit()

        deleted = []
        monkeypatch.setattr(storage, 'delete_object', deleted.append)
        removed = storage.delete_object_if_unreferenced(
            shared_key,
            tenant_id=tokens['alpha_id'],
        )

    assert removed is False
    assert deleted == []


def test_unprefixed_global_scan_covers_every_persistent_storage_field(
    monkeypatch,
    saas_app,
):
    app, tokens = saas_app
    beta_id = tokens['beta_id']
    keys = {
        'resume': 'legacy/all-fields/resume.pdf',
        'interview_feedback': 'legacy/all-fields/interview-feedback.mp3',
        'interview_recording': 'legacy/all-fields/interview-recording.mp3',
        'employee': 'legacy/all-fields/employee.pdf',
        'contract': 'legacy/all-fields/contract.pdf',
        'course': 'legacy/all-fields/course.png',
        'hour': 'legacy/all-fields/hour.mp4',
        'attachment': 'legacy/all-fields/attachment.pdf',
        'learning_path': 'legacy/all-fields/path.png',
        'certificate': 'legacy/all-fields/certificate.png',
        'feedback': 'legacy/all-fields/feedback.pdf',
        'chapter': 'legacy/all-fields/chapter.pdf',
    }
    with app.app_context():
        employee = Employee(
            id='legacy-all-fields-employee',
            tenant_id=beta_id,
            employee_no='LEGACY-ALL-FIELDS',
            name='旧版全字段员工',
            attachments=[{'url': f"/uploads/{keys['employee']}"}],
        )
        contract = Contract(
            id='legacy-all-fields-contract',
            tenant_id=beta_id,
            employee_id=employee.id,
            contract_no='LEGACY-ALL-FIELDS-CONTRACT',
            attachment_url=f"/uploads/{keys['contract']}",
        )
        course = Course(
            id='legacy-all-fields-course',
            tenant_id=beta_id,
            title='旧版全字段课程',
            cover_url=f"/uploads/{keys['course']}",
        )
        chapter = CourseChapter(
            id='legacy-all-fields-chapter',
            tenant_id=beta_id,
            course_id=course.id,
            name='旧版全字段章节',
            materials=[{'url': f"/uploads/{keys['chapter']}"}],
        )
        hour = CourseHour(
            id='legacy-all-fields-hour',
            tenant_id=beta_id,
            course_id=course.id,
            chapter_id=chapter.id,
            title='旧版全字段课时',
            video_key=keys['hour'],
        )
        attachment = CourseAttachment(
            id='legacy-all-fields-attachment',
            tenant_id=beta_id,
            course_id=course.id,
            title='旧版全字段附件',
            file_url=f"/uploads/{keys['attachment']}",
        )
        learning_path = LearningPath(
            id='legacy-all-fields-path',
            tenant_id=beta_id,
            name='旧版全字段学习路径',
            cover_url=f"/uploads/{keys['learning_path']}",
        )
        certificate = Certificate(
            id='legacy-all-fields-certificate',
            tenant_id=beta_id,
            employee_id=employee.id,
            course_id=course.id,
            cert_no='CERT-LEGACY-ALL-FIELDS',
            image_url=f"/uploads/{keys['certificate']}",
        )
        feedback = Feedback(
            id='legacy-all-fields-feedback',
            tenant_id=beta_id,
            user_id='beta-admin',
            feedback_type='bug',
            severity='medium',
            title='旧版全字段反馈',
            content='旧版全字段反馈内容',
            attachments=[{'url': f"/uploads/{keys['feedback']}"}],
        )
        resume = Resume(
            id='legacy-all-fields-resume',
            tenant_id=beta_id,
            candidate_name='旧版全字段候选人',
            file_url=f"/uploads/{keys['resume']}",
        )
        interview = Interview(
            id='legacy-all-fields-interview',
            tenant_id=beta_id,
            resume_id=resume.id,
            scheduled_at=datetime.utcnow(),
            feedback_file_url=f"/uploads/{keys['interview_feedback']}",
            recording_url=f"/uploads/{keys['interview_recording']}",
        )
        db.session.add_all([
            employee,
            contract,
            course,
            chapter,
            hour,
            attachment,
            learning_path,
            certificate,
            feedback,
            resume,
            interview,
        ])
        db.session.commit()

        deleted = []
        monkeypatch.setattr(storage, 'delete_object', deleted.append)
        results = {
            name: storage.delete_object_if_unreferenced(
                key,
                tenant_id=tokens['alpha_id'],
            )
            for name, key in keys.items()
        }

    assert results == {name: False for name in keys}
    assert deleted == []


def test_resume_delete_releases_file_after_record_commit(monkeypatch, saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    old_key = f'tenants/{tenant_id}/resumes/delete-me.pdf'
    with app.app_context():
        db.session.add(Resume(
            id='delete-storage-resume',
            tenant_id=tenant_id,
            candidate_name='删除文件候选人',
            file_url=f'/uploads/{old_key}',
        ))
        db.session.commit()

    events = []
    monkeypatch.setattr(storage, 'delete_object', lambda key: events.append(('delete', key)))
    with app.app_context():
        original_commit = db.session.commit

        def tracked_commit():
            result = original_commit()
            events.append(('commit', None))
            return result

        monkeypatch.setattr(db.session, 'commit', tracked_commit)
        response = _client(app, tokens['alpha']).delete('/api/resumes/delete-storage-resume')

    assert response.status_code == 200, response.get_json()
    assert events == [('commit', None), ('delete', old_key)]
