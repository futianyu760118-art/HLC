"""能力模型服务 - P0核心功能"""
from typing import Dict, List
from models import db, Employee

class CompetencyModelService:
    """能力模型管理"""
    
    COMPETENCY_CATEGORIES = {
        'technical': '技术能力',
        'leadership': '领导力',
        'communication': '沟通能力',
        'problem_solving': '问题解决',
        'teamwork': '团队协作',
    }
    
    @staticmethod
    def evaluate_employee_competency(employee_id: str, competencies: Dict) -> Dict:
        """评估员工能力"""
        scores = {}
        gaps = []
        
        for category, items in competencies.items():
            category_scores = []
            for item in items:
                score = item.get('score', 0)
                category_scores.append(score)
                if score < 60:
                    gaps.append({'competency': item['name'], 'score': score})
            
            scores[category] = sum(category_scores) / len(category_scores) if category_scores else 0
        
        overall_score = sum(scores.values()) / len(scores) if scores else 0
        
        return {
            'overall_score': overall_score,
            'category_scores': scores,
            'gaps': gaps,
            'level': 'expert' if overall_score >= 80 else 'proficient' if overall_score >= 60 else 'developing'
        }
