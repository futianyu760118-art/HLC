"""人才画像服务 - P0核心功能

功能：
- 360度人才画像
- 多维度数据聚合
- 能力/绩效/潜力评估
- 人才标签系统
"""

from typing import Dict, List, Any
from models import db, Employee, PerformanceReview, TrainingRecord
from datetime import datetime, timedelta


class TalentProfileService:
    """人才画像服务"""
    
    @staticmethod
    def get_talent_profile(employee_id: str, tenant_id: str) -> Dict[str, Any]:
        """获取员工360度人才画像"""
        employee = Employee.query.get(employee_id)
        if not employee or employee.tenant_id != tenant_id:
            raise ValueError("员工不存在")
        
        return {
            'basic_info': TalentProfileService._get_basic_info(employee),
            'performance': TalentProfileService._get_performance_dimension(employee_id, tenant_id),
            'competency': TalentProfileService._get_competency_dimension(employee_id, tenant_id),
            'potential': TalentProfileService._get_potential_dimension(employee_id, tenant_id),
            'learning': TalentProfileService._get_learning_dimension(employee_id, tenant_id),
            'tags': TalentProfileService._get_talent_tags(employee_id, tenant_id),
            'nine_box': TalentProfileService._calculate_nine_box_position(employee_id, tenant_id),
        }
    
    @staticmethod
    def _get_basic_info(employee: Employee) -> Dict[str, Any]:
        """基础信息"""
        return {
            'id': employee.id,
            'name': employee.name,
            'position': employee.position.name if employee.position else None,
            'department': employee.department.name if employee.department else None,
            'level': employee.level,
            'tenure_years': (datetime.now().date() - employee.join_date).days / 365 if employee.join_date else 0,
        }
    
    @staticmethod
    def _get_performance_dimension(employee_id: str, tenant_id: str) -> Dict[str, Any]:
        """绩效维度"""
        # 最近3次绩效
        reviews = PerformanceReview.query.filter_by(
            employee_id=employee_id,
            tenant_id=tenant_id
        ).order_by(PerformanceReview.created_at.desc()).limit(3).all()
        
        if not reviews:
            return {'score': 0, 'trend': 'stable', 'level': 'unknown'}
        
        scores = [r.final_score for r in reviews if r.final_score]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        # 趋势：上升/稳定/下降
        trend = 'stable'
        if len(scores) >= 2:
            if scores[0] > scores[1]:
                trend = 'rising'
            elif scores[0] < scores[1]:
                trend = 'declining'
        
        # 评级
        level = 'high' if avg_score >= 90 else 'medium' if avg_score >= 70 else 'low'
        
        return {
            'score': avg_score,
            'trend': trend,
            'level': level,
            'recent_reviews': len(reviews),
        }
    
    @staticmethod
    def _get_competency_dimension(employee_id: str, tenant_id: str) -> Dict[str, Any]:
        """能力维度（需要能力模型数据，这里先返回模拟）"""
        return {
            'overall_score': 75,
            'technical_competency': 80,
            'leadership_competency': 70,
            'communication_competency': 75,
            'gaps': ['战略思维', '团队管理'],
        }
    
    @staticmethod
    def _get_potential_dimension(employee_id: str, tenant_id: str) -> Dict[str, Any]:
        """潜力维度"""
        # 基于：学习能力、晋升速度、绩效趋势
        perf = TalentProfileService._get_performance_dimension(employee_id, tenant_id)
        learning = TalentProfileService._get_learning_dimension(employee_id, tenant_id)
        
        # 简化的潜力评分
        potential_score = (perf['score'] * 0.4 + learning['completion_rate'] * 0.6)
        
        level = 'high' if potential_score >= 80 else 'medium' if potential_score >= 60 else 'low'
        
        return {
            'score': potential_score,
            'level': level,
            'factors': {
                'learning_agility': learning['completion_rate'],
                'performance_trend': perf['trend'],
            }
        }
    
    @staticmethod
    def _get_learning_dimension(employee_id: str, tenant_id: str) -> Dict[str, Any]:
        """学习维度"""
        records = TrainingRecord.query.filter_by(
            employee_id=employee_id,
            tenant_id=tenant_id
        ).all()
        
        total = len(records)
        completed = len([r for r in records if r.status == 'completed'])
        completion_rate = (completed / total * 100) if total > 0 else 0
        
        return {
            'total_courses': total,
            'completed': completed,
            'completion_rate': completion_rate,
            'learning_hours': sum([r.duration or 0 for r in records if r.status == 'completed']),
        }
    
    @staticmethod
    def _get_talent_tags(employee_id: str, tenant_id: str) -> List[str]:
        """人才标签"""
        tags = []
        
        perf = TalentProfileService._get_performance_dimension(employee_id, tenant_id)
        potential = TalentProfileService._get_potential_dimension(employee_id, tenant_id)
        
        # 基于数据自动打标签
        if perf['level'] == 'high':
            tags.append('高绩效')
        if potential['level'] == 'high':
            tags.append('高潜力')
        if perf['level'] == 'high' and potential['level'] == 'high':
            tags.append('核心人才')
        if perf['trend'] == 'rising':
            tags.append('快速成长')
        
        return tags
    
    @staticmethod
    def _calculate_nine_box_position(employee_id: str, tenant_id: str) -> Dict[str, Any]:
        """计算九宫格位置"""
        perf = TalentProfileService._get_performance_dimension(employee_id, tenant_id)
        potential = TalentProfileService._get_potential_dimension(employee_id, tenant_id)
        
        # 绩效：low/medium/high
        perf_level = perf['level']
        # 潜力：low/medium/high
        potential_level = potential['level']
        
        # 九宫格分类
        box_map = {
            ('high', 'high'): '明星员工',
            ('high', 'medium'): '核心骨干',
            ('high', 'low'): '稳定贡献者',
            ('medium', 'high'): '潜力员工',
            ('medium', 'medium'): '中坚力量',
            ('medium', 'low'): '稳定员工',
            ('low', 'high'): '新手期',
            ('low', 'medium'): '待观察',
            ('low', 'low'): '需改进',
        }
        
        box_type = box_map.get((perf_level, potential_level), '未分类')
        
        return {
            'performance': perf_level,
            'potential': potential_level,
            'box_type': box_type,
            'position': f'{perf_level}-{potential_level}',
        }
