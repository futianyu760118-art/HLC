"""接收 M01 人员离职/复职事件，并在 HLC 内完成一次性收口。"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, jsonify, request

from models import AssistantSession, Employee, EmployeePortalAccount, OnboardingTask, User, db


person_lifecycle_bp = Blueprint('person_lifecycle', __name__)


class PersonLifecycleEvent(db.Model):
    __tablename__ = 'person_lifecycle_events'

    event_id = db.Column(db.String(200), primary_key=True)
    idempotency_key = db.Column(db.String(500), nullable=False, unique=True, index=True)
    tenant_id = db.Column(db.String(36), nullable=False, index=True)
    object_id = db.Column(db.String(200), nullable=False, index=True)
    revision = db.Column(db.Integer, nullable=False)
    event_type = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(40), nullable=False)
    result = db.Column(db.JSON, nullable=False, default=dict)
    received_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class PersonLifecycleChecklist(db.Model):
    __tablename__ = 'person_lifecycle_checklists'

    id = db.Column(db.String(36), primary_key=True)
    event_id = db.Column(db.String(200), nullable=False, index=True)
    tenant_id = db.Column(db.String(36), nullable=False, index=True)
    person_id = db.Column(db.String(200), nullable=False, index=True)
    item_type = db.Column(db.String(60), nullable=False)
    item_name = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


CHECKLIST_ITEMS = (
    ('personnel_service', '人员服务账号'),
    ('asset', '公司物品'),
    ('device', '电脑和设备'),
    ('agent_equipment', '智能体配备'),
)


def _now():
    return datetime.now(timezone.utc)


def _secret():
    return os.getenv('AEOS_PERSON_LIFECYCLE_SECRET') or os.getenv('HLC_PERSON_LIFECYCLE_SECRET') or ''


def _verify_request():
    key_id = request.headers.get('X-AEOS-Key-Id')
    timestamp = request.headers.get('X-AEOS-Timestamp')
    signature = request.headers.get('X-AEOS-Signature', '').removeprefix('sha256=')
    if not key_id or not timestamp or not signature or key_id != (os.getenv('AEOS_PERSON_LIFECYCLE_KEY_ID') or 'm01-kernel'):
        return False, ('缺少人员同步签名', 401)
    try:
        timestamp_ms = int(timestamp)
    except ValueError:
        return False, ('人员同步时间不正确', 401)
    max_skew = int(os.getenv('AEOS_PERSON_LIFECYCLE_MAX_SKEW_SECONDS', '300')) * 1000
    if abs(int(time.time() * 1000) - timestamp_ms) > max_skew:
        return False, ('人员同步请求已过期', 401)
    raw = request.get_data(cache=True)
    expected = hmac.new(_secret().encode(), timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    if not _secret() or not hmac.compare_digest(expected, signature):
        return False, ('人员同步签名无效', 401)
    return True, None


def _employee_for_event(payload):
    person = payload.get('person') or {}
    object_id = str(payload.get('object_id') or '').strip()
    emp_code = str(person.get('emp_code') or '').strip()
    candidates = Employee.query.filter(Employee.tenant_id == str(payload.get('tenant_id'))).filter(
        (Employee.id == object_id) | (Employee.employee_no == emp_code)
    ).all()
    unique = {row.id: row for row in candidates}
    if len(unique) > 1:
        return None, ('人员编号和员工编号指向了不同人员', 409)
    employee = next(iter(unique.values()), None)
    if not employee:
        return None, ('人员不存在，不能同步离职状态', 404)
    if object_id and employee.id != object_id:
        return None, ('人员身份不一致，拒绝覆盖其他人员', 409)
    if emp_code and employee.employee_no != emp_code:
        return None, ('员工编号不一致，拒绝覆盖其他人员', 409)
    return employee, None


def _make_checklist(event, employee, item_types, status, detail):
    existing = {
        row.item_type for row in PersonLifecycleChecklist.query.filter_by(
            event_id=event['event_id'], person_id=employee.id,
        ).all()
    }
    created = []
    for item_type, item_name in CHECKLIST_ITEMS:
        if item_type not in item_types or item_type in existing:
            continue
        db.session.add(PersonLifecycleChecklist(
            id=str(uuid4()), event_id=event['event_id'], tenant_id=employee.tenant_id,
            person_id=employee.id, item_type=item_type, item_name=item_name,
            status=status, detail=detail,
        ))
        created.append(item_type)
    return created


def _offboard(event, employee):
    employee.status = 'inactive'
    employee.oa_status = 'inactive'
    employee.source_modified_at = datetime.utcnow()
    users = User.query.filter_by(tenant_id=employee.tenant_id, employee_id=employee.id).all()
    for user in users:
        user.status = 'inactive'
        for session in AssistantSession.query.filter_by(user_id=user.id, is_active=True).all():
            session.is_active = False
    for account in EmployeePortalAccount.query.filter_by(employee_id=employee.id).all():
        account.status = 'inactive'
    reassigned = []
    open_statuses = {'pending', 'in_progress', 'assigned', 'open', 'doing'}
    for task in OnboardingTask.query.filter_by(tenant_id=employee.tenant_id, employee_id=employee.id).all():
        if task.status in open_statuses or task.owner_id:
            task.status = 'reassignment_required'
            task.owner_id = None
            task.remark = f'{task.remark or ""} 已因人员离职转入重新安排。'.strip()
            reassigned.append(task.id)
    closed_items = _make_checklist(
        event, employee, {item_type for item_type, _ in CHECKLIST_ITEMS}, 'closed',
        {'reason': '人员已离职，相关入口已关闭，物品和智能体配备进入交接清单'},
    )
    return {
        'status': 'synced', 'state': 'offboarded', 'event_id': event['event_id'],
        'closed_items': closed_items, 'reassigned_tasks': reassigned,
        'pending_confirmation': {'permissions': False, 'agents': False},
    }


def _reinstate(event, employee):
    employee.status = 'active'
    employee.oa_status = 'active'
    employee.source_modified_at = datetime.utcnow()
    for user in User.query.filter_by(tenant_id=employee.tenant_id, employee_id=employee.id).all():
        user.status = 'active'
    for account in EmployeePortalAccount.query.filter_by(employee_id=employee.id).all():
        account.status = 'active'
    for item_type, item_name in (('permission_restore', '原有权限恢复确认'), ('agent_restore', '智能体配备恢复确认')):
        db.session.add(PersonLifecycleChecklist(
            id=str(uuid4()), event_id=event['event_id'], tenant_id=employee.tenant_id,
            person_id=employee.id, item_type=item_type, item_name=item_name,
            status='pending_confirmation', detail={'requires_owner_confirmation': True},
        ))
    return {
        'status': 'pending_confirmation', 'state': 'active', 'event_id': event['event_id'],
        'closed_items': [], 'reassigned_tasks': [],
        'pending_confirmation': {'permissions': True, 'agents': True},
    }


def apply_person_lifecycle_event(payload):
    required = ('event_id', 'event_type', 'tenant_id', 'object_id', 'revision', 'idempotency_key', 'person')
    if any(not payload.get(field) for field in required):
        return {'status': 'failed', 'error': '人员同步事件缺少必填内容'}, 400
    existing = PersonLifecycleEvent.query.filter_by(idempotency_key=payload['idempotency_key']).first()
    if existing:
        result = dict(existing.result or {})
        result['duplicate'] = True
        return result, 200
    employee, error = _employee_for_event(payload)
    if error:
        return {'status': 'failed', 'error': error[0]}, error[1]
    current = PersonLifecycleEvent.query.filter_by(
        tenant_id=employee.tenant_id, object_id=employee.id,
    ).order_by(PersonLifecycleEvent.revision.desc()).first()
    if current and int(payload['revision']) < int(current.revision):
        return {'status': 'stale', 'state': 'stale', 'event_id': payload['event_id'], 'duplicate': False}, 200
    effective_at = payload.get('effective_at')
    if effective_at and datetime.fromisoformat(str(effective_at).replace('Z', '+00:00')) > _now():
        result = {'status': 'scheduled', 'state': 'scheduled', 'event_id': payload['event_id'], 'duplicate': False}
    elif payload['event_type'] == 'person.offboarded':
        result = _offboard(payload, employee)
        result['duplicate'] = False
    elif payload['event_type'] == 'person.reinstated':
        result = _reinstate(payload, employee)
        result['duplicate'] = False
    else:
        return {'status': 'failed', 'error': f"不支持的人员状态事件：{payload['event_type']}"}, 400
    db.session.add(PersonLifecycleEvent(
        event_id=payload['event_id'], idempotency_key=payload['idempotency_key'],
        tenant_id=employee.tenant_id, object_id=employee.id, revision=int(payload['revision']),
        event_type=payload['event_type'], status=result['status'], result=result,
    ))
    db.session.commit()
    return result, 200


@person_lifecycle_bp.route('/internal/aeos/person-lifecycle', methods=['POST'])
def person_lifecycle():
    ok, error = _verify_request()
    if not ok:
        return jsonify({'error': error[0]}), error[1]
    payload = request.get_json(silent=True) or {}
    try:
        result, status = apply_person_lifecycle_event(payload)
        return jsonify(result), status
    except Exception:
        db.session.rollback()
        raise
