"""继任计划服务 - P0核心功能"""
from typing import Dict, List
from models import db, Employee, Position

class SuccessionPlanningService:
    """继任计划管理"""
    
    @staticmethod
    def identify_key_positions(tenant_id: str) -> List[Dict]:
        """识别关键岗位"""
        # 基于：层级、业务影响、替代难度
        positions = Position.query.filter_by(tenant_id=tenant_id).all()
        key_positions = []
        
        for pos in positions:
            # 简化判断：管理层或技术骨干
            if pos.level and ('经理' in pos.level or '总监' in pos.level or '专家' in pos.level):
                incumbents = Employee.query.filter_by(
                    tenant_id=tenant_id,
                    position_id=pos.id,
                    status='active'
                ).count()
                
                key_positions.append({
                    'position_id': pos.id,
                    'position_name': pos.name,
                    'incumbents': incumbents,
                    'risk_level': 'high' if incumbents <= 1 else 'medium'
                })
        
        return key_positions
    
    @staticmethod
    def identify_successors(position_id: str, tenant_id: str) -> List[Dict]:
        """识别继任者候选人"""
        # 基于：绩效、潜力、能力匹配度
        from services.talent_profile_service import TalentProfileService
        
        # 获取同部门或相近岗位的高潜员工
        employees = Employee.query.filter_by(
            tenant_id=tenant_id,
            status='active'
        ).all()
        
        successors = []
        for emp in employees:
            try:
                profile = TalentProfileService.get_talent_profile(emp.id, tenant_id)
                nine_box = profile.get('nine_box', {})
                
                # 高绩效+高潜力的员工
                if nine_box.get('performance') == 'high' and nine_box.get('potential') in ['high', 'medium']:
                    successors.append({
                        'employee_id': emp.id,
                        'employee_name': emp.name,
                        'readiness': 'ready' if nine_box.get('potential') == 'high' else 'developing',
                        'performance': profile['performance']['score'],
                        'potential': profile['potential']['score'],
                    })
            except:
                continue
        
        return sorted(successors, key=lambda x: x['performance'], reverse=True)[:5]
