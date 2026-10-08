"""能力模型和继任计划API路由"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from services.tenancy import current_tenant_id
from services.competency_model_service import CompetencyModelService
from services.succession_planning_service import SuccessionPlanningService

competency_bp = Blueprint('competency', __name__)

@competency_bp.route('/competency/evaluate', methods=['POST'])
@jwt_required()
def evaluate_competency():
    """评估员工能力"""
    tenant_id = current_tenant_id()
    data = request.get_json()
    
    employee_id = data.get('employee_id')
    competencies = data.get('competencies')
    
    if not employee_id or not competencies:
        return jsonify({'error': '缺少必要参数'}), 400
    
    try:
        result = CompetencyModelService.evaluate_employee_competency(
            employee_id, competencies
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@competency_bp.route('/succession/key-positions', methods=['GET'])
@jwt_required()
def get_key_positions():
    """获取关键岗位"""
    tenant_id = current_tenant_id()
    try:
        positions = SuccessionPlanningService.identify_key_positions(tenant_id)
        return jsonify({'positions': positions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@competency_bp.route('/succession/successors/<position_id>', methods=['GET'])
@jwt_required()
def get_successors(position_id):
    """获取继任者候选人"""
    tenant_id = current_tenant_id()
    try:
        successors = SuccessionPlanningService.identify_successors(position_id, tenant_id)
        return jsonify({'successors': successors})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
