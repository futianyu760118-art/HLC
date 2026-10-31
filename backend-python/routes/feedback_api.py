"""持续反馈 API 路由"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, date

from models import db
from services.tenancy import current_tenant_id
from services.feedback_service import FeedbackService

feedback_bp = Blueprint('feedback_api', __name__)


@feedback_bp.route('/one-on-one', methods=['POST'])
@jwt_required()
def create_one_on_one():
    """创建 1-on-1 会议记录"""
    tenant_id = current_tenant_id()
    manager_id = get_jwt_identity()

    if not tenant_id:
        return jsonify({'error': '租户信息缺失'}), 400

    data = request.get_json()
    employee_id = data.get('employee_id')
    meeting_date_str = data.get('meeting_date')

    if not employee_id or not meeting_date_str:
        return jsonify({'error': '缺少必要参数'}), 400

    try:
        meeting_date = date.fromisoformat(meeting_date_str)
        result = FeedbackService.create_one_on_one(
            tenant_id=tenant_id,
            employee_id=employee_id,
            manager_id=manager_id,
            meeting_date=meeting_date,
            data=data,
        )
        return jsonify(result), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@feedback_bp.route('/one-on-one/employee/<employee_id>', methods=['GET'])
@jwt_required()
def get_employee_meetings(employee_id):
    """获取员工的 1-on-1 会议历史"""
    tenant_id = current_tenant_id()

    if not tenant_id:
        return jsonify({'error': '租户信息缺失'}), 400

    try:
        meetings = FeedbackService.get_employee_meetings(tenant_id, employee_id)
        return jsonify({'meetings': meetings})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@feedback_bp.route('/continuous-feedback', methods=['POST'])
@jwt_required()
def create_feedback():
    """创建即时反馈"""
    tenant_id = current_tenant_id()
    giver_id = get_jwt_identity()

    if not tenant_id:
        return jsonify({'error': '租户信息缺失'}), 400

    data = request.get_json()
    employee_id = data.get('employee_id')
    feedback_type = data.get('feedback_type')
    category = data.get('category')
    content = data.get('content')

    if not all([employee_id, feedback_type, content]):
        return jsonify({'error': '缺少必要参数'}), 400

    try:
        result = FeedbackService.create_feedback(
            tenant_id=tenant_id,
            employee_id=employee_id,
            giver_id=giver_id,
            feedback_type=feedback_type,
            category=category or '',
            content=content,
            is_private=data.get('is_private', True),
        )
        return jsonify(result), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@feedback_bp.route('/continuous-feedback/employee/<employee_id>', methods=['GET'])
@jwt_required()
def get_employee_feedback(employee_id):
    """获取员工收到的反馈历史"""
    tenant_id = current_tenant_id()

    if not tenant_id:
        return jsonify({'error': '租户信息缺失'}), 400

    try:
        feedbacks = FeedbackService.get_employee_feedback(tenant_id, employee_id)
        return jsonify({'feedbacks': feedbacks})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@feedback_bp.route('/feedback-stats/employee/<employee_id>', methods=['GET'])
@jwt_required()
def get_feedback_stats(employee_id):
    """获取员工反馈统计"""
    tenant_id = current_tenant_id()

    if not tenant_id:
        return jsonify({'error': '租户信息缺失'}), 400

    try:
        stats = FeedbackService.get_feedback_stats(tenant_id, employee_id)
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
