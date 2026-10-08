"""Governed talent strategy extension MVP services."""

from __future__ import annotations

import uuid
from statistics import mean
from typing import Any

from sqlalchemy import func

from models import (
    CompetencyAssessment,
    CompetencyModel,
    Department,
    Employee,
    Job,
    PerformanceReview,
    Position,
    TalentStrategySnapshot,
    TrainingRecord,
    db,
)
from services.extension_registry import extension_feature_maturity, extension_read_marker


TALENT_FEATURES = {
    'profile': 'extension.talent.profile',
    'competency_model': 'extension.talent.competency_model',
    'succession': 'extension.talent.succession',
    'review': 'extension.talent.review',
    'career_path': 'extension.talent.career_path',
    'idp': 'extension.talent.idp',
    'internal_marketplace': 'extension.talent.internal_marketplace',
}

ACTIVE_EMPLOYEE_STATUSES = ('active', 'probation', 'pending_onboard')


def _score(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _level_rank(level: str | None) -> int:
    if not level:
        return 0
    normalized = ''.join(ch for ch in str(level).upper() if ch.isdigit())
    return int(normalized) if normalized else 0


def _performance_level(score: float) -> str:
    if score >= 90:
        return 'high'
    if score >= 70:
        return 'medium'
    return 'low'


def _potential_level(score: float) -> str:
    if score >= 85:
        return 'high'
    if score >= 65:
        return 'medium'
    return 'low'


def _nine_box_label(performance_level: str, potential_level: str) -> str:
    labels = {
        ('high', 'high'): '核心人才',
        ('high', 'medium'): '稳定骨干',
        ('high', 'low'): '专家贡献者',
        ('medium', 'high'): '高潜人才',
        ('medium', 'medium'): '中坚力量',
        ('medium', 'low'): '稳定员工',
        ('low', 'high'): '待培养潜力',
        ('low', 'medium'): '待观察',
        ('low', 'low'): '需改进',
    }
    return labels.get((performance_level, potential_level), '未分类')


class TalentStrategyService:
    @staticmethod
    def build_feature_summary(tenant_id: str, feature: str, operator_id: str | None = None) -> dict[str, Any]:
        if feature not in TALENT_FEATURES:
            raise LookupError(feature)

        base = TalentStrategyService._base_context(tenant_id)
        builders = {
            'profile': TalentStrategyService._profile_payload,
            'competency_model': TalentStrategyService._competency_model_payload,
            'succession': TalentStrategyService._succession_payload,
            'review': TalentStrategyService._review_payload,
            'career_path': TalentStrategyService._career_path_payload,
            'idp': TalentStrategyService._idp_payload,
            'internal_marketplace': TalentStrategyService._internal_marketplace_payload,
        }
        payload = builders[feature](tenant_id, base)
        feature_key = TALENT_FEATURES[feature]
        payload.update({
            'featureKey': feature_key,
            'status': extension_feature_maturity(feature_key),
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
        positions = Position.query.filter_by(tenant_id=tenant_id, status='active').order_by(Position.title.asc()).all()
        departments = Department.query.filter_by(tenant_id=tenant_id, status='active').order_by(Department.name.asc()).all()
        reviews = PerformanceReview.query.filter_by(tenant_id=tenant_id).order_by(PerformanceReview.created_at.desc()).all()
        trainings = TrainingRecord.query.filter_by(tenant_id=tenant_id).all()
        assessments = CompetencyAssessment.query.filter_by(tenant_id=tenant_id).all()
        models = CompetencyModel.query.filter_by(tenant_id=tenant_id, status='active').order_by(CompetencyModel.name.asc()).all()
        jobs = Job.query.filter_by(tenant_id=tenant_id, status='open').order_by(Job.created_at.desc()).all()

        latest_review_by_employee: dict[str, PerformanceReview] = {}
        for review in reviews:
            latest_review_by_employee.setdefault(review.employee_id, review)
        latest_assessment_by_employee: dict[str, CompetencyAssessment] = {}
        for assessment in sorted(assessments, key=lambda row: row.created_at, reverse=True):
            latest_assessment_by_employee.setdefault(assessment.employee_id, assessment)
        trainings_by_employee: dict[str, list[TrainingRecord]] = {}
        for record in trainings:
            trainings_by_employee.setdefault(record.employee_id, []).append(record)

        return {
            'employees': employees,
            'positions': positions,
            'departments': departments,
            'reviews': reviews,
            'trainings': trainings,
            'assessments': assessments,
            'models': models,
            'jobs': jobs,
            'latestReviewByEmployee': latest_review_by_employee,
            'latestAssessmentByEmployee': latest_assessment_by_employee,
            'trainingsByEmployee': trainings_by_employee,
        }

    @staticmethod
    def _employee_profile(employee: Employee, base: dict[str, Any]) -> dict[str, Any]:
        review = base['latestReviewByEmployee'].get(employee.id)
        assessment = base['latestAssessmentByEmployee'].get(employee.id)
        trainings = base['trainingsByEmployee'].get(employee.id, [])
        completed_training = [record for record in trainings if record.status in ('completed', 'attended')]
        performance_score = _score(review.final_score if review else None)
        competency_score = int(assessment.overall_score or 0) if assessment else 0
        learning_score = round((len(completed_training) / len(trainings)) * 100, 2) if trainings else 0
        potential_score = round((performance_score * 0.45) + (competency_score * 0.35) + (learning_score * 0.2), 2)
        performance = _performance_level(performance_score)
        potential = _potential_level(potential_score)
        tags = []
        if performance == 'high':
            tags.append('高绩效')
        if potential == 'high':
            tags.append('高潜力')
        if performance == 'high' and potential == 'high':
            tags.append('核心人才')
        if completed_training:
            tags.append('持续学习')
        if not tags:
            tags.append('待观察')

        return {
            'employeeId': employee.id,
            'employeeName': employee.name,
            'departmentName': employee.department.name if employee.department else None,
            'positionTitle': employee.position.title if employee.position else employee.job_title,
            'jobTitle': employee.job_title,
            'performanceScore': performance_score,
            'competencyScore': competency_score,
            'learningScore': learning_score,
            'potentialScore': potential_score,
            'nineBox': _nine_box_label(performance, potential),
            'tags': tags,
        }

    @staticmethod
    def _profiles(base: dict[str, Any]) -> list[dict[str, Any]]:
        return sorted(
            [TalentStrategyService._employee_profile(employee, base) for employee in base['employees']],
            key=lambda item: (-item['potentialScore'], item['employeeName']),
        )

    @staticmethod
    def _profile_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        profiles = TalentStrategyService._profiles(base)
        return {
            'summary': {
                'employeeCount': len(base['employees']),
                'coreTalentCount': sum(1 for row in profiles if '核心人才' in row['tags']),
                'highPotentialCount': sum(1 for row in profiles if '高潜力' in row['tags']),
            },
            'profiles': profiles[:20],
        }

    @staticmethod
    def _competency_model_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        assessments = base['assessments']
        average_score = round(mean([int(row.overall_score or 0) for row in assessments]), 2) if assessments else 0
        weakest: dict[str, int] = {}
        for row in assessments:
            for dim in row.weakest_dims or []:
                weakest[str(dim)] = weakest.get(str(dim), 0) + 1
        return {
            'summary': {
                'modelCount': len(base['models']),
                'assessmentCount': len(assessments),
                'averageScore': average_score,
            },
            'models': [
                {
                    'id': model.id,
                    'name': model.name,
                    'dimensionCount': len(model.dimensions or []),
                    'dimensions': model.dimensions or [],
                }
                for model in base['models']
            ],
            'weakestDimensions': [
                {'dimensionKey': key, 'count': count}
                for key, count in sorted(weakest.items(), key=lambda item: (-item[1], item[0]))
            ],
        }

    @staticmethod
    def _succession_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        profiles = TalentStrategyService._profiles(base)
        by_department: dict[str | None, list[dict[str, Any]]] = {}
        for profile in profiles:
            by_department.setdefault(profile['departmentName'], []).append(profile)

        key_roles = []
        for department in base['departments']:
            successors = [
                profile for profile in by_department.get(department.name, [])
                if profile['potentialScore'] >= 70
            ][:3]
            if department.manager_id or successors:
                key_roles.append({
                    'roleId': department.id,
                    'roleName': f'{department.name}负责人',
                    'departmentName': department.name,
                    'incumbentId': department.manager_id,
                    'incumbentName': next((employee.name for employee in base['employees'] if employee.id == department.manager_id), None),
                    'successorCount': len(successors),
                    'successors': successors,
                    'readiness': 'ready' if successors else 'gap',
                })

        return {
            'summary': {
                'keyRoleCount': len(key_roles),
                'readyRoleCount': sum(1 for role in key_roles if role['successorCount'] > 0),
                'gapCount': sum(1 for role in key_roles if role['successorCount'] == 0),
            },
            'keyRoles': key_roles,
        }

    @staticmethod
    def _review_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        profiles = TalentStrategyService._profiles(base)
        boxes: dict[str, int] = {}
        for profile in profiles:
            boxes[profile['nineBox']] = boxes.get(profile['nineBox'], 0) + 1
        return {
            'summary': {
                'nineBoxCount': len(profiles),
                'coreTalentCount': boxes.get('核心人才', 0),
                'observationCount': boxes.get('待观察', 0),
            },
            'nineBox': [
                {'label': label, 'count': count}
                for label, count in sorted(boxes.items(), key=lambda item: (-item[1], item[0]))
            ],
            'talents': profiles[:20],
        }

    @staticmethod
    def _career_path_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        paths = []
        for employee in base['employees']:
            current_rank = _level_rank(employee.position.level if employee.position else None)
            candidates = [
                position for position in base['positions']
                if position.department_id == employee.department_id
                and position.id != employee.position_id
                and (_level_rank(position.level) >= current_rank)
            ]
            next_position = sorted(candidates, key=lambda row: (_level_rank(row.level), row.title))[-1] if candidates else None
            if next_position:
                paths.append({
                    'employeeId': employee.id,
                    'employeeName': employee.name,
                    'currentPosition': employee.position.title if employee.position else employee.job_title,
                    'targetPosition': next_position.title,
                    'targetLevel': next_position.level,
                    'readiness': 'medium',
                    'steps': ['完成岗位能力评估', '补齐短板学习计划', '参与关键项目历练'],
                })
        return {
            'summary': {
                'pathCount': len(paths),
                'employeeCount': len(base['employees']),
            },
            'paths': paths[:20],
        }

    @staticmethod
    def _idp_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        plans = []
        for profile in TalentStrategyService._profiles(base):
            focus = []
            if profile['competencyScore'] < 85:
                focus.append('能力短板提升')
            if profile['learningScore'] < 80:
                focus.append('学习计划完成')
            if profile['performanceScore'] < 90:
                focus.append('绩效目标辅导')
            if not focus:
                focus.append('关键岗位历练')
            plans.append({
                'employeeId': profile['employeeId'],
                'employeeName': profile['employeeName'],
                'focusAreas': focus,
                'targetOutcome': '下一轮人才盘点可复核',
                'reviewCadence': 'monthly',
            })
        return {
            'summary': {
                'planCount': len(plans),
                'monthlyReviewCount': len(plans),
            },
            'plans': plans[:20],
        }

    @staticmethod
    def _internal_marketplace_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        profiles = TalentStrategyService._profiles(base)
        opportunities = []
        for job in base['jobs']:
            matches = [
                profile for profile in profiles
                if (not job.department_id or profile['departmentName'] == (job.department_ref.name if job.department_ref else profile['departmentName']))
                and profile['potentialScore'] >= 65
            ][:5]
            opportunities.append({
                'jobId': job.id,
                'title': job.title,
                'departmentName': job.department or (job.department_ref.name if job.department_ref else None),
                'level': job.level,
                'headcount': job.headcount or 1,
                'matchCount': len(matches),
                'matches': matches,
            })
        return {
            'summary': {
                'openOpportunityCount': len(opportunities),
                'matchCount': sum(item['matchCount'] for item in opportunities),
            },
            'opportunities': opportunities[:20],
        }
