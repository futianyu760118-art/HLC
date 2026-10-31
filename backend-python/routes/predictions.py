"""预测性分析API路由"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from services.tenancy import current_tenant_id
from services.predictive_analytics_service import PredictiveAnalyticsService

predictions_bp = Blueprint('predictions', __name__)

@predictions_bp.route('/predict/turnover-risk/<employee_id>', methods=['GET'])
@jwt_required()
def predict_turnover_risk(employee_id):
    """预测离职风险"""
    tenant_id = current_tenant_id()
    try:
        prediction = PredictiveAnalyticsService.predict_turnover_risk(employee_id, tenant_id)
        return jsonify(prediction)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@predictions_bp.route('/predict/high-risk-employees', methods=['GET'])
@jwt_required()
def get_high_risk_employees():
    """获取高离职风险员工列表"""
    tenant_id = current_tenant_id()
    from models import Employee
    
    try:
        employees = Employee.query.filter_by(tenant_id=tenant_id, status='active').all()
        high_risk = []
        
        for emp in employees:
            prediction = PredictiveAnalyticsService.predict_turnover_risk(emp.id, tenant_id)
            if prediction['risk_level'] == 'high':
                high_risk.append(prediction)
        
        return jsonify({'employees': high_risk, 'count': len(high_risk)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
