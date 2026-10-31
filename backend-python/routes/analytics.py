"""人才分析和People Analytics API路由"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from services.tenancy import current_tenant_id
from services.people_analytics_service import PeopleAnalyticsService
from services.talent_profile_service import TalentProfileService

analytics_bp = Blueprint('analytics', __name__)

@analytics_bp.route('/people-analytics/dashboard', methods=['GET'])
@jwt_required()
def get_analytics_dashboard():
    """获取People Analytics仪表盘"""
    tenant_id = current_tenant_id()
    if not tenant_id:
        return jsonify({'error': '租户信息缺失'}), 400
    
    try:
        data = PeopleAnalyticsService.get_analytics_dashboard(tenant_id)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@analytics_bp.route('/talent-profile/<employee_id>', methods=['GET'])
@jwt_required()
def get_talent_profile(employee_id):
    """获取员工人才画像"""
    tenant_id = current_tenant_id()
    if not tenant_id:
        return jsonify({'error': '租户信息缺失'}), 400
    
    try:
        profile = TalentProfileService.get_talent_profile(employee_id, tenant_id)
        return jsonify(profile)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@analytics_bp.route('/talent-density', methods=['GET'])
@jwt_required()
def get_talent_density():
    """获取人才密度"""
    tenant_id = current_tenant_id()
    try:
        data = PeopleAnalyticsService.calculate_talent_density(tenant_id)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@analytics_bp.route('/org-health', methods=['GET'])
@jwt_required()
def get_org_health():
    """获取组织健康度"""
    tenant_id = current_tenant_id()
    try:
        data = PeopleAnalyticsService.calculate_org_health(tenant_id)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@analytics_bp.route('/turnover-analysis', methods=['GET'])
@jwt_required()
def get_turnover_analysis():
    """获取流失率分析"""
    tenant_id = current_tenant_id()
    time_range = request.args.get('range', 'year')
    try:
        data = PeopleAnalyticsService.analyze_turnover(tenant_id, time_range)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
