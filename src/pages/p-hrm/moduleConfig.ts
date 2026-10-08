import { STATUS_LABELS } from '../../utils/status';

const statusLabels: Record<string, string> = STATUS_LABELS;

export const roleLabels: Record<string, string> = {
  admin: '系统管理员', hr_admin: 'HR管理员', recruiter: '招聘专员', manager: '部门负责人', employee: '普通员工', finance: '财务人员', executive: '高管/老板', viewer: '查看者',
};

export const requestTypeOptions = [
  { label: '请假', value: 'leave' }, { label: '加班', value: 'overtime' }, { label: '出差', value: 'travel' }, { label: '补卡', value: 'makeup_card' },
];

export const employeeChangeTypeOptions = [
  { label: '调岗', value: 'transfer' },
  { label: '晋升', value: 'promotion' },
  { label: '降级', value: 'demotion' },
  { label: '部门变更', value: 'department_change' },
  { label: '岗位变更', value: 'position_change' },
  { label: '调薪', value: 'salary_adjustment' },
];

export const questionModeLabels: Record<string, string> = {
  fixed: '固定试卷',
  random: '随机抽题',
};

export const moduleConfigs: Record<string, any> = {
  departments: {
    title: '部门管理', resource: 'departments', icon: 'fa-sitemap', aiScene: 'org-advice',
    description: '维护部门、上级部门、部门负责人和启停用状态。',
    columns: ['name', 'code', 'parentName', 'managerName', 'status', 'updatedAt'],
    fields: [
      { name: 'name', label: '部门名称', required: true }, { name: 'code', label: '部门编码' },
      { name: 'parentId', label: '上级部门', type: 'select', lookup: 'departments' },
      { name: 'managerId', label: '部门负责人', type: 'select', lookup: 'employees' },
      { name: 'status', label: '状态', type: 'select', options: [{ label: '启用', value: 'active' }, { label: '停用', value: 'inactive' }], defaultValue: 'active' },
      { name: 'description', label: '部门说明', type: 'textarea' },
    ],
  },
  positions: {
    title: '岗位体系', resource: 'positions', icon: 'fa-layer-group', aiScene: 'position-advice',
    description: '维护岗位分类、所属部门、职级、岗位职责和任职要求。',
    columns: ['title', 'category', 'departmentName', 'level', 'status', 'updatedAt'],
    fields: [
      { name: 'title', label: '岗位名称', required: true }, { name: 'category', label: '岗位分类' },
      { name: 'departmentId', label: '所属部门', type: 'select', lookup: 'departments' }, { name: 'level', label: '职级' },
      { name: 'responsibilities', label: '岗位职责', type: 'textarea' }, { name: 'requirements', label: '任职要求', type: 'textarea' },
      { name: 'status', label: '状态', type: 'select', options: [{ label: '启用', value: 'active' }, { label: '停用', value: 'inactive' }], defaultValue: 'active' },
    ],
  },
  candidates: {
    title: '候选人管理', resource: 'candidates', icon: 'fa-user-tie', aiScene: 'candidate-summary',
    description: '从简历自动同步候选人，支持来源、标签、状态流转和AI摘要。',
    columns: ['name', 'jobTitle', 'phone', 'email', 'source', 'status', 'createdAt'],
    fields: [
      { name: 'name', label: '候选人姓名', required: true }, { name: 'jobId', label: '应聘岗位', type: 'select', lookup: 'jobs' },
      { name: 'email', label: '邮箱' }, { name: 'phone', label: '电话' }, { name: 'source', label: '来源', defaultValue: '简历上传' },
      { name: 'status', label: '状态', type: 'select', options: ['new', 'screening', 'interview', 'offer', 'offer_accepted', 'offer_rejected', 'converted', 'rejected'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'new' },
      { name: 'tags', label: '标签（逗号分隔）', type: 'tags' }, { name: 'aiSummary', label: 'AI候选人摘要', type: 'textarea' },
      { name: 'aiRecommendation', label: 'AI录用建议', type: 'textarea' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  offers: {
    title: 'Offer管理', resource: 'offers', icon: 'fa-file-signature', aiScene: 'hiring-advice',
    description: '维护Offer、审批状态、接受/拒绝，并支持一键转员工。',
    columns: ['title', 'candidateName', 'jobTitle', 'salary', 'onboardingDate', 'status', 'approvalStatus'],
    fields: [
      { name: 'candidateId', label: '候选人', type: 'select', lookup: 'candidates', required: true }, { name: 'jobId', label: '岗位', type: 'select', lookup: 'jobs' },
      { name: 'title', label: 'Offer标题', required: true }, { name: 'salary', label: 'Offer薪资', type: 'number' },
      { name: 'onboardingDate', label: '预计入职日期', type: 'date' }, { name: 'workLocation', label: '工作地点' },
      { name: 'status', label: 'Offer状态', type: 'select', options: ['draft', 'pending', 'sent', 'accepted', 'rejected', 'converted'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'draft' },
      { name: 'approvalStatus', label: '审批状态', type: 'select', options: ['draft', 'pending', 'approved', 'rejected'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'draft' },
      { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  employees: {
    title: '员工档案', resource: 'employees', icon: 'fa-id-card', aiScene: 'employee-summary',
    description: '员工基础档案、部门岗位、直属上级、入职和试用期信息。',
    columns: ['employeeNo', 'name', 'departmentName', 'jobTitle', 'managerName', 'hireDate', 'performanceParticipant', 'status'],
    fields: [
      { name: 'employeeNo', label: '员工编号（留空自动生成）' }, { name: 'name', label: '姓名', required: true },
      { name: 'email', label: '邮箱' }, { name: 'phone', label: '电话' }, { name: 'gender', label: '性别', type: 'select', options: ['男', '女', '其他'].map(v => ({ label: v, value: v })) },
      { name: 'departmentId', label: '所属部门', type: 'select', lookup: 'departments' }, { name: 'positionId', label: '所属岗位', type: 'select', lookup: 'positions' },
      { name: 'jobTitle', label: '岗位名称' }, { name: 'managerId', label: '直属上级', type: 'select', lookup: 'employees' },
      { name: 'hireDate', label: '入职日期', type: 'date' }, { name: 'probationMonths', label: '试用期（月）', type: 'number', defaultValue: 3 },
      { name: 'probationEndDate', label: '预计转正日期', type: 'date' },
      { name: 'performanceParticipant', label: '参与绩效考核', type: 'checkbox' },
      { name: 'status', label: '员工状态', type: 'select', options: ['pending_onboard', 'probation', 'active', 'inactive', 'resigned'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'pending_onboard' },
      { name: 'idNo', label: '证件号' }, { name: 'address', label: '联系地址' }, { name: 'emergencyContact', label: '紧急联系人' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  'onboarding-tasks': {
    title: '入职管理', resource: 'onboarding-tasks', icon: 'fa-clipboard-check', aiScene: 'onboarding-tasks',
    description: '待入职任务、资料收集和任务完成状态；员工页支持一键生成默认任务。',
    columns: ['employeeName', 'name', 'taskType', 'ownerName', 'dueDate', 'status'],
    fields: [
      { name: 'employeeId', label: '员工', type: 'select', lookup: 'employees', required: true }, { name: 'name', label: '任务名称', required: true },
      { name: 'taskType', label: '任务类型', defaultValue: '入职准备' }, { name: 'ownerId', label: '负责人', type: 'select', lookup: 'users' },
      { name: 'dueDate', label: '截止日期', type: 'date' }, { name: 'status', label: '任务状态', type: 'select', options: ['pending', 'processing', 'completed', 'cancelled'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'pending' },
      { name: 'materials', label: '资料清单（逗号分隔）', type: 'tags' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  probations: {
    title: '转正管理', resource: 'probations', icon: 'fa-user-check', aiScene: 'probation-draft',
    description: '试用期员工转正申请、审批、结果和转正日期。',
    columns: ['employeeName', 'applyDate', 'expectedRegularDate', 'regularDate', 'result', 'status'],
    fields: [
      { name: 'employeeId', label: '员工', type: 'select', lookup: 'employees', required: true }, { name: 'applyDate', label: '申请日期', type: 'date' },
      { name: 'expectedRegularDate', label: '预计转正日期', type: 'date' }, { name: 'regularDate', label: '实际转正日期', type: 'date' },
      { name: 'status', label: '状态', type: 'select', options: ['draft', 'pending', 'approved', 'rejected'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'draft' },
      { name: 'selfReview', label: '自评', type: 'textarea' }, { name: 'managerReview', label: '上级评价', type: 'textarea' }, { name: 'result', label: '转正结果' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  'employee-changes': {
    title: '人事异动', resource: 'employee-changes', icon: 'fa-random', aiScene: 'employee-change',
    description: '调岗、调薪预留、晋升、降级、部门/岗位变更和异动记录。',
    columns: ['employeeName', 'changeType', 'afterDepartmentName', 'afterPositionTitle', 'salaryAdjustment', 'effectiveDate', 'status'],
    fields: [
      { name: 'employeeId', label: '员工', type: 'select', lookup: 'employees', required: true },
      { name: 'changeType', label: '异动类型', type: 'select', options: employeeChangeTypeOptions, required: true },
      { name: 'beforeDepartmentId', label: '原部门', type: 'select', lookup: 'departments' }, { name: 'afterDepartmentId', label: '新部门', type: 'select', lookup: 'departments' },
      { name: 'beforePositionId', label: '原岗位', type: 'select', lookup: 'positions' }, { name: 'afterPositionId', label: '新岗位', type: 'select', lookup: 'positions' },
      { name: 'beforeLevel', label: '原职级' }, { name: 'afterLevel', label: '新职级' }, { name: 'salaryAdjustment', label: '调薪金额预留', type: 'number' },
      { name: 'effectiveDate', label: '生效日期', type: 'date' }, { name: 'status', label: '状态', type: 'select', options: ['draft', 'pending', 'approved', 'effective'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'draft' },
      { name: 'reason', label: '异动原因', type: 'textarea' },
    ],
  },
  resignations: {
    title: '离职管理', resource: 'resignations', icon: 'fa-user-minus', aiScene: 'resignation-summary',
    description: '离职申请、审批、原因、离职日期和交接事项，审批通过后员工状态变更为离职。',
    columns: ['employeeName', 'applyDate', 'expectedLeaveDate', 'actualLeaveDate', 'status', 'updatedAt'],
    fields: [
      { name: 'employeeId', label: '员工', type: 'select', lookup: 'employees', required: true }, { name: 'applyDate', label: '申请日期', type: 'date' },
      { name: 'expectedLeaveDate', label: '预计离职日期', type: 'date' }, { name: 'actualLeaveDate', label: '实际离职日期', type: 'date' },
      { name: 'status', label: '状态', type: 'select', options: ['draft', 'pending', 'approved', 'rejected'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'draft' },
      { name: 'reason', label: '离职原因', type: 'textarea' }, { name: 'handoverItems', label: '交接事项（逗号分隔）', type: 'tags' }, { name: 'aiSummary', label: 'AI离职原因总结', type: 'textarea' },
    ],
  },
  contracts: {
    title: '合同管理', resource: 'contracts', icon: 'fa-file-contract', aiScene: 'contract-risk',
    description: '合同类型、起止日期、状态、到期提醒和附件字段预留。',
    columns: ['employeeName', 'contractNo', 'contractType', 'startDate', 'endDate', 'status', 'reminderDate'],
    fields: [
      { name: 'employeeId', label: '员工', type: 'select', lookup: 'employees', required: true }, { name: 'contractNo', label: '合同编号' },
      { name: 'contractType', label: '合同类型', defaultValue: '劳动合同' }, { name: 'startDate', label: '开始日期', type: 'date' }, { name: 'endDate', label: '结束日期', type: 'date' },
      { name: 'status', label: '状态', type: 'select', options: ['active', 'expired', 'terminated', 'draft'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'active' },
      { name: 'reminderDate', label: '到期提醒日期', type: 'date' }, { name: 'attachmentUrl', label: '合同附件URL预留' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  'attendance-records': {
    title: '考勤记录', resource: 'attendance-records', icon: 'fa-clock', aiScene: 'attendance-analysis',
    description: '按员工查看每日上下班打卡。可用月份或员工筛选，并跳转到按月汇总。',
    columns: ['employeeName', 'attendanceDate', 'checkInTime', 'checkOutTime', 'workHours', 'status'],
    fields: [
      { name: 'employeeId', label: '员工', type: 'select', lookup: 'employees', required: true }, { name: 'attendanceDate', label: '考勤日期', type: 'date', required: true },
      { name: 'checkInTime', label: '上班时间', type: 'datetime-local' }, { name: 'checkOutTime', label: '下班时间', type: 'datetime-local' }, { name: 'workHours', label: '工时', type: 'number' },
      { name: 'status', label: '状态', type: 'select', options: ['normal', 'late', 'early_leave', 'missing_card', 'leave', 'overtime'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'normal' },
      { name: 'source', label: '来源', defaultValue: 'manual' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  'attendance-stats': { title: '考勤统计', special: 'attendance-stats', icon: 'fa-chart-line', description: '按月统计打卡记录与已审批申请，支撑考勤到薪酬链路。', columns: ['employeeName', 'normal', 'late', 'earlyLeave', 'missingCard', 'leave', 'overtime', 'travel', 'makeupCard', 'approvedRequests', 'exceptions'] },
  'employee-requests': {
    title: '请假/加班/出差/补卡', resource: 'employee-requests', icon: 'fa-calendar-plus', aiScene: 'request-review',
    description: '统一管理员工申请，支持草稿、提交审批、通过、驳回和撤销。',
    columns: ['employeeName', 'requestType', 'title', 'startTime', 'endTime', 'durationHours', 'status'],
    fields: [
      { name: 'employeeId', label: '员工', type: 'select', lookup: 'employees', required: true }, { name: 'requestType', label: '申请类型', type: 'select', options: requestTypeOptions, required: true },
      { name: 'title', label: '申请标题' }, { name: 'startTime', label: '开始时间', type: 'datetime-local' }, { name: 'endTime', label: '结束时间', type: 'datetime-local' },
      { name: 'durationHours', label: '时长/小时', type: 'number' }, { name: 'status', label: '状态', type: 'select', options: ['draft', 'pending', 'approved', 'rejected', 'cancelled'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'draft' },
      { name: 'reason', label: '申请原因', type: 'textarea' },
    ],
  },
  'my-applications': { title: '我的申请', special: 'approval-list', approvalKind: 'my-applications', icon: 'fa-inbox', description: '当前登录人发起的审批申请。', columns: ['title', 'businessType', 'applicantName', 'approverName', 'status', 'submittedAt', 'completedAt'], readOnly: true },
  'pending-approvals': { title: '待我审批', special: 'approval-list', approvalKind: 'pending', icon: 'fa-user-clock', description: '待审批事项，管理员/HR可看到全部待审批。', columns: ['title', 'businessType', 'applicantName', 'approverName', 'status', 'submittedAt'], readOnly: true },
  'approval-records': { title: '审批记录', special: 'approval-list', approvalKind: 'records', icon: 'fa-history', description: '审批通过/驳回的操作记录。', columns: ['approvalTitle', 'businessType', 'approverName', 'action', 'comment', 'createdAt'], readOnly: true },
  'performance-cycles': {
    title: '绩效周期', resource: 'performance-cycles', icon: 'fa-bullseye', aiScene: 'performance-cycle', description: '维护月度、季度、年度绩效周期。',
    columns: ['name', 'cycleType', 'startDate', 'endDate', 'status'], fields: [
      { name: 'name', label: '周期名称', required: true }, { name: 'cycleType', label: '周期类型', type: 'select', options: ['月度', '季度', '年度'].map(v => ({ label: v, value: v })), defaultValue: '月度' },
      { name: 'startDate', label: '开始日期', type: 'date' }, { name: 'endDate', label: '结束日期', type: 'date' }, { name: 'status', label: '状态', type: 'select', options: ['draft', 'active', 'completed'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'draft' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  'performance-templates': {
    title: '绩效模板', resource: 'performance-templates', icon: 'fa-list-check', aiScene: 'performance-template', description: '维护绩效指标模板，指标字段为JSON/逗号预留。',
    columns: ['name', 'templateType', 'status', 'updatedAt'], fields: [
      { name: 'name', label: '模板名称', required: true }, { name: 'templateType', label: '模板类型', defaultValue: '通用' }, { name: 'indicators', label: '指标（逗号分隔）', type: 'tags' }, { name: 'status', label: '状态', type: 'select', options: ['active', 'inactive'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'active' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  'performance-reviews': {
    title: '绩效评估', resource: 'performance-reviews', icon: 'fa-star-half-alt', aiScene: 'performance-review', description: '员工绩效评估、自评、上级评分、等级和结果。',
    columns: ['employeeName', 'cycleName', 'selfScore', 'managerScore', 'finalScore', 'grade', 'status'], fields: [
      { name: 'employeeId', label: '员工', type: 'select', lookup: 'employees', required: true }, { name: 'cycleId', label: '绩效周期', type: 'select', lookup: 'performance-cycles' }, { name: 'templateId', label: '绩效模板', type: 'select', lookup: 'performance-templates' },
      { name: 'selfReview', label: '自评', type: 'textarea' }, { name: 'selfScore', label: '自评分', type: 'number' }, { name: 'managerScore', label: '上级评分', type: 'number' }, { name: 'finalScore', label: '最终得分', type: 'number' },
      { name: 'grade', label: '绩效等级', type: 'select', options: ['S', 'A', 'B', 'C', 'D'].map(v => ({ label: v, value: v })) }, { name: 'result', label: '绩效结果', type: 'textarea' }, { name: 'status', label: '状态', type: 'select', options: ['draft', 'completed', 'published'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'draft' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  'salary-profiles': {
    title: '薪资档案', resource: 'salary-profiles', icon: 'fa-wallet', aiScene: 'salary-profile', description: '维护员工薪资结构，不含复杂个税社保计算。',
    columns: ['employeeName', 'baseSalary', 'positionSalary', 'performanceSalary', 'bonus', 'allowance', 'deduction', 'totalSalary'], fields: [
      { name: 'employeeId', label: '员工', type: 'select', lookup: 'employees', required: true }, { name: 'baseSalary', label: '基本工资', type: 'number' }, { name: 'positionSalary', label: '岗位工资', type: 'number' }, { name: 'performanceSalary', label: '绩效工资', type: 'number' }, { name: 'bonus', label: '奖金', type: 'number' }, { name: 'allowance', label: '补贴', type: 'number' }, { name: 'deduction', label: '扣款', type: 'number' }, { name: 'currency', label: '币种', defaultValue: 'CNY' }, { name: 'status', label: '状态', type: 'select', options: ['active', 'inactive'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'active' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  'payroll-records': {
    title: '工资条', resource: 'payroll-records', icon: 'fa-money-check-alt', aiScene: 'payroll-analysis', description: '月度薪资记录/工资条，员工查看字段已预留。',
    columns: ['employeeName', 'payrollMonth', 'grossSalary', 'deduction', 'netSalary', 'status', 'employeeVisible'], fields: [
      { name: 'employeeId', label: '员工', type: 'select', lookup: 'employees', required: true }, { name: 'payrollMonth', label: '薪资月份（YYYY-MM）', required: true }, { name: 'baseSalary', label: '基本工资', type: 'number' }, { name: 'positionSalary', label: '岗位工资', type: 'number' }, { name: 'performanceSalary', label: '绩效工资', type: 'number' }, { name: 'bonus', label: '奖金', type: 'number' }, { name: 'allowance', label: '补贴', type: 'number' }, { name: 'deduction', label: '扣款', type: 'number' }, { name: 'grossSalary', label: '应发工资（留空自动计算）', type: 'number' }, { name: 'netSalary', label: '实发工资（留空自动计算）', type: 'number' }, { name: 'status', label: '状态', type: 'select', options: ['draft', 'calculated', 'paid'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'draft' }, { name: 'employeeVisible', label: '员工可见', type: 'checkbox' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  'training-courses': {
    title: '培训课程', resource: 'training-courses', icon: 'fa-chalkboard-teacher', aiScene: 'training-course', description: '维护培训课程、讲师、时长和课程状态。',
    columns: ['name', 'category', 'lecturer', 'durationHours', 'status'], fields: [
      { name: 'name', label: '课程名称', required: true }, { name: 'category', label: '课程分类' }, { name: 'lecturer', label: '讲师' }, { name: 'durationHours', label: '课时', type: 'number' }, { name: 'description', label: '课程说明', type: 'textarea' }, { name: 'status', label: '状态', type: 'select', options: ['active', 'inactive'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'active' },
    ],
  },
  'training-plans': {
    title: '培训计划', resource: 'training-plans', icon: 'fa-calendar-days', aiScene: 'training-plan', description: '维护培训计划、课程、时间、目标部门和执行状态。',
    columns: ['name', 'courseName', 'startTime', 'endTime', 'status'], fields: [
      { name: 'name', label: '计划名称', required: true }, { name: 'courseId', label: '课程', type: 'select', lookup: 'training-courses' }, { name: 'startTime', label: '开始时间', type: 'datetime-local' }, { name: 'endTime', label: '结束时间', type: 'datetime-local' }, { name: 'targetDepartments', label: '目标部门（逗号分隔）', type: 'tags' }, { name: 'status', label: '状态', type: 'select', options: ['planned', 'active', 'completed', 'cancelled'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'planned' }, { name: 'remark', label: '备注', type: 'textarea' },
    ],
  },
  'training-records': {
    title: '培训记录', resource: 'training-records', icon: 'fa-graduation-cap', aiScene: 'training-record', description: '员工培训报名/参与、培训结果和反馈字段。',
    columns: ['employeeName', 'planName', 'courseName', 'status', 'result', 'score'], fields: [
      { name: 'employeeId', label: '员工', type: 'select', lookup: 'employees', required: true }, { name: 'planId', label: '培训计划', type: 'select', lookup: 'training-plans' }, { name: 'courseId', label: '培训课程', type: 'select', lookup: 'training-courses' }, { name: 'status', label: '状态', type: 'select', options: ['registered', 'attended', 'completed', 'cancelled'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'registered' }, { name: 'result', label: '培训结果' }, { name: 'score', label: '成绩', type: 'number' }, { name: 'feedback', label: '反馈预留', type: 'textarea' },
    ],
  },
  // ----- 培训中心（视频章节制课程，参照 PlayEdu 开源版）-----
  'course-categories': {
    title: '课程分类', resource: 'course-categories', icon: 'fa-folder-tree', description: '管理课程分类树（支持多级）。',
    columns: ['name', 'parentName', 'sort'], fields: [
      { name: 'name', label: '分类名称', required: true }, { name: 'parentId', label: '上级分类', type: 'select', lookup: 'course-categories' }, { name: 'sort', label: '排序', type: 'number' },
    ],
  },
  'courses': {
    title: '课程', resource: 'courses', icon: 'fa-book-open', description: '视频章节制培训课程。点击「编辑课程」管理章节、课时、视频和指派。',
    columns: ['title', 'categoryName', 'isRequired', 'classHour', 'isShow'], fields: [
      { name: 'title', label: '课程标题', required: true }, { name: 'categoryId', label: '分类', type: 'select', lookup: 'course-categories' }, { name: 'coverUrl', label: '封面图 URL' }, { name: 'isRequired', label: '必修', type: 'checkbox' }, { name: 'shortDesc', label: '简介', type: 'textarea' }, { name: 'content', label: '图文介绍', type: 'textarea' }, { name: 'isShow', label: '上架', type: 'checkbox' }, { name: 'classHour', label: '课时数', type: 'number' }, { name: 'sort', label: '排序', type: 'number' },
    ],
  },
  'course-chapters': {
    title: '课程章节', resource: 'course-chapters', icon: 'fa-list-ol', description: '课程的章节分组（建议在课程编辑器内管理）。',
    columns: ['courseTitle', 'name', 'sort'], readOnly: false, fields: [
      { name: 'courseId', label: '课程', type: 'select', lookup: 'courses', required: true }, { name: 'name', label: '章节名称', required: true }, { name: 'sort', label: '排序', type: 'number' },
    ],
  },
  'course-hours': {
    title: '课时', resource: 'course-hours', icon: 'fa-photo-video', description: '课时（视频）。建议在课程编辑器内管理，支持上传视频。',
    columns: ['courseTitle', 'chapterName', 'title', 'duration'], fields: [
      { name: 'courseId', label: '课程', type: 'select', lookup: 'courses', required: true }, { name: 'chapterId', label: '章节', type: 'select', lookup: 'course-chapters' }, { name: 'title', label: '课时标题', required: true }, { name: 'type', label: '类型', type: 'select', options: [{ label: '视频', value: 'VIDEO' }] }, { name: 'sort', label: '排序', type: 'number' }, { name: 'duration', label: '时长(秒)', type: 'number' }, { name: 'videoKey', label: '视频Key(自动)' },
    ],
  },
  'course-attachments': {
    title: '课程附件', resource: 'course-attachments', icon: 'fa-paperclip', description: '课程可下载的 PDF/Word 等材料。',
    columns: ['courseTitle', 'title', 'ext'], fields: [
      { name: 'courseId', label: '课程', type: 'select', lookup: 'courses', required: true }, { name: 'title', label: '附件名称', required: true }, { name: 'fileUrl', label: '文件URL' }, { name: 'ext', label: '扩展名' }, { name: 'sort', label: '排序', type: 'number' },
    ],
  },
  'course-assignments': {
    title: '课程指派', resource: 'course-assignments', icon: 'fa-user-tag', description: '课程按部门或员工指派（建议在课程编辑器内配置）。',
    columns: ['targetType', 'targetName'], readOnly: true, fields: [],
  },
  // ----- 考试管理（自研）-----
  'exam-questions': {
    title: '题库', resource: 'exam-questions', icon: 'fa-question-circle', description: '管理考试题目。AI 生成的题目需审核通过才能用于组卷。点「AI出题」批量生成。',
    columns: ['stem', 'type', 'difficulty', 'score', 'reviewStatus'], fields: [
      { name: 'stem', label: '题干', type: 'textarea', required: true }, { name: 'type', label: '题型', type: 'select', options: [{label:'单选',value:'single'},{label:'多选',value:'multiple'},{label:'判断',value:'judge'}] }, { name: 'options', label: '选项(逗号分隔)', type: 'tags' }, { name: 'answer', label: '正确答案索引(逗号分隔,如 0,2)', type: 'tags' }, { name: 'score', label: '分值', type: 'number' }, { name: 'explanation', label: '解析', type: 'textarea' }, { name: 'difficulty', label: '难度(1-5)', type: 'number' }, { name: 'category', label: '分类' }, { name: 'courseId', label: '关联课程', type: 'select', lookup: 'courses' }, { name: 'reviewStatus', label: '审核状态', type: 'select', options: ['pending','approved','rejected'].map(v => ({label:v,value:v})) },
    ],
  },
  'exam-papers': {
    title: '试卷', resource: 'exam-papers', icon: 'fa-file-pen', description: '试卷：支持固定题或题池随机抽题。',
    columns: ['title', 'questionMode', 'drawCount', 'totalScore', 'passScore', 'durationMinutes', 'status'], fields: [
      { name: 'title', label: '试卷名称', required: true }, { name: 'description', label: '说明', type: 'textarea' }, { name: 'questionIds', label: '题目ID(逗号分隔)', type: 'tags' }, { name: 'questionMode', label: '出题方式', type: 'select', options: [{ label: '固定试卷', value: 'fixed' }, { label: '随机抽题', value: 'random' }], defaultValue: 'fixed' }, { name: 'drawCount', label: '抽题数量', type: 'number' }, { name: 'totalScore', label: '总分', type: 'number' }, { name: 'passScore', label: '及格分', type: 'number' }, { name: 'durationMinutes', label: '时长(分钟)', type: 'number' }, { name: 'shuffle', label: '乱序', type: 'checkbox' }, { name: 'status', label: '状态', type: 'select', options: ['draft','published','archived'].map(v => ({label:v,value:v})), defaultValue: 'draft' },
    ],
  },
  'exam-tasks': {
    title: '考试任务', resource: 'exam-tasks', icon: 'fa-clipboard-list', description: '一次考试活动。配置后点「发布」生成员工授权。点「进度」看成绩单。',
    columns: ['title', 'paperTitle', 'startTime', 'endTime', 'status'], fields: [
      { name: 'title', label: '任务标题', required: true }, { name: 'paperId', label: '试卷', type: 'select', lookup: 'exam-papers' }, { name: 'description', label: '说明', type: 'textarea' }, { name: 'startTime', label: '开始时间', type: 'datetime-local' }, { name: 'endTime', label: '结束时间', type: 'datetime-local' }, { name: 'maxAttempts', label: '最大次数', type: 'number' }, { name: 'targetType', label: '指派方式', type: 'select', options: [{label:'按部门',value:'dept'},{label:'按员工',value:'user'}] }, { name: 'targetIds', label: '目标ID(逗号分隔)', type: 'tags' }, { name: 'status', label: '状态', type: 'select', options: ['draft','published','closed'].map(v => ({label:v,value:v})), defaultValue: 'draft' },
    ],
  },
  'exam-attempts': {
    title: '答题记录', resource: 'exam-attempts', icon: 'fa-pen-to-square', description: '员工考试答题记录与成绩（只读，由门户提交产生）。',
    columns: ['employeeName', 'taskTitle', 'score', 'totalScore', 'passed', 'status', 'submittedAt'], readOnly: true, fields: [],
  },
  users: {
    title: '用户管理', resource: 'users', icon: 'fa-users-cog', description: '管理后台登录账号、角色、状态、部门和员工关联。',
    columns: ['name', 'email', 'role', 'phone', 'status', 'updatedAt'], readOnlyCreate: true, allowAdminCreate: true, fields: [
      { name: 'name', label: '姓名', required: true }, { name: 'email', label: '邮箱', required: true }, { name: 'role', label: '角色', type: 'select', options: Object.entries(roleLabels).map(([value, label]) => ({ value, label })), defaultValue: 'recruiter', required: true }, { name: 'phone', label: '电话' }, { name: 'departmentId', label: '部门', type: 'select', lookup: 'departments' }, { name: 'employeeId', label: '关联员工', type: 'select', lookup: 'employees' }, { name: 'status', label: '状态', type: 'select', options: ['active', 'inactive'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'active', required: true },
    ],
  },
  roles: {
    title: '角色权限', resource: 'roles', icon: 'fa-user-shield', description: '基础角色管理与菜单/权限结构预留。',
    columns: ['code', 'name', 'status', 'updatedAt'], fields: [
      { name: 'code', label: '角色编码', required: true }, { name: 'name', label: '角色名称', required: true }, { name: 'description', label: '说明', type: 'textarea' }, { name: 'permissions', label: '权限标识（逗号分隔）', type: 'tags' }, { name: 'status', label: '状态', type: 'select', options: ['active', 'inactive'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'active' },
    ],
  },
  notifications: {
    title: '通知提醒', resource: 'notifications', icon: 'fa-bell', description: '系统通知、审批提醒和人事提醒基础版。',
    columns: ['title', 'noticeType', 'userName', 'status', 'createdAt'], fields: [
      { name: 'userId', label: '接收用户（留空为全局）', type: 'select', lookup: 'users' }, { name: 'title', label: '标题', required: true }, { name: 'content', label: '内容', type: 'textarea' }, { name: 'noticeType', label: '类型', defaultValue: 'system' }, { name: 'status', label: '状态', type: 'select', options: ['unread', 'read'].map(v => ({ label: statusLabels[v] || v, value: v })), defaultValue: 'unread' }, { name: 'linkUrl', label: '链接URL预留' },
    ],
  },
  'operation-logs': { title: '操作日志', resource: 'operation-logs', icon: 'fa-clipboard-list', description: '记录HRM模块关键新增、修改、删除和审批动作。', columns: ['userName', 'module', 'action', 'targetId', 'createdAt'], readOnly: true },
};
