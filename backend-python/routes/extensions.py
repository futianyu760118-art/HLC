"""Tenant-facing extension APIs.

Extension routes stay behind tenant module gates.  The catalog itself is always
readable for an authenticated tenant so the UI can explain what is enabled,
while feature endpoints require their matching extension module row to be open.
"""

from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from models import Department, Employee, ExtensionProviderConfig, OperationLog, db
from services.extension_registry import (
    EXTENSION_MODULE_KEY_SET,
    extension_catalog_payload,
    extension_feature_status_payload,
    public_provider_config,
)
from services.analytics_insight_service import AnalyticsInsightService
from services.authz import (
    ORG_READ_ROLES,
    ORG_WRITE_ROLES,
    PAYROLL_READ_ROLES,
    SYSTEM_ROLES,
    require_roles,
)
from services.collaboration_service import CollaborationService
from services.continuous_feedback_service import ContinuousFeedbackService
from services.headcount_service import HeadcountService
from services.intelligence_service import IntelligenceService
from services.integration_service import IntegrationService
from services.mobile_service import MobileService
from services.people_analytics_service import PeopleAnalyticsService
from services.security_service import SecurityService
from services.talent_strategy_service import TalentStrategyService
from services.tenancy import current_tenant_id
from services.workforce_service import WorkforceService


extensions_bp = Blueprint('extensions', __name__)
CONTINUOUS_FEEDBACK_WRITE_ROLES = {'admin', 'hr_admin', 'manager'}


def _summary_access(domain: str, feature: str | None = None):
    if domain == 'intelligence' and feature == 'smart_compensation':
        return require_roles(PAYROLL_READ_ROLES, '无权限查看薪酬智能数据')
    if domain in {'integration', 'security'}:
        return require_roles(SYSTEM_ROLES, '无权限查看平台配置或安全数据')
    return require_roles(ORG_READ_ROLES, '无权限查看组织级扩展数据')


@extensions_bp.route('/catalog', methods=['GET'])
@jwt_required()
def tenant_extension_catalog():
    return jsonify(extension_catalog_payload(current_tenant_id()))


@extensions_bp.route('/analytics/people/summary', methods=['GET'])
@jwt_required()
def people_analytics_summary():
    denied = _summary_access('analytics', 'people')
    if denied:
        return denied
    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    payload = PeopleAnalyticsService.build_extension_summary(tenant_id, operator_id=operator_id)
    return jsonify(payload)


@extensions_bp.route('/analytics/<feature>/summary', methods=['GET'])
@jwt_required()
def analytics_feature_summary(feature):
    denied = _summary_access('analytics', feature)
    if denied:
        return denied
    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    try:
        payload = AnalyticsInsightService.build_feature_summary(tenant_id, feature, operator_id=operator_id)
    except LookupError:
        return jsonify({'error': '扩展功能不存在', 'code': 'EXTENSION_FEATURE_NOT_FOUND'}), 404
    return jsonify(payload)


@extensions_bp.route('/intelligence/<feature>/summary', methods=['GET'])
@jwt_required()
def intelligence_feature_summary(feature):
    denied = _summary_access('intelligence', feature)
    if denied:
        return denied
    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    try:
        payload = IntelligenceService.build_feature_summary(tenant_id, feature, operator_id=operator_id)
    except LookupError:
        return jsonify({'error': '扩展功能不存在', 'code': 'EXTENSION_FEATURE_NOT_FOUND'}), 404
    return jsonify(payload)


@extensions_bp.route('/collaboration/<feature>/summary', methods=['GET'])
@jwt_required()
def collaboration_feature_summary(feature):
    denied = _summary_access('collaboration', feature)
    if denied:
        return denied
    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    try:
        payload = CollaborationService.build_feature_summary(tenant_id, feature, operator_id=operator_id)
    except LookupError:
        return jsonify({'error': '扩展功能不存在', 'code': 'EXTENSION_FEATURE_NOT_FOUND'}), 404
    return jsonify(payload)


@extensions_bp.route('/workforce/<feature>/summary', methods=['GET'])
@jwt_required()
def workforce_feature_summary(feature):
    denied = _summary_access('workforce', feature)
    if denied:
        return denied
    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    try:
        payload = WorkforceService.build_feature_summary(tenant_id, feature, operator_id=operator_id)
    except LookupError:
        return jsonify({'error': '扩展功能不存在', 'code': 'EXTENSION_FEATURE_NOT_FOUND'}), 404
    return jsonify(payload)


@extensions_bp.route('/integration/<feature>/summary', methods=['GET'])
@jwt_required()
def integration_feature_summary(feature):
    denied = _summary_access('integration', feature)
    if denied:
        return denied
    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    try:
        payload = IntegrationService.build_feature_summary(tenant_id, feature, operator_id=operator_id)
    except LookupError:
        return jsonify({'error': '扩展功能不存在', 'code': 'EXTENSION_FEATURE_NOT_FOUND'}), 404
    return jsonify(payload)


