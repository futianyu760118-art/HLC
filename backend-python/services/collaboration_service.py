"""Governed collaboration extension MVP services."""

from __future__ import annotations

import uuid
from datetime import date
from statistics import mean
from typing import Any

from models import (
    CollaborationInsightSnapshot,
    Department,
    Discussion,
    DiscussionReply,
    Employee,
    Feedback,
    Notification,
    OnboardingTask,
    PerformanceReview,
    db,
)
from services.extension_registry import extension_feature_maturity, extension_read_marker


COLLABORATION_FEATURES = {
    'okr': 'extension.collaboration.okr',
    'one_on_one': 'extension.collaboration.one_on_one',
    'survey_enps': 'extension.collaboration.survey_enps',
    'employee_care': 'extension.collaboration.employee_care',
    'social': 'extension.collaboration.social',
    'onboarding_experience': 'extension.collaboration.onboarding_experience',
    'virtual_assistant': 'extension.collaboration.virtual_assistant',
    'feedback_experience': 'extension.collaboration.feedback_experience',
}

ACTIVE_EMPLOYEE_STATUSES = ('active', 'probation', 'pending_onboard')


def _score(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _ratio(part: int | float, total: int | float) -> float:
    return round((float(part) / float(total)) * 100, 2) if total else 0


def _sentiment_for_feedback(row: Feedback) -> str:
    if row.severity in ('critical', 'high'):
        return 'negative'
    if row.status in ('resolved', 'closed'):
        return 'positive'
    return 'neutral'


class CollaborationService:
    @staticmethod
    def build_feature_summary(tenant_id: str, feature: str, operator_id: str | None = None) -> dict[str, Any]:
        if feature not in COLLABORATION_FEATURES:
            raise LookupError(feature)

        base = CollaborationService._base_context(tenant_id)
        builders = {
            'okr': CollaborationService._okr_payload,
            'one_on_one': CollaborationService._one_on_one_payload,
            'survey_enps': CollaborationService._survey_payload,
            'employee_care': CollaborationService._employee_care_payload,
            'social': CollaborationService._social_payload,
            'onboarding_experience': CollaborationService._onboarding_payload,
            'virtual_assistant': CollaborationService._assistant_payload,
            'feedback_experience': CollaborationService._feedback_payload,
        }
        payload = builders[feature](tenant_id, base)
        feature_key = COLLABORATION_FEATURES[feature]
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
        departments = Department.query.filter_by(tenant_id=tenant_id, status='active').order_by(Department.name.asc()).all()
        reviews = PerformanceReview.query.filter_by(tenant_id=tenant_id).order_by(PerformanceReview.created_at.desc()).all()
        discussions = Discussion.query.filter_by(tenant_id=tenant_id).order_by(Discussion.created_at.desc()).all()
        discussion_ids = [row.id for row in discussions]
        replies = []
        if discussion_ids:
            replies = DiscussionReply.query.filter(
                DiscussionReply.tenant_id == tenant_id,
                DiscussionReply.discussion_id.in_(discussion_ids),
            ).order_by(DiscussionReply.created_at.desc()).all()
        onboarding_tasks = OnboardingTask.query.filter_by(tenant_id=tenant_id).order_by(OnboardingTask.created_at.desc()).all()
        feedbacks = Feedback.query.filter_by(tenant_id=tenant_id).order_by(Feedback.created_at.desc()).all()
        notifications = Notification.query.filter_by(tenant_id=tenant_id).order_by(Notification.created_at.desc()).all()

        latest_review_by_employee: dict[str, PerformanceReview] = {}
        for review in reviews:
            latest_review_by_employee.setdefault(review.employee_id, review)
        tasks_by_employee: dict[str, list[OnboardingTask]] = {}
        for task in onboarding_tasks:
            tasks_by_employee.setdefault(task.employee_id, []).append(task)

        return {
            'employees': employees,
            'departments': departments,
            'reviews': reviews,
            'discussions': discussions,
            'replies': replies,
            'onboardingTasks': onboarding_tasks,
            'feedbacks': feedbacks,
            'notifications': notifications,
            'latestReviewByEmployee': latest_review_by_employee,
            'tasksByEmployee': tasks_by_employee,
        }

    @staticmethod
    def _okr_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        objectives = []
        for department in base['departments']:
            employee_count = sum(1 for employee in base['employees'] if employee.department_id == department.id)
            objectives.append({
                'id': f'okr-department-{department.id}',
                'title': f'{department.name} 组织协同目标',
                'owner': department.name,
                'progress': 75 if employee_count else 30,
                'keyResults': [
                    {'label': '活跃员工覆盖', 'value': employee_count, 'unit': '人'},
                    {'label': '协作讨论', 'value': len(base['discussions']), 'unit': '条'},
                ],
            })

        review_scores = [_score(row.final_score) for row in base['reviews'] if row.final_score is not None]
        objectives.append({
            'id': 'okr-performance-alignment',
            'title': '绩效目标对齐',
            'owner': 'HRBP',
            'progress': round(mean(review_scores), 2) if review_scores else 0,
            'keyResults': [
                {'label': '绩效记录', 'value': len(base['reviews']), 'unit': '条'},
                {'label': '平均得分', 'value': round(mean(review_scores), 2) if review_scores else 0, 'unit': '分'},
            ],
        })

        return {
            'summary': {
                'objectiveCount': len(objectives),
                'alignedDepartmentCount': len(base['departments']),
                'averageProgress': round(mean([row['progress'] for row in objectives]), 2) if objectives else 0,
            },
            'objectives': objectives[:20],
        }

    @staticmethod
    def _one_on_one_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        suggestions = []
        for employee in base['employees']:
            review = base['latestReviewByEmployee'].get(employee.id)
            score = _score(review.final_score if review else None)
            task_count = len(base['tasksByEmployee'].get(employee.id, []))
            reasons = []
            if score and score < 90:
                reasons.append('复盘绩效目标和支持事项')
            if employee.status == 'pending_onboard' or task_count:
                reasons.append('跟进入职体验和阻塞项')
            if any(note.employee_id == employee.id and note.status == 'unread' for note in base['notifications']):
                reasons.append('存在未读关怀或协同通知')
            if reasons:
                suggestions.append({
                    'employeeId': employee.id,
                    'employeeName': employee.name,
                    'departmentName': employee.department.name if employee.department else None,
                    'suggestedCadence': 'weekly' if employee.status == 'pending_onboard' else 'monthly',
                    'topics': reasons,
                })

        return {
            'summary': {
                'employeeCount': len(base['employees']),
                'suggestedMeetingCount': len(suggestions),
                'monthlyCadenceCount': sum(1 for row in suggestions if row['suggestedCadence'] == 'monthly'),
            },
            'suggestions': suggestions[:20],
        }

    @staticmethod
    def _survey_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        pending_feedbacks = [row for row in base['feedbacks'] if row.status in ('pending', 'in_progress')]
        unread_notifications = [row for row in base['notifications'] if row.status == 'unread']
        survey_signals = [
            {'key': 'feedback_volume', 'label': '员工反馈量', 'value': len(base['feedbacks']), 'sentiment': 'neutral'},
            {'key': 'open_feedback', 'label': '待处理反馈', 'value': len(pending_feedbacks), 'sentiment': 'negative' if pending_feedbacks else 'positive'},
            {'key': 'unread_care', 'label': '未读关怀通知', 'value': len(unread_notifications), 'sentiment': 'attention' if unread_notifications else 'positive'},
            {'key': 'social_activity', 'label': '学习社区互动', 'value': len(base['discussions']) + len(base['replies']), 'sentiment': 'positive'},
        ]
        positive = sum(1 for row in survey_signals if row['sentiment'] == 'positive')
        negative = sum(1 for row in survey_signals if row['sentiment'] in ('negative', 'attention'))
        enps = positive * 25 - negative * 20
        return {
            'summary': {
                'surveySignalCount': len(survey_signals),
                'openFeedbackCount': len(pending_feedbacks),
                'estimatedEnps': enps,
            },
            'signals': survey_signals,
        }

    @staticmethod
    def _employee_care_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        care_signals = []
        for note in base['notifications']:
            if note.notice_type in ('care', 'system', 'todo') or note.status == 'unread':
                care_signals.append({
                    'id': note.id,
                    'employeeId': note.employee_id,
                    'employeeName': note.employee.name if note.employee else None,
                    'title': note.title,
                    'status': note.status,
                    'linkUrl': note.link_url,
                    'recommendedAction': '安排经理跟进' if note.status == 'unread' else '保持观察',
                })
        for employee in base['employees']:
            review = base['latestReviewByEmployee'].get(employee.id)
            score = _score(review.final_score if review else None)
            if score and score < 70:
                care_signals.append({
                    'id': f'performance-care-{employee.id}',
                    'employeeId': employee.id,
                    'employeeName': employee.name,
                    'title': '绩效辅导关怀',
                    'status': 'open',
                    'linkUrl': '/performance-review',
                    'recommendedAction': '安排绩效辅导 1-on-1',
                })
        return {
            'summary': {
                'employeeCount': len(base['employees']),
                'careSignalCount': len(care_signals),
                'unreadCareCount': sum(1 for row in care_signals if row['status'] == 'unread'),
            },
            'careSignals': care_signals[:20],
        }

    @staticmethod
    def _social_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        posts = []
        replies_by_discussion: dict[str, list[DiscussionReply]] = {}
        for reply in base['replies']:
            replies_by_discussion.setdefault(reply.discussion_id, []).append(reply)
        for row in base['discussions']:
            replies = replies_by_discussion.get(row.id, [])
            posts.append({
                'id': row.id,
                'title': row.title,
                'authorName': row.employee.name if row.employee else None,
                'replyCount': row.reply_count or len(replies),
                'likeCount': row.like_count or 0,
                'engagementScore': int(row.like_count or 0) + int(row.reply_count or len(replies)),
                'latestReplies': [
                    {
                        'id': reply.id,
                        'employeeName': reply.employee.name if reply.employee else None,
                        'content': reply.content,
                    }
                    for reply in replies[:3]
                ],
            })
        return {
            'summary': {
                'postCount': len(posts),
                'replyCount': len(base['replies']),
                'engagementScore': sum(row['engagementScore'] for row in posts),
            },
            'posts': posts[:20],
        }

    @staticmethod
    def _onboarding_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        today = date.today()
        tasks = []
        for task in base['onboardingTasks']:
            days_left = (task.due_date - today).days if task.due_date else None
            tasks.append({
                'id': task.id,
                'employeeId': task.employee_id,
                'employeeName': task.employee.name if task.employee else None,
                'name': task.name,
                'taskType': task.task_type,
                'status': task.status,
                'dueDate': task.due_date.isoformat() if task.due_date else None,
                'daysLeft': days_left,
                'riskLevel': 'overdue' if days_left is not None and days_left < 0 else 'watch' if task.status != 'completed' else 'healthy',
            })
        return {
            'summary': {
                'taskCount': len(tasks),
                'pendingTaskCount': sum(1 for row in tasks if row['status'] != 'completed'),
                'newHireCount': sum(1 for employee in base['employees'] if employee.status == 'pending_onboard'),
            },
            'tasks': tasks[:20],
        }

    @staticmethod
    def _assistant_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        intents = [
            {
                'intent': 'okr_status',
                'label': '查询 OKR 进展',
                'sample': f"当前可生成 {len(base['departments']) + 1} 个协同目标",
            },
            {
                'intent': 'one_on_one',
                'label': '生成 1-on-1 建议',
                'sample': f"已纳入 {len(base['employees'])} 名员工信号",
            },
            {
                'intent': 'survey_enps',
                'label': '汇总员工调研信号',
                'sample': f"反馈 {len(base['feedbacks'])} 条，通知 {len(base['notifications'])} 条",
            },
            {
                'intent': 'onboarding_followup',
                'label': '跟进新员工体验',
                'sample': f"入职任务 {len(base['onboardingTasks'])} 项",
            },
            {
                'intent': 'social_activity',
                'label': '查看社区互动',
                'sample': f"讨论 {len(base['discussions'])} 条，回复 {len(base['replies'])} 条",
            },
        ]
        return {
            'summary': {
                'assistantIntentCount': len(intents),
                'knowledgeSourceCount': 5,
                'assistantMode': 'local_mvp',
            },
            'provider': {
                'providerCode': 'local_collaboration_assistant',
                'configured': False,
                'status': 'mock',
                'message': '未配置真实协同助手供应商，当前使用租户内数据生成本地 MVP 快照。',
            },
            'intents': intents,
        }

    @staticmethod
    def _feedback_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        feedbacks = [
            {
                'id': row.id,
                'title': row.title,
                'type': row.feedback_type,
                'severity': row.severity,
                'status': row.status,
                'sentiment': _sentiment_for_feedback(row),
                'recommendedAction': '进入产品/HR 联合跟进' if row.status in ('pending', 'in_progress') else '归档复盘',
            }
            for row in base['feedbacks']
        ]
        return {
            'summary': {
                'feedbackCount': len(feedbacks),
                'openFeedbackCount': sum(1 for row in feedbacks if row['status'] in ('pending', 'in_progress')),
                'criticalCount': sum(1 for row in feedbacks if row['severity'] == 'critical'),
            },
            'feedbacks': feedbacks[:20],
        }
