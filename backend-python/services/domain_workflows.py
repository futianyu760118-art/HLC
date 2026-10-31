from __future__ import annotations

from datetime import date, datetime
from typing import Any

from flask import request
from flask_jwt_extended import get_jwt_identity

from models import (
    Contract,
    Employee,
    EmployeePortalAccount,
    Notification,
    OperationLog,
    Probation,
    Resignation,
    User,
    db,
)
from services.tenancy import assign_tenant, object_belongs_to_current_tenant


class WorkflowError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


RESOURCE_MODELS = {
    'contracts': Contract,
    'probations': Probation,
    'resignations': Resignation,
}

TRANSITION_LABELS = {
    'renew': '续签',
    'terminate': '终止',
    'approve': '通过',
    'reject': '驳回',
    'extend': '延期',
    'complete': '离职确认',
}

TRANSITION_RULES = {
    'contracts': {
        'renew': {'from': {'active', 'expired'}, 'to': 'active', 'label': '续签合同'},
        'terminate': {'from': {'active', 'draft', 'expired'}, 'to': 'terminated', 'label': '终止合同'},
    },
    'probations': {
        'approve': {'from': {'draft', 'pending', 'rejected'}, 'to': 'approved', 'label': '通过转正'},
        'reject': {'from': {'draft', 'pending'}, 'to': 'rejected', 'label': '驳回转正'},
        'extend': {'from': {'draft', 'pending', 'rejected'}, 'to': 'pending', 'label': '延期转正'},
    },
    'resignations': {
        'complete': {'from': {'approved', 'pending'}, 'to': 'completed', 'label': '确认离职'},
        'reject': {'from': {'draft', 'pending', 'approved'}, 'to': 'rejected', 'label': '驳回离职'},
    },
}


def _today() -> date:
    return date.today()


def _parse_date(value: Any) -> date | None:
    if value in (None, ''):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], '%Y-%m-%d').date()
        except ValueError as exc:
            raise WorkflowError('日期格式无效，请使用 YYYY-MM-DD', 400) from exc


def _submitted_evidence(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_submitted_evidence(item) for item in value[:50]]
    if isinstance(value, dict):
        return {str(key): _submitted_evidence(item) for key, item in list(value.items())[:50]}
    return str(value)


def _new_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _model_for(resource: str):
    model = RESOURCE_MODELS.get(resource)
    if not model:
        raise WorkflowError('Unsupported workflow resource', 404)
    return model


def _record_title(resource: str, record: Any) -> str:
    employee_name = getattr(getattr(record, 'employee', None), 'name', None) or '员工'
    if resource == 'contracts':
        return f'合同：{getattr(record, "contract_no", None) or employee_name}'
    if resource == 'probations':
        return f'转正：{employee_name}'
    if resource == 'resignations':
        return f'离职：{employee_name}'
    return employee_name


def get_workflow_record(resource: str, item_id: str):
    model = _model_for(resource)
    record = model.query.get(item_id)
    if not record or not object_belongs_to_current_tenant(record):
        raise WorkflowError('Not found', 404)
    return record


def available_transitions(resource: str, record: Any) -> list[dict[str, Any]]:
    status = str(getattr(record, 'status', '') or '')
    transitions = []
    for key, rule in TRANSITION_RULES.get(resource, {}).items():
        transitions.append({
            'key': key,
            'label': rule['label'],
            'enabled': status in rule['from'],
            'from': sorted(rule['from']),
            'to': rule['to'],
        })
    return transitions


def _created_event(resource: str, record: Any) -> dict[str, Any]:
    return {
        'id': f'{resource}:{record.id}:created',
        'eventType': 'created',
        'module': resource,
        'action': 'created',
        'actorId': getattr(record, 'created_by', None),
        'actorName': None,
        'at': _iso(getattr(record, 'created_at', None)),
        'title': '创建记录',
        'detail': {},
    }


def _iso(value: Any) -> str | None:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return None


def workflow_timeline(resource: str, record: Any) -> list[dict[str, Any]]:
    rows = OperationLog.query.filter_by(module=resource, target_id=record.id).order_by(OperationLog.created_at.desc()).limit(100).all()
    events = []
    for row in rows:
        detail = row.detail or {}
        events.append({
            'id': row.id,
            'eventType': 'operation',
            'module': row.module,
            'action': row.action,
            'actorId': row.user_id,
            'actorName': row.user.name if row.user else None,
            'at': _iso(row.created_at),
            'title': detail.get('label') or TRANSITION_LABELS.get(str(row.action or '').replace('workflow_', ''), row.action),
            'detail': detail,
        })
    events.append(_created_event(resource, record))
    events.sort(key=lambda item: item.get('at') or '', reverse=True)
    return events


def workflow_payload(resource: str, record: Any) -> dict[str, Any]:
    return {
        'resource': resource,
        'recordId': record.id,
        'status': getattr(record, 'status', None),
        'record': record.to_dict(),
        'transitions': available_transitions(resource, record),
        'timeline': workflow_timeline(resource, record),
    }


def _log_operation(resource: str, transition: str, record: Any, detail: dict[str, Any]) -> OperationLog:
    log = OperationLog(
        id=_new_id(),
        user_id=get_jwt_identity(),
        module=resource,
        action=f'workflow_{transition}',
        target_id=record.id,
        detail=detail,
        ip=request.headers.get('X-Forwarded-For', request.remote_addr) if request else None,
    )
    assign_tenant(log)
    db.session.add(log)
    return log


