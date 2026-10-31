"""People Analytics服务 - P0核心功能

功能：
- 人力分析指标计算
- 组织健康度评估
- 敬业度指数
- 人才密度分析
"""

import uuid
from typing import Dict, List, Any, Optional
from models import db, Employee, Department, PerformanceReview, Resignation, PeopleAnalyticsSnapshot
from datetime import datetime, timedelta
from sqlalchemy import func
from services.extension_registry import extension_feature_maturity, extension_read_marker


class PeopleAnalyticsService:
    """人力分析服务"""

    @staticmethod
    def build_extension_summary(tenant_id: str, operator_id: Optional[str] = None) -> Dict[str, Any]:
        """Build a governed, read-only People Analytics payload."""
        active_statuses = ('active', 'probation', 'pending_onboard')
        total_employees = Employee.query.filter(Employee.tenant_id == tenant_id).count()
        active_employees = Employee.query.filter(
            Employee.tenant_id == tenant_id,
            Employee.status.in_(active_statuses),
        ).count()
        department_count = Department.query.filter_by(tenant_id=tenant_id, status='active').count()

        high_performer_count = (
            db.session.query(func.count(func.distinct(PerformanceReview.employee_id)))
            .join(Employee, Employee.id == PerformanceReview.employee_id)
            .filter(
                PerformanceReview.tenant_id == tenant_id,
                Employee.tenant_id == tenant_id,
                Employee.status.in_(active_statuses),
                PerformanceReview.final_score >= 90,
            )
            .scalar()
            or 0
        )
        high_performer_rate = round((high_performer_count / active_employees) * 100, 2) if active_employees else 0

        turnover = PeopleAnalyticsService.analyze_turnover(tenant_id, 'year')
        performance = PeopleAnalyticsService.analyze_performance_distribution(tenant_id)
        span = PeopleAnalyticsService.analyze_span_of_control(tenant_id)

        by_department = (
            db.session.query(
                Department.id,
                Department.name,
                func.count(Employee.id),
            )
            .outerjoin(
                Employee,
                (Employee.department_id == Department.id)
                & (Employee.tenant_id == tenant_id)
                & (Employee.status.in_(active_statuses)),
            )
            .filter(Department.tenant_id == tenant_id, Department.status == 'active')
            .group_by(Department.id, Department.name)
            .order_by(Department.name.asc())
            .all()
        )

        risks: List[Dict[str, Any]] = []
        if turnover.get('annual_rate', 0) >= 20:
            risks.append({
                'type': 'turnover',
                'level': 'high',
                'message': '年度流失率偏高，建议复盘离职原因和关键岗位保留策略。',
            })
        elif turnover.get('annual_rate', 0) >= 10:
            risks.append({
                'type': 'turnover',
                'level': 'medium',
                'message': '年度流失率进入关注区间，建议跟踪部门维度变化。',
            })
        if high_performer_rate < 15 and active_employees:
            risks.append({
                'type': 'performance',
                'level': 'medium',
                'message': '高绩效人才占比较低，建议完善培养、激励和绩效校准。',
            })
        if not active_employees:
            risks.append({
                'type': 'headcount',
                'level': 'medium',
                'message': '当前没有活跃员工数据，People Analytics 仅展示空样本状态。',
            })
        if not risks:
            risks.append({
                'type': 'turnover',
                'level': 'low',
                'message': '组织核心人力指标处于可观察区间，建议保持月度快照复盘。',
            })

        payload = {
            'featureKey': 'extension.analytics.people',
            'status': extension_feature_maturity('extension.analytics.people'),
            'summary': {
                'employeeCount': active_employees,
                'totalEmployees': total_employees,
                'departmentCount': department_count,
                'highPerformerCount': int(high_performer_count),
                'highPerformerRate': high_performer_rate,
                'turnoverRate': turnover.get('annual_rate', 0),
                'averageSpanOfControl': span.get('average_span', 0),
                'dataScope': 'currentTenant',
            },
            'distributions': {
                'byDepartment': [
                    {
                        'departmentId': department_id,
                        'departmentName': name,
                        'employeeCount': int(count or 0),
                    }
                    for department_id, name, count in by_department
                ],
                'performance': performance.get('distribution', []),
            },
            'risks': risks,
        }

        payload['snapshot'] = extension_read_marker(
            'extension.analytics.people',
            metricKey='people_analytics_summary',
        )
        return payload
    
    @staticmethod
    def get_analytics_dashboard(tenant_id: str, time_range: str = 'month') -> Dict[str, Any]:
        """获取人力分析仪表盘"""
        return {
            'talent_density': PeopleAnalyticsService.calculate_talent_density(tenant_id),
            'org_health': PeopleAnalyticsService.calculate_org_health(tenant_id),
            'engagement_index': PeopleAnalyticsService.calculate_engagement_index(tenant_id),
            'turnover_analysis': PeopleAnalyticsService.analyze_turnover(tenant_id, time_range),
            'performance_distribution': PeopleAnalyticsService.analyze_performance_distribution(tenant_id),
            'span_of_control': PeopleAnalyticsService.analyze_span_of_control(tenant_id),
        }
    
    @staticmethod
    def calculate_talent_density(tenant_id: str) -> Dict[str, Any]:
        """计算人才密度
        
        人才密度 = 高绩效员工占比 + 高潜力员工占比
        """
        total_employees = Employee.query.filter_by(
            tenant_id=tenant_id,
            status='active'
        ).count()
        
        if total_employees == 0:
            return {'score': 0, 'level': 'low', 'details': {}}
        
        # 高绩效员工（最近绩效评分>=90）
        high_performers = db.session.query(func.count(func.distinct(PerformanceReview.employee_id))).filter(
            PerformanceReview.tenant_id == tenant_id,
            PerformanceReview.final_score >= 90
        ).scalar() or 0
        
        high_perf_ratio = (high_performers / total_employees) * 100
        
        # 简化的人才密度评分
        density_score = high_perf_ratio
        
        level = 'high' if density_score >= 20 else 'medium' if density_score >= 10 else 'low'
        
        return {
            'score': round(density_score, 2),
            'level': level,
            'details': {
                'total_employees': total_employees,
                'high_performers': high_performers,
                'high_performers_ratio': round(high_perf_ratio, 2),
            }
        }
    
    @staticmethod
    def calculate_org_health(tenant_id: str) -> Dict[str, Any]:
        """计算组织健康度
        
        综合指标：流失率、绩效、敬业度、人才密度
        """
        # 获取各维度数据
        turnover = PeopleAnalyticsService.analyze_turnover(tenant_id, 'year')
        talent_density = PeopleAnalyticsService.calculate_talent_density(tenant_id)
        
        # 组织健康度评分（100分制）
        health_score = 0
        
        # 流失率维度（30分）- 流失率越低越好
        turnover_rate = turnover.get('annual_rate', 0)
        if turnover_rate < 10:
            health_score += 30
        elif turnover_rate < 15:
            health_score += 20
        elif turnover_rate < 20:
            health_score += 10
        
        # 人才密度维度（40分）
        if talent_density['level'] == 'high':
            health_score += 40
        elif talent_density['level'] == 'medium':
            health_score += 25
        else:
            health_score += 10
        
        # 绩效分布维度（30分）
        perf_dist = PeopleAnalyticsService.analyze_performance_distribution(tenant_id)
        high_perf_ratio = perf_dist.get('high_performance_ratio', 0)
        if high_perf_ratio >= 20:
            health_score += 30
        elif high_perf_ratio >= 10:
            health_score += 20
        else:
            health_score += 10
        
        level = 'excellent' if health_score >= 80 else 'good' if health_score >= 60 else 'fair' if health_score >= 40 else 'poor'
        
        return {
            'score': health_score,
            'level': level,
            'dimensions': {
                'turnover': turnover_rate,
                'talent_density': talent_density['score'],
                'performance': high_perf_ratio,
            },
            'insights': PeopleAnalyticsService._generate_health_insights(health_score, turnover_rate, talent_density['score']),
        }
    
    @staticmethod
    def calculate_engagement_index(tenant_id: str) -> Dict[str, Any]:
        """计算敬业度指数
        
        基于：绩效、培训参与度、在职时长
        """
        # 简化版，实际需要调研数据
        total_employees = Employee.query.filter_by(
            tenant_id=tenant_id,
            status='active'
        ).count()
        
        if total_employees == 0:
            return {'score': 0, 'level': 'low'}
        
        # 使用代理指标
        # 1. 绩效优秀比例
        perf_dist = PeopleAnalyticsService.analyze_performance_distribution(tenant_id)
        perf_factor = perf_dist.get('high_performance_ratio', 0)
        
        # 2. 流失率（反向指标）
        turnover = PeopleAnalyticsService.analyze_turnover(tenant_id, 'year')
        turnover_factor = max(0, 100 - turnover.get('annual_rate', 0) * 5)
        
        # 敬业度指数
        engagement_score = (perf_factor * 0.4 + turnover_factor * 0.6)
        
        level = 'high' if engagement_score >= 70 else 'medium' if engagement_score >= 50 else 'low'
        
        return {
            'score': round(engagement_score, 2),
            'level': level,
            'note': '基于绩效和流失率的代理指标，建议进行员工调研获取真实数据',
        }
    
    @staticmethod
    def analyze_turnover(tenant_id: str, time_range: str) -> Dict[str, Any]:
        """流失率分析"""
        # 计算时间范围
        end_date = datetime.now().date()
        if time_range == 'month':
            start_date = end_date - timedelta(days=30)
            period = '月度'
        elif time_range == 'quarter':
            start_date = end_date - timedelta(days=90)
            period = '季度'
        else:  # year
            start_date = end_date - timedelta(days=365)
            period = '年度'
        
        # 期初人数
        total_start = Employee.query.filter(
            Employee.tenant_id == tenant_id,
            Employee.hire_date <= start_date
        ).count()
        
        # 期末人数
        total_end = Employee.query.filter_by(
            tenant_id=tenant_id,
            status='active'
        ).count()
        
        # 期间离职人数
        resignations = Resignation.query.filter(
            Resignation.tenant_id == tenant_id,
            Resignation.actual_leave_date >= start_date,
            Resignation.actual_leave_date <= end_date
        ).count()
        
        # 平均人数
        avg_headcount = (total_start + total_end) / 2 if (total_start + total_end) > 0 else 1
        
        # 流失率 = 离职人数 / 平均人数 * 100
        turnover_rate = (resignations / avg_headcount * 100) if avg_headcount > 0 else 0
        
        return {
            'period': period,
            'rate': round(turnover_rate, 2),
            'resignations': resignations,
            'avg_headcount': int(avg_headcount),
            'annual_rate': round(turnover_rate * (365 / (end_date - start_date).days), 2) if time_range != 'year' else round(turnover_rate, 2),
        }
    
    @staticmethod
    def analyze_performance_distribution(tenant_id: str) -> Dict[str, Any]:
        """绩效分布分析"""
        # 最近一个周期的绩效
        all_reviews = PerformanceReview.query.filter_by(
            tenant_id=tenant_id
        ).all()
        
        if not all_reviews:
            return {
                'total': 0,
                'high_performance': 0,
                'medium_performance': 0,
                'low_performance': 0,
                'high_performance_ratio': 0,
                'distribution': [],
            }

        total = len(all_reviews)
        high = 0
        medium = 0
        low = 0

        for review in all_reviews:
            score = float(review.final_score or 0)
            if score >= 90:
                high += 1
            elif score >= 70:
                medium += 1
            else:
                low += 1

        return {
            'total': total,
            'high_performance': high,
            'medium_performance': medium,
            'low_performance': low,
            'high_performance_ratio': round(high / total * 100, 2) if total else 0,
            'distribution': [
                {'label': '高绩效', 'count': high, 'ratio': round(high / total * 100, 2)},
                {'label': '中绩效', 'count': medium, 'ratio': round(medium / total * 100, 2)},
                {'label': '待提升', 'count': low, 'ratio': round(low / total * 100, 2)},
            ],
        }

    @staticmethod
    def analyze_span_of_control(tenant_id: str) -> Dict[str, Any]:
        """管理幅度分析"""
        departments = Department.query.filter_by(tenant_id=tenant_id, status='active').all()
        managers = {dept.manager_id for dept in departments if dept.manager_id}
        manager_count = len(managers)
        employee_count = Employee.query.filter_by(tenant_id=tenant_id, status='active').count()
        avg_span = round(employee_count / manager_count, 2) if manager_count else 0

        return {
            'manager_count': manager_count,
            'employee_count': employee_count,
            'average_span': avg_span,
            'level': 'high' if avg_span > 12 else 'balanced' if avg_span >= 4 else 'low',
        }

    @staticmethod
    def _generate_health_insights(
        health_score: float,
        turnover_rate: float,
        talent_density_score: float,
    ) -> List[str]:
        """生成组织健康洞察"""
        insights: List[str] = []
        if health_score >= 80:
            insights.append('组织健康度良好，建议保持当前人才管理节奏')
        elif health_score >= 60:
            insights.append('组织健康度处于可接受区间，建议关注薄弱指标')
        else:
            insights.append('组织健康度偏低，建议优先复盘流失率和绩效分布')

        if turnover_rate >= 15:
            insights.append('年度流失率偏高，建议开展离职原因分析')
        if talent_density_score < 10:
            insights.append('高绩效人才占比较低，建议完善人才培养和激励机制')
        return insights
