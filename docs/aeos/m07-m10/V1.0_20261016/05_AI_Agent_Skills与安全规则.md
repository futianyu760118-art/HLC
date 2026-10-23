# M07/M10 Agent、Skills、工具与安全控制设计
> **控制状态：执行候选 / 尚未获各 Owner 与 Gate 批准。** 本包是供研发、评审、拆解任务使用的工程设计输入，不等同已冻结的 AEOS 标准。
> **来源等级：** [B] 上传的 AEOS V7.2.2 合订版；[C] 已核查 HLC 仓库代码（关键文件片段）；[D] 2026-10-15 V3.0 DEMO/讨论；[P] 本次新增的设计建议；[V] 生产部署或外部开源组件待验证。

## 1. 分层
- M10 Personal Agent：个人对话、解释任务、草拟表单、辅助采集、个人结果总结，不直接拥有 HR 事实。
- M07 Domain Agents：招聘助手、入职助手、培训助手、行政服务助手、绩效资料检查助手，专业知识与验收责任归 M07。
- M13 Agent Workforce：Agent 注册、工具/Prompt/Skill 版本、工作量、成本、失效、暂停、熔断、人工接管。[B/P]

## 2. 建议 Skill 定义
| Skill ID | 任务 | 允许 | 禁止/审批 |
|---|---|---|---|
| hlc.recruitment.screening | 岗位需求与简历筛查辅助 | 归纳岗位能力与候选人证据 | 不按敏感属性自动定录用 |
| hlc.onboarding.checklist | 入职资料完整性检查 | 提示缺项、草拟待办 | 不自动创建 M01 身份 |
| hlc.training.match | 资格与培训匹配 | 推荐课程和过期提醒 | 不伪造培训完成或资格 |
| hlc.logistics.triage | 后勤维修分流 | 分类、优先级建议、草拟分派 | 不直接控制设备/采购 |
| hlc.attendance.explain | 考勤制度解释 | 引用已批准政策 | 不自动确认加班/工资 |
| hlc.performance.evidence | 评价材料质量检查 | 核查证据有无、完整度 | 不自动给终评分或调薪 |

## 3. 工具调用强制链
User → M10 Personal Agent → M13 Agent Registry/Session → M01 Guard → M07 专业工具 API → M02 Trace/Result/Evidence → Personal Agent 回显。Agent 不得从 Prompt 自报 tenant、person 或审批权限。[B/P]

## 4. 危险动作政策
P0 高风险：录用、调岗生效、离职、薪酬、绩效结果签发、批量导出、权限变更、资产销账、跨租户访问，一律人工确认，资金和敏感数据按适用规则双人审批。Agent 的审批建议不得直接转成执行令。[B/P]

## 5. 评测建议
- 20 个人事行政问答与 10 个跨岗位场景；核对来源准确率、拒绝越权率、工具确认通过率、建议可用率和 Agent 花费。
- Prompt Injection、角色伪装、跨租户、工具参数污染、记忆越界、敏感资料外发、成本熔断及离职后的会话撤销为必测。[B/P]
- 不接入外部模型之前，演示应明确标注“模拟 Agent”。[D]