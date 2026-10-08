"""Public enterprise-service applications and platform follow-up APIs.

The public endpoint deliberately returns no contact information. Platform
endpoints are registered under ``/api/platform`` so the global platform-admin
boundary and an explicit JWT check both apply.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import case, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from models import (
    EnterpriseApplicationSubmissionGuard,
    EnterpriseServiceApplication,
    PlatformOperationLog,
    Tenant,
    User,
    db,
)
from services.extension_registry import EXTENSION_MODULE_KEYS
from services.tenancy import SAAS_MODULE_KEYS
from services.request_metadata import enterprise_source_fingerprint, request_id_for_client


enterprise_applications_public_bp = Blueprint('enterprise_applications_public', __name__)
enterprise_applications_platform_bp = Blueprint('enterprise_applications_platform', __name__)

APPLICATION_STATUSES = ('new', 'contacting', 'qualified', 'closed', 'converted')
EMPLOYEE_SCALES = {'1-49', '50-99', '100-499', '500-999', '1000-4999', '5000+'}
CONTACT_TIMES = {'weekday_morning', 'weekday_afternoon', 'weekday_evening', 'anytime'}
ALLOWED_MODULES = frozenset((*SAAS_MODULE_KEYS, *EXTENSION_MODULE_KEYS))
PUBLIC_FIELDS = {
    'companyName',
    'contactName',
    'mobile',
    'email',
    'region',
    'employeeScale',
    'interestedModules',
    'preferredContactTime',
    'notes',
    'privacyConsent',
    'website',
}
PATCH_FIELDS = {'status', 'ownerUserId', 'followUpAt', 'internalNote'}
VERSION_FIELD = 'version'
STATUS_TRANSITIONS = {
    'new': {'contacting'},
    'contacting': {'qualified', 'closed'},
    'qualified': {'closed'},
    'closed': {'contacting'},
    'converted': set(),
}
IDEMPOTENCY_RE = re.compile(r'^[A-Za-z0-9_.:-]{16,128}$')
EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
MOBILE_RE = re.compile(r'^1[3-9]\d{9}$')
COOLDOWN_SECONDS = 60
MAX_APPLICATION_PAGE = 100_000
SHANGHAI_TZ = timezone(timedelta(hours=8))
LIST_FIELDS = {'status', 'page', 'pageSize'}
SEARCH_FIELDS = LIST_FIELDS | {'keyword'}
TIMELINE_LABELS = {
    'new': '提交企业服务申请',
    'contacting': '开始人工跟进',
    'qualified': '标记为有效意向',
    'closed': '关闭申请',
    'converted': '关联既有企业',
}


class ApplicationPayloadError(ValueError):
    def __init__(self, message: str, *, code: str = 'APPLICATION_PAYLOAD_INVALID', status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _request_id() -> str:
    value = getattr(g, 'request_id', None)
    if value:
        return str(value)
    value = request_id_for_client(request.headers.get('X-Request-ID'))
    g.request_id = value
    return value


def _error(message: str, code: str, status: int):
    return jsonify({'error': message, 'code': code, 'requestId': _request_id()}), status


def _application_conflict():
    return _error(
        '申请已被其他管理员更新，请刷新后重试',
        'APPLICATION_CONFLICT',
        409,
    )


def _expected_version(data: dict[str, Any]) -> int:
    value = data.get(VERSION_FIELD)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ApplicationPayloadError('申请版本无效')
    return value


def _text(data: dict[str, Any], key: str, *, required: bool, min_length: int = 0,
          max_length: int) -> str | None:
    value = data.get(key)
    if value is None:
        if required:
            raise ApplicationPayloadError(f'{key} 不能为空')
        return None
    if not isinstance(value, str):
        raise ApplicationPayloadError(f'{key} 格式无效')
    value = value.strip()
    if not value:
        if required:
            raise ApplicationPayloadError(f'{key} 不能为空')
        return None
    if len(value) < min_length or len(value) > max_length:
        raise ApplicationPayloadError(f'{key} 长度无效')
    return value


def _normalize_mobile(value: Any) -> str:
    if not isinstance(value, str):
        raise ApplicationPayloadError('手机号格式无效')
    normalized = re.sub(r'[\s()\-]', '', value.strip())
    if normalized.startswith('+86'):
        normalized = normalized[3:]
    elif normalized.startswith('0086'):
        normalized = normalized[4:]
    elif normalized.startswith('86') and len(normalized) == 13:
        normalized = normalized[2:]
    if not MOBILE_RE.fullmatch(normalized):
        raise ApplicationPayloadError('手机号格式无效')
    return normalized


def _validate_public_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) - PUBLIC_FIELDS:
        raise ApplicationPayloadError('申请信息包含不支持的字段')
    if payload.get('website') not in (None, ''):
        raise ApplicationPayloadError('申请信息校验失败')

    company_name = _text(payload, 'companyName', required=True, min_length=2, max_length=120)
    contact_name = _text(payload, 'contactName', required=True, min_length=1, max_length=60)
    mobile = _normalize_mobile(payload.get('mobile'))
    email = _text(payload, 'email', required=False, max_length=255)
    if email and not EMAIL_RE.fullmatch(email):
        raise ApplicationPayloadError('邮箱格式无效')
    region = _text(payload, 'region', required=False, max_length=80)
    notes = _text(payload, 'notes', required=False, max_length=1000)

    employee_scale = payload.get('employeeScale')
    if employee_scale in (None, ''):
        employee_scale = None
    elif not isinstance(employee_scale, str) or employee_scale not in EMPLOYEE_SCALES:
        raise ApplicationPayloadError('员工规模选项无效')

    preferred_contact_time = payload.get('preferredContactTime')
    if preferred_contact_time in (None, ''):
        preferred_contact_time = None
    elif not isinstance(preferred_contact_time, str) or preferred_contact_time not in CONTACT_TIMES:
        raise ApplicationPayloadError('期望联系时间选项无效')

    interested_modules = payload.get('interestedModules', [])
    if not isinstance(interested_modules, list):
        raise ApplicationPayloadError('关注功能格式无效')
    if len(interested_modules) > len(ALLOWED_MODULES):
        raise ApplicationPayloadError('关注功能数量无效')
    if any(not isinstance(key, str) or key not in ALLOWED_MODULES for key in interested_modules):
        raise ApplicationPayloadError('关注功能包含未知选项')
    interested_modules = list(dict.fromkeys(interested_modules))

    if payload.get('privacyConsent') is not True:
        raise ApplicationPayloadError('请阅读并同意隐私政策')
    return {
        'company_name': company_name,
        'contact_name': contact_name,
        'mobile': mobile,
        'email': email,
        'region': region,
        'employee_scale': employee_scale,
        'interested_modules': interested_modules,
        'preferred_contact_time': preferred_contact_time,
        'notes': notes,
        # This public route owns the source value; callers cannot label their
        # own traffic as a trusted channel.
        'source': 'enterprise_application',
    }


def _idempotency_key() -> str:
    value = (request.headers.get('Idempotency-Key') or '').strip()
    if not IDEMPOTENCY_RE.fullmatch(value):
        raise ApplicationPayloadError(
            '缺少或无效的幂等键',
            code='APPLICATION_IDEMPOTENCY_KEY_INVALID',
        )
    return value


def _fingerprint_hash() -> str:
    return enterprise_source_fingerprint(request.headers.get('User-Agent'))


def _new_application_no() -> str:
    return f'ESA-{secrets.token_hex(12).upper()}'


def _claim_submission_guard(*, fingerprint_hash: str, idempotency_hash: str):
    """Atomically claim an expired/new source guard in the caller transaction."""

    table = EnterpriseApplicationSubmissionGuard.__table__
    claim_token = str(uuid.uuid4())
    now = datetime.utcnow()
    cooldown_until = now + timedelta(seconds=COOLDOWN_SECONDS)
    values = {
        'fingerprint_hash': fingerprint_hash,
        'active_idempotency_hash': idempotency_hash,
        'application_id': None,
        'claim_token': claim_token,
        'cooldown_until': cooldown_until,
        'updated_at': now,
    }
    dialect = db.session.get_bind().dialect.name
    if dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        statement = sqlite_insert(table).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.fingerprint_hash],
            set_={
                'active_idempotency_hash': idempotency_hash,
                'application_id': None,
                'claim_token': claim_token,
                'cooldown_until': cooldown_until,
                'updated_at': now,
            },
            where=table.c.cooldown_until <= now,
        )
    elif dialect.startswith('mysql'):
        from sqlalchemy.dialects.mysql import insert as mysql_insert

        statement = mysql_insert(table).values(**values)
        eligible = table.c.cooldown_until <= now
        statement = statement.on_duplicate_key_update(
            active_idempotency_hash=case(
                (eligible, statement.inserted.active_idempotency_hash),
                else_=table.c.active_idempotency_hash,
            ),
            application_id=case((eligible, None), else_=table.c.application_id),
            claim_token=case((eligible, statement.inserted.claim_token), else_=table.c.claim_token),
            cooldown_until=case(
                (eligible, statement.inserted.cooldown_until),
                else_=table.c.cooldown_until,
            ),
            updated_at=case((eligible, statement.inserted.updated_at), else_=table.c.updated_at),
        )
    else:  # The SaaS runtime and test contract intentionally support MySQL/SQLite only.
        raise RuntimeError('unsupported enterprise application guard database')

    db.session.execute(statement)
    guard = db.session.execute(
        select(EnterpriseApplicationSubmissionGuard)
        .where(EnterpriseApplicationSubmissionGuard.fingerprint_hash == fingerprint_hash)
        .execution_options(populate_existing=True)
    ).scalar_one()
    return guard, guard.claim_token == claim_token


@enterprise_applications_public_bp.route('/enterprise-applications', methods=['POST'])
def create_enterprise_application():
    try:
        raw_idempotency_key = _idempotency_key()
        values = _validate_public_payload(request.get_json(silent=True))
    except ApplicationPayloadError as exc:
        return _error(str(exc), exc.code, exc.status)

    fingerprint_hash = _fingerprint_hash()
    from services.request_metadata import enterprise_idempotency_digest
    idempotency_key = enterprise_idempotency_digest(raw_idempotency_key, fingerprint_hash)
    existing = EnterpriseServiceApplication.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        return jsonify(existing.to_public_dict()), 200

    guard, claimed = _claim_submission_guard(
        fingerprint_hash=fingerprint_hash,
        idempotency_hash=idempotency_key,
    )
    if not claimed:
        if guard.active_idempotency_hash == idempotency_key and guard.application_id:
            existing = db.session.get(EnterpriseServiceApplication, guard.application_id)
            if existing:
                db.session.rollback()
                return jsonify(existing.to_public_dict()), 200
        db.session.rollback()
        if guard.active_idempotency_hash == idempotency_key:
            return _error('申请正在处理中，请稍后重试', 'APPLICATION_SUBMISSION_IN_PROGRESS', 409)
        return _error('提交过于频繁，请稍后再试', 'APPLICATION_RATE_LIMITED', 429)

    now = datetime.utcnow()
    row = EnterpriseServiceApplication(
        id=str(uuid.uuid4()),
        application_no=_new_application_no(),
        idempotency_key=idempotency_key,
        fingerprint_hash=fingerprint_hash,
        request_id=_request_id(),
        consent_at=now,
        status='new',
        **values,
    )
    try:
        db.session.add(row)
        db.session.flush()
        guard.application_id = row.id
        response_payload = row.to_public_dict()
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = EnterpriseServiceApplication.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return jsonify(existing.to_public_dict()), 200
        current_app.logger.warning('enterprise_application_insert_conflict')
        return _error('申请提交失败，请稍后重试', 'APPLICATION_SUBMISSION_FAILED', 409)
    return jsonify(response_payload), 201


def _application_or_error(application_id: str):
    row = db.session.get(EnterpriseServiceApplication, application_id)
    if row is None:
        return None, _error('企业申请不存在', 'APPLICATION_NOT_FOUND', 404)
    return row, None


def _parse_positive_int(value: Any, *, default: int, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if result < 1:
        return default
    return min(result, maximum) if maximum is not None else result


def _parse_utc_datetime(value: Any) -> datetime | None:
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise ApplicationPayloadError('跟进时间格式无效')
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError as exc:
        raise ApplicationPayloadError('跟进时间格式无效') from exc
    if parsed.tzinfo is None:
        raise ApplicationPayloadError('跟进时间必须包含 UTC 时区')
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _shanghai_business_day_start_utc(now_utc: datetime | None = None) -> datetime:
    now = now_utc or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(SHANGHAI_TZ)
    local_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


def _timeline_for(row: EnterpriseServiceApplication) -> list[dict[str, Any]]:
    events = [{
        'status': 'new',
        'label': TIMELINE_LABELS['new'],
        'at': row.to_platform_list_dict()['createdAt'],
    }]
    logs = PlatformOperationLog.query.filter_by(
        target_type='enterprise_service_application',
        target_id=row.id,
        result='success',
    ).order_by(PlatformOperationLog.created_at.asc(), PlatformOperationLog.id.asc()).all()
    for log in logs:
        detail = log.detail if isinstance(log.detail, dict) else {}
        from_status = detail.get('fromStatus')
        to_status = detail.get('toStatus')
        if (
            to_status in TIMELINE_LABELS
            and from_status in APPLICATION_STATUSES
            and to_status != from_status
        ):
            from models import utc_iso
            events.append({
                'status': to_status,
                'label': TIMELINE_LABELS[to_status],
                'at': utc_iso(log.created_at),
            })
    return sorted(events, key=lambda event: event['at'] or '')


def _platform_audit(*, action: str, row: EnterpriseServiceApplication,
                    detail: dict[str, Any]) -> None:
    db.session.add(PlatformOperationLog(
        id=str(uuid.uuid4()),
        user_id=get_jwt_identity(),
        tenant_id=row.converted_tenant_id,
        action=action,
        target_type='enterprise_service_application',
        target_id=row.id,
        result='success',
        request_id=_request_id(),
        detail=detail,
        ip_address=None,
    ))


def _commit_application_change(row: EnterpriseServiceApplication):
    try:
        db.session.flush()
        response_payload = row.to_platform_detail_dict(timeline=_timeline_for(row))
        db.session.commit()
    except StaleDataError:
        db.session.rollback()
        return None, _application_conflict()
    return response_payload, None


@enterprise_applications_platform_bp.route('/enterprise-applications/summary', methods=['GET'])
@jwt_required()
def enterprise_application_summary():
    today = _shanghai_business_day_start_utc()
    result = {
        status: EnterpriseServiceApplication.query.filter_by(status=status).count()
        for status in APPLICATION_STATUSES
    }
    result['todayNew'] = EnterpriseServiceApplication.query.filter(
        EnterpriseServiceApplication.created_at >= today,
    ).count()
    return jsonify(result)


def _application_page(data: Any, *, allow_keyword: bool):
    allowed_fields = SEARCH_FIELDS if allow_keyword else LIST_FIELDS
    if not isinstance(data, dict) or set(data) - allowed_fields:
        return None, _error('申请筛选条件无效', 'APPLICATION_PAYLOAD_INVALID', 400)
    status_value = data.get('status')
    status = status_value.strip() if isinstance(status_value, str) else ''
    keyword_value = data.get('keyword') if allow_keyword else None
    keyword = keyword_value.strip() if isinstance(keyword_value, str) else ''
    if status and status not in APPLICATION_STATUSES:
        return None, _error('申请状态筛选无效', 'APPLICATION_PAYLOAD_INVALID', 400)
    if keyword_value is not None and not isinstance(keyword_value, str):
        return None, _error('搜索关键词格式无效', 'APPLICATION_PAYLOAD_INVALID', 400)
    if len(keyword) > 100:
        return None, _error('搜索关键词过长', 'APPLICATION_PAYLOAD_INVALID', 400)
    page = _parse_positive_int(
        data.get('page'),
        default=1,
        maximum=MAX_APPLICATION_PAGE,
    )
    page_size = _parse_positive_int(data.get('pageSize'), default=20, maximum=100)

    query = EnterpriseServiceApplication.query
    if status:
        query = query.filter(EnterpriseServiceApplication.status == status)
    if keyword:
        pattern = f'%{keyword}%'
        query = query.filter(or_(
            EnterpriseServiceApplication.application_no.ilike(pattern),
            EnterpriseServiceApplication.company_name.ilike(pattern),
            EnterpriseServiceApplication.contact_name.ilike(pattern),
            EnterpriseServiceApplication.mobile.ilike(pattern),
            EnterpriseServiceApplication.email.ilike(pattern),
        ))
    total = query.count()
    rows = query.order_by(
        EnterpriseServiceApplication.created_at.desc(),
        EnterpriseServiceApplication.id.desc(),
    ).offset((page - 1) * page_size).limit(page_size).all()
    return {
        'items': [row.to_platform_list_dict() for row in rows],
        'page': page,
        'pageSize': page_size,
        'total': total,
        'totalPages': (total + page_size - 1) // page_size,
    }, None


@enterprise_applications_platform_bp.route('/enterprise-applications', methods=['GET'])
@jwt_required()
def list_enterprise_applications():
    if 'keyword' in request.args:
        return _error(
            '包含联系人信息的搜索必须使用请求体提交',
            'APPLICATION_SEARCH_BODY_REQUIRED',
            400,
        )
    payload, error = _application_page(request.args.to_dict(flat=True), allow_keyword=False)
    return error or jsonify(payload)


@enterprise_applications_platform_bp.route('/enterprise-applications/search', methods=['POST'])
@jwt_required()
def search_enterprise_applications():
    payload, error = _application_page(request.get_json(silent=True), allow_keyword=True)
    return error or jsonify(payload)


@enterprise_applications_platform_bp.route('/enterprise-applications/<application_id>', methods=['GET'])
@jwt_required()
def enterprise_application_detail(application_id: str):
    row, error = _application_or_error(application_id)
    if error:
        return error
    return jsonify(row.to_platform_detail_dict(timeline=_timeline_for(row)))


@enterprise_applications_platform_bp.route('/enterprise-applications/<application_id>', methods=['PATCH'])
@jwt_required()
def update_enterprise_application(application_id: str):
    row, error = _application_or_error(application_id)
    if error:
        return error
    data = request.get_json(silent=True)
    if (
        not isinstance(data, dict)
        or not (set(data) & PATCH_FIELDS)
        or VERSION_FIELD not in data
        or set(data) - (PATCH_FIELDS | {VERSION_FIELD})
    ):
        return _error('只允许更新状态、负责人、跟进时间和内部备注', 'APPLICATION_PAYLOAD_INVALID', 400)
    try:
        expected_version = _expected_version(data)
    except ApplicationPayloadError as exc:
        return _error(str(exc), exc.code, exc.status)
    if row.version != expected_version:
        return _application_conflict()

    before_status = row.status
    before_owner = row.owner_user_id
    detail: dict[str, Any] = {'fromStatus': before_status}
    try:
        if 'status' in data:
            next_status = data.get('status')
            if not isinstance(next_status, str) or next_status not in STATUS_TRANSITIONS.get(row.status, set()):
                return _error('申请状态转换无效', 'APPLICATION_STATUS_INVALID', 409)
            row.status = next_status
            detail['toStatus'] = next_status

        if 'ownerUserId' in data:
            owner_user_id = data.get('ownerUserId')
            if owner_user_id in (None, ''):
                row.owner_user_id = None
            elif not isinstance(owner_user_id, str):
                return _error('跟进人无效', 'APPLICATION_OWNER_INVALID', 400)
            else:
                owner = db.session.get(User, owner_user_id)
                if (
                    owner is None
                    or owner.tenant_id is not None
                    or owner.role != 'platform_admin'
                    or owner.status != 'active'
                ):
                    return _error('跟进人无效', 'APPLICATION_OWNER_INVALID', 400)
                row.owner_user_id = owner.id
            detail['ownerUserId'] = row.owner_user_id

        if 'followUpAt' in data:
            row.follow_up_at = _parse_utc_datetime(data.get('followUpAt'))
            detail['followUpAtChanged'] = True

        if 'internalNote' in data:
            note = data.get('internalNote')
            if note in (None, ''):
                row.internal_note = None
            elif not isinstance(note, str) or len(note.strip()) > 2000:
                raise ApplicationPayloadError('内部备注格式无效')
            else:
                row.internal_note = note.strip()
            detail['internalNoteChanged'] = True
    except ApplicationPayloadError as exc:
        db.session.rollback()
        return _error(str(exc), exc.code, exc.status)

    if 'toStatus' not in detail:
        detail['toStatus'] = row.status
    if 'ownerUserId' not in detail and row.owner_user_id != before_owner:
        detail['ownerUserId'] = row.owner_user_id
    _platform_audit(action='update_enterprise_application', row=row, detail=detail)
    response_payload, conflict = _commit_application_change(row)
    if conflict:
        return conflict
    return jsonify(response_payload)


@enterprise_applications_platform_bp.route('/enterprise-applications/<application_id>/convert', methods=['POST'])
@jwt_required()
def convert_enterprise_application(application_id: str):
    row, error = _application_or_error(application_id)
    if error:
        return error
    data = request.get_json(silent=True)
    if (
        not isinstance(data, dict)
        or set(data) != {'tenantId', VERSION_FIELD}
        or not isinstance(data.get('tenantId'), str)
    ):
        return _error('请选择已创建的企业客户', 'APPLICATION_PAYLOAD_INVALID', 400)
    try:
        expected_version = _expected_version(data)
    except ApplicationPayloadError as exc:
        return _error(str(exc), exc.code, exc.status)
    if row.version != expected_version:
        return _application_conflict()
    if row.status != 'qualified':
        return _error('只有有效意向可以关联企业', 'APPLICATION_STATUS_INVALID', 409)
    tenant = db.session.get(Tenant, data['tenantId'].strip())
    if tenant is None:
        return _error('关联企业不存在', 'APPLICATION_TENANT_NOT_FOUND', 404)

    row.status = 'converted'
    row.converted_tenant_id = tenant.id
    _platform_audit(
        action='convert_enterprise_application',
        row=row,
        detail={
            'fromStatus': 'qualified',
            'toStatus': 'converted',
            'convertedTenantId': tenant.id,
        },
    )
    response_payload, conflict = _commit_application_change(row)
    if conflict:
        return conflict
    return jsonify(response_payload)
