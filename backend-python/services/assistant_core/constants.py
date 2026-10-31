"""助手核心常量：风险等级、动作类型、角色、敏感字段定义。"""

from __future__ import annotations

# ----------------------------------------------------------------------
# 风险等级
# ----------------------------------------------------------------------
RISK_LOW = 'low'
RISK_MEDIUM = 'medium'
RISK_HIGH = 'high'

# ----------------------------------------------------------------------
# 动作类型
# ----------------------------------------------------------------------
ACTION_READ_PUBLIC = 'READ_PUBLIC'        # 公开聚合数据
ACTION_READ_HR = 'READ_HR'                # HR 业务数据（按角色）
ACTION_READ_SENSITIVE = 'READ_SENSITIVE'  # 敏感（薪资、身份证、合同附件）
ACTION_GENERATE_DRAFT = 'GENERATE_DRAFT'  # 生成草稿
ACTION_WRITE_BUSINESS = 'WRITE_BUSINESS'  # 修改业务对象
ACTION_APPROVE = 'APPROVE'                # 审批通过/驳回
ACTION_DELETE = 'DELETE'                  # 删除
ACTION_SEND_MESSAGE = 'SEND_MESSAGE'      # 发送消息/邮件
ACTION_EXECUTE_CODE = 'EXECUTE_CODE'      # 任意代码执行（绝对禁止）

# 当前阶段：默认允许的动作集
ALLOWED_ACTIONS_AUTO = {
    ACTION_READ_PUBLIC,
    ACTION_READ_HR,
    ACTION_GENERATE_DRAFT,
}
# 当前阶段：需要 confirmation 但不立即执行的动作
ACTIONS_REQUIRE_CONFIRMATION = {
    ACTION_WRITE_BUSINESS,
    ACTION_APPROVE,
    ACTION_SEND_MESSAGE,
}
# 当前阶段：完全禁止
ACTIONS_FORBIDDEN = {
    ACTION_DELETE,
    ACTION_EXECUTE_CODE,
}

# ----------------------------------------------------------------------
# 角色
# ----------------------------------------------------------------------
ROLE_ADMIN = 'admin'
ROLE_HR_ADMIN = 'hr_admin'
ROLE_RECRUITER = 'recruiter'
ROLE_MANAGER = 'manager'
ROLE_EMPLOYEE = 'employee'
ROLE_FINANCE = 'finance'
ROLE_EXECUTIVE = 'executive'
ROLE_VIEWER = 'viewer'

ALL_ROLES = {
    ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER,
    ROLE_EMPLOYEE, ROLE_FINANCE, ROLE_EXECUTIVE, ROLE_VIEWER,
}

# 字段脱敏白名单按角色
PRIVILEGED_ROLES = {ROLE_ADMIN, ROLE_HR_ADMIN}
PAYROLL_AUTHORIZED_ROLES = {ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_FINANCE, ROLE_EXECUTIVE}

# ----------------------------------------------------------------------
# 敏感字段
# ----------------------------------------------------------------------
SENSITIVE_FIELDS = {
    'phone', 'email', 'id_card', 'id_no',
    'salary', 'payroll', 'bank', 'bank_account',
    'personal_address', 'address',
    'contract_attachment', 'resume_attachment',
}
