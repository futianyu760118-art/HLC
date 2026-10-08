// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { hrmApi, jobsApi } from '../../utils/api';
import { authUtils } from '../../utils/auth';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import { STATUS_LABELS, getStatusBadgeClass as getUnifiedStatusBadgeClass, getStatusLabel } from '../../utils/status';
import { FilterField, SearchInput, toFilterOptions } from '../../components/SmartFilters';
import { fieldLabels as columnLabels } from './fieldLabels';
import {
  employeeChangeTypeOptions,
  moduleConfigs,
  questionModeLabels,
  requestTypeOptions,
  roleLabels,
} from './moduleConfig';

import AppIcon from '../../components/AppIcon';
const statusLabels: Record<string, string> = STATUS_LABELS;

const optionsFromValues = (values: string[]) => values.map(value => ({ label: statusLabels[value] || value, value }));
const booleanOptions = [{ label: '是', value: 'true' }, { label: '否', value: 'false' }];
const activeOptions = optionsFromValues(['active', 'inactive']);
const dateRange = (key: string, label: string) => ({ key, label, type: 'date-range' });
const dateTimeRange = (key: string, label: string) => ({ key, label, type: 'datetime-range' });
const numberRange = (key: string, label: string) => ({ key, label, type: 'number-range' });
function monthDateBounds(monthValue) {
  const [year, monthNum] = String(monthValue || '').split('-').map(Number);
  if (!year || !monthNum) return null;
  const last = new Date(year, monthNum, 0).getDate();
  const month = `${String(year).padStart(4, '0')}-${String(monthNum).padStart(2, '0')}`;
  return {
    from: `${month}-01`,
    to: `${month}-${String(last).padStart(2, '0')}`,
  };
}
const DEFAULT_HRM_PAGE_SIZE = 50;
const HRM_PAGE_SIZE_OPTIONS = [25, 50, 100, 200];

const moduleFilterConfigs: Record<string, any[]> = {
  departments: [
    { key: 'status', label: '状态', type: 'segment', options: activeOptions },
    { key: 'parentId', label: '上级部门', type: 'combo', lookup: 'departments' },
    { key: 'managerId', label: '负责人', type: 'combo', lookup: 'employees' },
  ],
  positions: [
    { key: 'departmentId', label: '所属部门', type: 'combo', lookup: 'departments' },
    { key: 'category', label: '岗位分类', type: 'combo', source: 'records' },
    { key: 'level', label: '职级', type: 'select', source: 'records' },
    { key: 'status', label: '状态', type: 'segment', options: activeOptions },
  ],
  candidates: [
    { key: 'status', label: '候选状态', type: 'select', options: optionsFromValues(['new', 'screening', 'interview', 'offer', 'offer_accepted', 'offer_rejected', 'converted', 'rejected']) },
    { key: 'jobId', label: '应聘岗位', type: 'combo', lookup: 'jobs' },
    { key: 'source', label: '来源', type: 'combo', source: 'records' },
    { key: 'ownerId', label: '负责人', type: 'combo', lookup: 'users' },
    dateRange('createdAt', '创建时间'),
  ],
  offers: [
    { key: 'status', label: 'Offer状态', type: 'select', options: optionsFromValues(['draft', 'pending', 'sent', 'accepted', 'rejected', 'converted']) },
    { key: 'approvalStatus', label: '审批状态', type: 'select', options: optionsFromValues(['draft', 'pending', 'approved', 'rejected']) },
    { key: 'jobId', label: '岗位', type: 'combo', lookup: 'jobs' },
    { key: 'candidateId', label: '候选人', type: 'combo', lookup: 'candidates' },
    { key: 'workLocation', label: '工作地点', type: 'combo', source: 'records' },
    dateRange('onboardingDate', '入职日期'),
  ],
  employees: [
    { key: 'status', label: '员工状态', type: 'select', options: optionsFromValues(['pending_onboard', 'probation', 'active', 'inactive', 'resigned']) },
    { key: 'departmentId', label: '所属部门', type: 'combo', lookup: 'departments' },
    { key: 'positionId', label: '所属岗位', type: 'combo', lookup: 'positions' },
    { key: 'managerId', label: '直属上级', type: 'combo', lookup: 'employees' },
    { key: 'gender', label: '性别', type: 'segment', options: ['男', '女', '其他'].map(value => ({ label: value, value })) },
    dateRange('hireDate', '入职日期'),
  ],
  'onboarding-tasks': [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: 'ownerId', label: '负责人', type: 'combo', lookup: 'users' },
    { key: 'taskType', label: '任务类型', type: 'combo', source: 'records' },
    { key: 'status', label: '任务状态', type: 'select', options: optionsFromValues(['pending', 'processing', 'completed', 'cancelled']) },
    dateRange('dueDate', '截止日期'),
  ],
  probations: [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: 'status', label: '状态', type: 'select', options: optionsFromValues(['draft', 'pending', 'approved', 'rejected']) },
    { key: 'result', label: '转正结果', type: 'combo', source: 'records' },
    dateRange('applyDate', '申请日期'),
    dateRange('expectedRegularDate', '预计转正'),
  ],
  'employee-changes': [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: 'changeType', label: '异动类型', type: 'select', options: employeeChangeTypeOptions },
    { key: 'status', label: '状态', type: 'select', options: optionsFromValues(['draft', 'pending', 'approved', 'effective']) },
    { key: 'afterDepartmentId', label: '新部门', type: 'combo', lookup: 'departments' },
    { key: 'afterPositionId', label: '新岗位', type: 'combo', lookup: 'positions' },
    dateRange('effectiveDate', '生效日期'),
  ],
  resignations: [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: 'status', label: '状态', type: 'select', options: optionsFromValues(['draft', 'pending', 'approved', 'rejected']) },
    dateRange('applyDate', '申请日期'),
    dateRange('expectedLeaveDate', '预计离职'),
    dateRange('actualLeaveDate', '实际离职'),
  ],
  contracts: [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: 'contractType', label: '合同类型', type: 'combo', source: 'records' },
    { key: 'status', label: '状态', type: 'select', options: optionsFromValues(['active', 'expired', 'terminated', 'draft']) },
    dateRange('endDate', '结束日期'),
    dateRange('reminderDate', '提醒日期'),
  ],
  'attendance-records': [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: 'status', label: '考勤状态', type: 'select', options: optionsFromValues(['normal', 'late', 'early_leave', 'missing_card', 'leave', 'overtime']) },
    { key: 'source', label: '来源', type: 'combo', source: 'records' },
    dateRange('attendanceDate', '考勤日期'),
    numberRange('workHours', '工时'),
  ],
  'attendance-stats': [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: '__exceptionState', label: '异常情况', type: 'select', options: [
      { label: '有异常', value: 'has_exception' },
      { label: '无异常', value: 'no_exception' },
      { label: '有已批申请', value: 'has_request' },
      { label: '无已批申请', value: 'no_request' },
    ] },
    numberRange('exceptions', '异常次数'),
  ],
  'employee-requests': [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: 'requestType', label: '申请类型', type: 'segment', options: requestTypeOptions },
    { key: 'status', label: '审批状态', type: 'select', options: optionsFromValues(['draft', 'pending', 'approved', 'rejected', 'cancelled']) },
    dateTimeRange('startTime', '开始时间'),
    numberRange('durationHours', '时长'),
  ],
  'my-applications': [
    { key: 'businessType', label: '业务类型', type: 'combo', source: 'records' },
    { key: 'status', label: '审批状态', type: 'select', options: optionsFromValues(['pending', 'approved', 'rejected', 'cancelled']) },
    { key: 'approverId', label: '审批人', type: 'combo', lookup: 'users' },
    dateTimeRange('submittedAt', '提交时间'),
  ],
  'pending-approvals': [
    { key: 'businessType', label: '业务类型', type: 'combo', source: 'records' },
    { key: 'applicantId', label: '申请人', type: 'combo', lookup: 'users' },
    { key: 'approverId', label: '审批人', type: 'combo', lookup: 'users' },
    dateTimeRange('submittedAt', '提交时间'),
  ],
  'approval-records': [
    { key: 'businessType', label: '业务类型', type: 'combo', source: 'records' },
    { key: 'action', label: '动作', type: 'combo', source: 'records' },
    { key: 'approverId', label: '审批人', type: 'combo', lookup: 'users' },
    dateTimeRange('createdAt', '操作时间'),
  ],
  'performance-cycles': [
    { key: 'cycleType', label: '周期类型', type: 'segment', options: ['月度', '季度', '年度'].map(value => ({ label: value, value })) },
    { key: 'status', label: '状态', type: 'segment', options: optionsFromValues(['draft', 'active', 'completed']) },
    dateRange('startDate', '开始日期'),
    dateRange('endDate', '结束日期'),
  ],
  'performance-templates': [
    { key: 'templateType', label: '模板类型', type: 'combo', source: 'records' },
    { key: 'status', label: '状态', type: 'segment', options: activeOptions },
  ],
  'performance-reviews': [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: 'cycleId', label: '绩效周期', type: 'combo', lookup: 'performance-cycles' },
    { key: 'templateId', label: '绩效模板', type: 'combo', lookup: 'performance-templates' },
    { key: 'grade', label: '等级', type: 'segment', options: ['S', 'A', 'B', 'C', 'D'].map(value => ({ label: value, value })) },
    { key: 'status', label: '状态', type: 'select', options: optionsFromValues(['draft', 'completed', 'published']) },
    numberRange('finalScore', '最终得分'),
  ],
  'salary-profiles': [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: 'status', label: '状态', type: 'segment', options: activeOptions },
    { key: 'currency', label: '币种', type: 'select', source: 'records' },
    numberRange('totalSalary', '薪资合计'),
  ],
  'payroll-records': [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: 'payrollMonth', label: '薪资月份', type: 'month' },
    { key: 'status', label: '状态', type: 'select', options: optionsFromValues(['draft', 'calculated', 'paid']) },
    { key: 'employeeVisible', label: '员工可见', type: 'segment', options: booleanOptions },
    numberRange('netSalary', '实发工资'),
  ],
  'training-courses': [
    { key: 'category', label: '课程分类', type: 'combo', source: 'records' },
    { key: 'lecturer', label: '讲师', type: 'combo', source: 'records' },
    { key: 'status', label: '状态', type: 'segment', options: activeOptions },
    numberRange('durationHours', '课时'),
  ],
  'training-plans': [
    { key: 'courseId', label: '课程', type: 'combo', lookup: 'training-courses' },
    { key: 'status', label: '状态', type: 'select', options: optionsFromValues(['planned', 'active', 'completed', 'cancelled']) },
    { key: 'targetDepartments', label: '目标部门', type: 'text' },
    dateTimeRange('startTime', '开始时间'),
  ],
  'training-records': [
    { key: 'employeeId', label: '员工', type: 'combo', lookup: 'employees' },
    { key: 'planId', label: '培训计划', type: 'combo', lookup: 'training-plans' },
    { key: 'courseId', label: '培训课程', type: 'combo', lookup: 'training-courses' },
    { key: 'status', label: '状态', type: 'select', options: optionsFromValues(['registered', 'attended', 'completed', 'cancelled']) },
    { key: 'result', label: '结果', type: 'combo', source: 'records' },
    numberRange('score', '成绩'),
  ],
  users: [
    { key: 'role', label: '角色', type: 'select', options: Object.entries(roleLabels).map(([value, label]) => ({ value, label })) },
    { key: 'status', label: '状态', type: 'segment', options: activeOptions },
    { key: 'departmentId', label: '部门', type: 'combo', lookup: 'departments' },
    { key: 'employeeId', label: '关联员工', type: 'combo', lookup: 'employees' },
  ],
  roles: [
    { key: 'status', label: '状态', type: 'segment', options: activeOptions },
  ],
  notifications: [
    { key: 'noticeType', label: '类型', type: 'combo', source: 'records' },
    { key: 'status', label: '状态', type: 'segment', options: optionsFromValues(['unread', 'read']) },
    { key: 'userId', label: '接收用户', type: 'combo', lookup: 'users' },
    dateTimeRange('createdAt', '创建时间'),
  ],
  'operation-logs': [
    { key: 'module', label: '模块', type: 'combo', source: 'records' },
    { key: 'action', label: '动作', type: 'combo', source: 'records' },
    { key: 'userId', label: '用户', type: 'combo', lookup: 'users' },
    { key: 'targetId', label: '对象ID', type: 'text' },
    dateTimeRange('createdAt', '操作时间'),
  ],
};

