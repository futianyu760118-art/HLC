"""Skill 注册表。

把 13 个通用 skill 注册成 SkillSpec，方便 router/executor 引用。
不让 LLM 自由调用任意工具——必须由 task_template 显式声明 candidate_skills。
"""

from __future__ import annotations

from typing import Dict, List

from . import skills as S
from .constants import (
    ACTION_APPROVE, ACTION_GENERATE_DRAFT, ACTION_READ_HR, ACTION_READ_PUBLIC,
    ACTION_READ_SENSITIVE, RISK_HIGH, RISK_LOW, RISK_MEDIUM,
    ACTION_WRITE_BUSINESS,
    ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_EXECUTIVE, ROLE_FINANCE,
    ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_RECRUITER, ROLE_VIEWER,
)
from .schemas import SkillSpec


_SKILL_REGISTRY: Dict[str, SkillSpec] = {}


def _register(spec: SkillSpec) -> None:
    _SKILL_REGISTRY[spec.id] = spec


# 1. global_search
_register(SkillSpec(
    id='global_search',
    name='全局搜索',
    domain='global',
    description='在员工/候选人/简历/岗位/部门/反馈等多个模块中模糊搜索关键字。',
    input_schema={
        'keyword': {'type': 'string', 'required': True},
        'limit': {'type': 'integer', 'default': 10},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER,
                   ROLE_EMPLOYEE, ROLE_FINANCE, ROLE_EXECUTIVE, ROLE_VIEWER],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_PUBLIC,
    handler=S.skill_global_search,
))

