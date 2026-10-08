"""Seed coherent demo data for all HRM modules.

The script owns only rows whose IDs start with ``demo-``. Running it multiple
times refreshes the same demo business chain instead of creating duplicates.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterable

import bcrypt

from app import create_app
from models import (
    ApprovalInstance,
    ApprovalRecord,
    AssistantAuditLog,
    AssistantSession,
    AttendanceRecord,
    Candidate,
    Contract,
    Department,
    Employee,
    EmployeeChange,
    EmployeeRequest,
    Feedback,
    Interview,
    Job,
    Notification,
    Offer,
    OnboardingTask,
    OperationLog,
    PayrollRecord,
    PerformanceCycle,
    PerformanceReview,
    PerformanceTemplate,
    Position,
    Probation,
    Resignation,
    Resume,
    Role,
    SalaryProfile,
    TrainingCourse,
    TrainingPlan,
    TrainingRecord,
    User,
    db,
)


DEMO_PREFIX = 'demo-'
DEMO_PASSWORD = 'Demo@123456'
DEMO_EMAIL_DOMAIN = 'hengpintong.demo'


def d(value: str) -> date:
    return date.fromisoformat(value)


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def money(value: str | int | float) -> Decimal:
    return Decimal(str(value))


def password_hash() -> str:
    return bcrypt.hashpw(DEMO_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def delete_demo_rows() -> None:
    models_in_delete_order = [
        AssistantAuditLog,
        AssistantSession,
        ApprovalRecord,
        Notification,
        OperationLog,
        Feedback,
        PayrollRecord,
        SalaryProfile,
        TrainingRecord,
        TrainingPlan,
        TrainingCourse,
        PerformanceReview,
        PerformanceTemplate,
        PerformanceCycle,
        EmployeeRequest,
        AttendanceRecord,
        Contract,
        Resignation,
        EmployeeChange,
        Probation,
        OnboardingTask,
        ApprovalInstance,
        Employee,
        Offer,
        Candidate,
        Interview,
        Resume,
        Job,
        Position,
        Department,
        User,
    ]
    for model in models_in_delete_order:
        model.query.filter(model.id.like(f'{DEMO_PREFIX}%')).delete(synchronize_session=False)
    db.session.commit()


def add_all(rows: Iterable[object]) -> None:
    db.session.add_all(list(rows))


def ensure_roles() -> None:
    role_specs = [
        ('admin', '系统管理员', '全量系统配置、用户与数据管理权限'),
        ('hr_admin', 'HR管理员', '组织、员工、招聘、绩效、培训与审批管理'),
        ('recruiter', '招聘专员', '岗位、简历、候选人、面试与 Offer 管理'),
        ('manager', '部门负责人', '部门人员、审批、绩效与培训查看/处理'),
        ('employee', '普通员工', '个人档案、申请、通知与反馈'),
        ('finance', '财务人员', '薪资档案、工资条与薪酬报表'),
        ('executive', '高管/老板', '经营驾驶舱与关键人力指标查看'),
        ('viewer', '查看者', '只读查看权限'),
    ]
    for code, name, description in role_specs:
        role = Role.query.filter_by(code=code).first()
        if role is not None and not role.id.startswith(DEMO_PREFIX):
            continue
        if role is None:
            role = Role(id=f'{DEMO_PREFIX}role-{code}', code=code)
            db.session.add(role)
        role.name = name
        role.description = description
        role.permissions = ['demo:read', f'role:{code}']
        role.status = 'active'


def seed_demo_data() -> dict[str, int]:
    delete_demo_rows()
    ensure_roles()
    pw = password_hash()

    users = [
        User(id='demo-user-admin', email=f'admin@{DEMO_EMAIL_DOMAIN}', password_hash=pw, name='演示管理员', role='admin', phone='13800000001', status='active'),
        User(id='demo-user-hr', email=f'hr@{DEMO_EMAIL_DOMAIN}', password_hash=pw, name='林瑶', role='hr_admin', phone='13800000002', status='active', department_id='demo-dept-hr', employee_id='demo-emp-hr-linyao'),
        User(id='demo-user-recruiter', email=f'recruiter@{DEMO_EMAIL_DOMAIN}', password_hash=pw, name='周可', role='recruiter', phone='13800000003', status='active', department_id='demo-dept-hr', employee_id='demo-emp-hr-zhouke'),
        User(id='demo-user-manager-rd', email=f'rd.manager@{DEMO_EMAIL_DOMAIN}', password_hash=pw, name='陈宇', role='manager', phone='13800000004', status='active', department_id='demo-dept-rd', employee_id='demo-emp-rd-chenyu'),
        User(id='demo-user-employee', email=f'employee@{DEMO_EMAIL_DOMAIN}', password_hash=pw, name='张三', role='employee', phone='13800000005', status='active', department_id='demo-dept-rd', employee_id='demo-emp-rd-zhangsan'),
        User(id='demo-user-finance', email=f'finance@{DEMO_EMAIL_DOMAIN}', password_hash=pw, name='赵敏', role='finance', phone='13800000006', status='active', department_id='demo-dept-finance', employee_id='demo-emp-finance-zhaomin'),
        User(id='demo-user-executive', email=f'executive@{DEMO_EMAIL_DOMAIN}', password_hash=pw, name='顾明', role='executive', phone='13800000007', status='active', department_id='demo-dept-hq', employee_id='demo-emp-hq-guming'),
        User(id='demo-user-viewer', email=f'viewer@{DEMO_EMAIL_DOMAIN}', password_hash=pw, name='观察员', role='viewer', phone='13800000008', status='active'),
    ]
    add_all(users)

    departments = [
        Department(id='demo-dept-hq', name='总部办公室', code='DEMO-HQ', manager_id='demo-emp-hq-guming', status='active', description='公司管理与经营驾驶舱'),
        Department(id='demo-dept-hr', name='人力资源部', code='DEMO-HR', parent_id='demo-dept-hq', manager_id='demo-emp-hr-linyao', status='active', description='招聘、员工关系、薪酬绩效与组织发展'),
        Department(id='demo-dept-rd', name='研发部', code='DEMO-RD', parent_id='demo-dept-hq', manager_id='demo-emp-rd-chenyu', status='active', description='产品研发、架构与质量保障'),
        Department(id='demo-dept-product', name='产品部', code='DEMO-PD', parent_id='demo-dept-hq', manager_id='demo-emp-product-sunye', status='active', description='产品规划与用户研究'),
        Department(id='demo-dept-sales', name='销售部', code='DEMO-SALES', parent_id='demo-dept-hq', manager_id='demo-emp-sales-wangwu', status='active', description='客户开拓与商机推进'),
        Department(id='demo-dept-finance', name='财务部', code='DEMO-FIN', parent_id='demo-dept-hq', manager_id='demo-emp-finance-zhaomin', status='active', description='薪酬发放、预算与报销管理'),
    ]
    add_all(departments)

    positions = [
        Position(id='demo-pos-executive', title='总经理', category='管理序列', department_id='demo-dept-hq', level='M5', status='active', responsibilities='经营目标、组织能力和关键决策。', requirements='企业经营与组织管理经验。'),
        Position(id='demo-pos-hrbp', title='HRBP', category='专业序列', department_id='demo-dept-hr', level='P3', status='active', responsibilities='支持业务部门招聘、绩效和员工关系。', requirements='熟悉 HR 全模块。'),
        Position(id='demo-pos-recruiter', title='招聘专员', category='专业序列', department_id='demo-dept-hr', level='P2', status='active', responsibilities='岗位发布、简历筛选、面试推进。', requirements='熟悉招聘渠道和候选人运营。'),
        Position(id='demo-pos-backend', title='后端工程师', category='技术序列', department_id='demo-dept-rd', level='P3', status='active', responsibilities='后端服务、接口和数据库设计。', requirements='Python/Java、SQL、微服务经验。'),
        Position(id='demo-pos-electronics', title='电子工程师', category='技术序列', department_id='demo-dept-rd', level='P3', status='active', responsibilities='电子硬件方案设计、原理图/PCB评审、样机验证和量产问题闭环。', requirements='熟悉模拟/数字电路、EMC整改、硬件测试和跨部门协作。'),
        Position(id='demo-pos-qa', title='测试工程师', category='技术序列', department_id='demo-dept-rd', level='P2', status='active', responsibilities='自动化测试、质量度量和发布验证。', requirements='测试设计和自动化脚本能力。'),
        Position(id='demo-pos-product', title='产品经理', category='产品序列', department_id='demo-dept-product', level='P3', status='active', responsibilities='需求分析、产品规划、验收与增长指标。', requirements='B 端产品经验。'),
        Position(id='demo-pos-sales-manager', title='销售经理', category='销售序列', department_id='demo-dept-sales', level='M2', status='active', responsibilities='客户拓展、销售预测和团队管理。', requirements='企业客户销售经验。'),
        Position(id='demo-pos-finance', title='薪酬会计', category='专业序列', department_id='demo-dept-finance', level='P3', status='active', responsibilities='工资条核算、社保公积金和薪酬报表。', requirements='财务与薪酬核算经验。'),
    ]
    add_all(positions)

    jobs = [
        Job(id='demo-job-backend', title='后端工程师', description='负责 HRM 核心业务后端服务、数据库设计与接口稳定性。', status='open', scoring_criteria={'专业技能': 40, '项目经验': 30, '沟通协作': 20, '稳定性': 10}, category='技术', department='研发部', department_id='demo-dept-rd', level='P3', responsibilities='设计后端服务、优化查询性能、保障交付质量。', requirements='3 年以上后端经验，熟悉 Python/Java 和 SQL。', headcount=2, location='上海', employment_type='全职', salary_range='25k-35k', created_by='demo-user-recruiter', updated_by='demo-user-recruiter', created_at=dt('2026-05-03T09:00:00'), updated_at=dt('2026-05-20T10:00:00')),
        Job(id='demo-job-electronics', title='电子工程师', description='负责智能硬件控制板、电源与传感器模块设计，推进样机验证、EMC整改和量产问题闭环。', status='open', scoring_criteria={'硬件设计': 35, '调试验证': 25, '量产经验': 20, '协同沟通': 20}, category='技术', department='研发部', department_id='demo-dept-rd', level='P3', responsibilities='原理图设计、PCB评审、样机Bring-up、硬件测试与供应链问题定位。', requirements='3年以上电子硬件经验，熟悉模拟/数字电路、EMC、可靠性测试和量产导入。', headcount=2, location='上海', employment_type='全职', salary_range='22k-34k', created_by='demo-user-recruiter', updated_by='demo-user-recruiter', created_at=dt('2026-05-18T09:00:00'), updated_at=dt('2026-05-30T10:00:00')),
        Job(id='demo-job-product', title='产品经理', description='负责招聘与员工管理模块的需求设计、流程优化和数据指标。', status='open', scoring_criteria={'产品能力': 45, '业务理解': 30, '数据分析': 15, '协作': 10}, category='产品', department='产品部', department_id='demo-dept-product', level='P3', responsibilities='沉淀需求、推动研发、验收上线。', requirements='B 端 SaaS 产品经验，熟悉 HR 场景优先。', headcount=1, location='杭州', employment_type='全职', salary_range='22k-32k', created_by='demo-user-recruiter', updated_by='demo-user-recruiter', created_at=dt('2026-05-05T09:00:00'), updated_at=dt('2026-05-22T11:00:00')),
        Job(id='demo-job-sales', title='销售经理', description='负责重点客户开拓和销售团队过程管理。', status='closed', scoring_criteria={'客户开拓': 40, '成交经验': 30, '团队管理': 20, '行业理解': 10}, category='销售', department='销售部', department_id='demo-dept-sales', level='M2', responsibilities='客户拜访、商机推进、合同回款。', requirements='5 年以上企业客户销售经验。', headcount=1, location='北京', employment_type='全职', salary_range='20k-30k', created_by='demo-user-recruiter', updated_by='demo-user-recruiter', created_at=dt('2026-04-15T09:00:00'), updated_at=dt('2026-05-15T18:00:00')),
    ]
    add_all(jobs)

    resumes = [
        Resume(id='demo-resume-sunye', job_id='demo-job-product', candidate_name='孙悦', email='sunye@example.com', phone='13900001001', file_url='/uploads/demo-sunye.pdf', ai_analysis={'score': 92, 'summary': '熟悉 B 端产品闭环，有招聘系统经验。', 'strengths': ['业务抽象', '跨团队推进']}, tags=['产品', 'B端', '高匹配'], created_by='demo-user-recruiter', updated_by='demo-user-recruiter', created_at=dt('2026-05-08T10:00:00')),
        Resume(id='demo-resume-zhaoliu', job_id='demo-job-backend', candidate_name='赵六', email='zhaoliu@example.com', phone='13900001002', file_url='/uploads/demo-zhaoliu.pdf', ai_analysis={'score': 86, 'summary': '后端基础扎实，接口治理经验较多。', 'strengths': ['数据库优化', '服务稳定性']}, tags=['后端', 'Python'], created_by='demo-user-recruiter', updated_by='demo-user-recruiter', created_at=dt('2026-05-10T10:00:00')),
        Resume(id='demo-resume-denghao', job_id='demo-job-electronics', candidate_name='邓浩', email='denghao@example.com', phone='13900002001', file_url='/uploads/demo-denghao.pdf', ai_analysis={'score': 91, 'matchDegree': 94, 'summary': '主导过智能硬件控制板从样机到小批量量产，硬件调试和EMC整改经验完整。', 'strengths': ['模拟/数字电路设计', 'EMC整改', '量产导入'], 'weaknesses': ['团队管理经验较少'], 'recommendation': '优先推进终面和薪酬沟通', 'interviewFocus': ['量产问题闭环案例', '电源完整性分析', '跨部门协作方式']}, tags=['电子硬件', '高匹配', '量产'], created_by='demo-user-recruiter', updated_by='demo-user-recruiter', created_at=dt('2026-05-22T10:00:00')),
        Resume(id='demo-resume-yanglin', job_id='demo-job-electronics', candidate_name='杨琳', email='yanglin@example.com', phone='13900002002', file_url='/uploads/demo-yanglin.pdf', ai_analysis={'score': 84, 'matchDegree': 88, 'summary': '传感器与低功耗电路经验较强，量产导入经验中等。', 'strengths': ['传感器调试', '低功耗设计', '测试规范'], 'weaknesses': ['EMC整改项目较少'], 'recommendation': '建议进入二面，重点验证EMC和量产经验', 'interviewFocus': ['EMC整改方法', '供应链问题定位', '可靠性测试']}, tags=['电子硬件', '传感器', '二面'], created_by='demo-user-recruiter', updated_by='demo-user-recruiter', created_at=dt('2026-05-24T10:00:00')),
        Resume(id='demo-resume-luowei', job_id='demo-job-electronics', candidate_name='罗伟', email='luowei@example.com', phone='13900002003', file_url='/uploads/demo-luowei.pdf', ai_analysis={'score': 76, 'matchDegree': 72, 'summary': '硬件测试背景扎实，独立硬件方案设计经验偏少。', 'strengths': ['硬件测试', '问题复现', '文档规范'], 'weaknesses': ['原理图设计经验不足', '量产主导经历不足'], 'recommendation': '作为备选，先做技术加试', 'interviewFocus': ['独立设计能力', '复杂故障定位', '项目 ownership']}, tags=['电子硬件', '待观察'], created_by='demo-user-recruiter', updated_by='demo-user-recruiter', created_at=dt('2026-05-26T10:00:00')),
        Resume(id='demo-resume-qianqi', job_id='demo-job-sales', candidate_name='钱七', email='qianqi@example.com', phone='13900001003', file_url='/uploads/demo-qianqi.pdf', ai_analysis={'score': 78, 'summary': '销售经验丰富，但 HR SaaS 行业经验一般。'}, tags=['销售', '待观察'], created_by='demo-user-recruiter', updated_by='demo-user-recruiter', created_at=dt('2026-05-12T10:00:00')),
        Resume(id='demo-resume-wuminghua', job_id='demo-job-backend', candidate_name='吴明华', email='wuminghua@example.com', phone='13900001004', file_url='/uploads/demo-wuminghua.pdf', ai_analysis={'score': 89, 'summary': '后端平台经验完整，适合核心服务治理岗位。', 'strengths': ['平台治理', '稳定性建设']}, tags=['后端', '全生命周期'], created_by='demo-user-recruiter', updated_by='demo-user-recruiter', created_at=dt('2025-11-20T10:00:00')),
    ]
    add_all(resumes)

    candidates = [
        Candidate(id='demo-cand-sunye', resume_id='demo-resume-sunye', job_id='demo-job-product', name='孙悦', email='sunye@example.com', phone='13900001001', status='converted', source='Boss直聘', tags=['产品', '已转员工'], match_records=[{'jobId': 'demo-job-product', 'score': 92}], ai_summary='已接受 Offer 并进入入职流程。', ai_recommendation='建议重点跟进入职材料和产品培训。', owner_id='demo-user-recruiter', remark='候选人已转化为待入职员工。', created_at=dt('2026-05-08T12:00:00')),
        Candidate(id='demo-cand-zhaoliu', resume_id='demo-resume-zhaoliu', job_id='demo-job-backend', name='赵六', email='zhaoliu@example.com', phone='13900001002', status='interview', source='内推', tags=['后端', '二面'], match_records=[{'jobId': 'demo-job-backend', 'score': 86}], ai_summary='技术匹配度高，等待二面结论。', ai_recommendation='建议关注系统设计深度。', owner_id='demo-user-recruiter', remark='下周安排二面。', created_at=dt('2026-05-10T12:00:00')),
        Candidate(id='demo-cand-denghao', resume_id='demo-resume-denghao', job_id='demo-job-electronics', name='邓浩', email='denghao@example.com', phone='13900002001', status='interview', source='内推', tags=['电子硬件', '高匹配', '终面'], match_records=[{'jobId': 'demo-job-electronics', 'score': 94}], ai_summary='硬件方案、EMC整改和量产导入经验完整，是电子工程师岗位当前最强候选。', ai_recommendation='建议优先安排终面并同步薪酬预沟通。', owner_id='demo-user-recruiter', remark='研发负责人建议优先推进。', created_at=dt('2026-05-22T12:00:00')),
        Candidate(id='demo-cand-yanglin', resume_id='demo-resume-yanglin', job_id='demo-job-electronics', name='杨琳', email='yanglin@example.com', phone='13900002002', status='screening', source='Boss直聘', tags=['电子硬件', '二面'], match_records=[{'jobId': 'demo-job-electronics', 'score': 88}], ai_summary='传感器与低功耗方向契合，EMC和量产经验需二面补充验证。', ai_recommendation='建议进入二面，围绕EMC整改和供应链问题定位追问。', owner_id='demo-user-recruiter', remark='适合作为第二优先级。', created_at=dt('2026-05-24T12:00:00')),
        Candidate(id='demo-cand-luowei', resume_id='demo-resume-luowei', job_id='demo-job-electronics', name='罗伟', email='luowei@example.com', phone='13900002003', status='new', source='猎头', tags=['电子硬件', '待观察'], match_records=[{'jobId': 'demo-job-electronics', 'score': 72}], ai_summary='硬件测试和问题复现能力较好，但独立设计和量产主导经验不足。', ai_recommendation='建议作为备选，先安排技术加试。', owner_id='demo-user-recruiter', remark='可作为人才储备。', created_at=dt('2026-05-26T12:00:00')),
        Candidate(id='demo-cand-qianqi', resume_id='demo-resume-qianqi', job_id='demo-job-sales', name='钱七', email='qianqi@example.com', phone='13900001003', status='screening', source='猎头', tags=['销售'], match_records=[{'jobId': 'demo-job-sales', 'score': 78}], ai_summary='销售经验匹配，行业经验需要进一步验证。', ai_recommendation='建议先电话筛选。', owner_id='demo-user-recruiter', remark='销售岗位已关闭，作为人才储备。', created_at=dt('2026-05-12T12:00:00')),
        Candidate(id='demo-cand-wuminghua', resume_id='demo-resume-wuminghua', job_id='demo-job-backend', name='吴明华', email='wuminghua@example.com', phone='13900001004', status='converted', source='内推', tags=['后端', '已离职', '全生命周期'], match_records=[{'jobId': 'demo-job-backend', 'score': 89}], ai_summary='已完成从招聘、入职、在职发展到离职的完整链路。', ai_recommendation='可作为全链路验收样本。', owner_id='demo-user-recruiter', remark='全生命周期演示样本。', created_at=dt('2025-11-20T12:00:00')),
    ]
    add_all(candidates)

    interviews = [
        Interview(id='demo-interview-sunye', job_id='demo-job-product', resume_id='demo-resume-sunye', scheduled_at=dt('2026-05-14T14:00:00'), status='completed', notes='终面通过，进入 Offer。', created_by='demo-user-recruiter', updated_by='demo-user-recruiter', feedback_text='候选人能够清晰说明 B 端需求拆解、指标体系和跨团队协作方法，案例完整。', ai_analysis={'score': 91, 'recommendation': 'strong_hire'}, analyzed_at=dt('2026-05-14T16:00:00'), room_id='demo-room-sunye', invite_token='demo-token-sunye'),
        Interview(id='demo-interview-zhaoliu', job_id='demo-job-backend', resume_id='demo-resume-zhaoliu', scheduled_at=dt('2026-06-03T10:00:00'), status='scheduled', notes='二面重点考察系统设计和数据库优化。', created_by='demo-user-recruiter', updated_by='demo-user-recruiter', room_id='demo-room-zhaoliu', invite_token='demo-token-zhaoliu'),
        Interview(id='demo-interview-denghao-1', job_id='demo-job-electronics', resume_id='demo-resume-denghao', scheduled_at=dt('2026-05-27T10:00:00'), status='completed', notes='一面通过，硬件设计和量产经验充分。', created_by='demo-user-recruiter', updated_by='demo-user-recruiter', feedback_text='能清楚拆解电源噪声、EMC整改和小批量试产问题闭环，建议终面。', ai_analysis={'score': 92, 'recommendation': 'strong_hire'}, analyzed_at=dt('2026-05-27T12:00:00'), room_id='demo-room-denghao-1', invite_token='demo-token-denghao-1'),
        Interview(id='demo-interview-denghao-2', job_id='demo-job-electronics', resume_id='demo-resume-denghao', scheduled_at=dt('2026-06-04T15:00:00'), status='scheduled', notes='终面验证团队协作和量产导入细节。', created_by='demo-user-recruiter', updated_by='demo-user-recruiter', room_id='demo-room-denghao-2', invite_token='demo-token-denghao-2'),
        Interview(id='demo-interview-yanglin', job_id='demo-job-electronics', resume_id='demo-resume-yanglin', scheduled_at=dt('2026-05-30T14:00:00'), status='completed', notes='一面通过，低功耗与传感器调试较强，EMC需复核。', created_by='demo-user-recruiter', updated_by='demo-user-recruiter', feedback_text='低功耗设计经验扎实，但量产整改案例相对有限，建议二面追问。', ai_analysis={'score': 84, 'recommendation': 'next_round'}, analyzed_at=dt('2026-05-30T16:00:00'), room_id='demo-room-yanglin', invite_token='demo-token-yanglin'),
        Interview(id='demo-interview-qianqi', job_id='demo-job-sales', resume_id='demo-resume-qianqi', scheduled_at=dt('2026-05-16T11:00:00'), status='cancelled', notes='岗位关闭，面试取消。', created_by='demo-user-recruiter', updated_by='demo-user-recruiter', room_id='demo-room-qianqi', invite_token='demo-token-qianqi'),
        Interview(id='demo-interview-wuminghua', job_id='demo-job-backend', resume_id='demo-resume-wuminghua', scheduled_at=dt('2025-11-25T15:00:00'), status='completed', notes='技术终面通过，建议发 Offer。', created_by='demo-user-recruiter', updated_by='demo-user-recruiter', feedback_text='平台治理经验扎实，能结合可观测性和容量治理给出落地方案。', ai_analysis={'score': 88, 'recommendation': 'hire'}, analyzed_at=dt('2025-11-25T17:00:00'), room_id='demo-room-wuminghua', invite_token='demo-token-wuminghua'),
    ]
    add_all(interviews)

    offers = [
        Offer(id='demo-offer-sunye', candidate_id='demo-cand-sunye', job_id='demo-job-product', employee_id='demo-emp-product-sunye', title='孙悦-产品经理 Offer', salary=money('30000'), salary_structure={'base': 24000, 'performance': 4000, 'allowance': 2000}, onboarding_date=d('2026-06-10'), work_location='杭州', status='converted', approval_status='approved', accepted_at=dt('2026-05-20T09:30:00'), remark='已接受并转员工。', created_by='demo-user-recruiter', created_at=dt('2026-05-18T10:00:00')),
        Offer(id='demo-offer-zhaoliu', candidate_id='demo-cand-zhaoliu', job_id='demo-job-backend', title='赵六-后端工程师 Offer 草案', salary=money('32000'), salary_structure={'base': 26000, 'performance': 4000, 'allowance': 2000}, onboarding_date=d('2026-06-20'), work_location='上海', status='pending', approval_status='pending', remark='等待薪酬审批。', created_by='demo-user-recruiter', created_at=dt('2026-05-27T10:00:00')),
        Offer(id='demo-offer-wuminghua', candidate_id='demo-cand-wuminghua', job_id='demo-job-backend', employee_id='demo-emp-rd-wuminghua', title='吴明华-后端工程师 Offer', salary=money('28000'), salary_structure={'base': 22000, 'performance': 4000, 'allowance': 2000}, onboarding_date=d('2025-12-15'), work_location='上海', status='converted', approval_status='approved', accepted_at=dt('2025-12-02T10:00:00'), remark='全生命周期样本，已转员工并后续离职。', created_by='demo-user-recruiter', created_at=dt('2025-12-01T10:00:00')),
    ]
    add_all(offers)

    employees = [
        Employee(id='demo-emp-hq-guming', employee_no='DEMO0001', name='顾明', email=f'executive@{DEMO_EMAIL_DOMAIN}', phone='13800000007', gender='男', status='active', department_id='demo-dept-hq', position_id='demo-pos-executive', job_title='总经理', hire_date=d('2021-01-01'), probation_months=0, probation_end_date=d('2021-01-01'), id_no='310101198001010011', address='上海市浦东新区演示路 1 号', emergency_contact='顾太太 13900000007', remark='演示高管账号。'),
        Employee(id='demo-emp-hr-linyao', employee_no='DEMO0002', name='林瑶', email=f'hr@{DEMO_EMAIL_DOMAIN}', phone='13800000002', gender='女', status='active', department_id='demo-dept-hr', position_id='demo-pos-hrbp', job_title='HRBP', manager_id='demo-emp-hq-guming', hire_date=d('2022-03-01'), probation_months=3, probation_end_date=d('2022-06-01'), id_no='310101198803030022', address='上海市徐汇区演示路 2 号', emergency_contact='林先生 13900000002', remark='HR 管理员。'),
        Employee(id='demo-emp-hr-zhouke', employee_no='DEMO0003', name='周可', email=f'recruiter@{DEMO_EMAIL_DOMAIN}', phone='13800000003', gender='女', status='active', department_id='demo-dept-hr', position_id='demo-pos-recruiter', job_title='招聘专员', manager_id='demo-emp-hr-linyao', hire_date=d('2023-05-10'), probation_months=3, probation_end_date=d('2023-08-10'), remark='负责招聘流程。'),
        Employee(id='demo-emp-rd-chenyu', employee_no='DEMO0004', name='陈宇', email=f'rd.manager@{DEMO_EMAIL_DOMAIN}', phone='13800000004', gender='男', status='active', department_id='demo-dept-rd', position_id='demo-pos-backend', job_title='研发经理', manager_id='demo-emp-hq-guming', hire_date=d('2020-07-15'), probation_months=0, probation_end_date=d('2020-07-15'), remark='研发部门负责人。'),
        Employee(id='demo-emp-rd-zhangsan', employee_no='DEMO0005', name='张三', email=f'employee@{DEMO_EMAIL_DOMAIN}', phone='13800000005', gender='男', status='active', department_id='demo-dept-rd', position_id='demo-pos-backend', job_title='高级后端工程师', manager_id='demo-emp-rd-chenyu', hire_date=d('2024-02-18'), probation_months=3, probation_end_date=d('2024-05-18'), remark='绩效 A，参与调薪演示。'),
        Employee(id='demo-emp-rd-lisi', employee_no='DEMO0006', name='李四', email='lisi@hengpintong.demo', phone='13800000009', gender='女', status='probation', department_id='demo-dept-rd', position_id='demo-pos-qa', job_title='测试工程师', manager_id='demo-emp-rd-chenyu', hire_date=d('2026-03-01'), probation_months=3, probation_end_date=d('2026-06-01'), remark='转正审批待处理。'),
        Employee(id='demo-emp-sales-wangwu', employee_no='DEMO0007', name='王五', email='wangwu@hengpintong.demo', phone='13800000010', gender='男', status='active', department_id='demo-dept-sales', position_id='demo-pos-sales-manager', job_title='销售经理', manager_id='demo-emp-hq-guming', hire_date=d('2023-09-01'), probation_months=3, probation_end_date=d('2023-12-01'), remark='有部门变更审批演示。'),
        Employee(id='demo-emp-finance-zhaomin', employee_no='DEMO0008', name='赵敏', email=f'finance@{DEMO_EMAIL_DOMAIN}', phone='13800000006', gender='女', status='active', department_id='demo-dept-finance', position_id='demo-pos-finance', job_title='薪酬会计', manager_id='demo-emp-hq-guming', hire_date=d('2022-11-01'), probation_months=3, probation_end_date=d('2023-02-01'), remark='财务账号。'),
        Employee(id='demo-emp-product-sunye', employee_no='DEMO0009', name='孙悦', email='sunye@example.com', phone='13900001001', gender='女', status='pending_onboard', department_id='demo-dept-product', position_id='demo-pos-product', job_title='产品经理', manager_id='demo-emp-hq-guming', hire_date=d('2026-06-10'), probation_months=3, probation_end_date=d('2026-09-10'), source_offer_id='demo-offer-sunye', candidate_id='demo-cand-sunye', remark='由候选人转员工，等待入职。'),
        Employee(id='demo-emp-sales-liuna', employee_no='DEMO0010', name='刘娜', email='liuna@hengpintong.demo', phone='13800000011', gender='女', status='resigned', department_id='demo-dept-sales', position_id='demo-pos-sales-manager', job_title='客户经理', manager_id='demo-emp-sales-wangwu', hire_date=d('2022-06-01'), probation_months=3, probation_end_date=d('2022-09-01'), remark='离职流程演示。'),
        Employee(id='demo-emp-rd-wuminghua', employee_no='DEMO0011', name='吴明华', email='wuminghua@example.com', phone='13900001004', gender='男', status='resigned', department_id='demo-dept-rd', position_id='demo-pos-backend', job_title='后端工程师', manager_id='demo-emp-rd-chenyu', hire_date=d('2025-12-15'), probation_months=3, probation_end_date=d('2026-03-15'), source_offer_id='demo-offer-wuminghua', candidate_id='demo-cand-wuminghua', remark='全生命周期演示：招聘入职、培训、转正、调薪、发薪、离职均已记录。'),
    ]
    add_all(employees)

    onboarding = [
        OnboardingTask(id='demo-onboarding-sunye-1', employee_id='demo-emp-product-sunye', name='收集入职材料', task_type='入职资料', owner_id='demo-user-hr', due_date=d('2026-06-05'), status='processing', materials=['身份证复印件', '银行卡', '学历证明'], remark='候选人已上传身份证，待学历证明。'),
        OnboardingTask(id='demo-onboarding-sunye-2', employee_id='demo-emp-product-sunye', name='开通系统账号', task_type='IT 账号', owner_id='demo-user-admin', due_date=d('2026-06-08'), status='pending', materials=['邮箱', 'HRM账号', 'IM账号'], remark='入职前两天统一开通。'),
        OnboardingTask(id='demo-onboarding-sunye-3', employee_id='demo-emp-product-sunye', name='安排新人培训', task_type='入职培训', owner_id='demo-user-hr', due_date=d('2026-06-12'), status='pending', materials=['员工手册', '产品培训课'], remark='关联培训计划。'),
        OnboardingTask(id='demo-onboarding-wuminghua-1', employee_id='demo-emp-rd-wuminghua', name='入职资料归档', task_type='入职资料', owner_id='demo-user-hr', due_date=d('2025-12-12'), status='completed', materials=['身份证复印件', '银行卡', '学历证明'], remark='入职资料已归档。'),
        OnboardingTask(id='demo-onboarding-wuminghua-2', employee_id='demo-emp-rd-wuminghua', name='系统账号开通', task_type='IT 账号', owner_id='demo-user-admin', due_date=d('2025-12-14'), status='completed', materials=['邮箱', '代码仓库', 'HRM账号'], remark='账号与权限已开通。'),
        OnboardingTask(id='demo-onboarding-wuminghua-3', employee_id='demo-emp-rd-wuminghua', name='新人培训完成', task_type='入职培训', owner_id='demo-user-hr', due_date=d('2025-12-20'), status='completed', materials=['员工手册', '制度培训'], remark='新人培训已完成。'),
    ]
    add_all(onboarding)

    approvals = [
        ApprovalInstance(id='demo-approval-leave-zhang', business_type='employee_request', business_id='demo-request-leave-zhang', title='张三请假申请', applicant_id='demo-user-employee', approver_id='demo-user-manager-rd', status='approved', submitted_at=dt('2026-05-12T09:00:00'), completed_at=dt('2026-05-12T15:00:00'), remark='请假 1 天。', created_at=dt('2026-05-12T09:00:00')),
        ApprovalInstance(id='demo-approval-overtime-lisi', business_type='employee_request', business_id='demo-request-overtime-lisi', title='李四加班申请', applicant_id='demo-user-employee', approver_id='demo-user-manager-rd', status='pending', submitted_at=dt('2026-05-29T18:30:00'), remark='等待部门负责人审批。', created_at=dt('2026-05-29T18:30:00')),
        ApprovalInstance(id='demo-approval-offer-zhaoliu', business_type='offer', business_id='demo-offer-zhaoliu', title='赵六 Offer 薪酬审批', applicant_id='demo-user-recruiter', approver_id='demo-user-hr', status='pending', submitted_at=dt('2026-05-28T09:00:00'), remark='薪资上限需 HR 复核。', created_at=dt('2026-05-28T09:00:00')),
        ApprovalInstance(id='demo-approval-probation-lisi', business_type='probation', business_id='demo-probation-lisi', title='李四转正审批', applicant_id='demo-user-hr', approver_id='demo-user-manager-rd', status='pending', submitted_at=dt('2026-05-27T09:00:00'), remark='试用期表现稳定，待经理评价。', created_at=dt('2026-05-27T09:00:00')),
        ApprovalInstance(id='demo-approval-change-wangwu', business_type='employee_change', business_id='demo-change-wangwu-transfer', title='王五部门变更审批', applicant_id='demo-user-hr', approver_id='demo-user-executive', status='pending', submitted_at=dt('2026-05-25T09:00:00'), remark='销售组织调整。', created_at=dt('2026-05-25T09:00:00')),
        ApprovalInstance(id='demo-approval-resignation-liuna', business_type='resignation', business_id='demo-resignation-liuna', title='刘娜离职审批', applicant_id='demo-user-hr', approver_id='demo-user-executive', status='approved', submitted_at=dt('2026-05-10T09:00:00'), completed_at=dt('2026-05-16T14:00:00'), remark='交接完整，批准离职。', created_at=dt('2026-05-10T09:00:00')),
        ApprovalInstance(id='demo-approval-offer-wuminghua', business_type='offer', business_id='demo-offer-wuminghua', title='吴明华 Offer 审批', applicant_id='demo-user-recruiter', approver_id='demo-user-hr', status='approved', submitted_at=dt('2025-12-01T11:00:00'), completed_at=dt('2025-12-01T16:00:00'), remark='薪资预算内，批准发放 Offer。', created_at=dt('2025-12-01T11:00:00')),
        ApprovalInstance(id='demo-approval-onboarding-wuminghua', business_type='onboarding', business_id='demo-emp-rd-wuminghua', title='吴明华入职审批', applicant_id='demo-user-hr', approver_id='demo-user-manager-rd', status='approved', submitted_at=dt('2025-12-10T09:00:00'), completed_at=dt('2025-12-12T10:00:00'), remark='入职材料齐全，批准入职。', created_at=dt('2025-12-10T09:00:00')),
        ApprovalInstance(id='demo-approval-probation-wuminghua', business_type='probation', business_id='demo-probation-wuminghua', title='吴明华转正审批', applicant_id='demo-user-hr', approver_id='demo-user-manager-rd', status='approved', submitted_at=dt('2026-03-10T09:00:00'), completed_at=dt('2026-03-12T15:00:00'), remark='试用期目标达成，批准转正。', created_at=dt('2026-03-10T09:00:00')),
        ApprovalInstance(id='demo-approval-change-wuminghua', business_type='employee_change', business_id='demo-change-wuminghua-salary', title='吴明华 Q1 调薪审批', applicant_id='demo-user-hr', approver_id='demo-user-manager-rd', status='approved', submitted_at=dt('2026-04-01T09:00:00'), completed_at=dt('2026-04-02T11:00:00'), remark='绩效 B+，批准调薪。', created_at=dt('2026-04-01T09:00:00')),
        ApprovalInstance(id='demo-approval-resignation-wuminghua', business_type='resignation', business_id='demo-resignation-wuminghua', title='吴明华离职审批', applicant_id='demo-user-hr', approver_id='demo-user-manager-rd', status='approved', submitted_at=dt('2026-05-18T09:00:00'), completed_at=dt('2026-05-20T16:00:00'), remark='交接完成，批准离职。', created_at=dt('2026-05-18T09:00:00')),
    ]
    add_all(approvals)

    approval_records = [
        ApprovalRecord(id='demo-record-leave-zhang', approval_id='demo-approval-leave-zhang', approver_id='demo-user-manager-rd', action='approved', comment='安排好代码评审交接后同意。', created_at=dt('2026-05-12T15:00:00')),
        ApprovalRecord(id='demo-record-resignation-liuna', approval_id='demo-approval-resignation-liuna', approver_id='demo-user-executive', action='approved', comment='客户交接清单已确认，同意离职。', created_at=dt('2026-05-16T14:00:00')),
        ApprovalRecord(id='demo-record-offer-wuminghua', approval_id='demo-approval-offer-wuminghua', approver_id='demo-user-hr', action='approved', comment='批准 Offer。', created_at=dt('2025-12-01T16:00:00')),
        ApprovalRecord(id='demo-record-onboarding-wuminghua', approval_id='demo-approval-onboarding-wuminghua', approver_id='demo-user-manager-rd', action='approved', comment='入职准备完成。', created_at=dt('2025-12-12T10:00:00')),
        ApprovalRecord(id='demo-record-probation-wuminghua', approval_id='demo-approval-probation-wuminghua', approver_id='demo-user-manager-rd', action='approved', comment='同意转正。', created_at=dt('2026-03-12T15:00:00')),
        ApprovalRecord(id='demo-record-change-wuminghua', approval_id='demo-approval-change-wuminghua', approver_id='demo-user-manager-rd', action='approved', comment='同意调薪。', created_at=dt('2026-04-02T11:00:00')),
        ApprovalRecord(id='demo-record-resignation-wuminghua', approval_id='demo-approval-resignation-wuminghua', approver_id='demo-user-manager-rd', action='approved', comment='交接完整，同意离职。', created_at=dt('2026-05-20T16:00:00')),
    ]
    add_all(approval_records)

    probations = [
        Probation(id='demo-probation-lisi', employee_id='demo-emp-rd-lisi', apply_date=d('2026-05-27'), expected_regular_date=d('2026-06-01'), status='pending', self_review='完成自动化回归用例建设，熟悉核心业务流程。', manager_review='质量意识较好，建议加强跨团队沟通。', result='建议转正', approval_id='demo-approval-probation-lisi', remark='等待审批。', created_by='demo-user-hr'),
        Probation(id='demo-probation-zhangsan', employee_id='demo-emp-rd-zhangsan', apply_date=d('2024-05-10'), expected_regular_date=d('2024-05-18'), regular_date=d('2024-05-18'), status='approved', self_review='完成核心服务重构。', manager_review='产出稳定，技术影响力较好。', result='按期转正', remark='历史转正记录。', created_by='demo-user-hr'),
        Probation(id='demo-probation-wuminghua', employee_id='demo-emp-rd-wuminghua', apply_date=d('2026-03-10'), expected_regular_date=d('2026-03-15'), regular_date=d('2026-03-15'), status='approved', self_review='完成平台告警治理和核心链路压测。', manager_review='目标达成，技术沉淀较好。', result='通过转正', approval_id='demo-approval-probation-wuminghua', remark='全生命周期样本转正记录。', created_by='demo-user-hr'),
    ]
    add_all(probations)

    changes = [
        EmployeeChange(id='demo-change-zhangsan-promotion', employee_id='demo-emp-rd-zhangsan', change_type='晋升', before_department_id='demo-dept-rd', after_department_id='demo-dept-rd', before_position_id='demo-pos-backend', after_position_id='demo-pos-backend', before_level='P3', after_level='P4', salary_adjustment=money('3000'), effective_date=d('2026-06-01'), reason='Q2 绩效优秀，承担核心架构职责。', status='effective', created_by='demo-user-hr', created_at=dt('2026-05-24T10:00:00')),
        EmployeeChange(id='demo-change-wangwu-transfer', employee_id='demo-emp-sales-wangwu', change_type='部门变更', before_department_id='demo-dept-sales', after_department_id='demo-dept-product', before_position_id='demo-pos-sales-manager', after_position_id='demo-pos-product', before_level='M2', after_level='P3', salary_adjustment=money('0'), effective_date=d('2026-06-15'), reason='转入产品部负责客户成功产品化。', status='pending', created_by='demo-user-hr', created_at=dt('2026-05-25T10:00:00')),
        EmployeeChange(id='demo-change-lisi-salary', employee_id='demo-emp-rd-lisi', change_type='调薪', before_department_id='demo-dept-rd', after_department_id='demo-dept-rd', before_position_id='demo-pos-qa', after_position_id='demo-pos-qa', before_level='P2', after_level='P2', salary_adjustment=money('1200'), effective_date=d('2026-06-01'), reason='转正后薪资调整预留。', status='draft', created_by='demo-user-hr', created_at=dt('2026-05-27T10:00:00')),
        EmployeeChange(id='demo-change-wuminghua-salary', employee_id='demo-emp-rd-wuminghua', change_type='调薪', before_department_id='demo-dept-rd', after_department_id='demo-dept-rd', before_position_id='demo-pos-backend', after_position_id='demo-pos-backend', before_level='P3', after_level='P3', salary_adjustment=money('1500'), effective_date=d('2026-04-01'), reason='转正后 Q1 绩效达标调薪。', status='approved', created_by='demo-user-hr', created_at=dt('2026-04-01T10:00:00')),
    ]
    add_all(changes)

    resignations = [
        Resignation(id='demo-resignation-liuna', employee_id='demo-emp-sales-liuna', apply_date=d('2026-05-08'), expected_leave_date=d('2026-05-31'), actual_leave_date=d('2026-05-31'), reason='个人职业规划调整。', handover_items=['客户清单', '合同状态', '回款跟进'], status='approved', approval_id='demo-approval-resignation-liuna', ai_summary='离职风险低，主要为个人发展原因；客户交接已完成。', created_by='demo-user-hr', created_at=dt('2026-05-08T10:00:00')),
        Resignation(id='demo-resignation-wuminghua', employee_id='demo-emp-rd-wuminghua', apply_date=d('2026-05-18'), expected_leave_date=d('2026-05-31'), actual_leave_date=d('2026-05-31'), reason='回老家发展，已完成代码、文档和监控交接。', handover_items=['服务治理文档', '告警规则', '压测报告', '待办清单'], status='approved', approval_id='demo-approval-resignation-wuminghua', ai_summary='完整交接，离职原因以个人城市选择为主，组织风险低。', created_by='demo-user-hr', created_at=dt('2026-05-18T10:00:00')),
    ]
    add_all(resignations)

    contracts = [
        Contract(id='demo-contract-zhangsan', employee_id='demo-emp-rd-zhangsan', contract_no='HT-DEMO-2024-0005', contract_type='固定期限劳动合同', start_date=d('2024-02-18'), end_date=d('2027-02-17'), status='active', reminder_date=d('2026-12-17'), attachment_url='/uploads/demo-contract-zhangsan.pdf', remark='续签提醒提前 60 天。'),
        Contract(id='demo-contract-lisi', employee_id='demo-emp-rd-lisi', contract_no='HT-DEMO-2026-0006', contract_type='固定期限劳动合同', start_date=d('2026-03-01'), end_date=d('2029-02-28'), status='active', reminder_date=d('2028-12-30'), attachment_url='/uploads/demo-contract-lisi.pdf', remark='试用期合同。'),
        Contract(id='demo-contract-sunye', employee_id='demo-emp-product-sunye', contract_no='HT-DEMO-2026-0009', contract_type='劳动合同草案', start_date=d('2026-06-10'), end_date=d('2029-06-09'), status='draft', reminder_date=d('2029-04-10'), attachment_url='/uploads/demo-contract-sunye.pdf', remark='待入职签署。'),
        Contract(id='demo-contract-wuminghua', employee_id='demo-emp-rd-wuminghua', contract_no='HT-DEMO-2025-0011', contract_type='固定期限劳动合同', start_date=d('2025-12-15'), end_date=d('2028-12-14'), status='terminated', reminder_date=d('2028-10-15'), attachment_url='/uploads/demo-contract-wuminghua.pdf', remark='2026-05-31 离职终止。'),
    ]
    add_all(contracts)

    attendance = [
        AttendanceRecord(id='demo-att-zhang-0527', employee_id='demo-emp-rd-zhangsan', attendance_date=d('2026-05-27'), check_in_time=dt('2026-05-27T09:01:00'), check_out_time=dt('2026-05-27T18:30:00'), work_hours=money('8.5'), status='normal', source='dingtalk', remark='正常出勤'),
        AttendanceRecord(id='demo-att-zhang-0528', employee_id='demo-emp-rd-zhangsan', attendance_date=d('2026-05-28'), check_in_time=dt('2026-05-28T09:35:00'), check_out_time=dt('2026-05-28T18:20:00'), work_hours=money('7.8'), status='late', source='dingtalk', remark='早高峰迟到'),
        AttendanceRecord(id='demo-att-lisi-0528', employee_id='demo-emp-rd-lisi', attendance_date=d('2026-05-28'), check_in_time=dt('2026-05-28T09:00:00'), work_hours=money('4'), status='missing_card', source='manual', remark='忘记下班打卡，已提交补卡'),
        AttendanceRecord(id='demo-att-wang-0528', employee_id='demo-emp-sales-wangwu', attendance_date=d('2026-05-28'), work_hours=money('8'), status='normal', source='manual', remark='客户拜访外勤，出差申请已审批'),
        AttendanceRecord(id='demo-att-zhao-0528', employee_id='demo-emp-finance-zhaomin', attendance_date=d('2026-05-28'), check_in_time=dt('2026-05-28T08:55:00'), check_out_time=dt('2026-05-28T18:10:00'), work_hours=money('8.2'), status='normal', source='dingtalk', remark='正常出勤'),
        AttendanceRecord(id='demo-att-chen-0528', employee_id='demo-emp-rd-chenyu', attendance_date=d('2026-05-28'), check_in_time=dt('2026-05-28T09:00:00'), check_out_time=dt('2026-05-28T21:00:00'), work_hours=money('11'), status='overtime', source='manual', remark='上线保障加班'),
        AttendanceRecord(id='demo-att-wuminghua-0527', employee_id='demo-emp-rd-wuminghua', attendance_date=d('2026-05-27'), check_in_time=dt('2026-05-27T09:05:00'), check_out_time=dt('2026-05-27T18:30:00'), work_hours=money('8.3'), status='normal', source='dingtalk', remark='离职交接期正常出勤'),
        AttendanceRecord(id='demo-att-wuminghua-0528', employee_id='demo-emp-rd-wuminghua', attendance_date=d('2026-05-28'), check_in_time=dt('2026-05-28T09:20:00'), check_out_time=dt('2026-05-28T20:00:00'), work_hours=money('9.5'), status='overtime', source='manual', remark='交接文档整理加班'),
        AttendanceRecord(id='demo-att-linyao-0601', employee_id='demo-emp-hr-linyao', attendance_date=d('2026-06-01'), check_in_time=dt('2026-06-01T09:08:00'), check_out_time=dt('2026-06-01T18:12:00'), work_hours=money('8.1'), status='late', source='dingtalk', remark='月初晨会迟到'),
        AttendanceRecord(id='demo-att-zhang-0601', employee_id='demo-emp-rd-zhangsan', attendance_date=d('2026-06-01'), check_in_time=dt('2026-06-01T08:58:00'), check_out_time=dt('2026-06-01T18:45:00'), work_hours=money('8.8'), status='normal', source='dingtalk', remark='正常出勤'),
        AttendanceRecord(id='demo-att-lisi-0601', employee_id='demo-emp-rd-lisi', attendance_date=d('2026-06-01'), check_in_time=dt('2026-06-01T09:00:00'), work_hours=money('4'), status='missing_card', source='manual', remark='忘记下班打卡，已提醒补卡'),
        AttendanceRecord(id='demo-att-wang-0601', employee_id='demo-emp-sales-wangwu', attendance_date=d('2026-06-01'), check_in_time=dt('2026-06-01T09:10:00'), check_out_time=dt('2026-06-01T18:20:00'), work_hours=money('8'), status='normal', source='manual', remark='外勤拜访后回公司补录'),
        AttendanceRecord(id='demo-att-zhao-0601', employee_id='demo-emp-finance-zhaomin', attendance_date=d('2026-06-01'), check_in_time=dt('2026-06-01T08:55:00'), check_out_time=dt('2026-06-01T18:05:00'), work_hours=money('8.1'), status='normal', source='dingtalk', remark='正常出勤'),
        AttendanceRecord(id='demo-att-chen-0601', employee_id='demo-emp-rd-chenyu', attendance_date=d('2026-06-01'), check_in_time=dt('2026-06-01T09:00:00'), check_out_time=dt('2026-06-01T20:30:00'), work_hours=money('10.5'), status='overtime', source='manual', remark='版本排期评审加班'),
    ]
    add_all(attendance)

    requests = [
        EmployeeRequest(id='demo-request-leave-zhang', employee_id='demo-emp-rd-zhangsan', request_type='leave', title='张三 5月请假', start_time=dt('2026-05-13T09:00:00'), end_time=dt('2026-05-13T18:00:00'), duration_hours=money('8'), reason='家中事务处理。', status='approved', approval_id='demo-approval-leave-zhang', created_by='demo-user-employee', created_at=dt('2026-05-12T09:00:00')),
        EmployeeRequest(id='demo-request-overtime-lisi', employee_id='demo-emp-rd-lisi', request_type='overtime', title='李四 回归测试加班', start_time=dt('2026-05-29T19:00:00'), end_time=dt('2026-05-29T22:00:00'), duration_hours=money('3'), reason='版本发布前回归测试。', status='pending', approval_id='demo-approval-overtime-lisi', created_by='demo-user-employee', created_at=dt('2026-05-29T18:30:00')),
        EmployeeRequest(id='demo-request-travel-wang', employee_id='demo-emp-sales-wangwu', request_type='travel', title='王五 客户拜访出差', start_time=dt('2026-05-28T09:00:00'), end_time=dt('2026-05-28T18:00:00'), duration_hours=money('8'), reason='拜访重点客户。', status='approved', created_by='demo-user-hr', created_at=dt('2026-05-27T17:00:00')),
        EmployeeRequest(id='demo-request-makeup-lisi', employee_id='demo-emp-rd-lisi', request_type='makeup_card', title='李四 补卡申请', start_time=dt('2026-05-28T18:00:00'), end_time=dt('2026-05-28T18:00:00'), duration_hours=money('0'), reason='忘记下班打卡。', status='draft', created_by='demo-user-employee', created_at=dt('2026-05-28T19:00:00')),
        EmployeeRequest(id='demo-request-overtime-wuminghua', employee_id='demo-emp-rd-wuminghua', request_type='overtime', title='吴明华 离职交接加班', start_time=dt('2026-05-28T18:30:00'), end_time=dt('2026-05-28T20:00:00'), duration_hours=money('1.5'), reason='补充服务治理交接文档。', status='approved', created_by='demo-user-hr', created_at=dt('2026-05-28T18:00:00')),
    ]
    add_all(requests)

    performance_cycle = PerformanceCycle(id='demo-cycle-2026-q2', name='2026 Q2 绩效周期', cycle_type='季度', start_date=d('2026-04-01'), end_date=d('2026-06-30'), status='active', remark='Q2 绩效评估演示周期。')
    performance_template = PerformanceTemplate(id='demo-template-tech', name='技术与协作绩效模板', template_type='通用', indicators=['目标达成', '质量效率', '协作影响', '成长改进'], status='active', remark='适用于研发、产品、职能团队。')
    add_all([performance_cycle, performance_template])

    performance_reviews = [
        PerformanceReview(id='demo-review-zhangsan', employee_id='demo-emp-rd-zhangsan', cycle_id='demo-cycle-2026-q2', template_id='demo-template-tech', self_review='完成核心服务重构和薪酬链路优化。', self_score=money('91'), manager_score=money('94'), final_score=money('93'), grade='A', result='建议晋升并调薪。', remark='已生成晋升异动记录。', status='completed'),
        PerformanceReview(id='demo-review-lisi', employee_id='demo-emp-rd-lisi', cycle_id='demo-cycle-2026-q2', template_id='demo-template-tech', self_review='完成自动化回归框架初版。', self_score=money('82'), manager_score=money('80'), final_score=money('81'), grade='B', result='建议转正后继续提升自动化覆盖。', remark='关联转正和培训计划。', status='completed'),
        PerformanceReview(id='demo-review-wangwu', employee_id='demo-emp-sales-wangwu', cycle_id='demo-cycle-2026-q2', template_id='demo-template-tech', self_review='推进客户成功产品化线索。', self_score=money('76'), manager_score=money('78'), final_score=money('77'), grade='C', result='建议转入产品团队沉淀客户需求。', remark='关联部门变更审批。', status='published'),
        PerformanceReview(id='demo-review-zhaomin', employee_id='demo-emp-finance-zhaomin', cycle_id='demo-cycle-2026-q2', template_id='demo-template-tech', self_review='按期完成工资条核算。', self_score=money('88'), manager_score=money('87'), final_score=money('87'), grade='B', result='薪酬发放稳定。', remark='财务核算准确。', status='completed'),
        PerformanceReview(id='demo-review-wuminghua', employee_id='demo-emp-rd-wuminghua', cycle_id='demo-cycle-2026-q2', template_id='demo-template-tech', self_review='完成服务治理文档和离职交接。', self_score=money('86'), manager_score=money('84'), final_score=money('85'), grade='B', result='交接完整，建议沉淀平台治理经验。', remark='全生命周期样本绩效记录。', status='completed'),
    ]
    add_all(performance_reviews)

    salary_profiles = [
        SalaryProfile(id='demo-salary-zhangsan', employee_id='demo-emp-rd-zhangsan', base_salary=money('22000'), position_salary=money('6000'), performance_salary=money('4000'), allowance=money('1000'), bonus=money('3000'), deduction=money('500'), currency='CNY', status='active', remark='晋升后薪资结构。'),
        SalaryProfile(id='demo-salary-lisi', employee_id='demo-emp-rd-lisi', base_salary=money('12000'), position_salary=money('2500'), performance_salary=money('1500'), allowance=money('800'), bonus=money('0'), deduction=money('300'), currency='CNY', status='active', remark='试用期薪资。'),
        SalaryProfile(id='demo-salary-wangwu', employee_id='demo-emp-sales-wangwu', base_salary=money('16000'), position_salary=money('3000'), performance_salary=money('3000'), allowance=money('1000'), bonus=money('5000'), deduction=money('600'), currency='CNY', status='active', remark='销售奖金浮动。'),
        SalaryProfile(id='demo-salary-zhaomin', employee_id='demo-emp-finance-zhaomin', base_salary=money('15000'), position_salary=money('3000'), performance_salary=money('2500'), allowance=money('800'), bonus=money('1000'), deduction=money('500'), currency='CNY', status='active', remark='财务岗位薪资。'),
        SalaryProfile(id='demo-salary-sunye', employee_id='demo-emp-product-sunye', base_salary=money('24000'), position_salary=money('4000'), performance_salary=money('3000'), allowance=money('2000'), bonus=money('0'), deduction=money('0'), currency='CNY', status='active', remark='Offer 转入薪资档案。'),
        SalaryProfile(id='demo-salary-wuminghua', employee_id='demo-emp-rd-wuminghua', base_salary=money('22000'), position_salary=money('4000'), performance_salary=money('3000'), allowance=money('1200'), bonus=money('1500'), deduction=money('500'), currency='CNY', status='inactive', remark='Offer 转入薪资档案；离职后停用。'),
    ]
    add_all(salary_profiles)

    payrolls = [
        PayrollRecord(id='demo-payroll-zhangsan-202605', employee_id='demo-emp-rd-zhangsan', payroll_month='2026-05', base_salary=money('22000'), position_salary=money('6000'), performance_salary=money('4000'), bonus=money('3000'), allowance=money('1000'), deduction=money('1450'), gross_salary=money('36000'), net_salary=money('34550'), status='paid', employee_visible=True, remark='含晋升奖金。'),
        PayrollRecord(id='demo-payroll-lisi-202605', employee_id='demo-emp-rd-lisi', payroll_month='2026-05', base_salary=money('12000'), position_salary=money('2500'), performance_salary=money('1500'), bonus=money('0'), allowance=money('800'), deduction=money('650'), gross_salary=money('16800'), net_salary=money('16150'), status='calculated', employee_visible=False, remark='转正前工资条。'),
        PayrollRecord(id='demo-payroll-wangwu-202605', employee_id='demo-emp-sales-wangwu', payroll_month='2026-05', base_salary=money('16000'), position_salary=money('3000'), performance_salary=money('3000'), bonus=money('5000'), allowance=money('1000'), deduction=money('1200'), gross_salary=money('28000'), net_salary=money('26800'), status='paid', employee_visible=True, remark='含销售奖金。'),
        PayrollRecord(id='demo-payroll-zhaomin-202605', employee_id='demo-emp-finance-zhaomin', payroll_month='2026-05', base_salary=money('15000'), position_salary=money('3000'), performance_salary=money('2500'), bonus=money('1000'), allowance=money('800'), deduction=money('900'), gross_salary=money('22300'), net_salary=money('21400'), status='paid', employee_visible=True, remark='财务月度工资条。'),
        PayrollRecord(id='demo-payroll-wuminghua-202605', employee_id='demo-emp-rd-wuminghua', payroll_month='2026-05', base_salary=money('22000'), position_salary=money('4000'), performance_salary=money('3000'), bonus=money('1800'), allowance=money('1200'), deduction=money('500'), gross_salary=money('32000'), net_salary=money('31500'), status='paid', employee_visible=True, remark='离职当月工资条，含交接加班。'),
    ]
    add_all(payrolls)

    courses = [
        TrainingCourse(id='demo-course-onboarding', name='新人入职与制度培训', category='入职培训', lecturer='林瑶', duration_hours=money('4'), description='覆盖公司制度、考勤申请、审批和信息安全。', status='active'),
        TrainingCourse(id='demo-course-quality', name='质量效率提升训练营', category='专业能力', lecturer='陈宇', duration_hours=money('8'), description='面向研发与测试团队，提升自动化和发布质量。', status='active'),
        TrainingCourse(id='demo-course-leadership', name='管理者绩效沟通工作坊', category='管理能力', lecturer='顾明', duration_hours=money('6'), description='提升绩效反馈、目标设定和员工发展沟通能力。', status='active'),
    ]
    add_all(courses)

    plans = [
        TrainingPlan(id='demo-plan-onboarding-june', name='2026年6月新人入职培训', course_id='demo-course-onboarding', start_time=dt('2026-06-11T09:30:00'), end_time=dt('2026-06-11T12:00:00'), target_departments=['产品部', '人力资源部'], status='planned', remark='孙悦入职后参加。'),
        TrainingPlan(id='demo-plan-quality-q2', name='Q2 质量效率提升计划', course_id='demo-course-quality', start_time=dt('2026-06-05T14:00:00'), end_time=dt('2026-06-05T18:00:00'), target_departments=['研发部'], status='active', remark='由绩效评估触发。'),
        TrainingPlan(id='demo-plan-leadership-q2', name='Q2 管理者绩效沟通', course_id='demo-course-leadership', start_time=dt('2026-06-18T14:00:00'), end_time=dt('2026-06-18T17:00:00'), target_departments=['总部办公室', '研发部', '销售部'], status='planned', remark='提升管理者绩效沟通质量。'),
    ]
    add_all(plans)

    training_records = [
        TrainingRecord(id='demo-training-sunye-onboarding', plan_id='demo-plan-onboarding-june', course_id='demo-course-onboarding', employee_id='demo-emp-product-sunye', status='registered', result='待参加', score=None, feedback='入职后参加新人培训。'),
        TrainingRecord(id='demo-training-lisi-quality', plan_id='demo-plan-quality-q2', course_id='demo-course-quality', employee_id='demo-emp-rd-lisi', status='attended', result='已参加，待考试', score=money('82'), feedback='建议继续补充接口自动化实践。'),
        TrainingRecord(id='demo-training-zhang-quality', plan_id='demo-plan-quality-q2', course_id='demo-course-quality', employee_id='demo-emp-rd-zhangsan', status='completed', result='通过', score=money('94'), feedback='可担任后续分享讲师。'),
        TrainingRecord(id='demo-training-chen-leadership', plan_id='demo-plan-leadership-q2', course_id='demo-course-leadership', employee_id='demo-emp-rd-chenyu', status='registered', result='待参加', score=None, feedback='部门负责人必修。'),
        TrainingRecord(id='demo-training-wuminghua-onboarding', plan_id='demo-plan-onboarding-june', course_id='demo-course-onboarding', employee_id='demo-emp-rd-wuminghua', status='completed', result='通过', score=money('90'), feedback='新人制度和信息安全培训已完成。'),
        TrainingRecord(id='demo-training-wuminghua-quality', plan_id='demo-plan-quality-q2', course_id='demo-course-quality', employee_id='demo-emp-rd-wuminghua', status='completed', result='通过', score=money('88'), feedback='服务治理经验可沉淀为团队案例。'),
    ]
    add_all(training_records)

    feedbacks = [
        Feedback(id='demo-feedback-bug-attendance', user_id='demo-user-employee', feedback_type='bug', severity='high', title='考勤统计移动端表格溢出', content='在小屏幕查看考勤统计时，表格横向滚动不明显。', page_url='/attendance-stats', user_agent='Demo Browser', status='pending', handler_id='demo-user-hr'),
        Feedback(id='demo-feedback-feature-payroll-export', user_id='demo-user-finance', feedback_type='feature', severity='medium', title='工资条希望增加批量导出', content='财务每月需要导出工资条给归档系统。', page_url='/hrm/payroll-records', user_agent='Demo Browser', status='in_progress', handler_id='demo-user-admin', handler_reply='已排入薪酬模块优化清单。'),
        Feedback(id='demo-feedback-other-copy', user_id='demo-user-viewer', feedback_type='other', severity='low', title='审批提示文案优化', content='希望审批中心明确提示 AI 不会自动审批。', page_url='/approval-center/pending', user_agent='Demo Browser', status='resolved', handler_id='demo-user-hr', handler_reply='已更新提示文案。', handled_at=dt('2026-05-30T10:00:00')),
    ]
    add_all(feedbacks)

    notifications = [
        Notification(id='demo-notify-global-hrm-ready', user_id=None, title='演示数据已完成全模块联通', content='当前环境已加载招聘、员工、考勤、审批、绩效、薪酬、培训、通知与反馈演示链路。', notice_type='system', status='unread', link_url='/home', created_at=dt('2026-06-01T08:55:00')),
        Notification(id='demo-notify-hr-offer', user_id='demo-user-hr', title='赵六 Offer 待审批', content='后端工程师候选人赵六的 Offer 薪酬方案等待复核。', notice_type='approval', status='unread', link_url='/approval-center/pending', created_at=dt('2026-05-28T09:10:00')),
        Notification(id='demo-notify-manager-probation', user_id='demo-user-manager-rd', title='李四转正审批待处理', content='李四试用期即将结束，请完成转正审批。', notice_type='hr', status='unread', link_url='/approval-center/pending', created_at=dt('2026-05-27T09:10:00')),
        Notification(id='demo-notify-employee-payroll', user_id='demo-user-employee', title='2026-05 工资条已发布', content='您的 2026-05 工资条已开放查看。', notice_type='payroll', status='read', link_url='/hrm/payroll-records', created_at=dt('2026-05-31T18:00:00'), read_at=dt('2026-05-31T20:00:00')),
        Notification(id='demo-notify-sunye-onboarding', user_id='demo-user-hr', title='孙悦入职任务待推进', content='孙悦预计 2026-06-10 入职，请跟进材料与系统账号。', notice_type='onboarding', status='unread', link_url='/hrm/onboarding-tasks', created_at=dt('2026-06-01T09:00:00')),
        Notification(id='demo-notify-wuminghua-resignation', user_id='demo-user-hr', title='吴明华离职链路已归档', content='吴明华已完成招聘、入职、培训、发薪和离职闭环，可用于全链路验收。', notice_type='hr', status='unread', link_url='/hrm/resignations', created_at=dt('2026-06-01T09:05:00')),
    ]
    add_all(notifications)

    operation_logs = [
        OperationLog(id='demo-log-job-create', user_id='demo-user-recruiter', module='jobs', action='create', target_id='demo-job-backend', detail={'title': '后端工程师', 'source': 'demo_seed'}, ip='127.0.0.1', created_at=dt('2026-05-03T09:00:00')),
        OperationLog(id='demo-log-offer-convert', user_id='demo-user-hr', module='offers', action='convert_to_employee', target_id='demo-offer-sunye', detail={'employeeId': 'demo-emp-product-sunye', 'flow': 'candidate_to_employee'}, ip='127.0.0.1', created_at=dt('2026-05-20T10:00:00')),
        OperationLog(id='demo-log-payroll-generate', user_id='demo-user-finance', module='payroll-records', action='generate_month', target_id='2026-05', detail={'records': 4, 'month': '2026-05'}, ip='127.0.0.1', created_at=dt('2026-05-31T18:00:00')),
        OperationLog(id='demo-log-performance-training', user_id='demo-user-hr', module='performance-reviews', action='generate_training_plan', target_id='demo-review-lisi', detail={'planId': 'demo-plan-quality-q2'}, ip='127.0.0.1', created_at=dt('2026-05-29T10:00:00')),
        OperationLog(id='demo-log-wuminghua-lifecycle', user_id='demo-user-hr', module='employees', action='full_lifecycle_verified', target_id='demo-emp-rd-wuminghua', detail={'flow': 'resume_to_resignation', 'modules': ['resumes', 'candidates', 'interviews', 'offers', 'employees', 'onboarding-tasks', 'contracts', 'training-records', 'attendance-records', 'salary-profiles', 'payroll-records', 'probations', 'employee-changes', 'resignations']}, ip='127.0.0.1', created_at=dt('2026-06-01T09:10:00')),
    ]
    add_all(operation_logs)

    sessions = [
        AssistantSession(
            id='demo-assistant-session-hr',
            user_id='demo-user-hr',
            title='演示：本月 HRM 运营概览',
            messages=[
                {'role': 'user', 'content': '2026-05 考勤异常情况'},
                {'role': 'assistant', 'content': '2026-05 共有多条考勤记录，异常包含迟到、缺卡和出差。'},
                {'role': 'user', 'content': '待我审批有哪些'},
                {'role': 'assistant', 'content': '当前有 Offer、转正和人事异动审批待处理。'},
            ],
            is_active=True,
            message_count=4,
            created_at=dt('2026-06-01T09:20:00'),
            updated_at=dt('2026-06-01T09:25:00'),
        ),
    ]
    add_all(sessions)

    audit_logs = [
        AssistantAuditLog(
            id='demo-audit-sunye-lifecycle',
            user_id='demo-user-hr',
            session_id='demo-assistant-session-hr',
            request_id='demo-request-sunye-lifecycle',
            provider='siliconflow',
            model='deepseek-ai/DeepSeek-V4-Pro',
            model_profile='strong',
            use_case='evidence_analysis',
            prompt_messages=[
                {'role': 'system', 'content': '你是恒聘通 HRM 助手，需要基于系统记录回答。'},
                {'role': 'user', 'content': '孙悦从简历录入到入职、培训、薪资现在关联到了哪些模块？'},
            ],
            response_content='系统检索命中：简历、候选人、面试、Offer、员工、入职任务、合同、薪资档案、培训记录。',
            response_meta={'source': 'demo_seed', 'entityCount': 11},
            status='success',
            latency_ms=1280,
            prompt_chars=69,
            response_chars=43,
            created_at=dt('2026-06-01T09:28:00'),
        ),
        AssistantAuditLog(
            id='demo-audit-lisi-lifecycle',
            user_id='demo-user-hr',
            session_id='demo-assistant-session-hr',
            request_id='demo-request-lisi-lifecycle',
            provider='siliconflow',
            model='deepseek-ai/DeepSeek-V4-Pro',
            model_profile='strong',
            use_case='evidence_analysis',
            prompt_messages=[
                {'role': 'system', 'content': '你是恒聘通 HRM 助手，需要基于系统记录回答。'},
                {'role': 'user', 'content': '李四的转正、培训和调薪链路现在有哪些数据？'},
            ],
            response_content='系统检索命中：员工、试用期、异动、合同、员工申请、考勤、绩效、薪资档案、薪酬、培训记录。',
            response_meta={'source': 'demo_seed', 'entityCount': 12},
            status='success',
            latency_ms=1460,
            prompt_chars=61,
            response_chars=48,
            created_at=dt('2026-06-01T09:30:00'),
        ),
        AssistantAuditLog(
            id='demo-audit-wuminghua-full-lifecycle',
            user_id='demo-user-hr',
            session_id='demo-assistant-session-hr',
            request_id='demo-request-wuminghua-full-lifecycle',
            provider='siliconflow',
            model='deepseek-ai/DeepSeek-V4-Pro',
            model_profile='strong',
            use_case='evidence_analysis',
            prompt_messages=[
                {'role': 'system', 'content': '你是恒聘通 HRM 助手，需要基于系统记录回答。'},
                {'role': 'user', 'content': '吴明华从简历录入到入职、培训、发薪和离职的完整链路有哪些记录？'},
            ],
            response_content='系统检索命中：简历、候选人、面试、Offer、员工、入职任务、合同、培训、考勤、薪资档案、工资条、转正、异动、离职和审批记录。',
            response_meta={'source': 'demo_seed', 'entityCount': 20},
            status='success',
            latency_ms=1660,
            prompt_chars=76,
            response_chars=62,
            created_at=dt('2026-06-01T09:32:00'),
        ),
        AssistantAuditLog(
            id='demo-audit-prompt-timeout',
            user_id='demo-user-admin',
            session_id=None,
            request_id='demo-request-prompt-timeout',
            provider='siliconflow',
            model='deepseek-ai/DeepSeek-V4-Pro',
            model_profile='strong',
            use_case='prompt_optimization',
            prompt_messages=[
                {'role': 'user', 'content': '把“查一下这个月人力情况”优化成可执行提示词。'},
            ],
            response_content='',
            response_meta={'source': 'demo_seed'},
            status='timeout',
            error_message='request timeout',
            latency_ms=15000,
            prompt_chars=24,
            response_chars=0,
            created_at=dt('2026-06-01T09:35:00'),
        ),
    ]
    add_all(audit_logs)

    db.session.commit()

    summary_models = [
        Department, Position, User, Job, Resume, Candidate, Interview, Offer,
        Employee, OnboardingTask, Probation, EmployeeChange, Resignation, Contract,
        AttendanceRecord, EmployeeRequest, ApprovalInstance, ApprovalRecord,
        PerformanceCycle, PerformanceTemplate, PerformanceReview, SalaryProfile,
        PayrollRecord, TrainingCourse, TrainingPlan, TrainingRecord, Notification,
        Feedback, OperationLog, AssistantSession, AssistantAuditLog,
    ]
    return {
        model.__tablename__: model.query.filter(model.id.like(f'{DEMO_PREFIX}%')).count()
        for model in summary_models
    }


def main() -> None:
    app = create_app()
    with app.app_context():
        counts = seed_demo_data()
        total = sum(counts.values())
        print(f'Seeded {total} demo rows. Password for demo users: {DEMO_PASSWORD}')
        for table, count in sorted(counts.items()):
            print(f'{table}: {count}')


if __name__ == '__main__':
    main()
