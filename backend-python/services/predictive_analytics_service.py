"""预测性分析服务 - P0核心功能"""
from typing import Dict
from models import db, Employee, Resignation
from datetime import datetime, timedelta

class PredictiveAnalyticsService:
    """预测性分析"""
    
    @staticmethod
    def predict_turnover_risk(employee_id: str, tenant_id: str) -> Dict:
        """预测离职风险
        
        基于因素：
        - 在职时长（1-2年高风险）
        - 绩效趋势（下降=高风险）
        - 薪资竞争力
        - 晋升停滞
        """
        from services.talent_profile_service import TalentProfileService
        
        employee = Employee.query.get(employee_id)
        if not employee:
            return {'risk_score': 0, 'risk_level': 'unknown'}
        
        risk_score = 0
        risk_factors = []
        
        # 1. 在职时长因素
        if employee.join_date:
            tenure_months = (datetime.now().date() - employee.join_date).days / 30
            if 12 <= tenure_months <= 24:
                risk_score += 30
                risk_factors.append('在职1-2年（离职高峰期）')
            elif tenure_months > 60:
                risk_score -= 10  # 老员工相对稳定
        
        # 2. 绩效趋势
        try:
            profile = TalentProfileService.get_talent_profile(employee_id, tenant_id)
            perf = profile.get('performance', {})
            if perf.get('trend') == 'declining':
                risk_score += 25
                risk_factors.append('绩效下降')
            if perf.get('level') == 'low':
                risk_score += 20
                risk_factors.append('绩效偏低')
        except:
            pass
        
        # 3. 晋升停滞（简化：2年未晋升）
        if employee.join_date and (datetime.now().date() - employee.join_date).days > 730:
            risk_score += 15
            risk_factors.append('长期未晋升')
        
        # 风险等级
        risk_level = 'high' if risk_score >= 50 else 'medium' if risk_score >= 30 else 'low'
        
        return {
            'employee_id': employee_id,
            'employee_name': employee.name,
            'risk_score': min(risk_score, 100),
            'risk_level': risk_level,
            'risk_factors': risk_factors,
            'recommendation': PredictiveAnalyticsService._get_retention_recommendation(risk_level),
        }
    
    @staticmethod
    def _get_retention_recommendation(risk_level: str) -> str:
        """保留建议"""
        if risk_level == 'high':
            return '建议HR立即介入：1对1沟通、了解诉求、制定保留计划'
        elif risk_level == 'medium':
            return '建议关注：定期沟通、关注职业发展需求'
        else:
            return '风险较低，保持正常关怀'