# 2. employee_search
_register(SkillSpec(
    id='employee_search',
    name='员工查询',
    domain='employee',
    description='查询员工档案、状态、部门、岗位、入职时间、试用期等。',
    input_schema={
        'keyword': {'type': 'string'},
        'department_id': {'type': 'string'},
        'status': {'type': 'string'},
        'limit': {'type': 'integer', 'default': 10},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE,
                   ROLE_VIEWER, ROLE_RECRUITER, ROLE_EMPLOYEE, ROLE_FINANCE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_employee_search,
))

# 3. recruitment_search
_register(SkillSpec(
    id='recruitment_search',
    name='招聘查询',
    domain='recruitment',
    description='统一处理招聘域查询：jobs/resumes/candidates/interviews/offers。',
    input_schema={
        'keyword': {'type': 'string'},
        'module': {'type': 'string', 'enum': ['jobs', 'resumes', 'candidates', 'interviews', 'offers', 'all']},
        'status': {'type': 'string'},
        'date_range': {'type': 'object'},
        'limit': {'type': 'integer', 'default': 10},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER,
                   ROLE_EXECUTIVE, ROLE_VIEWER],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_recruitment_search,
))

# 4. resume_analysis
_register(SkillSpec(
    id='resume_analysis',
    name='简历分析',
    domain='recruitment',
    description='分析最近简历、TOP 简历、岗位匹配、候选人推荐。',
    input_schema={
        'recent_days': {'type': 'integer', 'default': 7},
        'job_id': {'type': 'string'},
        'top_n': {'type': 'integer', 'default': 10},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_EXECUTIVE, ROLE_VIEWER],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_resume_analysis,
))

# 5. interview_planning
_register(SkillSpec(
    id='interview_planning',
    name='面试计划生成',
    domain='recruitment',
    description='根据简历评分生成面试计划建议。只生成建议，不创建面试。',
    input_schema={
        'job_id': {'type': 'string'},
        'top_n': {'type': 'integer', 'default': 10},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_EXECUTIVE],
    risk_level=RISK_MEDIUM, side_effect=False,  # 中风险但只读
    action_type=ACTION_GENERATE_DRAFT,
    handler=S.skill_interview_planning,
))

# 6. organization_search
_register(SkillSpec(
    id='organization_search',
    name='组织查询',
    domain='organization',
    description='查询部门树、岗位体系、部门人数。',
    input_schema={
        'keyword': {'type': 'string'},
        'include_stats': {'type': 'boolean', 'default': True},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE,
                   ROLE_RECRUITER, ROLE_FINANCE, ROLE_VIEWER, ROLE_EMPLOYEE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_PUBLIC,
    handler=S.skill_organization_search,
))

# 7. approval_search
_register(SkillSpec(
    id='approval_search',
    name='审批查询',
    domain='approval',
    description='查询我的申请/待我审批/审批历史。不自动审批。',
    input_schema={
        'view': {'type': 'string', 'enum': ['mine', 'pending', 'history']},
        'business_type': {'type': 'string'},
        'status': {'type': 'string'},
        'limit': {'type': 'integer', 'default': 10},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EMPLOYEE,
                   ROLE_RECRUITER, ROLE_FINANCE, ROLE_EXECUTIVE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_approval_search,
))

# 8. attendance_analysis
_register(SkillSpec(
    id='attendance_analysis',
    name='考勤分析',
    domain='attendance',
    description='考勤异常、月度统计、部门/个人维度。',
    input_schema={
        'month': {'type': 'string'},
        'employee_id': {'type': 'string'},
        'department_id': {'type': 'string'},
        'anomaly_only': {'type': 'boolean', 'default': False},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_EXECUTIVE, ROLE_MANAGER, ROLE_EMPLOYEE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_attendance_analysis,
))

# 9. performance_analysis
_register(SkillSpec(
    id='performance_analysis',
    name='绩效分析',
    domain='performance',
    description='绩效周期、评分分布、等级分布。',
    input_schema={
        'cycle_id': {'type': 'string'},
        'department_id': {'type': 'string'},
        'employee_id': {'type': 'string'},
        'view': {'type': 'string', 'enum': ['summary', 'distribution', 'personal']},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_EXECUTIVE, ROLE_MANAGER, ROLE_EMPLOYEE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_performance_analysis,
))

# 10. payroll_analysis（高敏感）
_register(SkillSpec(
    id='payroll_analysis',
    name='薪酬分析',
    domain='payroll',
    description='薪资档案、工资条、月度薪酬汇总。仅授权角色可用。',
    input_schema={
        'month': {'type': 'string'},
        'employee_id': {'type': 'string'},
        'department_id': {'type': 'string'},
        'view': {'type': 'string', 'enum': ['summary', 'personal']},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_FINANCE, ROLE_EXECUTIVE],
    risk_level=RISK_HIGH, side_effect=False,
    action_type=ACTION_READ_SENSITIVE,
    handler=S.skill_payroll_analysis,
))

# 11. training_analysis
_register(SkillSpec(
    id='training_analysis',
    name='培训分析',
    domain='training',
    description='培训课程、计划、完成率、记录。',
    input_schema={
        'department_id': {'type': 'string'},
        'employee_id': {'type': 'string'},
        'status': {'type': 'string'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_EXECUTIVE, ROLE_MANAGER, ROLE_EMPLOYEE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_training_analysis,
))

# 12. feedback_triage
_register(SkillSpec(
    id='feedback_triage',
    name='反馈分类汇总',
    domain='feedback',
    description='问题反馈分类、状态流转、待处理统计。',
    input_schema={
        'feedback_type': {'type': 'string', 'enum': ['bug', 'feature', 'other']},
        'status': {'type': 'string'},
        'limit': {'type': 'integer', 'default': 10},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EMPLOYEE,
                   ROLE_RECRUITER, ROLE_EXECUTIVE, ROLE_VIEWER, ROLE_FINANCE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_PUBLIC,
    handler=S.skill_feedback_triage,
))

# 13. dashboard_report
_register(SkillSpec(
    id='dashboard_report',
    name='报表概览',
    domain='dashboard',
    description='系统概览、指标卡、维度分布、趋势。',
    input_schema={
        'scope': {'type': 'string', 'enum': ['system', 'recruitment', 'employee',
                                              'attendance', 'performance', 'payroll', 'training']},
        'date_range': {'type': 'object'},
        'group_by': {'type': 'string'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_EXECUTIVE, ROLE_MANAGER,
                   ROLE_RECRUITER, ROLE_FINANCE, ROLE_VIEWER, ROLE_EMPLOYEE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_PUBLIC,
    handler=S.skill_dashboard_report,
))

# 14. draft_generator
_register(SkillSpec(
    id='draft_generator',
    name='草稿生成器',
    domain='draft',
    description='生成 Offer/面试邀请/通知/审批意见等草稿。不发送、不写库。',
    input_schema={
        'draft_type': {'type': 'string'},
        'facts': {'type': 'object'},
        'tone': {'type': 'string'},
        'audience': {'type': 'string'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER, ROLE_EXECUTIVE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_GENERATE_DRAFT,
    handler=S.skill_draft_generator,
))

# 15. resume_get_detail
_register(SkillSpec(
    id='resume_get_detail',
    name='简历详情加载',
    domain='recruitment',
    description='根据 resume_id 或 candidate_id 加载脱敏简历/候选人上下文，供生成任务使用。',
    input_schema={
        'resume_id': {'type': 'string'},
        'candidate_id': {'type': 'string'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER,
                   ROLE_EXECUTIVE, ROLE_VIEWER],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_resume_get_detail,
))

# 16. employee_get_detail
_register(SkillSpec(
    id='employee_get_detail',
    name='员工详情加载',
    domain='employee',
    description='根据 employee_id 加载脱敏员工上下文，供生成/解释任务使用。',
    input_schema={'employee_id': {'type': 'string', 'required': True}},
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE,
                   ROLE_RECRUITER, ROLE_EMPLOYEE, ROLE_FINANCE, ROLE_VIEWER],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_employee_get_detail,
))

# 17. job_get_detail
_register(SkillSpec(
    id='job_get_detail',
    name='岗位详情加载',
    domain='recruitment',
    description='根据 job_id 加载岗位职责、要求、评分标准等上下文。',
    input_schema={'job_id': {'type': 'string', 'required': True}},
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER,
                   ROLE_EXECUTIVE, ROLE_VIEWER],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_job_get_detail,
))

# 18. render_document
_register(SkillSpec(
    id='render_document',
    name='文档渲染',
    domain='render',
    description='把 markdown/报告渲染为可下载文档。第一版返回占位提示。',
    input_schema={'title': {'type': 'string'}, 'content': {'type': 'string'}},
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER,
                   ROLE_EXECUTIVE, ROLE_VIEWER, ROLE_EMPLOYEE, ROLE_FINANCE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_GENERATE_DRAFT,
    handler=S.skill_render_document,
))

# 19. candidate_evidence_bundle
_register(SkillSpec(
    id='candidate_evidence_bundle',
    name='候选人完整证据包',
    domain='recruitment',
    description='按姓名或候选人/简历 ID 汇集简历、岗位、面试、Offer 和入职关联信息，供分析推理使用。',
    input_schema={
        'keyword': {'type': 'string'},
        'candidate_id': {'type': 'string'},
        'resume_id': {'type': 'string'},
        'job_keyword': {'type': 'string'},
        'job_id': {'type': 'string'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER, ROLE_EXECUTIVE, ROLE_VIEWER],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_candidate_evidence_bundle,
))

# 20. employee_evidence_bundle
_register(SkillSpec(
    id='employee_evidence_bundle',
    name='员工完整证据包',
    domain='employee',
    description='按姓名或员工 ID 汇集员工档案及考勤、绩效、培训、申请、入职任务与招聘来源。',
    input_schema={'keyword': {'type': 'string'}, 'employee_id': {'type': 'string'}},
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE, ROLE_RECRUITER, ROLE_EMPLOYEE, ROLE_FINANCE, ROLE_VIEWER],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_employee_evidence_bundle,
))

# 21. recruitment_match_matrix
_register(SkillSpec(
    id='recruitment_match_matrix',
    name='招聘匹配矩阵',
    domain='recruitment',
    description='按岗位聚合候选人、简历和面试证据，输出候选人对比矩阵和推荐顺序。',
    input_schema={
        'keyword': {'type': 'string'},
        'job_id': {'type': 'string'},
        'limit': {'type': 'integer', 'default': 8},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER, ROLE_EXECUTIVE, ROLE_VIEWER],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_recruitment_match_matrix,
))

# 22. employee_change_impact
_register(SkillSpec(
    id='employee_change_impact',
    name='员工异动影响分析',
    domain='employee',
    description='模拟员工调岗/异动影响，关联员工、部门、岗位、薪资、审批、通知和历史异动，不直接改库。',
    input_schema={
        'keyword': {'type': 'string'},
        'employee_id': {'type': 'string'},
        'target_department': {'type': 'string'},
        'action_id': {'type': 'string'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_employee_change_impact,
))

# 23. employee_salary_adjustment_impact
_register(SkillSpec(
    id='employee_salary_adjustment_impact',
    name='员工调薪影响分析',
    domain='employee',
    description='模拟员工调薪影响，关联员工档案、薪资档案、绩效、历史异动、审批和通知，不直接改库。',
    input_schema={
        'keyword': {'type': 'string'},
        'employee_id': {'type': 'string'},
        'salary_adjustment': {'type': 'number'},
        'action_id': {'type': 'string'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_SENSITIVE,
    handler=S.skill_employee_salary_adjustment_impact,
))

# 24. payroll_performance_link
_register(SkillSpec(
    id='payroll_performance_link',
    name='薪资绩效考勤联动分析',
    domain='payroll',
    description='关联低绩效员工、薪资档案和考勤异常，输出共性风险和复盘建议。',
    input_schema={
        'year': {'type': 'integer'},
        'quarter': {'type': 'integer'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_FINANCE, ROLE_EXECUTIVE],
    risk_level=RISK_MEDIUM, side_effect=False,
    action_type=ACTION_READ_SENSITIVE,
    handler=S.skill_payroll_performance_link,
))

# 25. employee_attendance_evidence
_register(SkillSpec(
    id='employee_attendance_evidence',
    name='员工考勤证据包',
    domain='attendance',
    description='按员工聚合考勤记录、统计口径和已批请假/加班/出差/补卡申请，输出个人异常证据。',
    input_schema={
        'keyword': {'type': 'string'},
        'employee_id': {'type': 'string'},
        'recent_days': {'type': 'integer', 'default': 30},
        'month': {'type': 'string'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE, ROLE_EMPLOYEE, ROLE_VIEWER],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_employee_attendance_evidence,
))

# 25. system_search
_register(SkillSpec(
    id='system_search',
    name='系统通用检索',
    domain='system',
    description=(
        '跨 HRM 全模块只读检索，覆盖候选人、简历、岗位、员工、组织、面试、Offer、入职、试用期、'
        '异动、离职、合同、考勤、申请、审批、绩效、薪酬、培训、反馈、通知。用于用户只给姓名、岗位、'
        '关键词或模糊自然语言时先找系统证据。'
    ),
    input_schema={
        'keyword': {'type': 'string'},
        'module': {'type': 'string', 'enum': [
            'all', 'recruitment', 'candidate', 'resume', 'job', 'employee',
            'organization', 'interview', 'offer', 'lifecycle', 'attendance',
            'performance', 'payroll', 'training', 'feedback',
            'notifications', 'users', 'roles', 'operation_logs', 'settings',
            'model_settings', 'module_catalog',
        ]},
        'view': {'type': 'string'},
        'module_id': {'type': 'string'},
        'flow_id': {'type': 'string'},
        'limit': {'type': 'integer', 'default': 12},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER,
                   ROLE_EXECUTIVE, ROLE_VIEWER, ROLE_EMPLOYEE, ROLE_FINANCE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_system_search,
))

# 26. workset_analyze
_register(SkillSpec(
    id='workset_analyze',
    name='结果集通用分析',
    domain='system',
    description=(
        '分析上一轮返回的 WorkSet 结果集，支持按已有字段回答最高/最低/最大/最小/最近/最早/评分/匹配度/'
        '年龄/经验/学历/状态等追问。字段不存在时明确说明缺失，并列出可用指标。'
    ),
    input_schema={
        'question': {'type': 'string', 'required': True},
        'entity_type': {'type': 'string'},
        'limit': {'type': 'integer', 'default': 20},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER,
                   ROLE_EXECUTIVE, ROLE_VIEWER, ROLE_EMPLOYEE, ROLE_FINANCE],
    risk_level=RISK_LOW, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_workset_analyze,
))

# 27. smart_data_query
_register(SkillSpec(
    id='smart_data_query',
    name='智能只读数据查询',
    domain='analytics',
    description=(
        '当固定业务技能无法覆盖复杂统计、跨表 JOIN、分组、排序、排名、趋势、交叉分析时使用。'
        '接收自然语言问题和候选 SELECT SQL，后端校验为只读查询后执行，返回表格、来源和中文摘要。'
        '禁止写入、删除、DDL、审批、发送等副作用 SQL。'
    ),
    input_schema={
        'question': {'type': 'string', 'required': True},
        'sql': {'type': 'string'},
        'explanation': {'type': 'string'},
        'limit': {'type': 'integer', 'default': 50},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER,
                   ROLE_EXECUTIVE, ROLE_VIEWER, ROLE_EMPLOYEE, ROLE_FINANCE],
    risk_level=RISK_MEDIUM, side_effect=False,
    action_type=ACTION_READ_HR,
    handler=S.skill_smart_data_query,
))

# 28. interview_create (requires an explicit chat confirmation before ToolExecutor is called)
_register(SkillSpec(
    id='interview_create',
    name='创建面试安排',
    domain='recruitment',
    description='在用户确认后的动作计划中创建面试记录。',
    input_schema={'resume_id': {'type': 'string', 'required': True}, 'job_id': {'type': 'string', 'required': True}, 'scheduled_at': {'type': 'string', 'required': True}},
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER],
    risk_level=RISK_HIGH, side_effect=True,
    action_type=ACTION_WRITE_BUSINESS,
    handler=S.skill_interview_create,
))

# 29. followup_task_create (requires an explicit chat confirmation before ToolExecutor is called)
_register(SkillSpec(
    id='followup_task_create',
    name='创建跟进提醒',
    domain='task',
    description='在用户确认后向通知中心写入个人跟进提醒。',
    input_schema={'title': {'type': 'string', 'required': True}, 'content': {'type': 'string'}},
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER, ROLE_EXECUTIVE],
    risk_level=RISK_HIGH, side_effect=True,
    action_type=ACTION_WRITE_BUSINESS,
    handler=S.skill_followup_task_create,
))

# 30. notification_create (requires an explicit chat confirmation before ToolExecutor is called)
_register(SkillSpec(
    id='notification_create',
    name='创建系统通知',
    domain='notification',
    description='在用户确认后向通知中心写入一条站内通知，可用于 HR 提醒、审批提醒和业务通知。',
    input_schema={
        'title': {'type': 'string', 'required': True},
        'content': {'type': 'string'},
        'notice_type': {'type': 'string', 'default': 'hr'},
        'user_id': {'type': 'string'},
        'link_url': {'type': 'string'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE],
    risk_level=RISK_HIGH, side_effect=True,
    action_type=ACTION_WRITE_BUSINESS,
    handler=S.skill_notification_create,
))


# 31. approval_decision (requires an explicit chat confirmation before ToolExecutor is called)
_register(SkillSpec(
    id='approval_decision',
    name='处理审批',
    domain='approval',
    description='在用户确认后审批通过或驳回一条待审批记录，并按原业务审批规则更新关联业务单据。',
    input_schema={
        'approval_id': {'type': 'string', 'required': True},
        'action': {'type': 'string', 'enum': ['approve', 'reject'], 'required': True},
        'comment': {'type': 'string'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE],
    risk_level=RISK_HIGH, side_effect=True,
    action_type=ACTION_APPROVE,
    handler=S.skill_approval_decision,
))


# 32. employee_change_submit (requires an explicit chat confirmation before ToolExecutor is called)
_register(SkillSpec(
    id='employee_change_submit',
    name='提交员工异动审批',
    domain='employee',
    description='在用户确认后创建员工异动申请、关联审批实例、待办通知和操作审计；审批通过前不直接修改员工档案。',
    input_schema={
        'employee_id': {'type': 'string'},
        'keyword': {'type': 'string'},
        'target_department_id': {'type': 'string'},
        'target_department': {'type': 'string'},
        'target_position_id': {'type': 'string'},
        'target_position': {'type': 'string'},
        'salary_adjustment': {'type': 'number'},
        'effective_date': {'type': 'string'},
        'reason': {'type': 'string'},
        'action_id': {'type': 'string'},
    },
    allowed_roles=[ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE],
    risk_level=RISK_HIGH, side_effect=True,
    action_type=ACTION_WRITE_BUSINESS,
    handler=S.skill_employee_change_submit,
))


def get(skill_id: str):
    return _SKILL_REGISTRY.get(skill_id)


def all_skills() -> List[SkillSpec]:
    return list(_SKILL_REGISTRY.values())


def list_brief() -> List[dict]:
    """给 Router 看的精简列表。"""
    return [
        {'id': s.id, 'domain': s.domain, 'description': s.description}
        for s in _SKILL_REGISTRY.values()
    ]


def exists(skill_id: str) -> bool:
    return skill_id in _SKILL_REGISTRY