@extensions_bp.route('/mobile/<feature>/summary', methods=['GET'])
@jwt_required()
def mobile_feature_summary(feature):
    denied = _summary_access('mobile', feature)
    if denied:
        return denied
    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    try:
        payload = MobileService.build_feature_summary(tenant_id, feature, operator_id=operator_id)
    except LookupError:
        return jsonify({'error': '扩展功能不存在', 'code': 'EXTENSION_FEATURE_NOT_FOUND'}), 404
    return jsonify(payload)


@extensions_bp.route('/security/<feature>/summary', methods=['GET'])
@jwt_required()
def security_feature_summary(feature):
    denied = _summary_access('security', feature)
    if denied:
        return denied
    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    try:
        payload = SecurityService.build_feature_summary(tenant_id, feature, operator_id=operator_id)
    except LookupError:
        return jsonify({'error': '扩展功能不存在', 'code': 'EXTENSION_FEATURE_NOT_FOUND'}), 404
    return jsonify(payload)


@extensions_bp.route('/foundation/headcount/summary', methods=['GET'])
@jwt_required()
def headcount_summary():
    denied = require_roles(ORG_READ_ROLES, '无权限查看编制数据')
    if denied:
        return denied
    return jsonify(HeadcountService.get_headcount_summary(current_tenant_id()))


@extensions_bp.route('/foundation/headcount/departments/<department_id>', methods=['PUT'])
@jwt_required()
def update_department_headcount(department_id):
    denied = require_roles(ORG_WRITE_ROLES, '无权限修改部门编制')
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if 'plan' not in data:
        return jsonify({'error': '缺少编制人数', 'code': 'HEADCOUNT_PLAN_REQUIRED'}), 400
    try:
        headcount_plan = int(data.get('plan'))
    except (TypeError, ValueError):
        return jsonify({'error': '编制人数必须是整数', 'code': 'HEADCOUNT_PLAN_INVALID'}), 400

    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    try:
        payload = HeadcountService.update_department_headcount(
            department_id=department_id,
            tenant_id=tenant_id,
            headcount_plan=headcount_plan,
            operator_id=operator_id,
            note=data.get('note') or '',
        )
    except LookupError:
        db.session.rollback()
        return jsonify({'error': '部门不存在或无权访问', 'code': 'HEADCOUNT_DEPARTMENT_FORBIDDEN'}), 403
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'HEADCOUNT_PLAN_INVALID'}), 400

    db.session.add(OperationLog(
        id=str(uuid.uuid4()),
        user_id=operator_id,
        tenant_id=tenant_id,
        module='extension.foundation.headcount',
        action='update_department_plan',
        target_id=department_id,
        detail={
            'oldPlan': payload['oldPlan'],
            'newPlan': payload['newPlan'],
            'actual': payload['actual'],
            'note': payload.get('note') or '',
        },
        ip=request.headers.get('X-Forwarded-For', request.remote_addr),
    ))
    db.session.commit()
    return jsonify(payload)


@extensions_bp.route('/foundation/headcount/history', methods=['GET'])
@jwt_required()
def headcount_history():
    denied = require_roles(ORG_READ_ROLES, '无权限查看编制历史')
    if denied:
        return denied
    return jsonify(HeadcountService.list_history(
        tenant_id=current_tenant_id(),
        department_id=request.args.get('departmentId') or None,
        limit=request.args.get('limit', 100),
    ))


@extensions_bp.route('/foundation/continuous_feedback/entries', methods=['GET'])
@jwt_required()
def continuous_feedback_entries():
    denied = require_roles(ORG_READ_ROLES, '无权限查看持续反馈')
    if denied:
        return denied
    return jsonify(ContinuousFeedbackService.list_entries(
        tenant_id=current_tenant_id(),
        employee_id=request.args.get('employeeId') or None,
        status=request.args.get('status') or None,
        limit=request.args.get('limit', 100),
    ))