def _notify_actor(resource: str, transition: str, record: Any) -> Notification | None:
    user_id = get_jwt_identity()
    if not user_id:
        return None
    actor = User.query.get(user_id)
    if not actor:
        return None
    title = f'{_record_title(resource, record)}已{TRANSITION_LABELS.get(transition, transition)}'
    notice = Notification(
        id=_new_id(),
        user_id=user_id,
        title=title,
        content=f'状态已更新为：{getattr(record, "status", "")}',
        notice_type='workflow',
        status='unread',
        link_url=f'/hrm/{resource}?id={record.id}',
    )
    assign_tenant(notice)
    db.session.add(notice)
    return notice


def _ensure_allowed(resource: str, transition: str, record: Any) -> dict[str, Any]:
    rules = TRANSITION_RULES.get(resource, {})
    rule = rules.get(transition)
    if not rule:
        raise WorkflowError('Unsupported workflow transition', 404)
    current_status = str(getattr(record, 'status', '') or '')
    if current_status not in rule['from']:
        allowed = '、'.join(sorted(rule['from']))
        raise WorkflowError(f'当前状态不允许执行该动作，可执行状态：{allowed}', 400)
    return rule


def _apply_contract_transition(record: Contract, transition: str, data: dict[str, Any], next_status: str) -> None:
    if transition == 'renew':
        start_date = _parse_date(data.get('startDate'))
        end_date = _parse_date(data.get('endDate'))
        if not start_date or not end_date:
            raise WorkflowError('续签合同需要开始日期和结束日期', 400)
        if end_date < start_date:
            raise WorkflowError('合同结束日期不能早于开始日期', 400)
        record.start_date = start_date
        record.end_date = end_date
        record.reminder_date = _parse_date(data.get('reminderDate')) or record.reminder_date
    if transition == 'terminate':
        record.reminder_date = None
    if 'attachmentUrl' in data:
        record.attachment_url = str(data.get('attachmentUrl') or '')
    if 'remark' in data:
        record.remark = str(data.get('remark') or '')
    record.status = next_status
    record.updated_at = datetime.utcnow()


def _apply_probation_transition(record: Probation, transition: str, data: dict[str, Any], next_status: str) -> None:
    if 'selfReview' in data:
        record.self_review = str(data.get('selfReview') or '')
    if 'managerReview' in data:
        record.manager_review = str(data.get('managerReview') or '')
    if 'remark' in data:
        record.remark = str(data.get('remark') or '')
    if transition == 'approve':
        record.regular_date = _parse_date(data.get('regularDate')) or record.regular_date or _today()
        record.result = str(data.get('result') or record.result or '通过')
        employee = Employee.query.get(record.employee_id)
        if employee:
            employee.status = 'active'
            employee.updated_at = datetime.utcnow()
    elif transition == 'reject':
        record.result = str(data.get('result') or record.result or '驳回')
    elif transition == 'extend':
        expected_regular_date = _parse_date(data.get('expectedRegularDate'))
        if not expected_regular_date:
            raise WorkflowError('延期转正需要新的预计转正日期', 400)
        record.expected_regular_date = expected_regular_date
        record.result = str(data.get('result') or record.result or '延期')
    record.status = next_status
    record.updated_at = datetime.utcnow()


def _apply_resignation_transition(record: Resignation, transition: str, data: dict[str, Any], next_status: str) -> None:
    if 'reason' in data:
        record.reason = str(data.get('reason') or '')
    if 'handoverItems' in data:
        value = data.get('handoverItems')
        if isinstance(value, list):
            record.handover_items = value
        elif isinstance(value, str):
            record.handover_items = [item.strip() for item in value.replace('，', ',').split(',') if item.strip()]
    if transition == 'complete':
        record.actual_leave_date = _parse_date(data.get('actualLeaveDate')) or record.actual_leave_date or record.expected_leave_date or _today()
        employee = Employee.query.get(record.employee_id)
        if employee:
            employee.status = 'resigned'
            employee.updated_at = datetime.utcnow()
        EmployeePortalAccount.query.filter_by(employee_id=record.employee_id).update({'status': 'inactive'})
    record.status = next_status
    record.updated_at = datetime.utcnow()


def apply_workflow_transition(resource: str, item_id: str, transition: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    record = get_workflow_record(resource, item_id)
    rule = _ensure_allowed(resource, transition, record)
    previous_status = getattr(record, 'status', None)

    if resource == 'contracts':
        _apply_contract_transition(record, transition, data, rule['to'])
    elif resource == 'probations':
        _apply_probation_transition(record, transition, data, rule['to'])
    elif resource == 'resignations':
        _apply_resignation_transition(record, transition, data, rule['to'])
    else:
        raise WorkflowError('Unsupported workflow resource', 404)

    detail = {
        'label': rule['label'],
        'transition': transition,
        'fromStatus': previous_status,
        'toStatus': getattr(record, 'status', None),
        'submitted': _submitted_evidence(data),
    }
    _log_operation(resource, transition, record, detail)
    _notify_actor(resource, transition, record)
    db.session.commit()
    return {
        'record': record.to_dict(),
        'workflow': workflow_payload(resource, record),
    }
