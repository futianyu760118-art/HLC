import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  orgApi,
  type OrgChartEmployee,
  type OrgChartPayload,
  type OrgTreeNode,
} from '../../utils/api';
import { authUtils } from '../../utils/auth';

const ORG_WRITE_ROLES = new Set(['admin', 'hr_admin']);

const flattenDepartments = (nodes: OrgTreeNode[]): OrgTreeNode[] => {
  const result: OrgTreeNode[] = [];
  const walk = (items: OrgTreeNode[]) => {
    items.forEach((item) => {
      result.push(item);
      if (item.children.length) walk(item.children);
    });
  };
  walk(nodes);
  return result;
};

const employeeLabel = (employee: OrgChartEmployee): string => {
  const suffix = employee.employeeNo ? ` (${employee.employeeNo})` : '';
  return `${employee.name}${suffix}`;
};

const statusLabel = (status: string): string => {
  if (['inactive', 'resigned', 'terminated', 'departed'].includes(status)) return '已停用/离职';
  if (status === 'probation') return '试用';
  return '在职';
};

function DepartmentTreeNode({
  node,
  selectedId,
  onSelect,
}: {
  node: OrgTreeNode;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;
  const selected = selectedId === node.id;

  return (
    <div>
      <div
        className={`flex items-center gap-1 rounded px-2 py-1 text-sm ${
          selected ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-50 text-gray-700'
        }`}
      >
        <button
          type="button"
          aria-label={expanded ? '收起' : '展开'}
          className={`h-4 w-4 shrink-0 text-xs ${hasChildren ? 'text-gray-400' : 'text-transparent'}`}
          onClick={() => hasChildren && setExpanded((value) => !value)}
        >
          {hasChildren ? (expanded ? '▾' : '▸') : '•'}
        </button>
        <button
          type="button"
          className="flex-1 truncate text-left"
          onClick={() => onSelect(node.id)}
          title={node.name}
        >
          {node.shortName || node.name}
          <span className="ml-1 text-xs text-gray-400">
            {node.totalEmployeeCount ?? node.employeeCount}人
          </span>
        </button>
      </div>
      {hasChildren && expanded && (
        <div className="ml-4 border-l border-gray-100 pl-1">
          {node.children.map((child) => (
            <DepartmentTreeNode
              key={child.id}
              node={child}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function OrganizationPage() {
  const [tree, setTree] = useState<OrgTreeNode[]>([]);
  const [chart, setChart] = useState<OrgChartPayload | null>(null);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [selectedDeptId, setSelectedDeptId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canEdit = ORG_WRITE_ROLES.has(authUtils.getUser()?.role || '');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [treePayload, chartPayload] = await Promise.all([
        orgApi.tree(includeInactive),
        orgApi.chart(includeInactive),
      ]);
      setTree(treePayload.tree || []);
      setChart(chartPayload);
      setSelectedDeptId((current) => {
        if (current && flattenDepartments(treePayload.tree || []).some((node) => node.id === current)) {
          return current;
        }
        return treePayload.tree?.[0]?.id ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载组织架构失败');
    } finally {
      setLoading(false);
    }
  }, [includeInactive]);

  useEffect(() => {
    void load();
  }, [load]);

  const departments = useMemo(() => flattenDepartments(tree), [tree]);
  const employees = useMemo(() => chart?.employees ?? [], [chart]);
  const employeeById = useMemo(() => {
    const map = new Map<string, OrgChartEmployee>();
    employees.forEach((employee) => map.set(employee.id, employee));
    return map;
  }, [employees]);

  const selectedDepartment = useMemo(
    () => departments.find((node) => node.id === selectedDeptId) ?? null,
    [departments, selectedDeptId],
  );

  const departmentEmployees = useMemo(
    () => employees.filter((employee) => employee.departmentId === selectedDeptId),
    [employees, selectedDeptId],
  );

  const managerOptions = useMemo(
    () =>
      [...employees].sort((a, b) => employeeLabel(a).localeCompare(employeeLabel(b), 'zh-Hans-CN')),
    [employees],
  );

  const handleEmployeeManager = async (employeeId: string, managerId: string) => {
    setSaving(true);
    setError(null);
    try {
      await orgApi.setEmployeeManager(employeeId, managerId || null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '设置直属上级失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDepartmentManager = async (departmentId: string, managerId: string) => {
    setSaving(true);
    setError(null);
    try {
      await orgApi.setDepartmentManager(departmentId, managerId || null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '设置部门负责人失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">组织架构</h1>
          <p className="mt-1 text-sm text-gray-500">
            部门层级、负责人与汇报关系；部门主管与工号由 OA 同步维护。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(event) => setIncludeInactive(event.target.checked)}
            />
            显示已停用
          </label>
          <button
            type="button"
            className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            onClick={() => void load()}
            disabled={loading}
          >
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
        <aside className="rounded-lg border border-gray-200 bg-white p-3">
          <div className="mb-2 flex items-center justify-between text-xs font-medium uppercase text-gray-400">
            <span>部门</span>
            <span>{departments.length} 个</span>
          </div>
          {tree.length === 0 && !loading ? (
            <div className="px-2 py-6 text-center text-sm text-gray-400">暂无可展示的部门</div>
          ) : (
            <div className="max-h-[560px] space-y-0.5 overflow-y-auto">
              {tree.map((node) => (
                <DepartmentTreeNode
                  key={node.id}
                  node={node}
                  selectedId={selectedDeptId}
                  onSelect={setSelectedDeptId}
                />
              ))}
            </div>
          )}
        </aside>

        <section className="rounded-lg border border-gray-200 bg-white p-4">
          {!selectedDepartment ? (
            <div className="py-16 text-center text-sm text-gray-400">请选择左侧部门</div>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 pb-3">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">
                    {selectedDepartment.shortName || selectedDepartment.name}
                  </h2>
                  <div className="mt-1 text-xs text-gray-500">
                    编码 {selectedDepartment.code || '-'}
                    {selectedDepartment.shortName && selectedDepartment.shortName !== selectedDepartment.name
                      ? ` · 全称 ${selectedDepartment.name}`
                      : ''}
                    {' · '}在职{' '}
                    {selectedDepartment.totalEmployeeCount ?? selectedDepartment.employeeCount} 人
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm text-gray-600">
                  <span className="shrink-0">部门负责人</span>
                  <select
                    className="min-w-[180px] rounded border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-50"
                    value={selectedDepartment.managerId || ''}
                    disabled={!canEdit || saving}
                    onChange={(event) =>
                      void handleDepartmentManager(selectedDepartment.id, event.target.value)
                    }
                  >
                    <option value="">未指定</option>
                    {managerOptions.map((employee) => (
                      <option key={employee.id} value={employee.id}>
                        {employeeLabel(employee)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div>
                <div className="mb-2 text-sm font-medium text-gray-700">部门成员与汇报关系</div>
                {departmentEmployees.length === 0 ? (
                  <div className="rounded border border-dashed border-gray-200 py-8 text-center text-sm text-gray-400">
                    该部门暂无在职员工
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs uppercase text-gray-400">
                          <th className="px-2 py-2">姓名</th>
                          <th className="px-2 py-2">工号</th>
                          <th className="px-2 py-2">状态</th>
                          <th className="px-2 py-2">直属上级</th>
                        </tr>
                      </thead>
                      <tbody>
                        {departmentEmployees.map((employee) => (
                          <tr key={employee.id} className="border-t border-gray-100">
                            <td className="px-2 py-2 text-gray-800">{employee.name}</td>
                            <td className="px-2 py-2 text-gray-500">{employee.employeeNo || '-'}</td>
                            <td className="px-2 py-2 text-gray-500">{statusLabel(employee.status)}</td>
                            <td className="px-2 py-2">
                              <select
                                className="min-w-[180px] rounded border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-50"
                                value={employee.managerId || ''}
                                disabled={!canEdit || saving}
                                onChange={(event) =>
                                  void handleEmployeeManager(employee.id, event.target.value)
                                }
                              >
                                <option value="">未指定</option>
                                {managerOptions
                                  .filter((candidate) => candidate.id !== employee.id)
                                  .map((candidate) => (
                                    <option key={candidate.id} value={candidate.id}>
                                      {employeeLabel(candidate)}
                                    </option>
                                  ))}
                              </select>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {selectedDepartment.managerId && employeeById.get(selectedDepartment.managerId) && (
                <p className="text-xs text-gray-400">
                  当前负责人：
                  {employeeById.get(selectedDepartment.managerId)?.name}
                </p>
              )}

              {!canEdit && (
                <p className="text-xs text-gray-400">仅管理员可维护负责人与汇报关系。</p>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