const LIFECYCLE_WORKFLOW_MODULES = new Set(['contracts', 'probations', 'resignations']);
const HRM_RECORD_CACHE_TTL_MS = 45_000;

type HrmRecordCacheEntry = {
  records: any[];
  pageMeta: HrmPageMeta;
  storedAt: number;
};

type HrmPageMeta = {
  total: number;
  page: number;
  size: number;
  pages: number;
};

const hrmRecordCache = new Map<string, HrmRecordCacheEntry>();
const hrmRecordInflight = new Map<string, Promise<HrmRecordCacheEntry>>();

function defaultHrmPageMeta(size = DEFAULT_HRM_PAGE_SIZE): HrmPageMeta {
  return { total: 0, page: 1, size, pages: 1 };
}

function readHrmRecordCache(cacheKey: string) {
  const cached = hrmRecordCache.get(cacheKey);
  if (!cached) return null;
  if (Date.now() - cached.storedAt > HRM_RECORD_CACHE_TTL_MS) {
    hrmRecordCache.delete(cacheKey);
    return null;
  }
  return cached;
}

function writeHrmRecordCache(cacheKey: string, entry: Omit<HrmRecordCacheEntry, 'storedAt'>) {
  const nextEntry = { ...entry, storedAt: Date.now() };
  hrmRecordCache.set(cacheKey, nextEntry);
  return nextEntry;
}

