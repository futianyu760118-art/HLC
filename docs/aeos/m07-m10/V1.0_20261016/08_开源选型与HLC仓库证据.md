# HLC 源码证据与开源对标决策
> **控制状态：执行候选 / 尚未获各 Owner 与 Gate 批准。** 本包是供研发、评审、拆解任务使用的工程设计输入，不等同已冻结的 AEOS 标准。
> **来源等级：** [B] 上传的 AEOS V7.2.2 合订版；[C] 已核查 HLC 仓库代码（关键文件片段）；[D] 2026-10-15 V3.0 DEMO/讨论；[P] 本次新增的设计建议；[V] 生产部署或外部开源组件待验证。

## 1. 已检查的 HLC 代码
仓库 `https://github.com/futianyu760118-art/HLC.git`，已见默认分支 `master`。GitHub Git Tree 显示 779 个条目（含目录）；该数字不是经过构建验证的源码文件数。[C]
| 位置 | 可确定的信息 | 适配建议 |
|---|---|---|
| package.json | React 19、TS、Vite、E2E 和安全相关测试脚本 | 可借鉴界面及测试规范 |
| backend-python/routes/org.py | JWT、RBAC、tenant context、组织树/图 | 只经受控接口读取，须 M01 授权 |
| backend-python/services/org_structure.py | tenant_id 下组织层级/经理校验 | 组织业务视图，不是 canonical identity |
| src/pages/p-hrm/moduleConfig.ts | positions/employees/onboarding/probations/employee-changes 字段 | M07 表单复用候选 |
| backend-python/services/hrm_module_catalog.py | HRM 模块目录与 AI Skill 元信息 | 向 M13 注册专业 Skill 的依据之一 |
| backend-python/routes/tasks.py | 进程内 upload_tasks 字典 | 不适用于持久业务待办 |
| backend-python/routes/auth.py | 独立 JWT，默认初始口令变量和内存失败计数 | 安全基线优先评审 |
| src/config/capabilityNavigation.ts | PWA、SSO、API、移动能力项的导航声明 | 非生产成熟度证据 |

## 2. 参考开源项目（仅用于设计研究，非本次实时安装验证）
| 项目 | 地址 | 参考价值 | 采用策略 | 许可证/版本风险 |
|---|---|---|---|---|
| Frappe HR | https://github.com/frappe/hrms | 招聘、入转调离、请假、薪资/HR 业务体系 | 学领域模型，勿直接与 Flask 混跑 | 复核 GPL 与部署版本 |
| Horilla | https://github.com/horilla-opensource/horilla | 考勤、休假、人力后勤、员工资产 | 对标流程和数据模型 | 复核 LGPL 范围 |
| OrangeHRM | https://github.com/orangehrm/orangehrm | 成熟 HR 业务与员工自助 | 对标验收清单与 UX | 开源/商业功能界限 |
| NocoBase | https://github.com/nocobase/nocobase | 动态配置表单、插件、工作流 | 借鉴 RoleTemplate/配置模型 | 插件许可与数据主权 |
| Budibase | https://github.com/Budibase/budibase | 内部表单、工作台和移动交互 | 借鉴 UI 构建技术 | 社区/商业功能界限 |
| Activepieces | https://github.com/activepieces/activepieces | 自动化事件与多步骤工具调度 | 评估非权威适配层 | 社区/企业许可与工具滥用 |
| Ever Gauzy | https://github.com/ever-co/ever-gauzy | HR/项目/工时综合模型 | 只用于体系参考 | 边界重叠与整体过重 |

### 选型决议建议
**保留 HLC React + Flask 为 M07 基础，M10 独立开发轻量 React 工作面。** 不引入整套外部 HRMS 替换已有仓库；对 Frappe HR/Horilla 做专业流程 Gap 检查；对 NocoBase/Budibase 参考动态 UI/Schema；Activepieces 仅候选自动化适配，不能绕过 M01/02 与领域 Owner。[P]

## 3. 验证任务
OSS-01 拉取各仓库当前 release、commit、许可证文件和依赖 SBOM；OSS-02 检查是否存在兼容的公开接口和插件许可；OSS-03 进行概念验证与安全对抗测试。前次对标中的 Star 与版本为历史研究信息，不在此作为当前冻结值。[V]