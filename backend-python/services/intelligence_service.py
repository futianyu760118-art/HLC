"""Governed intelligence extension MVP services."""

from __future__ import annotations

import uuid
from datetime import date
from statistics import mean
from typing import Any

from models import (
    Department,
    Employee,
    IntelligenceInsightSnapshot,
    Job,
    PerformanceReview,
    Resume,
    SalaryProfile,
    TrainingRecord,
    db,
    money,
)
from services.extension_registry import extension_feature_maturity, extension_read_marker


INTELLIGENCE_FEATURES = {
    'predictive': 'extension.intelligence.predictive',
    'turnover_risk': 'extension.intelligence.turnover_risk',
    'ai_recruiting_assistant': 'extension.intelligence.ai_recruiting_assistant',
    'smart_compensation': 'extension.intelligence.smart_compensation',
    'hr_bot': 'extension.intelligence.hr_bot',
    'smart_performance': 'extension.intelligence.smart_performance',
    'advanced_ai_analytics': 'extension.intelligence.advanced_ai_analytics',
}

ACTIVE_EMPLOYEE_STATUSES = ('active', 'probation', 'pending_onboard')


def _score(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _ratio(part: int | float, total: int | float) -> float:
    return round((float(part) / float(total)) * 100, 2) if total else 0


def _total_salary(profile: SalaryProfile) -> float:
    return round(
        (money(profile.base_salary) or 0)
        + (money(profile.position_salary) or 0)
        + (money(profile.performance_salary) or 0)
        + (money(profile.allowance) or 0)
        + (money(profile.bonus) or 0)
        - (money(profile.deduction) or 0),
        2,
    )


def _provider_payload() -> dict[str, Any]:
    return {
        'providerCode': 'local_rule_engine',
        'configured': False,
        'status': 'mock',
        'message': '未配置真实供应商，当前使用本地规则引擎生成可测 MVP 快照。',
    }


class IntelligenceService:
    @staticmethod
    def build_feature_summary(tenant_id: str, feature: str, operator_id: str | None = None) -> dict[str, Any]:
        if feature not in INTELLIGENCE_FEATURES:
            raise LookupError(feature)

        base = IntelligenceService._base_context(tenant_id)
        builders = {
            'predictive': IntelligenceService._predictive_payload,
            'turnover_risk': IntelligenceService._turnover_risk_payload,
            'ai_recruiting_assistant': IntelligenceService._recruiting_payload,
            'smart_compensation': IntelligenceService._compensation_payload,
            'hr_bot': IntelligenceService._hr_bot_payload,
            'smart_performance': IntelligenceService._performance_payload,
            'advanced_ai_analytics': IntelligenceService._advanced_payload,
        }
        payload = builders[feature](tenant_id, base)
        feature_key = INTELLIGENCE_FEATURES[feature]
        payload.update({
            'featureKey': feature_key,
            'status': extension_feature_maturity(feature_key),
            'provider': _provider_payload(),
        })
        payload.setdefault('summary', {})['dataScope'] = 'currentTenant'

        payload['snapshot'] = extension_read_marker(feature_key)
        return payload

    @staticmethod
    def _base_context(tenant_id: str) -> dict[str, Any]:
        employees = Employee.query.filter(
            Employee.tenant_id == tenant_id,
            Employee.status.in_(ACTIVE_EMPLOYEE_STATUSES),
        ).order_by(Employee.name.asc()).all()
        departments = Department.query.filter_by(tenant_id=tenant_id, status='active').order_by(Department.name.asc()).all()
        jobs = Job.query.filter_by(tenant_id=tenant_id, status='open').order_by(Job.created_at.desc()).all()
        resumes = Resume.query.filter_by(tenant_id=tenant_id).order_by(Resume.created_at.desc()).all()
        reviews = PerformanceReview.query.filter_by(tenant_id=tenant_id).order_by(PerformanceReview.created_at.desc()).all()
        trainings = TrainingRecord.query.filter_by(tenant_id=tenant_id).all()
        salaries = SalaryProfile.query.filter_by(tenant_id=tenant_id, status='active').all()

        latest_review_by_employee: dict[str, PerformanceReview] = {}
        for review in reviews:
            latest_review_by_employee.setdefault(review.employee_id, review)
        trainings_by_employee: dict[str, list[TrainingRecord]] = {}
        for record in trainings:
            trainings_by_employee.setdefault(record.employee_id, []).append(record)
        salaries_by_employee = {row.employee_id: row for row in salaries}
        review_scores = [_score(row.final_score) for row in reviews if row.final_score is not None]
        salary_values = [_total_salary(row) for row in salaries]

        return {
            'employees': employees,
            'departments': departments,
            'jobs': jobs,
            'resumes': resumes,
            'reviews': reviews,
            'trainings': trainings,
            'salaries': salaries,
            'latestReviewByEmployee': latest_review_by_employee,
            'trainingsByEmployee': trainings_by_employee,
            'salariesByEmployee': salaries_by_employee,
            'reviewScores': review_scores,
            'salaryValues': salary_values,
        }

    @staticmethod
    def _employee_risk(employee: Employee, base: dict[str, Any]) -> dict[str, Any]:
        review = base['latestReviewByEmployee'].get(employee.id)
        trainings = base['trainingsByEmployee'].get(employee.id, [])
        salary = base['salariesByEmployee'].get(employee.id)
        performance_score = _score(review.final_score if review else None)
        training_completed = sum(1 for item in trainings if item.status in ('completed', 'attended'))
        tenure_days = (date.today() - employee.hire_date).days if employee.hire_date else 0
        risk_score = 15
        reasons = []
        if performance_score and performance_score < 70:
            risk_score += 35
            reasons.append('最近绩效低于 70 分')
        if tenure_days and tenure_days < 90:
            risk_score += 20
            reasons.append('入职 90 天内需重点跟进')
        if not training_completed:
            risk_score += 15
            reasons.append('暂无已完成培训记录')
        if salary and base['salaryValues']:
            avg_salary = mean(base['salaryValues'])
            if _total_salary(salary) < avg_salary * 0.75:
                risk_score += 15
                reasons.append('薪酬低于当前样本均值')
        risk_score = min(100, risk_score)
        level = 'high' if risk_score >= 70 else 'medium' if risk_score >= 45 else 'low'
        if not reasons:
            reasons.append('核心指标处于可观察区间')
        return {
            'employeeId': employee.id,
            'employeeName': employee.name,
            'departmentName': employee.department.name if employee.department else None,
            'riskScore': risk_score,
            'riskLevel': level,
            'reasons': reasons,
            'recommendedAction': '安排经理 1-on-1 并复盘发展计划' if level != 'low' else '保持月度观察',
        }

    @staticmethod
    def _predictive_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        risks = [IntelligenceService._employee_risk(employee, base) for employee in base['employees']]
        signals = [
            {'key': 'employee_growth', 'label': '在职员工样本', 'value': len(base['employees']), 'trend': 'stable'},
            {'key': 'open_jobs', 'label': '开放岗位', 'value': len(base['jobs']), 'trend': 'demand'},
            {'key': 'average_performance', 'label': '绩效均分', 'value': round(mean(base['reviewScores']), 2) if base['reviewScores'] else 0, 'trend': 'quality'},
            {'key': 'risk_employees', 'label': '中高风险员工', 'value': sum(1 for row in risks if row['riskLevel'] != 'low'), 'trend': 'attention'},
        ]
        return {
            'summary': {
                'employeeCount': len(base['employees']),
                'signalCount': len(signals),
                'riskEmployeeCount': sum(1 for row in risks if row['riskLevel'] != 'low'),
            },
            'signals': signals,
            'predictions': risks[:10],
        }

    @staticmethod
    def _turnover_risk_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        risks = sorted(
            [IntelligenceService._employee_risk(employee, base) for employee in base['employees']],
            key=lambda item: (-item['riskScore'], item['employeeName']),
        )
        risk_rows = [row for row in risks if row['riskLevel'] != 'low']
        return {
            'summary': {
                'employeeCount': len(base['employees']),
                'riskEmployeeCount': len(risk_rows),
                'highRiskCount': sum(1 for row in risks if row['riskLevel'] == 'high'),
            },
            'riskEmployees': risks[:20],
        }

    @staticmethod
    def _recruiting_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        candidates = []
        for resume in base['resumes']:
            analysis = resume.ai_analysis if isinstance(resume.ai_analysis, dict) else {}
            score = _score(analysis.get('matchScore') or analysis.get('score') or 0)
            candidates.append({
                'resumeId': resume.id,
                'candidateName': resume.candidate_name,
                'jobId': resume.job_id,
                'jobTitle': resume.job.title if resume.job else None,
                'matchScore': score,
                'tags': resume.tags or [],
                'recommendation': '优先推进' if score >= 80 else '补充筛选' if score else '待解析',
            })
        candidates.sort(key=lambda row: (-row['matchScore'], row['candidateName']))
        return {
            'summary': {
                'candidateCount': len(candidates),
                'openJobCount': len(base['jobs']),
                'recommendedCount': sum(1 for row in candidates if row['matchScore'] >= 80),
            },
            'candidates': candidates[:20],
        }

    @staticmethod
    def _compensation_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        avg_salary = round(mean(base['salaryValues']), 2) if base['salaryValues'] else 0
        profiles = []
        for row in base['salaries']:
            total = _total_salary(row)
            profiles.append({
                'employeeId': row.employee_id,
                'employeeName': row.employee.name if row.employee else None,
                'departmentName': row.employee.department.name if row.employee and row.employee.department else None,
                'totalSalary': total,
                'currency': row.currency or 'CNY',
                'positioning': 'below_band' if avg_salary and total < avg_salary * 0.8 else 'above_band' if avg_salary and total > avg_salary * 1.2 else 'in_band',
            })
        return {
            'summary': {
                'profileCount': len(profiles),
                'averageTotalSalary': avg_salary,
                'belowBandCount': sum(1 for row in profiles if row['positioning'] == 'below_band'),
            },
            'profiles': sorted(profiles, key=lambda item: (item['positioning'], item['employeeName'] or ''))[:20],
            'note': '未配置外部薪酬对标供应商，当前使用租户内薪酬样本做本地定位。',
        }

    @staticmethod
    def _hr_bot_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        intents = [
            {'intent': 'headcount_query', 'label': '查询组织人数', 'sample': f"当前在职 {len(base['employees'])} 人"},
            {'intent': 'recruiting_query', 'label': '查询招聘进展', 'sample': f"开放岗位 {len(base['jobs'])} 个"},
            {'intent': 'performance_query', 'label': '查询绩效概览', 'sample': f"绩效记录 {len(base['reviews'])} 条"},
            {'intent': 'compensation_query', 'label': '查询薪酬定位', 'sample': f"薪酬档案 {len(base['salaries'])} 份"},
        ]
        return {
            'summary': {
                'intentCount': len(intents),
                'knowledgeSourceCount': 4,
                'assistantMode': 'local_mvp',
            },
            'intents': intents,
        }

    @staticmethod
    def _performance_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        reviews = []
        for review in base['reviews']:
            score = _score(review.final_score)
            reviews.append({
                'reviewId': review.id,
                'employeeId': review.employee_id,
                'employeeName': review.employee.name if review.employee else None,
                'score': score,
                'grade': review.grade,
                'status': review.status,
                'insight': '高绩效，可纳入激励和继任观察' if score >= 90 else '建议安排绩效辅导' if score < 70 else '稳定表现，保持目标跟踪',
            })
        return {
            'summary': {
                'reviewCount': len(reviews),
                'highPerformerCount': sum(1 for row in reviews if row['score'] >= 90),
                'coachingCount': sum(1 for row in reviews if row['score'] < 70),
            },
            'reviews': reviews[:20],
        }

    @staticmethod
    def _advanced_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        risks = [IntelligenceService._employee_risk(employee, base) for employee in base['employees']]
        avg_performance = round(mean(base['reviewScores']), 2) if base['reviewScores'] else 0
        insights = [
            {'key': 'workforce', 'title': '组织样本', 'value': len(base['employees']), 'message': '当前租户员工样本已纳入分析'},
            {'key': 'quality', 'title': '绩效质量', 'value': avg_performance, 'message': '绩效均分用于识别培养和激励方向'},
            {'key': 'risk', 'title': '风险预警', 'value': sum(1 for row in risks if row['riskLevel'] != 'low'), 'message': '中高风险员工建议进入经理跟进清单'},
            {'key': 'recruiting', 'title': '招聘需求', 'value': len(base['jobs']), 'message': '开放岗位用于预测人力需求压力'},
        ]
        return {
            'summary': {
                'employeeCount': len(base['employees']),
                'insightCount': len(insights),
                'riskEmployeeCount': sum(1 for row in risks if row['riskLevel'] != 'low'),
            },
            'insights': insights,
        }