function stableHrmListParamsKey(params: Record<string, any>) {
  return Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${String(value)}`)
    .join('&');
}

function hasFilterValue(value: any) {
  if (value === undefined || value === null || value === '') return false;
  if (typeof value === 'object') return Boolean(value.from || value.to);
  return true;
}

function formatValue(key: string, value: any) {
  if (value === null || value === undefined || value === '') return '-';
  if (key === 'status' || key === 'approvalStatus' || key === 'action') return getStatusLabel(value);
  if (key === 'role') return roleLabels[value] || value;
  if (key === 'questionMode') return questionModeLabels[value] || value;
  if (key === 'requestType') return requestTypeOptions.find(item => item.value === value)?.label || value;
  if (key === 'changeType') return employeeChangeTypeOptions.find(item => item.value === value)?.label || value;
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value)) return value.join('，') || '-';
  if (typeof value === 'object') return JSON.stringify(value);
  if (String(key).toLowerCase().includes('date') || String(key).toLowerCase().includes('time') || key.endsWith('At')) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) {
      // 考勤日期类字段只显示日期，打卡时间类字段只显示时间（日期在旁边已有）
      const lowerKey = String(key).toLowerCase();
      if (lowerKey.includes('date')) {
        return date.toLocaleDateString('zh-CN');
      }
      if (lowerKey.includes('checkin') || lowerKey.includes('checkout') || lowerKey.includes('punch')) {
        return date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' });
      }
      return date.toLocaleString('zh-CN', { hour12: false });
    }
  }
  return String(value);
}

function toInputValue(value: any, type?: string) {
  if (value === null || value === undefined) return '';
  if (type === 'date') return String(value).slice(0, 10);
  if (type === 'datetime-local') return String(value).slice(0, 16);
  if (type === 'tags') return Array.isArray(value) ? value.join('，') : String(value);
  return value;
}

function compactText(value: any) {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.join(' ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function getRecordDate(value: any) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function normalizeFilterValue(value: any) {
  return String(value ?? '').trim().toLowerCase();
}

function getRecordOptions(records: any[], key: string) {
  return Array.from(new Set(records.flatMap((record) => {
    const value = record[key];
    if (Array.isArray(value)) return value.map(item => compactText(item).trim()).filter(Boolean);
    const text = compactText(value).trim();
    return text ? [text] : [];
  }))).sort((a, b) => a.localeCompare(b, 'zh-CN')).map(value => ({
    value,
    label: key === 'status' || key === 'approvalStatus' || key === 'action' || key === 'requestType' || key === 'changeType'
      ? formatValue(key, value)
      : value,
  }));
}

function isEmptyDetailValue(value: any) {
  return value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
}

function cleanDetailValue(key: string, value: any) {
  if (key === 'remark' && typeof value === 'string') {
    const cleaned = value
      .split('\n')
      .filter((line) => !line.includes('[wecom-excel-import]'))
      .join('\n')
      .trim();
    return cleaned;
  }
  return value;
}

function hasFriendlyReference(record: any, key: string) {
  const base = key.replace(/Id$/, '');
  const candidates = [
    `${base}Name`,
    `${base}Title`,
    `${base}No`,
    `${base}Email`,
    key.replace(/Id$/, 'Name'),
    key.replace(/Id$/, 'Title'),
  ];
  return candidates.some((candidate) => !isEmptyDetailValue(record[candidate]));
}

function getDetailEntries(record: any) {
  const hiddenKeys = new Set([
    'id',
    'createdBy',
    'updatedBy',
    'passwordHash',
    'sourceOfferId',
    'candidateId',
    'attachments',
  ]);
  return Object.entries(record || {}).filter(([key, value]) => {
    if (hiddenKeys.has(key)) return false;
    if (key.endsWith('Id') && hasFriendlyReference(record, key)) return false;
    const cleaned = cleanDetailValue(key, value);
    return !isEmptyDetailValue(cleaned);
  });
}

function getLookupLabel(item: any) {
  return item.name || item.title || item.employeeNo || item.email || item.code || item.id;
}

const ORG_TREE_MODULES = new Set([
  'departments',
  'positions',
  'employees',
  'onboarding-tasks',
  'probations',
  'employee-changes',
  'resignations',
  'contracts',
  'attendance-records',
  'attendance-stats',
  'employee-requests',
  'performance-reviews',
  'salary-profiles',
  'payroll-records',
  'training-records',
  'users',
]);

const EMPLOYEE_TREE_MODULES = new Set([
  'employees',
  'onboarding-tasks',
  'probations',
  'employee-changes',
  'resignations',
  'contracts',
  'attendance-records',
  'attendance-stats',
  'employee-requests',
  'performance-reviews',
  'salary-profiles',
  'payroll-records',
  'training-records',
  'users',
]);

const RECORD_TREE_MODULES = new Set([
  'positions',
  'onboarding-tasks',
  'probations',
  'employee-changes',
  'resignations',
  'contracts',
  'attendance-records',
  'attendance-stats',
  'employee-requests',
  'performance-reviews',
  'salary-profiles',
  'payroll-records',
  'training-records',
  'users',
]);

const AI_ACTION_MODULES = new Set([
  'candidates',
  'offers',
]);

const TREE_ALL_KEY = 'all';

function treeKey(type: string, id?: string) {
  return id ? `${type}:${id}` : TREE_ALL_KEY;
}

function parseTreeKey(key: string) {
  if (!key || key === TREE_ALL_KEY) return { type: 'all', id: '' };
  const index = key.indexOf(':');
  if (index < 0) return { type: key, id: '' };
  return { type: key.slice(0, index), id: key.slice(index + 1) };
}

function getOrgTreeLookupNames(module: string) {
  if (!ORG_TREE_MODULES.has(module)) return [];
  const names = new Set(['departments']);
  if (EMPLOYEE_TREE_MODULES.has(module) && module !== 'employees') names.add('employees');
  return Array.from(names);
}

function buildDepartmentTree(departments: any[]) {
  const map = new Map<string, any>();
  departments.forEach((department) => {
    if (!department?.id) return;
    map.set(department.id, { ...department, children: [] });
  });
  const roots: any[] = [];
  map.forEach((node) => {
    const parent = node.parentId ? map.get(node.parentId) : null;
    if (parent && parent.id !== node.id) parent.children.push(node);
    else roots.push(node);
  });
  const sortNodes = (nodes: any[]) => {
    nodes.sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'));
    nodes.forEach((node) => sortNodes(node.children));
  };
  sortNodes(roots);
  return roots;
}

function buildDepartmentDescendantMap(departments: any[]) {
  const childrenByParent = new Map<string, string[]>();
  departments.forEach((department) => {
    if (!department?.id || !department.parentId) return;
    const siblings = childrenByParent.get(department.parentId) || [];
    siblings.push(department.id);
    childrenByParent.set(department.parentId, siblings);
  });

  const cache = new Map<string, Set<string>>();
  const collect = (id: string, seen = new Set<string>()) => {
    if (cache.has(id)) return cache.get(id);
    const result = new Set<string>([id]);
    if (seen.has(id)) return result;
    seen.add(id);
    (childrenByParent.get(id) || []).forEach((childId) => {
      collect(childId, new Set(seen)).forEach((value) => result.add(value));
    });
    cache.set(id, result);
    return result;
  };

  departments.forEach((department) => department?.id && collect(department.id));
  return cache;
}

function groupById(records: any[]) {
  return new Map(records.filter(Boolean).map((record) => [record.id, record]));
}

function groupBy(records: any[], getKey: (record: any) => string | undefined | null) {
  const map = new Map<string, any[]>();
  records.forEach((record) => {
    const key = getKey(record);
    if (!key) return;
    const list = map.get(key) || [];
    list.push(record);
    map.set(key, list);
  });
  return map;
}

function getEmployeeIdForRecord(record: any, module: string) {
  if (!record) return '';
  if (module === 'employees') return record.id || '';
  if (module === 'users') return record.employeeId || '';
  return record.employeeId || '';
}

function getDepartmentIdsForRecord(record: any, module: string, employeesById: Map<string, any>) {
  const ids = new Set<string>();
  if (!record) return ids;
  ['departmentId', 'beforeDepartmentId', 'afterDepartmentId', 'targetDepartmentId'].forEach((key) => {
    if (record[key]) ids.add(record[key]);
  });
  if (module === 'departments' && record.id) ids.add(record.id);
  if (module === 'employees' && record.departmentId) ids.add(record.departmentId);
  const employeeId = getEmployeeIdForRecord(record, module);
  const employee = employeeId ? employeesById.get(employeeId) : null;
  if (employee?.departmentId) ids.add(employee.departmentId);
  return ids;
}

function recordMatchesTreeSelection(
  record: any,
  module: string,
  selection: any,
  descendantsByDepartment: Map<string, Set<string>>,
  employeesById: Map<string, any>,
) {
  if (!ORG_TREE_MODULES.has(module) || selection.type === 'all') return true;

  if (selection.type === 'department') {
    const departmentIds = descendantsByDepartment.get(selection.id) || new Set([selection.id]);
    if (module === 'departments') {
      return departmentIds.has(record.id) || departmentIds.has(record.parentId);
    }
    const recordDepartments = getDepartmentIdsForRecord(record, module, employeesById);
    return Array.from(recordDepartments).some((id) => departmentIds.has(id));
  }

  if (selection.type === 'employee') {
    const employeeId = getEmployeeIdForRecord(record, module);
    return employeeId === selection.id || record.id === selection.id;
  }

  if (selection.type === 'record') {
    return record.id === selection.id || record.employeeId === selection.id;
  }

  return true;
}

function getRecordTitle(record: any, module: string) {
  if (!record) return '-';
  if (module === 'positions') return record.title || record.name || '未命名岗位';
  if (module === 'users') return record.name || record.email || '未命名用户';
  return record.name || record.title || record.contractNo || record.payrollMonth || record.attendanceDate || record.applyDate || record.id;
}

function getRecordSubtitle(record: any, module: string) {
  if (!record) return '';
  if (module === 'positions') return [record.category, record.level].filter(Boolean).join(' · ');
  if (module === 'onboarding-tasks') return [record.taskType, formatValue('status', record.status)].filter(Boolean).join(' · ');
  if (module === 'payroll-records') return [record.payrollMonth, formatValue('status', record.status)].filter(Boolean).join(' · ');
  if (module === 'attendance-records' || module === 'attendance-stats') return [record.attendanceDate, formatValue('status', record.status)].filter(Boolean).join(' · ');
  if (module === 'users') return [roleLabels[record.role] || record.role, formatValue('status', record.status)].filter(Boolean).join(' · ');
  return [formatValue('status', record.status), record.dueDate || record.applyDate || record.startDate || record.endDate].filter(Boolean).join(' · ');
}

function getTreeRecordIcon(module: string) {
  if (module === 'positions') return 'fa-briefcase';
  if (module === 'onboarding-tasks') return 'fa-list-check';
  if (module === 'contracts') return 'fa-file-contract';
  if (module === 'attendance-records' || module === 'attendance-stats') return 'fa-calendar-check';
  if (module === 'performance-reviews') return 'fa-star-half-alt';
  if (module === 'salary-profiles' || module === 'payroll-records') return 'fa-wallet';
  if (module === 'training-records') return 'fa-graduation-cap';
  if (module === 'users') return 'fa-users-cog';
  return 'fa-file-lines';
}

function isStatus(record: any, values: string[]) {
  return values.includes(String(record?.status || ''));
}

function canRunOfferAction(record: any, action: string) {
  const status = String(record?.status || '');
  const approvalStatus = String(record?.approvalStatus || '');
  if (action === 'offer-submit') return ['draft', 'rejected'].includes(approvalStatus) || status === 'draft';
  if (action === 'offer-accept') return ['approved', 'sent'].includes(approvalStatus) || ['sent', 'pending'].includes(status);
  if (action === 'offer-reject') return ['approved', 'sent', 'pending'].includes(approvalStatus) || ['sent', 'pending'].includes(status);
  if (action === 'offer-convert') return status === 'accepted' || approvalStatus === 'approved';
  return false;
}

function canGenerateOnboarding(record: any) {
  return isStatus(record, ['pending_onboard', 'probation', 'active']);
}

function canSubmitOnboarding(record: any) {
  return isStatus(record, ['pending_onboard']);
}

function canSubmitWorkflow(record: any) {
  return isStatus(record, ['draft', 'rejected']);
}

function canCancelWorkflow(record: any) {
  return isStatus(record, ['draft', 'pending']);
}

function canGeneratePerformanceAction(record: any) {
  return isStatus(record, ['completed', 'published']);
}

function OrgTreePanel({
  module,
  config,
  departments,
  employees,
  records,
  selectedKey,
  expandedKeys,
  descendantsByDepartment,
  employeesById,
  onSelect,
  onToggle,
  onCollapse,
}: any) {
  const departmentTree = useMemo(() => buildDepartmentTree(departments), [departments]);
  const directEmployeesByDepartment = useMemo(() => {
    const source = module === 'employees' ? records : employees;
    const recordsByEmployee = groupBy(records, (record) => getEmployeeIdForRecord(record, module));
    return groupBy(source.filter((employee: any) => {
      if (module === 'employees' || module === 'onboarding-tasks') return true;
      return (recordsByEmployee.get(employee.id) || []).length > 0;
    }), (employee: any) => employee.departmentId);
  }, [employees, records, module]);
  const recordsByEmployee = useMemo(() => groupBy(records, (record) => getEmployeeIdForRecord(record, module)), [records, module]);
  const recordsByDepartment = useMemo(() => {
    const map = new Map<string, any[]>();
    records.forEach((record) => {
      getDepartmentIdsForRecord(record, module, employeesById).forEach((departmentId) => {
        const list = map.get(departmentId) || [];
        list.push(record);
        map.set(departmentId, list);
      });
    });
    return map;
  }, [records, module, employeesById]);

  const rowClass = (key: string) => `hrm-org-tree-row ${selectedKey === key ? 'is-selected' : ''}`;
  const toggle = (event: any, key: string) => {
    event.stopPropagation();
    onToggle(key);
  };
  const countForDepartment = (departmentId: string) => {
    const deptIds = descendantsByDepartment.get(departmentId) || new Set([departmentId]);
    if (module === 'departments') return deptIds.size;
    if (module === 'employees') {
      return Array.from(deptIds).reduce((total, id) => total + (directEmployeesByDepartment.get(id) || []).length, 0);
    }
    return Array.from(deptIds).reduce((total, id) => total + (recordsByDepartment.get(id) || []).length, 0);
  };

  const renderToggle = (hasChildren: boolean, expanded: boolean, key: string) => (
    <button
      type="button"
      className={`hrm-org-tree-toggle ${hasChildren ? '' : 'is-empty'}`}
      onClick={(event) => hasChildren && toggle(event, key)}
      aria-label={expanded ? '收起' : '展开'}
    >
      {hasChildren && <AppIcon className={`fas ${expanded ? 'fa-caret-down' : 'fa-caret-right'}`} />}
    </button>
  );

  const renderRecordNode = (record: any, depth: number) => {
    const key = treeKey('record', record.id || record.employeeId);
    return (
      <button key={key} type="button" className={rowClass(key)} style={{ paddingLeft: `${depth * 14 + 8}px` }} onClick={() => onSelect(key)}>
        <span className="hrm-org-tree-toggle is-empty" />
        <AppIcon className={`fas ${getTreeRecordIcon(module)} hrm-org-tree-icon is-record`} />
        <span className="hrm-org-tree-main">
          <span className="hrm-org-tree-label">{getRecordTitle(record, module)}</span>
          {getRecordSubtitle(record, module) && <span className="hrm-org-tree-subtitle">{getRecordSubtitle(record, module)}</span>}
        </span>
      </button>
    );
  };

  const renderEmployeeNode = (employee: any, depth: number) => {
    const key = treeKey('employee', employee.id);
    const childRecords = module === 'employees' ? [] : (recordsByEmployee.get(employee.id) || []);
    const hasChildren = childRecords.length > 0;
    const expanded = expandedKeys.has(key);
    return (
      <div key={key}>
        <button type="button" className={rowClass(key)} style={{ paddingLeft: `${depth * 14 + 8}px` }} onClick={() => onSelect(key)}>
          {renderToggle(hasChildren, expanded, key)}
          <AppIcon className="fas fa-user hrm-org-tree-icon is-employee" />
          <span className="hrm-org-tree-main">
            <span className="hrm-org-tree-label">{employee.name || employee.employeeNo || '未命名员工'}</span>
            <span className="hrm-org-tree-subtitle">{[employee.employeeNo, employee.jobTitle].filter(Boolean).join(' · ')}</span>
          </span>
          <span className="hrm-org-tree-count">{module === 'employees' ? 1 : childRecords.length}</span>
        </button>
        {expanded && childRecords.length > 0 && (
          <div>{childRecords.map((record: any) => renderRecordNode(record, depth + 1))}</div>
        )}
      </div>
    );
  };

  const renderDepartmentNode = (department: any, depth = 0) => {
    const key = treeKey('department', department.id);
    const childDepartments = department.children || [];
    const directEmployees = directEmployeesByDepartment.get(department.id) || [];
    const directRecords = (recordsByDepartment.get(department.id) || []).filter((record: any) => !getEmployeeIdForRecord(record, module));
    const showEmployees = EMPLOYEE_TREE_MODULES.has(module);
    const showRecords = RECORD_TREE_MODULES.has(module) && !showEmployees;
    const visibleRecordNodes = showRecords ? directRecords : [];
    const hasChildren = childDepartments.length > 0 || directEmployees.length > 0 || visibleRecordNodes.length > 0;
    const expanded = expandedKeys.has(key);
    return (
      <div key={key}>
        <button type="button" className={rowClass(key)} style={{ paddingLeft: `${depth * 14 + 8}px` }} onClick={() => onSelect(key)}>
          {renderToggle(hasChildren, expanded, key)}
          <AppIcon className="fas fa-folder hrm-org-tree-icon is-department" />
          <span className="hrm-org-tree-main">
            <span className="hrm-org-tree-label">{department.name || '未命名部门'}</span>
            {department.code && <span className="hrm-org-tree-subtitle">{department.code}</span>}
          </span>
          <span className="hrm-org-tree-count">{countForDepartment(department.id)}</span>
        </button>
        {expanded && (
          <div>
            {childDepartments.map((child: any) => renderDepartmentNode(child, depth + 1))}
            {showEmployees && directEmployees.map((employee: any) => renderEmployeeNode(employee, depth + 1))}
            {visibleRecordNodes.map((record: any) => renderRecordNode(record, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <aside className="hrm-org-tree-panel">
      <div className="hrm-org-tree-head">
        <div>
          <div className="hrm-org-tree-title">组织架构</div>
          <div className="hrm-org-tree-meta">{config.title} · {records.length}</div>
        </div>
        <div className="hrm-org-tree-head-actions">
          <button type="button" className="hrm-org-tree-icon-button" onClick={() => onSelect(TREE_ALL_KEY)} aria-label="全部">
            <AppIcon className="fas fa-layer-group" />
          </button>
          <button type="button" className="hrm-org-tree-icon-button" onClick={onCollapse} aria-label="收起组织架构">
            <AppIcon className="fas fa-chevron-left" />
          </button>
        </div>
      </div>
      <div className="hrm-org-tree-body">
        <button type="button" className={rowClass(TREE_ALL_KEY)} onClick={() => onSelect(TREE_ALL_KEY)}>
          <span className="hrm-org-tree-toggle is-empty" />
          <AppIcon className="fas fa-building hrm-org-tree-icon is-root" />
          <span className="hrm-org-tree-main">
            <span className="hrm-org-tree-label">全部组织</span>
            <span className="hrm-org-tree-subtitle">全公司</span>
          </span>
          <span className="hrm-org-tree-count">{records.length}</span>
        </button>
        {departmentTree.length === 0 ? (
          <div className="hrm-org-tree-empty">暂无组织架构</div>
        ) : (
          departmentTree.map((department: any) => renderDepartmentNode(department, 0))
        )}
      </div>
    </aside>
  );
}

function recordMatchesFilter(record: any, field: any, value: any) {
  if (field.type === 'date-range' || field.type === 'datetime-range' || field.type === 'number-range') {
    const start = value?.from;
    const end = value?.to;
    if (!start && !end) return true;
    if (field.type === 'number-range') {
      const raw = Number(record[field.key]);
      if (Number.isNaN(raw)) return false;
      if (start !== '' && start !== undefined && raw < Number(start)) return false;
      if (end !== '' && end !== undefined && raw > Number(end)) return false;
      return true;
    }
    const recordDate = getRecordDate(record[field.key]);
    if (!recordDate) return false;
    if (start) {
      const startDate = new Date(`${start}${field.type === 'date-range' ? 'T00:00:00' : ''}`);
      if (recordDate < startDate) return false;
    }
    if (end) {
      const endDate = new Date(`${end}${field.type === 'date-range' ? 'T23:59:59' : ''}`);
      if (recordDate > endDate) return false;
    }
    return true;
  }

  if (!value) return true;

  if (field.key === '__exceptionState') {
    if (value === 'has_exception') return Number(record.exceptions || 0) > 0;
    if (value === 'no_exception') return Number(record.exceptions || 0) === 0;
    if (value === 'has_request') return Number(record.approvedRequests || 0) > 0;
    if (value === 'no_request') return Number(record.approvedRequests || 0) === 0;
    return true;
  }

  if (field.type === 'text') {
    return compactText(record[field.key]).toLowerCase().includes(normalizeFilterValue(value));
  }

  if (field.type === 'month') {
    return compactText(record[field.key]).slice(0, 7) === value;
  }

  if (field.options === booleanOptions || typeof record[field.key] === 'boolean') {
    return String(!!record[field.key]) === value;
  }

  const currentValue = record[field.key];
  if (Array.isArray(currentValue)) return currentValue.map(normalizeFilterValue).includes(normalizeFilterValue(value));
  return normalizeFilterValue(currentValue) === normalizeFilterValue(value);
}

function defaultPerformanceSalaryAdjustment(record: any) {
  const grade = String(record?.grade || '').toUpperCase();
  if (grade === 'S') return 3000;
  if (grade === 'A') return 2000;
  if (grade === 'B') return 800;
  if (grade === 'D') return -500;
  return 0;
}

function todayInput() {
  return new Date().toISOString().slice(0, 10);
}

function dateInput(value: any) {
  if (!value) return todayInput();
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return todayInput();
  return date.toISOString().slice(0, 10);
}

function shiftDate(value: any, days: number) {
  const date = new Date(dateInput(value));
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function shiftMonth(value: any, months: number) {
  const date = new Date(dateInput(value));
  date.setMonth(date.getMonth() + months);
  return date.toISOString().slice(0, 10);
}

function workflowTransitionPayload(record: any, transition: string) {
  if (transition === 'renew') {
    const startDate = shiftDate(record.endDate || todayInput(), 1);
    const endDate = shiftDate(shiftMonth(startDate, 12), -1);
    return {
      startDate,
      endDate,
      reminderDate: shiftDate(endDate, -30),
      remark: record.remark || '续签合同',
    };
  }
  if (transition === 'terminate') {
    return { remark: record.remark || '合同终止' };
  }
  if (transition === 'approve') {
    return {
      regularDate: record.regularDate || todayInput(),
      managerReview: record.managerReview || '',
      result: '通过',
    };
  }
  if (transition === 'extend') {
    return {
      expectedRegularDate: shiftMonth(record.expectedRegularDate || todayInput(), 1),
      result: '延期',
      remark: record.remark || '延期转正',
    };
  }
  if (transition === 'reject') {
    return { result: '驳回', remark: record.remark || '流程驳回' };
  }
  if (transition === 'complete') {
    return {
      actualLeaveDate: record.actualLeaveDate || record.expectedLeaveDate || todayInput(),
      handoverItems: record.handoverItems || [],
    };
  }
  return {};
}

export default function HrmModulePage() {
  const { module = '' } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const currentUserRole = authUtils.getUser()?.role;
  const config = moduleConfigs[module];
  const [records, setRecords] = useState<any[]>([]);
  const [lookups, setLookups] = useState<Record<string, any[]>>({});
  const [keyword, setKeyword] = useState('');
  const [filterValues, setFilterValues] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [detail, setDetail] = useState<any | null>(null);
  const [form, setForm] = useState<Record<string, any>>({});
  const [month, setMonth] = useState(() => {
    const param = searchParams.get('month');
    return param && /^\d{4}-\d{2}$/.test(param) ? param : new Date().toISOString().slice(0, 7);
  });
  const routeKey = `${module}:${month}`;
  const [aiResult, setAiResult] = useState<any | null>(null);
  const [lifecycle, setLifecycle] = useState<any | null>(null);
  const [lifecycleLoading, setLifecycleLoading] = useState(false);
  const [workflow, setWorkflow] = useState<any | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [resetCredential, setResetCredential] = useState<any | null>(null);
  const [passwordResetting, setPasswordResetting] = useState(false);
  const [selectedTreeKey, setSelectedTreeKey] = useState(TREE_ALL_KEY);
  const [expandedTreeKeys, setExpandedTreeKeys] = useState<Set<string>>(() => new Set([TREE_ALL_KEY]));
  const [orgTreeCollapsed, setOrgTreeCollapsed] = useState(false);
  const [openedQueryRecordId, setOpenedQueryRecordId] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_HRM_PAGE_SIZE);
  const [pageMeta, setPageMeta] = useState<HrmPageMeta>(() => defaultHrmPageMeta());
  const [debouncedKeyword, setDebouncedKeyword] = useState('');
  const [activeRouteKey, setActiveRouteKey] = useState(routeKey);
  const filterFields = useMemo(() => moduleFilterConfigs[module] || [], [module]);
  const treeEnabled = ORG_TREE_MODULES.has(module);
  const treeSelection = useMemo(() => parseTreeKey(selectedTreeKey), [selectedTreeKey]);
  const searchDebounceRef = useRef<number | undefined>(undefined);
  const loadGenerationRef = useRef(0);
  const departmentsForTree = useMemo(
    () => module === 'departments' ? records : (lookups.departments || []),
    [module, records, lookups.departments],
  );
  const employeesForTree = useMemo(
    () => module === 'employees' ? records : (lookups.employees || []),
    [module, records, lookups.employees],
  );
  const employeesById = useMemo(() => groupById(employeesForTree), [employeesForTree]);
  const descendantsByDepartment = useMemo(() => buildDepartmentDescendantMap(departmentsForTree), [departmentsForTree]);

  useEffect(() => {
    const handleAuthChanged = () => {
      hrmRecordCache.clear();
      hrmRecordInflight.clear();
      loadGenerationRef.current += 1;
      setRecords([]);
      setPageMeta(defaultHrmPageMeta(pageSize));
    };
    window.addEventListener('hpt-auth-changed', handleAuthChanged);
    return () => window.removeEventListener('hpt-auth-changed', handleAuthChanged);
  }, [pageSize]);

  const buildHrmListParams = () => {
    const params: Record<string, string | number | boolean | undefined | null> = {
      page: currentPage,
      size: pageSize,
    };
    const trimmedKeyword = debouncedKeyword.trim();
    if (trimmedKeyword) params.keyword = trimmedKeyword;
    filterFields.forEach((field: any) => {
      const value = filterValues[field.key];
      if (!hasFilterValue(value)) return;
      if (field.type === 'date-range' || field.type === 'datetime-range' || field.type === 'number-range') {
        if (value.from) params[`${field.key}From`] = value.from;
        if (value.to) params[`${field.key}To`] = value.to;
      } else if (!String(field.key).startsWith('__')) {
        params[field.key] = value;
      }
    });
    const selection = parseTreeKey(selectedTreeKey);
    if (treeEnabled && selection.type === 'employee' && EMPLOYEE_TREE_MODULES.has(module)) {
      params.employeeId = selection.id;
    }
    if (treeEnabled && selection.type === 'record') {
      params.id = selection.id;
    }
    if (treeEnabled && selection.type === 'department') {
      const departmentIds = Array.from(descendantsByDepartment.get(selection.id) || new Set([selection.id]));
      if (departmentIds.length) params.departmentIds = departmentIds.join(',');
    }
    return params;
  };
  const listParamsKey = useMemo(
    () => stableHrmListParamsKey(buildHrmListParams()),
    [currentPage, pageSize, debouncedKeyword, filterValues, selectedTreeKey, module, filterFields, treeEnabled, descendantsByDepartment],
  );
  const cacheKey = `${authUtils.getSessionScopeKey()}:${module}:${month}:${listParamsKey}`;

  useEffect(() => {
    if (!config) return;
    document.title = `${config.title} - 恒聘通HRM`;
    setDetail(null);
    setAiResult(null);
    setWorkflow(null);
    setResetCredential(null);
    setKeyword('');
    setDebouncedKeyword('');
    const nextFilters = {};
    if (module === 'attendance-records') {
      const bounds = monthDateBounds(month);
      if (bounds) nextFilters.attendanceDate = bounds;
      const employeeId = searchParams.get('employeeId');
      if (employeeId) nextFilters.employeeId = employeeId;
    }
    setFilterValues(nextFilters);
    setSelectedTreeKey(TREE_ALL_KEY);
    setExpandedTreeKeys(new Set([TREE_ALL_KEY]));
    setOpenedQueryRecordId('');
    setCurrentPage(1);
    setPageMeta(defaultHrmPageMeta(pageSize));
    setActiveRouteKey(routeKey);
  }, [module, month, searchParams.toString()]);

  useEffect(() => {
    if (module !== 'attendance-records') return;
    const monthParam = searchParams.get('month');
    if (monthParam && /^\d{4}-\d{2}$/.test(monthParam) && monthParam !== month) {
      setMonth(monthParam);
    }
  }, [module, month, searchParams.toString()]);

  useEffect(() => {
    if (searchDebounceRef.current) window.clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = window.setTimeout(() => {
      setDebouncedKeyword(keyword.trim());
    }, 220);
    return () => {
      if (searchDebounceRef.current) window.clearTimeout(searchDebounceRef.current);
    };
  }, [keyword]);

  useEffect(() => {
    if (activeRouteKey !== routeKey) return;
    void loadData();
  }, [activeRouteKey, routeKey, currentPage, pageSize, listParamsKey]);

  // Load lookups when the current module needs them for filters or forms.
  useEffect(() => {
    if ((modalOpen || treeEnabled || filterFields.some((field: any) => field.lookup)) && lookupNames.length > 0) {
      loadLookups();
    }
  }, [modalOpen, module]);

  const lookupNames = useMemo(() => {
    const names = new Set<string>();
    config?.fields?.forEach((field: any) => field.lookup && names.add(field.lookup));
    filterFields.forEach((field: any) => field.lookup && names.add(field.lookup));
    getOrgTreeLookupNames(module).forEach((name) => names.add(name));
    return Array.from(names);
  }, [config, filterFields, module]);

  const toggleTreeKey = (key: string) => {
    setExpandedTreeKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const selectTreeKey = (key: string) => {
    setCurrentPage(1);
    setSelectedTreeKey(key);
  };

  const loadLookups = async () => {
    if (!config) return;
    const tasks = lookupNames.map(async (name) => {
      try {
        const data = name === 'jobs' ? await jobsApi.getAll() : await hrmApi.list(name);
        return [name, data] as [string, any[]];
      } catch {
        return [name, []] as [string, any[]];
      }
    });
    const entries = await Promise.all(tasks);
    setLookups(Object.fromEntries(entries));
  };

  const loadData = async (options: { forceRefresh?: boolean } = {}) => {
    if (!config) return;
    if (activeRouteKey !== routeKey) return;
    const generation = ++loadGenerationRef.current;
    const cachedEntry = options.forceRefresh ? null : readHrmRecordCache(cacheKey);
    if (cachedEntry) {
      if (generation !== loadGenerationRef.current) return;
      setRecords(cachedEntry.records);
      setPageMeta(cachedEntry.pageMeta);
      setLoading(false);
      return;
    }
    setLoading(true);
    let request: Promise<HrmRecordCacheEntry> | undefined;
    try {
      request = hrmRecordInflight.get(cacheKey);
      if (!request || options.forceRefresh) {
        request = (async () => {
          if (config.special === 'approval-list') {
            const records = await hrmApi.approvals(config.approvalKind);
            return { records, pageMeta: { total: records.length, page: 1, size: records.length || pageSize, pages: 1 } };
          }
          if (config.special === 'attendance-stats') {
            const data = await hrmApi.attendanceMonthly(month);
            const records = data.records || [];
            return { records, pageMeta: { total: records.length, page: 1, size: records.length || pageSize, pages: 1 } };
          }
          const pageResult = await hrmApi.listPage(config.resource, buildHrmListParams());
          return {
            records: pageResult.items || [],
            pageMeta: {
              total: Number(pageResult.total || 0),
              page: Number(pageResult.page || currentPage),
              size: Number(pageResult.size || pageSize),
              pages: Math.max(1, Number(pageResult.pages || 1)),
            },
          };
        })();
        hrmRecordInflight.set(cacheKey, request);
      }
      const nextEntry = await request;
      if (generation !== loadGenerationRef.current) return;
      const cached = writeHrmRecordCache(cacheKey, nextEntry);
      setRecords(cached.records);
      setPageMeta(cached.pageMeta);
    } catch (error: any) {
      if (generation !== loadGenerationRef.current) return;
      toast.error(error.message || '加载失败');
    } finally {
      if (request && hrmRecordInflight.get(cacheKey) === request) {
        hrmRecordInflight.delete(cacheKey);
      }
      if (generation === loadGenerationRef.current) setLoading(false);
    }
  };

  const changePageSize = (nextSize: number) => {
    setPageSize(nextSize);
    setCurrentPage(1);
  };

  const goToPage = (nextPage: number) => {
    const boundedPage = Math.max(1, Math.min(pageMeta.pages || 1, nextPage));
    setCurrentPage(boundedPage);
  };

  const openCreate = () => {
    const initial: Record<string, any> = {};
    config.fields?.forEach((field: any) => { initial[field.name] = field.defaultValue ?? (field.type === 'checkbox' ? false : ''); });
    const selection = parseTreeKey(selectedTreeKey);
    if (selection.type === 'department') {
      if (module === 'departments') initial.parentId = selection.id;
      if (config.fields?.some((field: any) => field.name === 'departmentId')) initial.departmentId = selection.id;
      if (config.fields?.some((field: any) => field.name === 'afterDepartmentId')) initial.afterDepartmentId = selection.id;
    }
    if (selection.type === 'employee' && config.fields?.some((field: any) => field.name === 'employeeId')) {
      initial.employeeId = selection.id;
    }
    setEditing(null);
    setForm(initial);
    setModalOpen(true);
  };

  const openEdit = (record: any) => {
    const initial: Record<string, any> = {};
    config.fields?.forEach((field: any) => { initial[field.name] = toInputValue(record[field.name], field.type); });
    setEditing(record);
    setForm(initial);
    setModalOpen(true);
  };

  const openDetail = (record: any) => {
    setDetail(record);
    setWorkflow(null);
    if (LIFECYCLE_WORKFLOW_MODULES.has(module) && record?.id) {
      loadWorkflow(record);
    }
  };

  const loadWorkflow = async (record: any) => {
    if (!record?.id || !LIFECYCLE_WORKFLOW_MODULES.has(module)) return;
    setWorkflowLoading(true);
    try {
      const result = await hrmApi.getWorkflow(config.resource, record.id);
      setWorkflow(result);
    } catch (error: any) {
      setWorkflow(null);
      toast.error(error.message || '工作流加载失败');
    } finally {
      setWorkflowLoading(false);
    }
  };

  useEffect(() => {
    if (!config || loading || !LIFECYCLE_WORKFLOW_MODULES.has(module)) return;
    const targetId = searchParams.get('id');
    if (!targetId || openedQueryRecordId === targetId || detail?.id === targetId) return;
    const match = records.find((record) => String(record.id) === targetId);
    if (!match) return;
    setOpenedQueryRecordId(targetId);
    openDetail(match);
  }, [config, loading, module, records, searchParams, openedQueryRecordId, detail?.id]);

  const getOptions = (field: any) => {
    if (field.options) return field.options;
    const data = lookups[field.lookup] || [];
    return data.map((item: any) => ({ label: getLookupLabel(item), value: item.id }));
  };

  const getFilterOptions = (field: any) => {
    if (field.options) return field.options;
    if (field.lookup) return (lookups[field.lookup] || []).map((item: any) => ({ label: getLookupLabel(item), value: item.id }));
    if (field.source === 'records') return getRecordOptions(records, field.key);
    return [];
  };

  const updateFilter = (key: string, value: any) => {
    setCurrentPage(1);
    setFilterValues((prev) => ({ ...prev, [key]: value }));
  };

  const activeFilterCount = useMemo(() => {
    let count = keyword.trim() ? 1 : 0;
    if (treeEnabled && selectedTreeKey !== TREE_ALL_KEY) count += 1;
    filterFields.forEach((field: any) => {
      const value = filterValues[field.key];
      if (field.type === 'date-range' || field.type === 'datetime-range' || field.type === 'number-range') {
        if (value?.from || value?.to) count += 1;
      } else if (value) {
        count += 1;
      }
    });
    return count;
  }, [keyword, filterValues, filterFields, treeEnabled, selectedTreeKey]);

  const filteredRecords = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return records.filter((record) => {
      if (!recordMatchesTreeSelection(record, module, treeSelection, descendantsByDepartment, employeesById)) return false;
      const matchesKeyword = !kw || compactText(Object.values(record)).toLowerCase().includes(kw);
      if (!matchesKeyword) return false;
      return filterFields.every((field: any) => recordMatchesFilter(record, field, filterValues[field.key]));
    });
  }, [records, keyword, filterFields, filterValues, module, treeSelection, descendantsByDepartment, employeesById]);

  const resetFilters = () => {
    setKeyword('');
    setDebouncedKeyword('');
    if (module === 'attendance-records') {
      const bounds = monthDateBounds(month);
      const employeeId = searchParams.get('employeeId');
      setFilterValues({
        ...(bounds ? { attendanceDate: bounds } : {}),
        ...(employeeId ? { employeeId } : {}),
      });
    } else {
      setFilterValues({});
    }
    setCurrentPage(1);
    selectTreeKey(TREE_ALL_KEY);
  };

  const renderFilterField = (field: any) => {
    return (
      <FilterField
        key={field.key}
        label={field.label}
        type={field.type || 'select'}
        value={filterValues[field.key]}
        options={toFilterOptions(getFilterOptions(field))}
        searchable={field.type === 'combo' || Boolean(field.lookup)}
        onChange={(next) => {
          if (field.type === 'date-range' || field.type === 'datetime-range' || field.type === 'number-range') {
            updateFilter(field.key, next);
          } else {
            updateFilter(field.key, next);
          }
        }}
      />
    );
  };

  const submitForm = async (event: any) => {
    event.preventDefault();
    // 必填字段校验（之前红星仅装饰，未强制）
    const missing = (config.fields || []).filter(
      (f: any) => f.required && (
        form[f.name] === undefined || form[f.name] === null || String(form[f.name]).trim() === ''
      )
    );
    if (missing.length) {
      toast.error(`请填写必填项：${missing.map((f: any) => f.label).join('、')}`);
      return;
    }
    // 日期范围校验：成对 start/end 字段
    const startName = (config.fields || []).find((f: any) => /startTime|startDate|hireDate/i.test(f.name))?.name;
    const endName = (config.fields || []).find((f: any) => /endTime|endDate/i.test(f.name))?.name;
    if (startName && endName && form[startName] && form[endName] && new Date(form[endName]) < new Date(form[startName])) {
      toast.error('结束时间不能早于开始时间');
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form };
      let saved: any = null;
      if (editing) {
        saved = await hrmApi.update(config.resource, editing.id, payload);
      } else if (module === 'users') {
        const result = await hrmApi.createUser(payload);
        setResetCredential({
          ...result,
          targetName: result.account.name || result.account.email || '新用户',
          accountLabel: '新建的管理后台账号',
        });
      } else {
        saved = await hrmApi.create(config.resource, payload);
      }
      if (saved?.performanceIndicatorWarning) {
        toast.warning(saved.performanceIndicatorWarning);
      }
      setModalOpen(false);
      await loadData({ forceRefresh: true });
    } catch (error: any) {
      toast.error(error.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const removeRecord = async (record: any) => {
    const ok = await confirm({
      title: '确认删除',
      message: `确定删除「${record.name || record.title || record.id}」吗？此操作不可撤销。`,
      danger: true,
      confirmText: '删除',
    });
    if (!ok) return;
    try {
      await hrmApi.remove(config.resource, record.id);
      toast.success('删除成功');
      await loadData({ forceRefresh: true });
    } catch (error: any) {
      toast.error(error.message || '删除失败');
    }
  };

  const closeResetCredential = () => {
    setResetCredential(null);
  };

  const copyResetCredential = async () => {
    if (!resetCredential?.initialPassword) return;
    try {
      await navigator.clipboard.writeText(resetCredential.initialPassword);
      toast.success('一次性密码已复制');
    } catch {
      toast.error('复制失败，请手动选择密码');
    }
  };

  const resetAccountPassword = async (record: any, accountType: 'hrm' | 'employee_portal') => {
    const isPortal = accountType === 'employee_portal';
    const targetName = record.name || record.email || record.employeeNo || record.id;
    const ok = await confirm({
      title: isPortal ? '重置员工门户密码' : '重置后台密码',
      message: isPortal
        ? `确定为「${targetName}」生成新的员工门户一次性密码吗？当前密码将立即失效。`
        : `确定为「${targetName}」生成新的后台一次性密码吗？当前密码将立即失效。`,
      danger: true,
      confirmText: '确认重置',
    });
    if (!ok) return;

    setPasswordResetting(true);
    try {
      const result = isPortal
        ? await hrmApi.resetEmployeePortalPassword(record.id)
        : await hrmApi.resetUserPassword(record.id);
      setResetCredential({
        ...result,
        targetName,
        accountLabel: isPortal ? '员工门户账号' : '管理后台账号',
      });
    } catch (error: any) {
      toast.error(error.message || '密码重置失败');
    } finally {
      setPasswordResetting(false);
    }
  };

  const runAction = async (record: any, action: string) => {
    try {
      if (action.startsWith('workflow:')) {
        const transition = action.slice('workflow:'.length);
        const transitionConfig = workflow?.transitions?.find((item: any) => item.key === transition);
        const ok = await confirm({
          title: transitionConfig?.label || '确认操作',
          message: `确定对「${record.employeeName || record.contractNo || record.name || record.id}」执行该工作流动作吗？`,
          confirmText: transitionConfig?.label || '确认',
        });
        if (!ok) return;
        const result = await hrmApi.runWorkflowTransition(config.resource, record.id, transition, workflowTransitionPayload(record, transition));
        setDetail(result.record);
        setWorkflow(result.workflow);
        toast.success('工作流状态已更新');
        await loadData({ forceRefresh: true });
        return;
      }
      if (action === 'offer-submit') await hrmApi.postAction(`offers/${record.id}/submit-approval`);
      if (action === 'offer-accept') await hrmApi.postAction(`offers/${record.id}/accept`);
      if (action === 'offer-reject') await hrmApi.postAction(`offers/${record.id}/reject`);
      if (action === 'offer-convert') await hrmApi.postAction(`offers/${record.id}/convert-to-employee`);
      if (action === 'generate-onboarding') await hrmApi.postAction(`employees/${record.id}/generate-onboarding`);
      if (action === 'submit-onboarding') await hrmApi.postAction(`employees/${record.id}/submit-onboarding`);
      if (action === 'submit') await hrmApi.postAction(`${module}/${record.id}/submit`);
      if (action === 'cancel') await hrmApi.postAction(`${module}/${record.id}/cancel`);
      if (action === 'payroll-generate-month') await hrmApi.postAction('payroll-records/generate-month', { month });
      if (action === 'performance-salary-change') {
        await hrmApi.postAction(`performance-reviews/${record.id}/generate-salary-change`, {
          salaryAdjustment: defaultPerformanceSalaryAdjustment(record),
          effectiveDate: new Date().toISOString().slice(0, 10),
        });
      }
      if (action === 'performance-training-plan') await hrmApi.postAction(`performance-reviews/${record.id}/generate-training-plan`);
      if (action === 'approve') await hrmApi.handleApproval(record.id, 'approve', '同意');
      if (action === 'reject') await hrmApi.handleApproval(record.id, 'reject', '不同意');
      if (action === 'ai') {
        if (!AI_ACTION_MODULES.has(module) || !config.aiScene) {
          toast.info('当前模块未启用AI动作');
          return;
        }
        const result = await hrmApi.ai(config.aiScene || module, { module, record });
        setAiResult(result);
        return;
      }
      if (action === 'employee-lifecycle') {
        setLifecycleLoading(true);
        const result = await hrmApi.employeeLifecycle(record.id);
        setLifecycle(result);
        return;
      }
      toast.success('操作完成，关联模块已同步更新');
      await loadData({ forceRefresh: true });
    } catch (error: any) {
      toast.error(error.message || '操作失败');
    } finally {
      if (action === 'employee-lifecycle') setLifecycleLoading(false);
    }
  };

  const getStatusBadgeClass = (status: string) => {
    return getUnifiedStatusBadgeClass(status);
  };
  const canUseAi = AI_ACTION_MODULES.has(module) && Boolean(config?.aiScene);

  if (!config) {
    return <Layout><div className="bg-white rounded-xl p-10 text-center"><h2 className="text-xl font-bold text-gray-800">模块不存在</h2><button onClick={() => navigate('/home')} className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg">返回首页</button></div></Layout>;
  }

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        {/* Page Header */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center">
                <AppIcon className={`fas ${config.icon || 'fa-table'} text-sm`} />
              </div>
              <div>
                <h1 className="text-[15px] font-bold text-gray-900">{config.title}</h1>
                <p className="text-xs text-gray-400 mt-0.5">{config.description}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {(config.special === 'attendance-stats' || module === 'attendance-records') && (
                <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500/40" aria-label="考勤月份" />
              )}
              {module === 'attendance-records' && (
                <button type="button" onClick={() => navigate('/attendance-stats')} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-600 hover:text-blue-600 hover:border-blue-200">
                  按月汇总
                </button>
              )}
              {module === 'payroll-records' && (
                <>
                  <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500/40" />
                  <button onClick={() => runAction({}, 'payroll-generate-month')} className="px-4 py-1.5 bg-emerald-500 text-white rounded-lg text-sm font-medium hover:bg-emerald-600 transition-colors shadow-sm">
                    <AppIcon className="fas fa-calculator mr-1.5 text-xs" />生成月度工资
                  </button>
                </>
              )}
              {!config.readOnly && !config.special && (
                (!config.readOnlyCreate || (config.allowAdminCreate && module === 'users' && currentUserRole === 'admin')) &&
                <button onClick={openCreate} className="px-4 py-1.5 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors shadow-sm">
                  <AppIcon className="fas fa-plus mr-1.5 text-xs" />新增{config.title.replace('管理', '')}
                </button>
              )}
            </div>
          </div>
        </div>

        <div className={treeEnabled ? `hrm-org-workspace ${orgTreeCollapsed ? 'is-tree-collapsed' : ''}` : ''}>
        {treeEnabled && orgTreeCollapsed && (
          <aside className="hrm-org-tree-rail">
            <button type="button" className="hrm-org-tree-rail-button" onClick={() => setOrgTreeCollapsed(false)} aria-label="展开组织架构">
              <AppIcon className="fas fa-chevron-right" />
            </button>
            <div className="hrm-org-tree-rail-label">组织</div>
          </aside>
        )}
        {treeEnabled && !orgTreeCollapsed && (
          <OrgTreePanel
            module={module}
            config={config}
            departments={departmentsForTree}
            employees={employeesForTree}
            records={records}
            selectedKey={selectedTreeKey}
            expandedKeys={expandedTreeKeys}
            descendantsByDepartment={descendantsByDepartment}
            employeesById={employeesById}
            onSelect={selectTreeKey}
            onToggle={toggleTreeKey}
            onCollapse={() => setOrgTreeCollapsed(true)}
          />
        )}

        {/* Table Card */}
        <div className="bg-white rounded-xl border border-gray-100 min-w-0">
          {/* Search / Filter Bar */}
          <div className="px-5 py-3 border-b border-gray-100 space-y-3">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
              <div className="flex items-center gap-2 flex-1 max-w-xl">
                <SearchInput
                  value={keyword}
                  onChange={(value) => {
                    setCurrentPage(1);
                    setKeyword(value);
                  }}
                  placeholder={`搜索${config.title}...`}
                  className="flex-1"
                />
                <button onClick={() => loadData({ forceRefresh: true })} className="px-3.5 py-[6px] bg-gray-800 text-white rounded-lg text-sm hover:bg-gray-900 transition-colors flex-shrink-0">
                  <AppIcon className="fas fa-rotate mr-1 text-xs" />刷新
                </button>
                <button onClick={resetFilters} disabled={activeFilterCount === 0} className="px-3.5 py-[6px] border border-gray-200 rounded-lg text-sm text-gray-500 hover:text-blue-600 hover:border-blue-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0">
                  <AppIcon className="fas fa-rotate-left mr-1 text-xs" />重置{activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
                </button>
              </div>
              <div className="text-xs text-gray-400">
                本页 <span className="font-medium text-gray-600">{filteredRecords.length}</span> 条，
                共 <span className="font-medium text-gray-600">{pageMeta.total}</span> 条
              </div>
            </div>
            {filterFields.length > 0 && (
              <div className="hpt-filter-surface p-3">
                <div className="hpt-filter-grid">
                {filterFields.map(renderFilterField)}
                </div>
              </div>
            )}
          </div>

          {/* Table */}
          {loading ? (
            <div className="py-24 text-center text-gray-400"><AppIcon className="fas fa-spinner fa-spin text-xl" /><div className="mt-2 text-sm">加载中...</div></div>
          ) : filteredRecords.length === 0 ? (
            <div className="py-24 text-center"><AppIcon className="fas fa-inbox text-3xl text-gray-200 mb-3" /><div className="text-sm text-gray-400">{records.length === 0 ? '暂无数据' : '没有匹配的记录'}</div></div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full hrm-table">
                <thead>
                  <tr className="border-b border-gray-100">
                    {config.columns.map((column: string) => <th key={column} className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase whitespace-nowrap bg-gray-50/80">{columnLabels[column] || column}</th>)}
                    <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase whitespace-nowrap bg-gray-50/80">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRecords.map((record) => (
                    <tr key={record.id || record.employeeId} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors">
                      {config.columns.map((column: string) => (
                        <td key={column} className="px-4 py-2.5 text-[13px] text-gray-600 max-w-xs truncate" title={formatValue(column, record[column])}>
                          {(column === 'status' || column === 'approvalStatus') ? (
                            <span className={getStatusBadgeClass(formatValue(column, record[column]))}>{formatValue(column, record[column])}</span>
                          ) : column === 'name' || column === 'employeeName' || column === 'candidateName' ? (
                            <span className="font-medium text-gray-800">{formatValue(column, record[column])}</span>
                          ) : formatValue(column, record[column])}
                        </td>
                      ))}
                      <td className="px-4 py-2.5 text-right whitespace-nowrap">
                        <button onClick={() => openDetail(record)} className="text-xs text-gray-500 hover:text-blue-600 mr-2 transition-colors">
                          <AppIcon className="fas fa-eye text-[11px]" />详情
                        </button>
                        {canUseAi && <button onClick={() => runAction(record, 'ai')} className="text-xs text-purple-500 hover:text-purple-700 mr-2 transition-colors"><AppIcon className="fas fa-wand-magic-sparkles text-[11px]" />AI</button>}
                        {!config.readOnly && !config.special && <button onClick={() => openEdit(record)} className="text-xs text-blue-500 hover:text-blue-700 mr-2 transition-colors">
                          <AppIcon className="fas fa-edit text-[11px]" />编辑
                        </button>}
                        {module === 'offers' && <>
                          {canRunOfferAction(record, 'offer-submit') && <button onClick={() => runAction(record, 'offer-submit')} className="text-xs text-indigo-500 hover:text-indigo-700 mr-2"><AppIcon className="fas fa-paper-plane text-[11px]" />提审</button>}
                          {canRunOfferAction(record, 'offer-accept') && <button onClick={() => runAction(record, 'offer-accept')} className="text-xs text-green-500 hover:text-green-700 mr-2"><AppIcon className="fas fa-check text-[11px]" />接受</button>}
                          {canRunOfferAction(record, 'offer-reject') && <button onClick={() => runAction(record, 'offer-reject')} className="text-xs text-red-500 hover:text-red-700 mr-2"><AppIcon className="fas fa-times text-[11px]" />拒绝</button>}
                          {canRunOfferAction(record, 'offer-convert') && <button onClick={() => runAction(record, 'offer-convert')} className="text-xs text-orange-500 hover:text-orange-700 mr-2"><AppIcon className="fas fa-user-plus text-[11px]" />转员工</button>}
                        </>}
                        {module === 'performance-reviews' && <>
                          {canGeneratePerformanceAction(record) && <button onClick={() => runAction(record, 'performance-salary-change')} className="text-xs text-emerald-500 hover:text-emerald-700 mr-2"><AppIcon className="fas fa-wallet text-[11px]" />生成调薪</button>}
                          {canGeneratePerformanceAction(record) && <button onClick={() => runAction(record, 'performance-training-plan')} className="text-xs text-cyan-500 hover:text-cyan-700 mr-2"><AppIcon className="fas fa-graduation-cap text-[11px]" />生成培训</button>}
                        </>}
                        {module === 'courses' && <>
                          <button onClick={() => navigate(`/course-edit/${record.id}`)} className="text-xs text-indigo-500 hover:text-indigo-700 mr-2"><AppIcon className="fas fa-edit text-[11px]" />编辑课程</button>
                        </>}
                        {module === 'exam-tasks' && <>
                          <button onClick={() => navigate(`/exam-task-progress/${record.id}`)} className="text-xs text-emerald-500 hover:text-emerald-700 mr-2"><AppIcon className="fas fa-chart-bar text-[11px]" />进度</button>
                        </>}
                        {['employee-requests', 'probations', 'employee-changes', 'resignations'].includes(module) && <>
                          {canSubmitWorkflow(record) && <button onClick={() => runAction(record, 'submit')} className="text-xs text-indigo-500 hover:text-indigo-700 mr-2"><AppIcon className="fas fa-paper-plane text-[11px]" />提交</button>}
                          {canCancelWorkflow(record) && <button onClick={() => runAction(record, 'cancel')} className="text-xs text-gray-500 hover:text-gray-700 mr-2"><AppIcon className="fas fa-undo text-[11px]" />撤销</button>}
                        </>}
                        {module === 'pending-approvals' && <>
                          <button onClick={() => runAction(record, 'approve')} className="text-xs text-green-500 hover:text-green-700 mr-2"><AppIcon className="fas fa-check text-[11px]" />通过</button>
                          <button onClick={() => runAction(record, 'reject')} className="text-xs text-red-500 hover:text-red-700 mr-2"><AppIcon className="fas fa-times text-[11px]" />驳回</button>
                        </>}
                        {!config.readOnly && !config.special && <button onClick={() => removeRecord(record)} className="text-xs text-red-400 hover:text-red-600 transition-colors"><AppIcon className="fas fa-trash text-[11px]" />删除</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!config.special && (
            <div className="px-5 py-3 border-t border-gray-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 text-xs text-gray-500">
              <div>
                第 <span className="font-medium text-gray-700">{pageMeta.page}</span> / {pageMeta.pages || 1} 页
                <span className="ml-2 text-gray-400">每页</span>
                <select
                  aria-label="每页条数"
                  value={pageSize}
                  onChange={(event) => changePageSize(Number(event.target.value))}
                  className="mx-1 rounded-md border border-gray-200 bg-white px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                >
                  {HRM_PAGE_SIZE_OPTIONS.map((size) => (
                    <option key={size} value={size}>{size}</option>
                  ))}
                </select>
                条
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => goToPage(pageMeta.page - 1)}
                  disabled={loading || pageMeta.page <= 1}
                  className="px-3 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:border-blue-200 hover:text-blue-600 disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-600"
                >
                  上一页
                </button>
                <button
                  type="button"
                  onClick={() => goToPage(pageMeta.page + 1)}
                  disabled={loading || pageMeta.page >= (pageMeta.pages || 1)}
                  className="px-3 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:border-blue-200 hover:text-blue-600 disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-600"
                >
                  下一页
                </button>
              </div>
            </div>
          )}
        </div>
        </div>
      </div>

      {/* Create/Edit Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={() => setModalOpen(false)}>
          <form onSubmit={submitForm} onClick={(e) => e.stopPropagation()} className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[85vh] overflow-y-auto animate-fade-in">
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between sticky top-0 bg-white rounded-t-xl z-10">
              <h2 className="text-base font-bold text-gray-800">{editing ? '编辑' : '新增'}{config.title}</h2>
              <button type="button" onClick={() => setModalOpen(false)} className="w-7 h-7 rounded-lg hover:bg-gray-100 flex items-center justify-center text-gray-400 hover:text-gray-600 transition-colors"><AppIcon className="fas fa-times text-sm" /></button>
            </div>
            <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-4">
              {config.fields?.map((field: any) => (
                <label key={field.name} className={field.type === 'textarea' ? 'md:col-span-2' : ''}>
                  <span className="block text-xs font-medium text-gray-500 mb-1.5">{field.label}{field.required && <span className="text-red-500 ml-0.5">*</span>}</span>
                  {field.type === 'textarea' ? <textarea aria-label={field.label} value={form[field.name] || ''} onChange={(e) => setForm({ ...form, [field.name]: e.target.value })} className="w-full min-h-20 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 transition-all resize-none" /> :
                    field.type === 'select' ? <select aria-label={field.label} value={form[field.name] || ''} onChange={(e) => setForm({ ...form, [field.name]: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg bg-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 transition-all"><option value="">请选择</option>{getOptions(field).map((option: any) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> :
                    field.type === 'checkbox' ? <div className="pt-1"><input checked={!!form[field.name]} onChange={(e) => setForm({ ...form, [field.name]: e.target.checked })} type="checkbox" className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500" /></div> :
                    <input aria-label={field.label} value={form[field.name] || ''} onChange={(e) => setForm({ ...form, [field.name]: e.target.value })} type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : field.type === 'datetime-local' ? 'datetime-local' : 'text'} min={field.type === 'number' ? (field.min ?? 0) : undefined} max={field.max ?? undefined} step={field.type === 'number' ? (field.step ?? '0.01') : undefined} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 transition-all" />}
                </label>
              ))}
            </div>
            <div className="px-6 py-3 border-t border-gray-100 flex justify-end gap-2 sticky bottom-0 bg-white rounded-b-xl">
              <button type="button" onClick={() => setModalOpen(false)} className="px-4 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors">取消</button>
              <button disabled={saving} type="submit" className="px-5 py-1.5 bg-blue-500 text-white rounded-lg text-sm font-medium disabled:opacity-60 hover:bg-blue-600 transition-colors">{saving ? '保存中...' : '保存'}</button>
            </div>
          </form>
        </div>
      )}

      {/* Detail Drawer (right side panel) */}
      {detail && (
        <div className="fixed inset-0 z-50 bg-black/20" onClick={() => setDetail(null)}>
          <div className="absolute right-0 top-0 bottom-0 w-full max-w-lg bg-white shadow-2xl overflow-y-auto animate-fade-in" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between sticky top-0 bg-white z-10">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center"><AppIcon className={`fas ${config.icon || 'fa-info-circle'} text-xs`} /></div>
                <h2 className="text-base font-bold text-gray-800">{detail.name || detail.title || detail.employeeName || '详情'}</h2>
              </div>
              <button onClick={() => setDetail(null)} className="w-7 h-7 rounded-lg hover:bg-gray-100 flex items-center justify-center text-gray-400 hover:text-gray-600 transition-colors"><AppIcon className="fas fa-times text-sm" /></button>
            </div>
            <div className="p-5 space-y-3">
              {getDetailEntries(detail).map(([key, value]) => (
                <div key={key} className="flex items-start gap-3 py-2 border-b border-gray-50 last:border-0">
                  <span className="text-xs text-gray-400 w-24 flex-shrink-0 pt-0.5">{columnLabels[key] || key}</span>
                  <span className="text-[13px] text-gray-700 flex-1 break-words">
                    {(key === 'status' || key === 'approvalStatus') ? <span className={getStatusBadgeClass(formatValue(key, value))}>{formatValue(key, value)}</span> : formatValue(key, cleanDetailValue(key, value))}
                  </span>
                </div>
              ))}
              {LIFECYCLE_WORKFLOW_MODULES.has(module) && (
                <div className="pt-3 mt-2 border-t border-gray-100 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold text-gray-500">工作流动作</div>
                      <div className="text-[11px] text-gray-400 mt-0.5">状态、审计和提醒由后端服务统一处理</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => loadWorkflow(detail)}
                      disabled={workflowLoading}
                      className="w-8 h-8 rounded-lg border border-gray-200 text-gray-500 hover:text-blue-600 hover:border-blue-200 disabled:opacity-50"
                      aria-label="刷新工作流"
                    >
                      <AppIcon className={`fas fa-rotate text-xs ${workflowLoading ? 'fa-spin' : ''}`} />
                    </button>
                  </div>
                  {workflowLoading && !workflow ? (
                    <div className="py-4 text-xs text-gray-400">工作流加载中...</div>
                  ) : workflow?.transitions?.length ? (
                    <div className="flex flex-wrap gap-2">
                      {workflow.transitions.map((transition: any) => (
                        <button
                          key={transition.key}
                          type="button"
                          disabled={!transition.enabled || workflowLoading}
                          onClick={() => runAction(detail, `workflow:${transition.key}`)}
                          className="px-3 py-1.5 rounded-lg border border-gray-200 text-xs font-medium text-gray-600 hover:border-blue-200 hover:text-blue-600 disabled:opacity-40 disabled:hover:text-gray-600 disabled:hover:border-gray-200"
                        >
                          {transition.label}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="py-4 text-xs text-gray-400">暂无可执行动作</div>
                  )}
                  <div className="rounded-lg border border-gray-100 overflow-hidden">
                    <div className="px-3 py-2 bg-gray-50 text-xs font-semibold text-gray-500">流程时间线</div>
                    <div className="divide-y divide-gray-50">
                      {(workflow?.timeline || []).slice(0, 8).map((item: any) => (
                        <div key={item.id} className="px-3 py-2 text-xs">
                          <div className="flex items-center justify-between gap-3">
                            <span className="font-medium text-gray-700 truncate">{item.title || item.action}</span>
                            <span className="text-[11px] text-gray-400 flex-shrink-0">{formatValue('createdAt', item.at)}</span>
                          </div>
                          <div className="mt-1 text-[11px] text-gray-400">{item.actorName || item.actorId || '系统'} · {item.action}</div>
                        </div>
                      ))}
                      {!workflow?.timeline?.length && <div className="px-3 py-4 text-xs text-gray-400">暂无流程事件</div>}
                    </div>
                  </div>
                </div>
              )}
            </div>
            <div className="px-5 py-3 border-t border-gray-100 sticky bottom-0 bg-white flex flex-wrap gap-2">
              {!config.readOnly && !config.special && <button onClick={() => { openEdit(detail); setDetail(null); }} className="px-4 py-1.5 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors"><AppIcon className="fas fa-edit mr-1.5 text-xs" />编辑</button>}
              {canUseAi && <button onClick={() => { runAction(detail, 'ai'); }} className="px-4 py-1.5 bg-purple-50 text-purple-600 rounded-lg text-sm font-medium hover:bg-purple-100 transition-colors"><AppIcon className="fas fa-wand-magic-sparkles mr-1.5 text-xs" />AI建议</button>}
              {module === 'employees' && <button disabled={lifecycleLoading} onClick={() => { runAction(detail, 'employee-lifecycle'); }} className="px-4 py-1.5 bg-cyan-50 text-cyan-600 rounded-lg text-sm font-medium hover:bg-cyan-100 transition-colors disabled:opacity-60"><AppIcon className="fas fa-timeline mr-1.5 text-xs" />{lifecycleLoading ? '加载中' : '关联链路'}</button>}
              {module === 'employees' && canGenerateOnboarding(detail) && <button onClick={() => { runAction(detail, 'generate-onboarding'); }} className="px-4 py-1.5 bg-green-50 text-green-600 rounded-lg text-sm font-medium hover:bg-green-100 transition-colors"><AppIcon className="fas fa-list-check mr-1.5 text-xs" />生成入职任务</button>}
              {module === 'employees' && canSubmitOnboarding(detail) && <button onClick={() => { runAction(detail, 'submit-onboarding'); }} className="px-4 py-1.5 bg-indigo-50 text-indigo-600 rounded-lg text-sm font-medium hover:bg-indigo-100 transition-colors"><AppIcon className="fas fa-paper-plane mr-1.5 text-xs" />入职提审</button>}
              {module === 'users' && currentUserRole === 'admin' && detail.status === 'active' && <button disabled={passwordResetting} onClick={() => resetAccountPassword(detail, 'hrm')} className="px-4 py-1.5 border border-amber-200 text-amber-700 rounded-lg text-sm font-medium hover:bg-amber-50 transition-colors disabled:opacity-50"><AppIcon className="fas fa-key mr-1.5 text-xs" />重置后台密码</button>}
              {module === 'employees' && ['admin', 'hr_admin'].includes(currentUserRole || '') && ['pending_onboard', 'probation', 'active'].includes(detail.status) && <button disabled={passwordResetting} onClick={() => resetAccountPassword(detail, 'employee_portal')} className="px-4 py-1.5 border border-amber-200 text-amber-700 rounded-lg text-sm font-medium hover:bg-amber-50 transition-colors disabled:opacity-50"><AppIcon className="fas fa-key mr-1.5 text-xs" />重置门户密码</button>}
              <button onClick={() => setDetail(null)} className="px-4 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors">关闭</button>
            </div>
          </div>
        </div>
      )}

      {resetCredential && (
        <div className="fixed inset-0 z-[60] bg-black/30 flex items-center justify-center p-4" onClick={closeResetCredential}>
          <div role="dialog" aria-modal="true" aria-labelledby="reset-credential-title" className="bg-white rounded-lg shadow-2xl w-full max-w-md" onClick={(event) => event.stopPropagation()}>
            <div className="px-5 py-4 border-b border-gray-100 flex items-start justify-between gap-4">
              <div>
                <h2 id="reset-credential-title" className="text-base font-bold text-gray-900">一次性密码已生成</h2>
                <p className="mt-1 text-xs text-gray-500">{resetCredential.targetName} · {resetCredential.accountLabel}</p>
              </div>
              <button type="button" onClick={closeResetCredential} className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-700" aria-label="关闭一次性密码弹窗">
                <AppIcon className="fas fa-times" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
                <div className="text-xs font-medium text-emerald-700">一次性密码</div>
                <div className="mt-2 flex items-center gap-2">
                  <code className="min-w-0 flex-1 select-all break-all text-sm font-semibold text-emerald-950">{resetCredential.initialPassword}</code>
                  <button type="button" onClick={copyResetCredential} className="w-9 h-9 flex-shrink-0 rounded-lg border border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-100" aria-label="复制一次性密码" title="复制一次性密码">
                    <AppIcon className="fas fa-copy" />
                  </button>
                </div>
              </div>
              <p className="text-sm leading-6 text-gray-600">请通过安全渠道交给本人。该账号首次登录时必须修改密码；关闭后系统不会再次显示这段密码。</p>
            </div>
            <div className="px-5 py-3 border-t border-gray-100 flex justify-end">
              <button type="button" onClick={closeResetCredential} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">我已妥善记录</button>
            </div>
          </div>
        </div>
      )}

      {/* AI Result Modal */}
      {aiResult && (
        <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={() => setAiResult(null)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl animate-fade-in" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-purple-50 text-purple-500 flex items-center justify-center"><AppIcon className="fas fa-wand-magic-sparkles text-xs" /></div>
                <h2 className="text-base font-bold text-gray-800">AI HR建议</h2>
              </div>
              <button onClick={() => setAiResult(null)} className="w-7 h-7 rounded-lg hover:bg-gray-100 flex items-center justify-center text-gray-400 hover:text-gray-600 transition-colors"><AppIcon className="fas fa-times text-sm" /></button>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-sm text-gray-700 leading-relaxed">{aiResult.summary}</p>
              {aiResult.suggestions?.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-xs font-semibold text-gray-500 uppercase">建议措施</h4>
                  {aiResult.suggestions.map((item: string, i: number) => (
                    <div key={i} className="flex items-start gap-2 text-sm text-gray-600">
                      <span className="w-5 h-5 rounded-full bg-purple-50 text-purple-500 flex items-center justify-center text-xs flex-shrink-0 mt-0.5">{i + 1}</span>
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="text-[11px] text-gray-400 pt-2 border-t border-gray-100">生成时间：{formatValue('createdAt', aiResult.generatedAt)}</div>
            </div>
          </div>
        </div>
      )}
      {lifecycle && (
        <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={() => setLifecycle(null)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-5xl max-h-[86vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 bg-white px-5 py-4 border-b border-gray-100 flex items-center justify-between rounded-t-xl">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-cyan-50 text-cyan-600 flex items-center justify-center"><AppIcon className="fas fa-timeline text-sm" /></div>
                <div>
                  <h3 className="text-sm font-bold text-gray-900">{lifecycle.employee?.name || '-'} 关联链路</h3>
                  <p className="text-xs text-gray-400 mt-1">从招聘、入职、合同、考勤、绩效、薪酬到离职的跨模块记录</p>
                </div>
              </div>
              <button type="button" onClick={() => setLifecycle(null)} className="w-8 h-8 rounded-lg hover:bg-gray-100 text-gray-400"><AppIcon className="fas fa-times" /></button>
            </div>
            <div className="p-5 space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
                {Object.entries(lifecycle.moduleCounts || {}).filter(([, value]) => Number(value) > 0).map(([key, value]) => (
                  <div key={key} className="rounded-lg border border-gray-100 p-3">
                    <div className="text-[11px] text-gray-400">{key}</div>
                    <div className="mt-1 text-lg font-bold text-gray-900">{String(value)}</div>
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-3">
                {(lifecycle.connectivity || []).map((item: any) => (
                  <div key={item.id} className={`rounded-lg border p-3 ${item.ok ? 'border-green-100 bg-green-50/50' : 'border-orange-100 bg-orange-50/50'}`}>
                    <div className={`text-xs font-semibold ${item.ok ? 'text-green-700' : 'text-orange-700'}`}>{item.label}</div>
                    <div className="mt-1 text-[11px] text-gray-500">{item.ok ? '已打通' : '需补齐'}</div>
                  </div>
                ))}
              </div>
              <div className="rounded-lg border border-gray-100">
                <div className="px-4 py-3 border-b border-gray-100 text-xs font-semibold text-gray-500">时间线</div>
                <div className="divide-y divide-gray-50">
                  {(lifecycle.timeline || []).map((item: any, index: number) => (
                    <div key={`${item.module}-${item.recordId}-${index}`} className="px-4 py-3 grid grid-cols-[110px_140px_1fr_90px] gap-3 text-xs">
                      <div className="text-gray-400">{item.at || '-'}</div>
                      <div className="font-medium text-gray-700">{item.module}</div>
                      <div className="text-gray-700 truncate">{item.title || '-'}</div>
                      <div className="text-gray-500">{formatValue('status', item.status)}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
