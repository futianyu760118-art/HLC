"""接收 M01 人员离职/复职事件，并在 HLC 内完成一次性收口。"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

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
RESULT_STATUSES = {'synced', 'skipped', 'pending_confirmation', 'retrying', 'failed'}
PERSON_CHANGE_ACTIONS = {'hire', 'transfer', 'offboard', 'reinstate'}


def _contract_result(payload, result):
    status = str(result.get('status') or 'failed').lower()
    if status == 'stale':
        status = 'skipped'
    elif status == 'scheduled':
        status = 'pending_confirmation'
    if status not in RESULT_STATUSES:
        status = 'failed'
    return {
        **result,
        'event_id': result.get('event_id') or payload['event_id'],
        'target_system': 'M07_HLC',
        'status': status,
        'changed': result.get('changed') or {
            'closed_items': len(result.get('closed_items') or []),
            'reassigned_tasks': len(result.get('reassigned_tasks') or []),
        },
        'received_at': _now().isoformat(),
    }


def _now():
    return datetime.now(timezone.utc)


def _secret():
    return os.getenv('AEOS_PERSON_LIFECYCLE_SECRET') or os.getenv('HLC_PERSON_LIFECYCLE_SECRET') or ''


def _m01_change_url():
    return (
        os.getenv('AEOS_M01_PERSON_CHANGE_URL')
        or os.getenv('M01_PERSON_CHANGE_URL')
        or (os.getenv('AEOS_M01_URL', '').rstrip('/') + '/integrations/m07' if os.getenv('AEOS_M01_URL') else '')
    )


def _m01_change_secret():
    return os.getenv('AEOS_M01_WEBHOOK_SECRET') or os.getenv('M07_WEBHOOK_SECRET') or ''


def _m01_person_id(employee):
    """统一使用人员编号；有上游统一编号时优先使用它，不能把 HLC 用户表 ID 当人员 ID。"""
    return str(employee.oa_person_id or employee.id)


def _submit_m01_person_change(payload):
    """把 M07 的人员变动资料交给 M01；M01 是唯一的审核和办理入口。"""
    url = _m01_change_url()
    secret = _m01_change_secret()
    if not url or not secret:
        return {'status': 'failed', 'reason': 'M01人员变动接口未配置'}, 503
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), raw, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        url,
        data=raw,
        headers={'Content-Type': 'application/json', 'X-M01-Signature': f'sha256={signature}'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=float(os.getenv('AEOS_M01_TIMEOUT_SECONDS', '5'))) as response:
            body = response.read().decode('utf-8')
            return (json.loads(body) if body else {'status': 'failed', 'reason': 'M01返回为空'}), response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        try:
            result = json.loads(body) if body else {'status': 'failed', 'reason': f'M01返回HTTP {exc.code}'}
        except json.JSONDecodeError:
            result = {'status': 'failed', 'reason': f'M01返回HTTP {exc.code}'}
        return result, exc.code
    except (OSError, ValueError):
        return {'status': 'retrying', 'reason': 'M01暂时无法访问'}, 503


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


@person_lifecycle_bp.route('/api/hrm/person-change-requests', methods=['POST'])
@jwt_required()
def submit_person_change_request():
    """M07填写人员变动资料后提交到M01，不能在M07直接改最终状态。"""
    body = request.get_json(silent=True) or {}
    action = str(body.get('action') or '').strip().lower()
    if action not in PERSON_CHANGE_ACTIONS:
        return jsonify({'status': 'failed', 'reason': '办理事项只能是入职、调岗、离职或复职'}), 400

    requester_id = str(get_jwt_identity() or '').strip()
    requester = db.session.get(User, requester_id)
    if not requester or requester.status != 'active':
        return jsonify({'status': 'failed', 'reason': '当前办理人员不是在职人员'}), 403

    person_id = str(body.get('person_id') or body.get('employee_id') or '').strip()
    employee_no = str(body.get('employee_no') or '').strip()
    employee = None
    if person_id:
        employee = Employee.query.filter_by(id=person_id, tenant_id=requester.tenant_id).first()
    if not employee and person_id:
        employee = Employee.query.filter_by(oa_person_id=person_id, tenant_id=requester.tenant_id).first()
    if not employee and employee_no:
        employee = Employee.query.filter_by(employee_no=employee_no, tenant_id=requester.tenant_id).first()
    if action != 'hire' and not employee:
        return jsonify({'status': 'failed', 'reason': '找不到要办理的人员'}), 404

    if body.get('tenant_id') and str(body['tenant_id']) != str(requester.tenant_id):
        return jsonify({'status': 'failed', 'reason': '不能办理其他单位的人员'}), 403
    required = ('department_id', 'position_id', 'job_title', 'effective_at', 'reason')
    missing = next((field for field in required if not str(body.get(field) or (getattr(employee, field, '') if employee else '')).strip()), None)
    if missing:
        return jsonify({'status': 'failed', 'reason': f'请填写{missing}'}), 400

    effective_at = str(body.get('effective_at') or '').strip()
    requester_employee = (
        Employee.query.filter_by(id=requester.employee_id, tenant_id=requester.tenant_id).first()
        if requester.employee_id else None
    )
    payload = {
        'type': 'person.change.request',
        'tenant_id': str(requester.tenant_id),
        'requester_id': _m01_person_id(requester_employee) if requester_employee else requester_id,
        'person_id': _m01_person_id(employee) if employee else person_id,
        'action': action,
        'department_id': str(body.get('department_id') or employee.department_id),
        'position_id': str(body.get('position_id') or employee.position_id),
        'job_title': str(body.get('job_title') or employee.job_title),
        'effective_at': effective_at,
        'reason': str(body.get('reason') or '').strip(),
        'idempotency_key': str(body.get('idempotency_key') or f'{requester.tenant_id}:{employee.id if employee else person_id}:{action}:{effective_at}'),
    }
    result, status = _submit_m01_person_change(payload)
    return jsonify(result), status


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
        return _contract_result(payload, result), 200
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
    return _contract_result(payload, result), 200


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