@extensions_bp.route('/foundation/continuous_feedback/entries', methods=['POST'])
@jwt_required()
def create_continuous_feedback_entry():
    denied = require_roles(CONTINUOUS_FEEDBACK_WRITE_ROLES, '无权限创建持续反馈')
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    employee_id = data.get('employeeId') or data.get('employee_id')
    if not employee_id:
        return jsonify({'error': '缺少员工', 'code': 'CONTINUOUS_FEEDBACK_EMPLOYEE_REQUIRED'}), 400

    try:
        entry = ContinuousFeedbackService.create_entry(
            tenant_id=tenant_id,
            employee_id=employee_id,
            giver_id=operator_id,
            data=data,
        )
    except LookupError:
        db.session.rollback()
        return jsonify({'error': '员工不存在或无权访问', 'code': 'CONTINUOUS_FEEDBACK_EMPLOYEE_FORBIDDEN'}), 403
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'CONTINUOUS_FEEDBACK_INVALID'}), 400

    db.session.flush()
    db.session.add(OperationLog(
        id=str(uuid.uuid4()),
        user_id=operator_id,
        tenant_id=tenant_id,
        module='extension.foundation.continuous_feedback',
        action='create_feedback',
        target_id=entry.id,
        detail={
            'employeeId': entry.employee_id,
            'feedbackType': entry.feedback_type,
            'visibility': entry.visibility,
            'sentiment': entry.sentiment,
        },
        ip=request.headers.get('X-Forwarded-For', request.remote_addr),
    ))
    db.session.commit()
    return jsonify({'featureKey': 'extension.foundation.continuous_feedback', 'item': entry.to_dict()}), 201


@extensions_bp.route('/foundation/continuous_feedback/stats', methods=['GET'])
@jwt_required()
def continuous_feedback_stats():
    denied = require_roles(ORG_READ_ROLES, '无权限查看持续反馈统计')
    if denied:
        return denied
    return jsonify(ContinuousFeedbackService.stats(
        tenant_id=current_tenant_id(),
        employee_id=request.args.get('employeeId') or None,
    ))


@extensions_bp.route('/talent/<feature>/summary', methods=['GET'])
@jwt_required()
def talent_strategy_summary(feature):
    denied = _summary_access('talent', feature)
    if denied:
        return denied
    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    try:
        payload = TalentStrategyService.build_feature_summary(tenant_id, feature, operator_id=operator_id)
    except LookupError:
        return jsonify({'error': '扩展功能不存在', 'code': 'EXTENSION_FEATURE_NOT_FOUND'}), 404
    return jsonify(payload)


@extensions_bp.route('/foundation/continuous_feedback/entries/<entry_id>/status', methods=['PUT'])
@jwt_required()
def update_continuous_feedback_status(entry_id):
    denied = require_roles(ORG_WRITE_ROLES, '无权限处理持续反馈')
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    tenant_id = current_tenant_id()
    operator_id = get_jwt_identity()
    try:
        entry = ContinuousFeedbackService.update_status(
            tenant_id=tenant_id,
            entry_id=entry_id,
            status=(data.get('status') or '').strip(),
            handler_id=operator_id,
            handler_reply=data.get('handlerReply') or data.get('handler_reply') or '',
        )
    except LookupError:
        db.session.rollback()
        return jsonify({'error': '反馈不存在或无权访问', 'code': 'CONTINUOUS_FEEDBACK_FORBIDDEN'}), 403
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'CONTINUOUS_FEEDBACK_INVALID_STATUS'}), 400

    db.session.add(OperationLog(
        id=str(uuid.uuid4()),
        user_id=operator_id,
        tenant_id=tenant_id,
        module='extension.foundation.continuous_feedback',
        action='update_feedback_status',
        target_id=entry.id,
        detail={
            'status': entry.status,
            'handlerReply': entry.handler_reply or '',
        },
        ip=request.headers.get('X-Forwarded-For', request.remote_addr),
    ))
    db.session.commit()
    return jsonify({'featureKey': 'extension.foundation.continuous_feedback', 'item': entry.to_dict()})


@extensions_bp.route('/integration/provider-status/<provider_code>', methods=['GET'])
@jwt_required()
def integration_provider_status(provider_code):
    denied = require_roles(SYSTEM_ROLES, '无权限查看供应商配置状态')
    if denied:
        return denied
    row = ExtensionProviderConfig.query.filter_by(provider_code=provider_code).first()
    if not row:
        return jsonify({
            'providerCode': provider_code,
            'configured': False,
            'status': 'unconfigured',
            'message': '未配置真实供应商，当前仅保留本地可测模拟入口。',
        })
    return jsonify({
        'providerType': row.provider_type,
        'providerCode': row.provider_code,
        'configured': bool(row.secret_ref or row.config_json),
        'status': row.status,
        'message': '已配置 provider 适配层；真实供应商能力以平台配置为准。',
        'configJson': public_provider_config(row.config_json),
        'lastTestedAt': row.to_dict().get('lastTestedAt'),
    })


@extensions_bp.route('/<domain>/<feature>/status', methods=['GET'])
@jwt_required()
def extension_feature_status(domain, feature):
    feature_key = f'extension.{domain}.{feature}'
    if feature_key not in EXTENSION_MODULE_KEY_SET:
        return jsonify({'error': '扩展功能不存在', 'code': 'EXTENSION_FEATURE_NOT_FOUND'}), 404
    return jsonify(extension_feature_status_payload(feature_key))
