"""用户可见的技能卡片定义。

每张卡片是对 task_template 的用户友好包装，包含：
- 展示信息（名称、图标、描述、分类）
- 映射的 task_template_id
- 前端表单字段定义
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ── 表单字段类型 ────────────────────────────────────────────
# type: text | number | select | month | date
# 当 type=select 时需要提供 options: [{value, label}]

SKILL_CARDS: List[Dict[str, Any]] = [
    # ── 综合 ──
    {
        'id': 'system_dashboard',
        'name': '系统总览',
        'icon': 'fa-tachometer-alt',
        'description': '查看系统整体概况、关键指标',
        'category': '综合',
        'color': 'blue',
        'task_template_id': 'system_dashboard',
        'allowed_roles': ['admin', 'hr_admin', 'executive', 'manager',
                          'recruiter', 'finance', 'viewer', 'employee'],
        'fields': [],  # 无需参数
    },
    {
        'id': 'global_search',
        'name': '全局搜索',
        'icon': 'fa-search',
        'description': '跨模块模糊搜索员工/岗位/候选人',
        'category': '综合',
        'color': 'gray',
        'task_template_id': 'global_search_answer',
        'allowed_roles': ['admin', 'hr_admin', 'recruiter', 'manager',
                          'employee', 'finance', 'executive', 'viewer'],
        'fields': [
            {'key': 'keyword', 'label': '搜索关键词', 'type': 'text',
             'required': True, 'placeholder': '输入姓名/岗位/部门...'},
        ],
    },

    # ── 招聘 ──
    {
        'id': 'resume_analysis',
        'name': '简历分析',
        'icon': 'fa-file-alt',
        'description': '分析最近简历、推荐高分候选人',
        'category': '招聘',
        'color': 'indigo',
        'task_template_id': 'recent_resume_analysis',
        'allowed_roles': ['admin', 'hr_admin', 'recruiter', 'executive', 'viewer'],
        'fields': [
            {'key': 'recent_days', 'label': '最近天数', 'type': 'number',
             'default': 7, 'placeholder': '默认7天', 'min': 1, 'max': 90},
            {'key': 'top_n', 'label': '显示条数', 'type': 'number',
             'default': 10, 'placeholder': '默认10条', 'min': 1, 'max': 50},
        ],
    },
    {
        'id': 'recruitment_overview',
        'name': '招聘概览',
        'icon': 'fa-chart-pie',
        'description': '招聘整体数据、进展报表',
        'category': '招聘',
        'color': 'green',
        'task_template_id': 'recruitment_overview',
        'allowed_roles': ['admin', 'hr_admin', 'recruiter', 'executive', 'viewer', 'manager'],
        'fields': [
            {'key': 'recent_days', 'label': '统计天数', 'type': 'number',
             'default': 7, 'placeholder': '默认7天', 'min': 1, 'max': 90},
        ],
    },
    {
        'id': 'interview_planning',
        'name': '面试计划',
        'icon': 'fa-calendar-check',
        'description': '推荐面试候选人、生成时段建议',
        'category': '招聘',
        'color': 'purple',
        'task_template_id': 'interview_schedule_plan',
        'allowed_roles': ['admin', 'hr_admin', 'recruiter', 'executive'],
        'fields': [
            {'key': 'top_n', 'label': '推荐人数', 'type': 'number',
             'default': 10, 'placeholder': '默认10人', 'min': 1, 'max': 30},
        ],
    },

    # ── 人事 ──
    {
        'id': 'employee_lookup',
        'name': '员工查询',
        'icon': 'fa-user-tie',
        'description': '查询员工信息、部门、岗位',
        'category': '人事',
        'color': 'cyan',
        'task_template_id': 'employee_lookup',
        'allowed_roles': ['admin', 'hr_admin', 'manager', 'executive',
                          'viewer', 'recruiter', 'employee', 'finance'],
        'fields': [
            {'key': 'keyword', 'label': '员工姓名/关键词', 'type': 'text',
             'required': True, 'placeholder': '输入姓名或关键词'},
        ],
    },
    {
        'id': 'organization_overview',
        'name': '组织架构',
        'icon': 'fa-sitemap',
        'description': '部门结构、人员分布',
        'category': '人事',
        'color': 'teal',
        'task_template_id': 'organization_overview',
        'allowed_roles': ['admin', 'hr_admin', 'manager', 'executive',
                          'recruiter', 'viewer', 'employee', 'finance'],
        'fields': [
            {'key': 'keyword', 'label': '部门名称', 'type': 'text',
             'placeholder': '可选，留空查看全部'},
        ],
    },

    # ── 考勤 ──
    {
        'id': 'attendance_analysis',
        'name': '考勤分析',
        'icon': 'fa-clock',
        'description': '考勤异常、迟到缺卡、加班统计',
        'category': '考勤',
        'color': 'amber',
        'task_template_id': 'attendance_exception_analysis',
        'allowed_roles': ['admin', 'hr_admin', 'executive', 'manager', 'employee'],
        'fields': [
            {'key': 'month', 'label': '月份', 'type': 'month',
             'placeholder': '如 2026-05，留空查当月'},
            {'key': 'anomaly_only', 'label': '仅异常', 'type': 'select',
             'default': 'true',
             'options': [
                 {'value': 'true', 'label': '仅看异常'},
                 {'value': 'false', 'label': '全部记录'},
             ]},
        ],
    },

    # ── 绩效 ──
    {
        'id': 'performance_analysis',
        'name': '绩效分析',
        'icon': 'fa-chart-line',
        'description': '绩效评分分布、等级分布',
        'category': '绩效',
        'color': 'orange',
        'task_template_id': 'performance_distribution_report',
        'allowed_roles': ['admin', 'hr_admin', 'executive', 'manager', 'employee'],
        'fields': [],
    },

    # ── 薪酬 ──
    {
        'id': 'payroll_analysis',
        'name': '薪酬分析',
        'icon': 'fa-money-bill-wave',
        'description': '月度薪酬汇总、工资条',
        'category': '薪酬',
        'color': 'red',
        'task_template_id': 'payroll_month_summary',
        'allowed_roles': ['admin', 'hr_admin', 'finance', 'executive'],
        'fields': [
            {'key': 'month', 'label': '月份', 'type': 'month',
             'placeholder': '如 2026-05，留空查当月'},
        ],
    },

    # ── 培训 ──
    {
        'id': 'training_analysis',
        'name': '培训分析',
        'icon': 'fa-graduation-cap',
        'description': '培训完成率、出勤统计',
        'category': '培训',
        'color': 'lime',
        'task_template_id': 'training_completion_report',
        'allowed_roles': ['admin', 'hr_admin', 'executive', 'manager', 'employee'],
        'fields': [],
    },

    # ── 审批 ──
    {
        'id': 'approval_summary',
        'name': '审批查询',
        'icon': 'fa-clipboard-check',
        'description': '待审批、我的申请、审批历史',
        'category': '审批',
        'color': 'sky',
        'task_template_id': 'approval_pending_summary',
        'allowed_roles': ['admin', 'hr_admin', 'manager', 'employee',
                          'recruiter', 'finance', 'executive'],
        'fields': [
            {'key': 'view', 'label': '查看视角', 'type': 'select',
             'default': 'pending',
             'options': [
                 {'value': 'pending', 'label': '待我审批'},
                 {'value': 'mine', 'label': '我的申请'},
                 {'value': 'history', 'label': '审批历史'},
             ]},
        ],
    },

    # ── 反馈 ──
    {
        'id': 'feedback_triage',
        'name': '反馈汇总',
        'icon': 'fa-comment-dots',
        'description': '问题反馈分类、状态流转',
        'category': '反馈',
        'color': 'pink',
        'task_template_id': 'feedback_triage_summary',
        'allowed_roles': ['admin', 'hr_admin', 'manager', 'employee',
                          'recruiter', 'executive', 'viewer', 'finance'],
        'fields': [
            {'key': 'feedback_type', 'label': '反馈类型', 'type': 'select',
             'default': '',
             'options': [
                 {'value': '', 'label': '全部'},
                 {'value': 'bug', 'label': 'Bug/缺陷'},
                 {'value': 'feature', 'label': '需求建议'},
                 {'value': 'other', 'label': '其他'},
             ]},
        ],
    },

    # ── 文案 ──
    {
        'id': 'draft_generator',
        'name': '文案生成',
        'icon': 'fa-pen-fancy',
        'description': '面试邀请/Offer/通知等文案草稿',
        'category': '工具',
        'color': 'violet',
        'task_template_id': 'hr_draft_generation',
        'allowed_roles': ['admin', 'hr_admin', 'recruiter', 'manager', 'executive'],
        'fields': [
            {'key': 'draft_type', 'label': '文案类型', 'type': 'select',
             'default': 'interview_invite',
             'options': [
                 {'value': 'interview_invite', 'label': '面试邀请'},
                 {'value': 'offer_communication', 'label': 'Offer通知'},
                 {'value': 'onboarding_notice', 'label': '入职通知'},
                 {'value': 'training_notice', 'label': '培训通知'},
             ]},
            {'key': 'keyword', 'label': '相关人/岗位', 'type': 'text',
             'placeholder': '可选，留空通用'},
        ],
    },
]


def get_cards_for_role(role: str) -> List[Dict[str, Any]]:
    """返回当前角色可用的技能卡片列表。"""
    return [
        {k: v for k, v in card.items() if k != 'allowed_roles'}
        for card in SKILL_CARDS
        if role in card.get('allowed_roles', [])
    ]
