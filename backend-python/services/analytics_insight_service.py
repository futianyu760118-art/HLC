"""Governed analytics extension MVP services."""

from __future__ import annotations

import uuid
from statistics import mean
from typing import Any

from sqlalchemy import func

from models import (
    AnalyticsInsightSnapshot,
    Department,
    Employee,
    Job,
    PerformanceReview,
    TrainingRecord,
    db,
)
from services.extension_registry import extension_feature_maturity, extension_read_marker


ANALYTICS_FEATURES = {
    'basic_bi': 'extension.analytics.basic_bi',
    'custom_reports': 'extension.analytics.custom_reports',
    'realtime_dashboard': 'extension.analytics.realtime_dashboard',
    'benchmark': 'extension.analytics.benchmark',
    'visualization': 'extension.analytics.visualization',
}

ACTIVE_EMPLOYEE_STATUSES = ('active', 'probation', 'pending_onboard')


def _score(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _ratio(part: int | float, total: int | float) -> float:
    return round((float(part) / float(total)) * 100, 2) if total else 0


def _health_status(value: float, high: float, medium: float) -> str:
    if value >= high:
        return 'healthy'
    if value >= medium:
        return 'watch'
    return 'attention'


class AnalyticsInsightService:
    @staticmethod
    def build_feature_summary(tenant_id: str, feature: str, operator_id: str | None = None) -> dict[str, Any]:
        if feature not in ANALYTICS_FEATURES:
            raise LookupError(feature)

        base = AnalyticsInsightService._base_context(tenant_id)
        builders = {
            'basic_bi': AnalyticsInsightService._basic_bi_payload,
            'custom_reports': AnalyticsInsightService._custom_reports_payload,
            'realtime_dashboard': AnalyticsInsightService._realtime_dashboard_payload,
            'benchmark': AnalyticsInsightService._benchmark_payload,
            'visualization': AnalyticsInsightService._visualization_payload,
        }
        payload = builders[feature](tenant_id, base)
        feature_key = ANALYTICS_FEATURES[feature]
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
        all_employees = Employee.query.filter_by(tenant_id=tenant_id).all()
        departments = Department.query.filter_by(tenant_id=tenant_id, status='active').order_by(Department.name.asc()).all()
        jobs = Job.query.filter_by(tenant_id=tenant_id, status='open').order_by(Job.created_at.desc()).all()
        reviews = PerformanceReview.query.filter_by(tenant_id=tenant_id).order_by(PerformanceReview.created_at.desc()).all()
        trainings = TrainingRecord.query.filter_by(tenant_id=tenant_id).all()

        latest_review_by_employee: dict[str, PerformanceReview] = {}
        for review in reviews:
            latest_review_by_employee.setdefault(review.employee_id, review)
        trainings_by_employee: dict[str, list[TrainingRecord]] = {}
        for record in trainings:
            trainings_by_employee.setdefault(record.employee_id, []).append(record)

        completed_trainings = [
            record for record in trainings
            if record.status in ('completed', 'attended') or str(record.result or '').lower() in ('pass', '通过', '优秀')
        ]
        review_scores = [_score(review.final_score) for review in reviews if review.final_score is not None]
        high_performers = [score for score in review_scores if score >= 90]
        department_rows = AnalyticsInsightService._department_breakdown(tenant_id, departments)

        metrics = {
            'employeeCount': len(employees),
            'totalEmployees': len(all_employees),
            'departmentCount': len(departments),
            'openJobCount': len(jobs),
            'reviewCount': len(reviews),
            'trainingRecordCount': len(trainings),
            'trainingCompletionRate': _ratio(len(completed_trainings), len(trainings)),
            'averagePerformanceScore': round(mean(review_scores), 2) if review_scores else 0,
            'highPerformerCount': len(high_performers),
            'highPerformerRate': _ratio(len(high_performers), len(review_scores)),
            'openJobsPer100Employees': round((len(jobs) / max(len(employees), 1)) * 100, 2) if employees else 0,
        }

        return {
            'employees': employees,
            'departments': departments,
            'jobs': jobs,
            'reviews': reviews,
            'trainings': trainings,
            'completedTrainings': completed_trainings,
            'latestReviewByEmployee': latest_review_by_employee,
            'trainingsByEmployee': trainings_by_employee,
            'departmentRows': department_rows,
            'metrics': metrics,
        }

    @staticmethod
    def _department_breakdown(tenant_id: str, departments: list[Department]) -> list[dict[str, Any]]:
        rows = (
            db.session.query(
                Department.id,
                Department.name,
                func.count(Employee.id),
            )
            .outerjoin(
                Employee,
                (Employee.department_id == Department.id)
                & (Employee.tenant_id == tenant_id)
                & (Employee.status.in_(ACTIVE_EMPLOYEE_STATUSES)),
            )
            .filter(Department.tenant_id == tenant_id, Department.status == 'active')
            .group_by(Department.id, Department.name)
            .order_by(Department.name.asc())
            .all()
        )
        if rows:
            return [
                {
                    'departmentId': department_id,
                    'departmentName': name,
                    'employeeCount': int(count or 0),
                }
                for department_id, name, count in rows
            ]
        return [
            {
                'departmentId': department.id,
                'departmentName': department.name,
                'employeeCount': 0,
            }
            for department in departments
        ]

    @staticmethod
    def _performance_distribution(reviews: list[PerformanceReview]) -> list[dict[str, Any]]:
        buckets = [
            ('high', '高绩效', lambda score: score >= 90),
            ('medium', '中绩效', lambda score: 70 <= score < 90),
            ('low', '待提升', lambda score: score < 70),
        ]
        scores = [_score(review.final_score) for review in reviews if review.final_score is not None]
        total = len(scores)
        distribution = []
        for key, label, predicate in buckets:
            count = sum(1 for score in scores if predicate(score))
            distribution.append({
                'key': key,
                'label': label,
                'count': count,
                'ratio': _ratio(count, total),
            })
        return distribution

    @staticmethod
    def _basic_bi_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        metrics = base['metrics']
        kpis = [
            {'key': 'employee_count', 'label': '在职员工', 'value': metrics['employeeCount'], 'unit': '人'},
            {'key': 'department_count', 'label': '活跃部门', 'value': metrics['departmentCount'], 'unit': '个'},
            {'key': 'average_performance', 'label': '平均绩效', 'value': metrics['averagePerformanceScore'], 'unit': '分'},
            {'key': 'training_completion', 'label': '培训完成率', 'value': metrics['trainingCompletionRate'], 'unit': '%'},
        ]
        return {
            'summary': {
                'employeeCount': metrics['employeeCount'],
                'departmentCount': metrics['departmentCount'],
                'kpiCount': len(kpis),
                'averagePerformanceScore': metrics['averagePerformanceScore'],
            },
            'kpis': kpis,
            'departmentBreakdown': base['departmentRows'],
            'performanceDistribution': AnalyticsInsightService._performance_distribution(base['reviews']),
        }

    @staticmethod
    def _custom_reports_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        metrics = base['metrics']
        reports = [
            {
                'id': 'report-headcount-by-department',
                'name': '部门人力结构报表',
                'dimension': 'department',
                'metricCount': 3,
                'rows': base['departmentRows'],
            },
            {
                'id': 'report-performance-summary',
                'name': '绩效分布报表',
                'dimension': 'performance',
                'metricCount': 4,
                'rows': AnalyticsInsightService._performance_distribution(base['reviews']),
            },
            {
                'id': 'report-learning-effectiveness',
                'name': '学习成效报表',
                'dimension': 'training',
                'metricCount': 3,
                'rows': [
                    {'label': '培训记录', 'value': metrics['trainingRecordCount']},
                    {'label': '已完成', 'value': len(base['completedTrainings'])},
                    {'label': '完成率', 'value': metrics['trainingCompletionRate']},
                ],
            },
        ]
        return {
            'summary': {
                'employeeCount': metrics['employeeCount'],
                'reportCount': len(reports),
                'exportReadyCount': len(reports),
            },
            'reports': reports,
        }

    @staticmethod
    def _realtime_dashboard_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        metrics = base['metrics']
        widgets = [
            {
                'key': 'headcount_live',
                'title': '实时在职人数',
                'value': metrics['employeeCount'],
                'unit': '人',
                'status': 'healthy' if metrics['employeeCount'] else 'attention',
            },
            {
                'key': 'open_jobs',
                'title': '开放岗位',
                'value': metrics['openJobCount'],
                'unit': '个',
                'status': 'watch' if metrics['openJobCount'] else 'healthy',
            },
            {
                'key': 'performance_average',
                'title': '绩效均分',
                'value': metrics['averagePerformanceScore'],
                'unit': '分',
                'status': _health_status(metrics['averagePerformanceScore'], 85, 70),
            },
            {
                'key': 'training_completion',
                'title': '培训完成率',
                'value': metrics['trainingCompletionRate'],
                'unit': '%',
                'status': _health_status(metrics['trainingCompletionRate'], 80, 50),
            },
        ]
        return {
            'summary': {
                'employeeCount': metrics['employeeCount'],
                'widgetCount': len(widgets),
                'refreshMode': 'near_realtime_snapshot',
            },
            'widgets': widgets,
            'activityFeed': [
                {'type': 'performance', 'message': f"已纳入 {metrics['reviewCount']} 条绩效记录"},
                {'type': 'training', 'message': f"已纳入 {metrics['trainingRecordCount']} 条培训记录"},
                {'type': 'recruiting', 'message': f"当前开放岗位 {metrics['openJobCount']} 个"},
            ],
        }

    @staticmethod
    def _benchmark_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        metrics = base['metrics']
        benchmarks = [
            {
                'key': 'high_performer_rate',
                'label': '高绩效人才占比',
                'tenantValue': metrics['highPerformerRate'],
                'benchmarkValue': 20,
                'unit': '%',
                'status': _health_status(metrics['highPerformerRate'], 20, 10),
            },
            {
                'key': 'training_completion_rate',
                'label': '培训完成率',
                'tenantValue': metrics['trainingCompletionRate'],
                'benchmarkValue': 80,
                'unit': '%',
                'status': _health_status(metrics['trainingCompletionRate'], 80, 50),
            },
            {
                'key': 'open_jobs_per_100',
                'label': '每百人开放岗位',
                'tenantValue': metrics['openJobsPer100Employees'],
                'benchmarkValue': 8,
                'unit': '个',
                'status': 'watch' if metrics['openJobsPer100Employees'] > 12 else 'healthy',
            },
        ]
        return {
            'summary': {
                'employeeCount': metrics['employeeCount'],
                'benchmarkCount': len(benchmarks),
                'source': 'local_mvp_baseline',
            },
            'benchmarks': benchmarks,
            'note': '未配置外部薪酬或行业对标供应商，当前使用本地 MVP 基线。',
        }

    @staticmethod
    def _visualization_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        metrics = base['metrics']
        charts = [
            {
                'key': 'headcount_bar',
                'title': '部门人数柱状图',
                'type': 'bar',
                'series': base['departmentRows'],
            },
            {
                'key': 'performance_donut',
                'title': '绩效分布环图',
                'type': 'donut',
                'series': AnalyticsInsightService._performance_distribution(base['reviews']),
            },
            {
                'key': 'learning_gauge',
                'title': '培训完成仪表',
                'type': 'gauge',
                'value': metrics['trainingCompletionRate'],
            },
            {
                'key': 'recruiting_line',
                'title': '开放岗位趋势',
                'type': 'line',
                'series': [
                    {'label': '当前', 'value': metrics['openJobCount']},
                    {'label': '目标', 'value': max(metrics['openJobCount'], 1)},
                ],
            },
        ]
        return {
            'summary': {
                'employeeCount': metrics['employeeCount'],
                'chartCount': len(charts),
                'visualLayer': 'mvp_canvas_ready',
            },
            'charts': charts,
        }
