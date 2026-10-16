# AEOS V7.2.2 M00–M14 各子系统最新方案合订版

**版本：** V7.2.2  
**状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**周期：** 9 个月 / 36 周  
**建议起始日：** 2026-10-19（PMO 签发后生效）

本合订版根据 AEOS 执行前评审总方案、当前模块领域资料、GitHub 与 ChatGPT 项目证据，形成 M00–M14 各子系统的最新可执行方案。附件总方案中的架构、边界、安全和 Gate 条目作为约束；待签批或待补证据内容保持对应状态。

## 一 总体协作原则

M00 负责治理与 Gate；M01 负责身份、权限、Policy 和 Guard；M02 负责事实、事件、结果、证据和审计；M03 负责经营工作面；M04–M11 负责专业事实和结果；M12 负责工程安全与质量门禁；M13 负责 Agent Workforce；M14 NOMI 负责系统研发工作面。

# M00 GOV AEOS 治理与总体架构 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** AEOS Governance & Architecture  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

AEOS 的治理、标准、架构、决策和执行门禁中心。M00 不承载业务事实，负责让每个系统、模块、标准和执行动作有边界、有 Owner、有证据、有签批。

## 二 当前目标

在 9 个月/36 周执行周期内建立唯一的当前架构基线、标准状态、责任矩阵、Gate 结论和复制条件。

## 三 Own 范围

- 总体架构基线、System Registry、Module Mapping Matrix 和标准目录
- 决策、风险、变更、签批、Gate、No-Go 和放行条件
- 证据完整性规则、版本状态规则、SHA-256 manifest 规则和归档目录
- 跨系统边界冲突、职责冲突、未决项和升级规则

## 四 Must Not 边界

- 不拥有 Customer、Order、Finance、Quality、Repo 等业务或工程事实
- 不以会议结论替代正式文件、来源、版本和 SHA-256
- 不绕过 M01/M02/M12 的授权、证据和安全门禁

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| ArchitectureBaseline | 当前架构版本、状态、批准人、适用范围 | M00 |
| SystemRegistry | system_id、名称、边界、Owner、Must Not、关键性 | M00/P0-01 |
| ModuleMapping | 模块 Current, Target、依赖、迁移和 Gate | M00/P0-02 |
| Decision/Risk/Change | 决策、风险、变更、期限、责任和结论 | M00 |
| Gate/Signoff/Evidence | Gate 条件、签批、证据索引、SHA-256 | M00/M02 |

## 六 接口与协作

- M01–M14：登记边界、Owner、依赖、验收和 No-Go
- PMO/Architecture Board：签发周期、Gate 和风险接受
- GitHub/ChatGPT/本地归档：只做候选线索、实现证据和文件级核验，不直接替代标准

## 七 安全控制

- 架构和标准变更采用双人复核、版本递增、签批和 manifest
- P0 安全、租户、身份、数据泄露、不可回滚问题自动进入 No-Go
- 所有 Gate 证据必须可定位到文件、来源、版本、状态和 SHA-256
- 禁止无 Owner、无验收人、无回滚路径的任务进入完成状态

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W01–W04 | G0 | 确认 M00–M14 边界、Owner、Must Not、P0 和安全风险 |
| W05–W12 | G1/G2 | 冻结契约、试点、风险、签批和首条真实闭环的验收规则 |
| W13–W28 | G3–G6 | 按 Gate 管理底座、业务中心、POMS、M13、M14 的接入证据 |
| W29–W36 | G7/G8 | 安全演练、终验、运营移交、复制包和最终完整性清单 |

## 九 验收标准

- System Registry 与 Module Mapping Matrix 具有唯一当前版本、Owner、签批和 manifest
- P0-03/P0-04/P0-05、POMS V2.2、M14 来源均有责任人、截止时间和证据状态
- 每个 Gate 都有通过、保持或 No-Go 结论和可定位 Evidence
- 终验包包含 KPI、风险签收、运营移交、复制模板和 SHA-256 清单

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_执行前评审方案_20261014_V7.2.2/01_执行前评审总方案/AEOS_V7.2.2_执行前评审总方案.docx | AVAILABLE / HASHED | 9463B9DB83BF01437A782F4DC4F5F56511C577645C9102F14180AC9A379A3549 |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/AEOS_V7.2_整体更新方案_M13_M14_V7.2.2.md | AVAILABLE / HASHED | 88733AEB764317596D097C822FC49C98450C7DA45EB40F6CE7BB079AFDD20B0D |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/02_AEOS标准文件权威源与版本矩阵.md | AVAILABLE / HASHED | 9E6D38D648EC8D1FD11DB422201AB2FC519DDF8F6C014A78B48D18768CC0ACDD |

正式冻结前需完成架构负责人、PMO 和各模块 Owner 的签批；本方案提供执行控制，不替代签批本身。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M01 Kernel AEOS 核心内核 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** AEOS Kernel  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

AEOS 的身份、组织、岗位、权限、Policy 和 Guard 内核，是人、Agent、服务和设备访问系统能力的唯一授权入口。

## 二 当前目标

统一 person_id、org_id、position_id、agent_id、team_id、service_id 和 device_id 的引用关系，确保最小权限、租户隔离、撤权和职责分离可验证。

## 三 Own 范围

- Person/Organization/Position 的 canonical identity 引用
- Agent、服务和设备身份的注册、绑定、状态和撤销
- RBAC+ABAC、Policy、Guard、授权决定和高风险动作审批前置
- 租户、职责分离、Break-glass、撤权和权限审计

## 四 Must Not 边界

- 不拥有业务 Customer、Order、Finance、Quality 或研发成果
- 不把客户端字段、Agent 自报身份或业务角色名当作授权事实
- 不允许模块自行维护第二套权限事实或直接修改 M01 权威数据

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| CanonicalIdentity | person, org, position, agent, team, service, device 的稳定引用 | M01 |
| Permission/Policy | 主体、资源、动作、条件、租户、有效期 | M01 |
| GuardDecision | 允许, 拒绝, 需人工审批、依据、策略版本 | M01/M02 |
| Grant/Revocation | 授权、撤权、原因、时间、执行结果 | M01/M02 |
| AccessAudit | 访问主体、对象、动作、结果、Trace | M01/M02 |

## 六 接口与协作

- M02：记录授权决定、撤权、特权访问和审计证据
- M13：Agent Workforce身份和岗位引用；M14：研发 Agent 和服务身份引用
- 所有业务中心：通过 API/Policy/Guard 获取授权，不直接读写权限表

## 七 安全控制

- MFA、短时凭证、服务身份轮换、默认拒绝和最小权限
- 高风险动作采用 maker-checker、双人复核或业务 Owner 确认
- 撤权、租户切换、Break-glass 和权限提升必须实时审计
- 跨租户、对象级和字段级授权测试列为 G7 前置

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W05–W08 | G1 | 统一身份、岗位、Agent、服务和设备 ID；定义 Policy/Guard 契约 |
| W09–W16 | G2/G3 | 完成租户隔离、撤权、审计和共享授权底座 |
| W17–W28 | G4–G6 | 为业务中心、M13、M14 接入岗位和动作权限 |
| W29–W36 | G7/G8 | 完成越权、跨租户、密钥、人工接管和恢复演练 |

## 九 验收标准

- 关键主体和对象均可唯一引用，撤权可在运行链路生效
- RBAC+ABAC、租户隔离、对象级权限和职责分离测试通过
- 特权操作和高风险 Agent 调用 100% 有审计
- 任何模块无法绕过 M01 获得生产、资金、设备或数据导出权限

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/AEOS_P0-01_System_Registry_V1.2_M13_M14同步候选.md | AVAILABLE / HASHED | 01E5B3389DC0C208D4A60BD514A860DD44F3E4B032E073AB31075953E342285D |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/AEOS_P0-02_Module_Mapping_Matrix_V1.2_M13_M14同步候选.md | AVAILABLE / HASHED | C3C4D10C8B916A795655E8C5C79599C625A5AE6AD6A4B22C06D809423A5690F6 |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/AEOS_P0-03_Data_Ownership.md | MISSING / EVIDENCE-PENDING |  |

P0-03 Data Ownership、P0-04 Object ID、P0-05 Contract Pack 尚需正式文件、来源、版本和 SHA-256 后进入正式矩阵。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M02 EDP 企业数据与证据平台 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** Enterprise Data & Evidence Platform  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

AEOS 的企业事实、事件、结果、证据、审计、指标、价值和 Trace 统一关联平台，任何模块通过契约使用，不直接跨域写库。

## 二 当前目标

建立 Fact/Object → Event → Decision、Action → Result → Verification → Evidence 的可回放闭环，支持业务、Agent 和工程结果的可验证、可审计和可恢复。

## 三 Own 范围

- BusinessObject、Event、Result、Evidence、Audit、Metric、Value、Trace 的通用模型
- 数据域、事实 Owner、来源 Provenance、质量规则、Outbox 和重放
- API/Event/Result/Evidence/Decision、Action Contract 的执行和版本管理
- 租户隔离、数据分级、留存、备份、血缘、审计和证据索引

## 四 Must Not 边界

- 不拥有各业务专业事实和算法结果；专业中心保留事实 Owner
- 不允许 EBMS、Agent 或业务模块直接访问其他域数据库
- 不以日志、页面状态或聊天文本替代 Result/Evidence

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| BusinessObject | 业务对象和事实状态 | 专业中心 |
| Event | 状态变化、来源、时间、主体、对象 | M02 |
| Result、Metric、Value | 计算结果、指标、价值、版本、口径 | 专业中心/M02 |
| Evidence/Provenance | 文件、截图、测试、审批、来源、哈希 | M02 |
| Decision、Action/Verification | 决策、执行、验证、关闭和学习 | M03/业务中心/M02 |

## 六 接口与协作

- M03：只消费 Result、Metric、Exception、Decision、Action、Evidence
- M13：接收 Agent 运行、工作量、成本、绩效和退出证据
- M14：接收需求、变更、构建、测试、发布、部署、回滚和漏洞证据
- M01/M12：记录授权、扫描、发布、告警和恢复证据

## 七 安全控制

- 数据分级、字段脱敏、租户隔离、传输/存储加密和密钥轮换
- Evidence 只追加或版本化，不允许静默覆盖；删除/留存需要授权和证明
- Outbox、幂等、重试上限、死信和重放保护，防止重复外部副作用
- 敏感数据导出、跨租户查询和 Evidence 分享需要审批和审计

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W05–W08 | G1 | 完成 Data Ownership、Object ID、Contract Pack、Event/Result/Evidence 版本规则 |
| W09–W16 | G2/G3 | 跑通一条真实业务/研发闭环并形成可回放证据 |
| W17–W28 | G4–G6 | 接入 EBMS、业务中心、M13、M14 和 POMS 候选 |
| W29–W36 | G7/G8 | 完成灾备恢复、数据隔离、DLP、审计和最终证据包 |

## 九 验收标准

- 每个关键对象只有一个事实 Owner，来源和版本可定位
- 关键动作均能关联 Event、Result、Evidence、Trace 和授权决定
- 重复提交、失败重试、重放和恢复测试通过
- 备份可恢复、审计不可静默修改、跨租户查询被阻断

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/EDP数据库/AEOS 企业数据与证据中台 EDP 迭代版总体方案 V1.0.md | AVAILABLE / HASHED | ABFC2BDC96EBE235B3C2FA6E804740AEE570172163A88CF5546B6DFA0CD2EA65 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/EDP数据库/EDP 数据与智能中台 × AEOS V7.2 架构与代码核准报告 V1.0.md | AVAILABLE / HASHED | A05F623C994EC57086F9C701040BD3045161993FD8CBA57AF15FC0285AB27FF8 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/EDP数据库/FDE_A档_场景契约与指标字典.xlsx | AVAILABLE / HASHED | 95771F9E256C2714431635C05665DF5099BD82748AA4353487825A6E72D103B5 |

正式 P0-03/P0-04/P0-05 仍需补齐；本方案以 EDP 候选基线作为实现边界，不把候选契约标记为正式冻结。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M03 EBMS 企业经营管理系统 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** Enterprise Business Management System  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

AEOS 的经营结果、异常、决策、行动和管理工作面，消费各专业中心的 Result/Evidence，不复制专业主数据和专业算法。

## 二 当前目标

将经营管理统一为 Result → Exception → Decision → Action → Result → Verification → Evidence，形成可执行、可复盘的经营闭环。

## 三 Own 范围

- 经营目标、经营指标、异常池、决策案例、行动项、升级和经营看板
- 跨专业结果汇总、偏差识别、管理层决策引用和行动督办
- 经营类 Exception、Decision、Action 的生命周期和验收引用
- 经营管理工作面、权限、通知、升级和责任分派

## 四 Must Not 边界

- 不拥有 Sales、Delivery、Finance、Quality、R&D 的专业事实
- 不直接 CRUD 业务域数据库，不复制各专业算法
- AI 只做识别、建议和草案，不直接改变经营事实或执行不可逆动作

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| ManagementGoal | 企业, 组织, 岗位, 项目目标和指标口径 | M03/业务 Owner |
| Exception | 异常、严重度、原因、证据、责任和期限 | 专业中心/M03 |
| DecisionCase | 待决策事项、选项、影响、依据和审批 | M03 |
| Action | 行动、Owner、期限、状态、结果和验证 | M03/执行中心 |
| ManagementResult | 经营结果、偏差、趋势、价值和证据 | M03/M02 |

## 六 接口与协作

- M02：消费 Result/Metric/Exception/Decision、Action/Evidence
- M04–M11：提交专业结果、异常、行动回执和证据引用
- M13/M14：消费 Agent/工程绩效和交付状态，不接管其事实 Owner

## 七 安全控制

- 经营指标按组织、岗位、租户和敏感级别授权
- 资金、客户、价格、人员和生产影响的行动必须人审
- 管理看板只消费已验证 Result，展示层不能写回事实
- 所有 Decision、Action 必须记录建议来源、审批人、执行人和证据

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W17–W20 | G4 | 建立经营 Exception/Decision、Action/Result 业务闭环 |
| W21–W28 | G5/G6 | 接入销售、交付、研发、财务和 Agent 绩效结果 |
| W29–W32 | G7 | 开展经营数据隔离、权限、人工审批和异常升级测试 |
| W33–W36 | G8 | 完成经营 KPI、运营移交和管理复制模板 |

## 九 验收标准

- 至少一条经营异常从识别到 Decision、Action、Result、Verification、Evidence 闭环
- EBMS 不直接读专业库、不复制专业算法
- 高风险经营动作有审批、责任人和证据
- 管理指标口径、来源、时间窗口和 Owner 清晰

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/EBMS企业经营管理/EBMS_AEOS_V7.2_整改实施方案与12周行动计划_V1.0.docx | AVAILABLE / HASHED | CAAD9FB4C62197399CB5BD1B6E0A2F4F796FABED954D3A494759566DE3880AB0 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/EBMS企业经营管理/EBMS_AEOS_V7.2_核对评估报告_V1.0.docx | AVAILABLE / HASHED | 4B37002820BEA167DAACCABEBC655C9E18BDAFF87E09ED02C8BCDBD20D3D44E1 |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/AEOS_V7.2_整体更新方案_M13_M14_V7.2.2.md | AVAILABLE / HASHED | 88733AEB764317596D097C822FC49C98450C7DA45EB40F6CE7BB079AFDD20B0D |

EBMS 的实施验收必须采用当前 36 周 Gate；来源资料中的专业整改项需映射为 M03 的当前 Action/Result/Evidence。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M04 RDC 研发自治中心 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** R&D Autonomous Center  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

研发、PLM-2、项目、BOM、测试、变更和工程 Action 的专业自治中心；M14 负责系统开发管理工作面，M04 保留研发专业事实和验收。

## 二 当前目标

将研发需求、项目、Part/BOM、ECN、模具、3D、测试、质量和研发 Action 纳入统一事实、结果和证据链。

## 三 Own 范围

- 研发项目、需求、产品/部件、BOM、ECN、样件、测试、研发质量和研发专业 Result
- 研发事项、Action、节点、责任、验收、技术风险和研发证据
- 研发专业 Agent/Skill 的业务范围、输出质量和专业人工验收
- 研发专业数据与 M02/M14 的系统研发关联

## 四 Must Not 边界

- 不拥有 M01 身份权限、M02 Evidence、M14 系统研发流程或 M03 经营决策
- 不让 Agent 直接修改正式 BOM、ECN、发布或质量结论
- 自动化测试通过不替代工程、法规、工艺或业务责任人验收

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| R&D Project/Node | 研发项目、阶段、节点、责任、依赖 | M04 |
| Part/BOM/ECN | 产品部件、物料结构、工程变更 | M04 |
| Test/QualityResult | 测试、缺陷、验证、质量结果和 Evidence | M04/M08 |
| R&D Action | 研发行动、状态、验收、回执 | M04/M02 |
| TechnicalRisk | 技术风险、影响、缓解、Owner 和期限 | M04/M00 |

## 六 接口与协作

- M14：提供系统、仓库、分支、Change、Build、Test、Release 的工程管理关联
- M12：接入 CI/CD、SAST/SCA、测试、SBOM、制品签名和环境门禁
- M02：统一研发 Object/Event/Result/Evidence/Trace
- M13：提供研发 Agent 岗位、任务、工作量、绩效和成本上下文

## 七 安全控制

- BOM、ECN、图纸、3D、工艺和测试数据按项目、岗位、租户和敏感级别隔离
- 工程变更必须关联审批、影响分析、测试和回滚/恢复措施
- Agent 只允许受控查询、草案和低风险动作；关键工程写入需人审
- 研发制品、代码、构建和部署由 M14/M12 形成供应链证据

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W21–W24 | G5 | 建立研发 Agent、任务、Result、Evidence 与工程链路闭环 |
| W25–W28 | G6 | 接入 M13 Workforce 和 M14 NOMI 的工程管理工作面 |
| W29–W32 | G7 | 完成研发数据隔离、供应链、漏洞、回滚和人工接管测试 |
| W33–W36 | G8 | 完成研发复制模板、运营移交、技术债和质量 KPI |

## 九 验收标准

- 需求/项目/变更/测试/结果/证据可关联，关键工程变更可回放
- 至少一条研发闭环完成审批、构建、测试、发布或回滚
- BOM/ECN/工程文件越权、泄露和误写测试通过
- 研发专业验收和 M14 工程验收职责清晰

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/研发自治中心/V1.1版/AEOS_研发自治中心_PLM-2迭代解决方案与行动计划_V1.1_2026-09-23.docx | AVAILABLE / HASHED | A9A63576904908CC1EFBD5B30BD2424457D05284E60785C714C4BAE21A701026 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/研发自治中心/V1.1版/AEOS_研发自治中心_PLM-2开发点检与进度表_V1.1_2026-09-23.xlsx | AVAILABLE / HASHED | 50D15A4B0DFCAEFC0B0ED0749EC19FA3289E0E408BC3D3E919BEB0BD5DB6E978 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/研发自治中心/923改善方案/AEOS_研发事项与执行中心_解决方案_V1.0_2026-09-23.docx | AVAILABLE / HASHED | 02AA0C967685BAAAEBAF211C0070C728F6DF38B41702567FA1624E2678167FF2 |

研发方案已有较强模块资料基础；本方案将其与 M13 Workforce、M14 NOMI 和 36 周 Gate 对齐，需由研发 Owner 验收。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M05 CRM 销售自治中心 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** Sales Autonomous Center  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

销售专业事实和全生命周期自治中心，覆盖 Lead、Customer、Contact、Opportunity、Inquiry、Quotation、Commercial Order 和 Customer Operation。

## 二 当前目标

建立从线索、客户、商机、询盘、报价、商务订单到客户运营的销售闭环，使每个销售结果、异常、决策和行动可验证。

## 三 Own 范围

- Lead、Customer、Contact、Opportunity、Inquiry、Quotation、Commercial Order、Sales Activity
- SalesResult、SalesException、SalesDecisionRef、SalesEvidenceRef 和 SalesEvent
- 销售 Domain Agent、销售 Skill、销售业务上下文和专业验收
- 产品销售视图、销售材料引用、客户经营和销售风险

## 四 Must Not 边界

- 不拥有 Person/Org/Position、Product/BOM/Certification、Delivery/Capacity、Quality、Revenue/Margin/AR/AP 等专业事实
- 不把 M10 Personal Agent 当成 CRM 主数据 Owner
- 报价、发信、订单和高风险客户动作不得无确认自动执行

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| Lead/Customer/Contact | 客户、线索、联系人、来源和证据 | M05 |
| Opportunity/Inquiry | 商机、询盘、阶段、需求、匹配和风险 | M05 |
| Quotation/CommercialOrder | 报价、审批、商务订单和状态 | M05 |
| SalesActivity/Result | 沟通、跟进、销售结果和价值 | M05/M02 |
| SalesException/Decision | 价格、信用、交期、合规和客户风险 | M05/M03/M09/M06 |

## 六 接口与协作

- M10：提供 Personal Agent 的销售上下文、Todo、Exception、Past Result 和交互入口
- M04：读取产品销售视图；正式 Product/BOM/Certification 仍由 M04 负责
- M06/M08/M09：引用交付、质量、收入、信用、AR/AP 结果
- M13/M02：接入 Sales Agent Workforce、结果、证据和成本

## 七 安全控制

- 客户、价格、报价、合同、信用和外贸数据按租户、岗位和客户范围隔离
- 公开来源线索必须保留来源证据、去重、验证和人工复核
- 报价、发信、订单、价格和外部写入采用 Guard、人审和审计
- 禁止将客户资料、合同和敏感信息直接送入未授权模型或工具

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W21–W24 | G5 | 打通销售 Agent、Inquiry/Quote/Follow-up、Result/Evidence 闭环 |
| W25–W28 | G6 | 接入 M10 Personal Agent、M13 Workforce、M03 经营工作面 |
| W29–W32 | G7 | 完成客户隔离、Prompt Injection、发信/报价工具滥用和数据外发测试 |
| W33–W36 | G8 | 完成销售 KPI、复制模板、培训和运营移交 |

## 九 验收标准

- 询盘到报价准备、Guard、人审、发送、跟进、Result、Verification、Evidence 可闭环
- CRM 主数据和销售专业结果由 M05 负责，M10 只提供个人工作面
- 客户、价格、合同和外部沟通权限测试通过
- 销售 Agent 质量、时效、成本和人工验收口径明确

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/销售自治中心/AEOS_销售全生命周期自治简版方案_V1.2.md | AVAILABLE / HASHED | 0D51324DB841693D99828E2B7FB82729435AF954B8143A340F4430DD137566DF |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/销售自治中心/AEOS_M05_M10_Agent_标准与总体方案_归档资料包_2026-10-10/AEOS_M05_M10_Agent_总体方案_V2.0.md | AVAILABLE / HASHED | B52812BDFBEACB922E63D5EACC12AAE04883BEEC54050985CF11CDAD8D101DDB |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/销售自治中心/AEOS_M05_M10_Agent_标准与总体方案_归档资料包_2026-10-10/M05_M10_边界规范_V1.0.md | AVAILABLE / HASHED | EF33BC0A8ABB3777395F4CB0FCA18E022C083133E3D2FB6146B6B6E35C17A6DD |

M05/M10 当前方案为 G0 待审候选；POMS V2.2 需补齐具体原件后才能转为正式依赖。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M06 SPC 交付自治中心 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** Delivery Autonomous Center  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

供应链、生产协同、交付、项目履约、容量、发运和交付质量的专业自治中心。

## 二 当前目标

建立订单/项目到交付任务、计划、容量、发运、异常、验收和交付 Result/Evidence 的统一闭环。

## 三 Own 范围

- Delivery Project、Delivery Task、Capacity、Shipment、Supplier/Material 状态和交付计划
- 交付风险、延期、缺料、质量和履约异常
- 交付专业 Result、验收、客户交付证据和改进 Action
- 交付 Agent/Skill 的专业边界和人工接管规则

## 四 Must Not 边界

- 不拥有销售订单、产品 BOM、财务收入/应收、质量放行或人员权限事实
- 不允许 Agent 直接变更供应商、发运、产能或客户承诺
- 不得以系统状态替代现场交付、质量或客户验收

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| DeliveryProject/Task | 交付项目、任务、里程碑、责任和期限 | M06 |
| Capacity/Shipment | 产能、物料、发运、交期和执行状态 | M06 |
| DeliveryException | 延期、缺料、质量、供应商、客户和成本异常 | M06/M03 |
| DeliveryResult | 交付完成、客户验收、质量和价值结果 | M06/M02 |
| HandoverEvidence | 签收、照片、文件、验收和现场证据 | M06/M02 |

## 六 接口与协作

- M05：消费商业订单和客户承诺引用
- M04：消费产品、BOM、工程释放和变更引用
- M08/M09/M11：接收质量、成本、设备和现场接入结果
- M03/M13/M02：提交交付异常、Agent 工作负载、Result 和 Evidence

## 七 安全控制

- 供应商、客户、合同、交期、成本和现场数据分级隔离
- 发运、交期承诺、供应商切换、产能和外部通知需要审批
- 设备/现场接入通过 M11 受控网关，禁止 Agent 直接控制未登记设备
- 交付证据必须具备来源、时间、对象、责任和防篡改校验

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W21–W24 | G5 | 建立交付任务、异常、结果、验收和证据闭环 |
| W25–W28 | G6 | 接入销售承诺、研发变更、质量、财务和 M13 Agent Workforce |
| W29–W32 | G7 | 完成供应商、现场、设备、数据外发、人工接管和恢复测试 |
| W33–W36 | G8 | 完成交付 KPI、复制模板、客户验收和运营移交 |

## 九 验收标准

- 至少一条交付项目从计划到验收、异常关闭和客户证据闭环
- 交期、容量、发运、质量和成本结果可关联
- 不可逆交付承诺和外部通知具有审批和审计
- 现场/设备异常具备人工接管、回滚和证据保全路径

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/供应链中台/SPC供应链与生产协同中台 vs AEOS V7.2 对标评估报告 V1.0.md | AVAILABLE / HASHED | 9693A912507A9C3B7AFE69288C91902498EAA861EF546502C5766F20B26AB7A7 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/供应链中台/SPC → AEOS M06 交付自治中心整改实施方案 V1.0.md | AVAILABLE / HASHED | BEADC78F03FD40E4F035C10ADDA25D0F431FD5783D13252EEEDA7FFEFB9AE155 |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/AEOS_V7.2_整体更新方案_M13_M14_V7.2.2.md | AVAILABLE / HASHED | 88733AEB764317596D097C822FC49C98450C7DA45EB40F6CE7BB079AFDD20B0D |

M06 采用供应链对标与整改资料作为当前领域输入；正式边界、Owner 和数据契约需在 G1 完成确认。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M07 HLC 人力后勤自治中心 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** Human & Logistics Center  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

人员、人才、组织支持、人力服务和后勤服务的专业自治中心；M01 保留身份/组织/岗位权威，M10 保留个人操作工作面。

## 二 当前目标

建立人员服务、人才能力、岗位支持、培训、绩效、后勤请求与结果证据的可授权闭环。

## 三 Own 范围

- 人才能力、培训、绩效周期、招聘/任用流程的专业结果
- HR/后勤服务请求、任务、异常、通知和验收
- 人员服务和后勤服务的专业规则、模板、结果和证据
- 与 M01 的组织/岗位引用及与 M10 的个人工作面协作

## 四 Must Not 边界

- 不拥有 Person/Org/Position 的身份主数据和权限事实
- 不把 HR 对标检查结果直接当作完整 POMS V2.2 原件
- 涉及人事、薪酬、健康、身份和考核的动作不得无人工复核自动执行

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| TalentProfile | 能力、技能、培训、认证和发展目标引用 | M07 |
| HRServiceRequest | 人力服务请求、处理、结果和证据 | M07 |
| Training/Performance | 培训、评估、绩效周期和结果 | M07 |
| LogisticsRequest | 后勤、资产、空间、服务请求和验收 | M07 |
| Person/Org/PositionRef | 人员、组织和岗位的引用 | M01 |

## 六 接口与协作

- M01：引用人员、组织、岗位、授权和职责分离
- M10：提供个人待办、异常、结果、通知和 Personal Agent 上下文
- M13：管理 HR/后勤 Agent 的岗位、工作量、质量和成本
- M02/M03：提交服务 Result、异常、决策、行动和 Evidence

## 七 安全控制

- 人事、薪酬、健康、身份和绩效数据强制分级、最小权限、脱敏和审计
- 招聘、任用、绩效、权限、薪酬、离职和资产回收需要人工审批
- 模型和 Agent 不得依据敏感属性作未经批准的自动决定
- 个人数据导出、共享、留存和删除有授权、期限和证明

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W25–W28 | G6 | 建立 HR/后勤服务、个人工作面、Agent 任务和结果闭环 |
| W29–W32 | G7 | 完成个人敏感数据、访问撤销、模型偏差和人工复核测试 |
| W33–W36 | G8 | 完成服务 KPI、运营移交、培训和复制模板 |

## 九 验收标准

- 人员和岗位引用全部来自 M01，M07 不维护第二套身份权威
- 敏感人事动作有人工审批、审计和撤销路径
- 服务请求从提出到 Result、Verification、Evidence 可追踪
- M07 与 M10/POMS 的边界明确；POMS 证据不足时保持候选状态

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/人力资源自治中心/AEOS_V7.2_恒聘通_HRM_对标检查报告_V0.1.md | AVAILABLE / HASHED | 0D4820790954349F0FC3FC9B8C3A14B4DB9D3B43860FB499A65260238E5FDC82 |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/POMS_V2.2_来源核验与待加载记录_V1.1.md | AVAILABLE / HASHED | 6AA46B680B384F38F9D73CB46CB0C7A0D7A219340FBA8935C5E8677F4B64B3A2 |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/AEOS_P0-01_System_Registry_V1.2_M13_M14同步候选.md | AVAILABLE / HASHED | 01E5B3389DC0C208D4A60BD514A860DD44F3E4B032E073AB31075953E342285D |

当前人力资料以对标检查为主，不能替代 POMS V2.2；正式 POMS 文件、来源、版本和 SHA-256 仍是 M07/M10 进入正式矩阵的前置条件。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M08 QAC 质量自治中心 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** Quality Autonomous Center  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

质量规则、验证、缺陷、例外、现场质量、CAPA 和质量证据的专业自治中心；质量结论由专业责任人验收。

## 二 当前目标

将质量计划、检验、缺陷、异常、纠正预防、放行和质量价值纳入统一 Object/Event/Result/Evidence 闭环。

## 三 Own 范围

- 质量规则、检查计划、检验任务、缺陷、质量异常和 CAPA
- 质量验证、放行建议、质量 Result、证据和趋势指标
- 现场质量、供应商质量、产品质量和交付质量的专业判断
- 质量 Agent/Skill 的受控建议、抽检、归因和学习

## 四 Must Not 边界

- 不拥有产品工程主数据、交付计划、财务价值或系统发布权限
- 不让自动质量评分直接替代法规、工艺、客户或专业负责人签字
- 不允许质量数据静默修改或缺陷无证据关闭

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| QualityRule/Plan | 质量规则、检查计划、版本和适用范围 | M08 |
| Inspection/Test | 检验、测试、样本、设备、方法和结果 | M08/M04/M12 |
| Defect/Nonconformity | 缺陷、不符合、严重度、原因和证据 | M08 |
| CAPA | 纠正预防措施、责任、期限、验证和关闭 | M08 |
| QualityRelease | 质量放行建议、审批、限制和证据 | M08/业务 Owner |

## 六 接口与协作

- M04/M06/M11：接收研发、交付、设备和现场质量输入
- M12：接收软件质量、扫描、测试、漏洞和发布门禁结果
- M02/M03：提交质量 Result、Exception、Decision、Action、Evidence
- M13/M14：管理质量 Agent 工作和涉及系统质量门禁

## 七 安全控制

- 质量、客户、法规、产品和现场证据分级管理、不可静默覆盖
- 放行、封存、返工、召回和外部质量通知需人工审批
- 检验设备和现场接入采用 M11 设备身份和网络分区
- 质量结论可追溯到规则版本、样本、方法、人员/Agent 和 Evidence

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W25–W28 | G6 | 建立质量规则、缺陷、CAPA、Result/Evidence 与业务闭环 |
| W29–W32 | G7 | 完成质量数据防篡改、现场接入、扫描、放行和人工接管测试 |
| W33–W36 | G8 | 完成质量 KPI、审计、复制模板和运营移交 |

## 九 验收标准

- 缺陷/不符合从识别到 CAPA、验证和关闭有完整证据
- 关键放行、召回、返工和客户质量动作有人工授权
- 质量结果可回放并能关联规则、样本、设备、人员/Agent 和时间
- 质量系统与 M04/M06/M12/M11 边界清晰

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/AEOS_V7.2_整体更新方案_M13_M14_V7.2.2.md | AVAILABLE / HASHED | 88733AEB764317596D097C822FC49C98450C7DA45EB40F6CE7BB079AFDD20B0D |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/研发自治中心/V1.1版/AEOS_研发自治中心_PLM-2迭代解决方案与行动计划_V1.1_2026-09-23.docx | AVAILABLE / HASHED | A9A63576904908CC1EFBD5B30BD2424457D05284E60785C714C4BAE21A701026 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/供应链中台/SPC供应链与生产协同中台 vs AEOS V7.2 对标评估报告 V1.0.md | AVAILABLE / HASHED | 9693A912507A9C3B7AFE69288C91902498EAA861EF546502C5766F20B26AB7A7 |

当前没有独立质量中心正式主方案，本方案为当前架构下的执行候选；需在 G0 指定质量 Owner 并在 G1 补齐质量契约。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M09 FAC 财经自治中心 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** Finance Autonomous Center  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

企业经营财经事实、盈利判断、现金判断、预算、成本、风险、财务预测和价值结果的专业自治中心。

## 二 当前目标

将收入、成本、毛利、应收、应付、现金、预算、投资和 ROI 统一形成 Fact → Event → Decision → Action → Result → Verification → Evidence → Value。

## 三 Own 范围

- 财务对象、成本、收入、毛利、AR/AP、现金、预算、投资和 ROI 专业事实
- 财经计算、版本、口径、预测、风险识别和财经 Result
- 财经 Agent/Skill 的建议、解释、证据和人工验收
- 价值账、成本归集、经营财经异常和审批引用

## 四 Must Not 边界

- 不直接读取 ERP/CRM/SPC/HR/MES 数据库，统一通过 M02 接入
- 不让 Agent 直接付款、改账、改预算或确认财务结论
- 不复制 EBMS 的经营看板和管理行动；M03 只消费财经 Result/Exception/Decision、Action

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| FinanceFact | 收入、成本、毛利、AR, AP、现金、预算、投资等事实 | M09 |
| FinanceEvent | 交易、结算、收款、付款、成本、预算变化 | M09/M02 |
| FinanceResult | 毛利、现金、预算、ROI、预测、风险结果 | M09 |
| FinanceDecision、Action | 融资、预算、收款、成本和风险行动 | M09/M03 |
| ValueLedger | 价值、成本、收益、口径、周期和证据 | M09/M02 |

## 六 接口与协作

- M02：Source Adapter、Object、Event、Evidence、Provenance、DQ、Value Ledger
- M03：提供 Margin、Cash、AR、ROI、Exception、Decision、Action 和 Evidence
- M05/M06/M07：引用销售、交付、人力、成本和履约结果
- M13/M14：管理财经 Agent 工作和财经系统变更证据

## 七 安全控制

- 财务、薪酬、客户信用、银行和税务数据强隔离、加密和最小权限
- 付款、改账、预算、信用、税务和资金动作采用职责分离和双人审批
- 财务计算必须有版本、输入、口径、公式、时间窗口和 Evidence
- 禁止秘密、银行凭证、税务信息进入 Prompt、日志或未授权外部工具

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W17–W20 | G4 | 建立 M09 财经 Result 与 M03 经营异常/决策闭环 |
| W25–W28 | G6 | 接入 M13 财经 Agent 绩效/成本和 M14 财经相关系统变更 |
| W29–W32 | G7 | 完成资金、权限、数据导出、供应链和灾备测试 |
| W33–W36 | G8 | 完成财经 KPI、结算/审计证据、运营移交和复制模板 |

## 九 验收标准

- 毛利、现金或 ROI 至少一条 Result Contract 可由输入追溯到 Evidence
- 财务事实和算法由 M09 Owner 负责，EBMS 不复制专业计算
- 付款、改账、预算和信用动作的审批、职责分离和审计通过
- 财务数据备份恢复、导出控制和敏感信息防护通过

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/FAC财经自制中心/AEOS V7.2 — M09 FAC  V2.1财经自治中心完整总体方案与分阶段实施计划.md | AVAILABLE / HASHED | 2978D87CD4553391A7D07C6B89C46395E048E9A8F025FE015A713176F667F8B6 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/FAC财经自制中心/AEOS V7.2 — M09 FAC 第一阶段 MVP 开发执行方案 V1.1.md | AVAILABLE / HASHED | 7D4A0F1E13819357DD0F065550B922559C9BC3FB6534D4F9039D38677E49F8C8 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/FAC财经自制中心/FAC行动计划.md | AVAILABLE / HASHED | FF22EFC94F5235262FC2E0A0C0D806FAE51A01967661BC6FAD2764B9D258DBEB |

FAC V2.1 和 MVP V1.1 作为当前财经领域输入；正式接入仍需 M02 Contract、M01 权限和业务 Owner 验收。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M10 POMS 岗位与个人运营微系统 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** Role & Personal Operations Micro-system  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

岗位模板、个人上下文、待办、异常、结果和 Personal Agent 的个人操作工作面；不拥有业务主数据。

## 二 当前目标

为每个人和 Agent 提供受岗位、目标、权限和业务上下文约束的操作入口，将 Todo、Exception、Past Result、Personal Agent 连接到专业中心和 M02。

## 三 Own 范围

- ui_manifest、role_template_ref、personal_context、session_context、notification_state、local_pending_input、sync_state
- 岗位模板引用、个人工作面、待办、异常、通知、交互和个人结果引用
- Personal Agent 装配入口、上下文切换和个人操作体验
- POMS 与 M05/M07/M13 的个人工作关系

## 四 Must Not 边界

- 不拥有 Customer、Order、Quote、Product、Finance、Quality 等专业对象
- 不拥有 Person/Org/Position 和 Permission/Policy/Guard 的权威事实
- 不把 ChatGPT 项目线索或 M05/M10 依赖文字当作 POMS V2.2 正式原件

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| RoleTemplateRef | 岗位能力、目标、权限和流程引用 | M10 引用 M01/M07 |
| PersonalContext | 个人, Agent 当前上下文、目标、工作范围 | M10 |
| Todo/Exception | 未来待办、当前异常、期限、责任和升级 | M10/M02 |
| PastResult | 过去结果的引用和证据链接 | M02 |
| PersonalAgentSession | Personal Agent 会话、工具、权限和审计 | M10/M13/M01 |

## 六 接口与协作

- M01：读取岗位、组织、权限、Policy 和 Guard，不复制权威事实
- M05/M07/M13：提供个人/Agent 工作面和任务上下文
- M02：写入 Todo、Exception、Result、Evidence、Audit 的契约记录
- M03：展示经营异常和行动，但不重复经营看板事实

## 七 安全控制

- 个人、岗位、绩效、会话和敏感上下文分级隔离
- Personal Agent 工具白名单、会话预算、记忆隔离、敏感内容脱敏和人工接管
- 本地待同步输入需加密、过期、冲突解决和审计
- 不允许通过 UI 或 Prompt 绕过 M01 权限或直接写专业库

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W25–W28 | G6 | 完成 POMS 证据核验、RoleTemplate、PersonalContext、Todo/Exception/Result 最小闭环 |
| W29–W32 | G7 | 完成个人数据、会话、工具、记忆、同步和权限测试 |
| W33–W36 | G8 | 完成 POMS 运行手册、培训、验收和复制模板 |

## 九 验收标准

- POMS V2.2 具有具体文件、来源、版本、日期/状态、主格式和 SHA-256 后再进入正式矩阵
- M10 不拥有专业业务主数据，所有业务动作仍通过专业中心和 M01/M02 契约
- 个人/Agent 操作面可关联 Todo、Exception、Result、Evidence 和权限
- 同步冲突、离线输入、撤权、会话终止和记忆隔离测试通过

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/销售自治中心/AEOS_M05_M10_Agent_标准与总体方案_归档资料包_2026-10-10/M05_M10_边界规范_V1.0.md | AVAILABLE / HASHED | EF33BC0A8ABB3777395F4CB0FCA18E022C083133E3D2FB6146B6B6E35C17A6DD |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/销售自治中心/AEOS_M05_M10_Agent_标准与总体方案_归档资料包_2026-10-10/AEOS_M05_M10_Agent_总体方案_V2.0.md | AVAILABLE / HASHED | B52812BDFBEACB922E63D5EACC12AAE04883BEEC54050985CF11CDAD8D101DDB |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/POMS_V2.2_来源核验与待加载记录_V1.1.md | AVAILABLE / HASHED | 6AA46B680B384F38F9D73CB46CB0C7A0D7A219340FBA8935C5E8677F4B64B3A2 |

POMS V2.2 当前为 PROVISIONAL / EVIDENCE-PENDING；具体文件、来源、版本和 SHA-256 未补齐前只能作为依赖候选。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M11 IHC 集成与智能硬件接入中心 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** Integration & Intelligent Hardware Center  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

外部系统、会议、消息、智能硬件、现场和设备接入中心；将接入事件转化为受控 Event、Decision、Action、Result 和 Evidence。

## 二 当前目标

通过连接器、设备网关、会议模块和接入审计，把外部输入和现场操作纳入 AEOS 统一契约和安全控制。

## 三 Own 范围

- 连接器、Outbox、Webhook、设备身份、会议输入和现场接入适配
- Meeting/ASR/文档/图片/设备事件到 Event、Decision、Action、Evidence 的转换
- 设备/会议/现场接入的重试、幂等、授权、状态和审计
- 接入层可观测性、限流、隔离、降级和人工接管

## 四 Must Not 边界

- 不让 Meeting 成为全局业务主对象；会议输入必须降维为 AEOS Event/Decision、Action 等通用对象
- 不允许连接器直接跨域写业务库或执行未经授权的外部副作用
- 不把会议助手或设备报告直接当作所有业务系统的正式标准

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| Connector/Integration | 连接器、版本、凭证、租户、状态和策略 | M11/M01 |
| Meeting/SourceEvent | 会议、ASR、文档、图片、外部事件和来源 | M11/M02 |
| Device/AccessEvent | 设备、现场、远程访问和操作事件 | M11/M02 |
| Action/Notification | 通知、任务、外部发送、现场动作 | M11/M02/M01 |
| IntegrationEvidence | 来源、时间、响应、重试、回执和审计 | M02 |

## 六 接口与协作

- M01：设备/连接器身份、权限、凭证、Guard 和租户
- M02：统一 Event、Result、Evidence、Audit、Outbox 和 Trace
- M03/M05/M06/M07/M09：接收各域通知、会议、现场和外部系统输入
- M12：运行观测、密钥、网络分段、告警和发布门禁

## 七 安全控制

- 连接器凭证存于 Secret 管理，短时化、轮换、分租户和可撤销
- 外部内容、会议转写、附件、网页和设备数据按不可信输入处理
- 设备和现场动作采用白名单、审批、人审、双人复核、限时授权和断路器
- 出网白名单、域名/地址限制、签名回执、重放保护、限流和异常隔离

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W17–W20 | G4 | 完成 Meeting/Connector/Outbox 到 Decision、Action/Result/Evidence 的最小闭环 |
| W25–W28 | G6 | 接入 M05/M06/M07/M13 的通知、会议和现场证据 |
| W29–W32 | G7 | 完成凭证、Prompt Injection、出网、设备控制和恢复演练 |
| W33–W36 | G8 | 完成连接器目录、值班、告警、培训和复制包 |

## 九 验收标准

- 外部输入可追踪到来源、身份、时间、策略、Action、回执和 Evidence
- 所有外部写入、发送、设备和现场动作有审批/审计/回滚或人工接管
- 连接器重试、幂等、断网、凭证撤销和降级测试通过
- Meeting 作为接入模块服务 AEOS 通用对象，不形成平行主数据体系

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/会议系统-AEOS/meeting-helper_AEOS_V7.2_适配评估正式报告_V1.0.docx | AVAILABLE / HASHED | 5BCDFB8984002099BD567EA9230162E49C7900D9721593B11436E3879636C5D2 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/AEOS V7.2 完整合并版deep-research-report (4).md | AVAILABLE / HASHED | 9D744BF04720564B84C540FF7BEE48DE4FB3C41044D99E4CB930E0CC3D02C438 |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/AEOS_V7.2_整体更新方案_M13_M14_V7.2.2.md | AVAILABLE / HASHED | 88733AEB764317596D097C822FC49C98450C7DA45EB40F6CE7BB079AFDD20B0D |

meeting-helper 适合作为 M11 的 Meeting Module/接入能力；正式接入需完成连接器、设备、凭证和安全验收。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M12 DSO DevSecOps 与可观测性质量中心 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** DevSecOps, Observability & Quality Center  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

AEOS 的工程基础设施、安全扫描、测试、质量、构建、制品、发布、观测、告警和恢复门禁中心。

## 二 当前目标

让 M14 和所有模块的代码、依赖、制品、部署、运行、告警和回滚具备可追溯、可阻断和可恢复能力。

## 三 Own 范围

- CI/CD、分支保护、PR、SAST、SCA、Secret Scan、容器/IaC 扫描、SBOM 和制品签名
- 测试、质量门禁、环境、配置、部署、观测、告警、日志和 Trace
- 发布审批、变更审计、回滚、备份恢复和事件响应基础设施
- 工程安全策略、门禁规则、运行可靠性、容量和成本监控

## 四 Must Not 边界

- 不拥有 M14 的研发管理业务对象和 M04 的研发专业事实
- 不以扫描通过替代业务、现场、法规或专业 Owner 验收
- 不允许生产变更、凭证或制品绕过发布门禁和审计

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| Pipeline、Build | 流水线、构建、输入、环境、状态和日志 | M12 |
| Test/Scan | 测试、漏洞、质量、扫描规则、结果和例外 | M12 |
| SBOM/Artifact | 依赖、制品、签名、来源、哈希和证明 | M12 |
| Release/Deploy/Rollback | 发布、部署、环境、审批、回滚和恢复 | M12/M14 |
| Observability/Incident | 日志、指标、Trace、告警、事件和响应 | M12 |

## 六 接口与协作

- M14：接收系统研发任务，返回 Build/Test/Release/Deploy/Rollback 状态和证据
- M01：服务身份、环境权限、审批和撤权
- M02：写入工程 Evidence、Audit、Trace、Result 和风险
- M13：记录 Agent 运行资源、成本、失败、质量和熔断

## 七 安全控制

- 构建环境隔离、最小权限、短时凭证、不可变制品和签名验证
- Critical 漏洞、密钥泄露、未签名制品、来源不明和质量门禁失败阻断发布
- 运行环境非 root、只读文件系统、资源配额、网络分段和出网控制
- 备份恢复、日志保全、事件隔离、凭证撤销和人工降级可执行

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W13–W16 | G3 | 接入 CI/CD、扫描、测试、观测、审计和发布门禁 |
| W17–W28 | G4–G6 | 为 M03–M11、M13、M14 提供可复用工程安全能力 |
| W29–W32 | G7 | 完成供应链、红队、灾备、恢复、人工接管和回滚演练 |
| W33–W36 | G8 | 完成运营值班、告警、容量、成本和发布移交 |

## 九 验收标准

- 所有生产制品具有 SBOM、签名、来源、构建和部署证据
- Critical=0；High 已关闭或完成授权风险接受
- 发布、回滚、备份恢复、凭证撤销和事件响应演练通过
- M14 无法绕过 M12 的扫描、质量、发布和审计门禁

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/AEOS_V7.2_完整总体方案与开发治理基线.docx | AVAILABLE / HASHED | 5BA7718C8FDF915DE46B6935220C0B39AFBD720AC2351130EC5368EB6ACFC015 |
| AEOS_执行前评审方案_20261014_V7.2.2/01_执行前评审总方案/AEOS_V7.2.2_执行前评审总方案.docx | AVAILABLE / HASHED | 9463B9DB83BF01437A782F4DC4F5F56511C577645C9102F14180AC9A379A3549 |
| AEOS_团队执行资料包_20261014_V7.2.2/02_执行台账与模板/04_Gate与安全门禁检查表.md | AVAILABLE / HASHED | 2C0B771D3EF3A80F63BC4246734E9C95E5EC8C4DDF86F71FFE7FD17F9FB22D9F |

M12 的当前基线由总体开发治理与执行前安全门禁组成；实施前需要指定 M12 Owner 并锁定工具链、环境和发布证据格式。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M13 Hub 智能体员工自治管理中心 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** AEOS Agent Workforce Center  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

面向 Agent 员工/Agent Workforce 的自治管理平台，类似人员管理平台，负责 Agent 的组织、岗位、能力、生命周期、运行、工作量、SLA、绩效、成本和退出。

## 二 当前目标

建立 Agent 从登记、岗位绑定、配置、训练/评测、启用、排班、运行、暂停、转岗、降权、人工接管到退出的完整管理闭环。

## 三 Own 范围

- Agent 员工档案、agent_id、岗位绑定、团队关系、Skill/Model/Prompt/Tool 版本引用
- Lead Agent、Specialist Agent、Agent Team、工作负载、任务分派和排班
- Runtime、Workload、SLA、失败、重试、熔断、绩效、质量、成本和版本评测
- Agent 在 M03–M10、M14 中的投影、入口、生命周期和控制记录

## 四 Must Not 边界

- 不取代 M01 的 Person/Org/Position、Permission、Policy 和 Guard
- 不取代 M02 的 Object/Event/Result/Evidence/Audit 权威
- 不成为业务对象、业务结果或系统研发成果的 Owner
- 不让 Agent 绕过授权、审批、Guard、M12 门禁或人工接管

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| AgentRegistry | agent_id、角色、岗位、技能、模型、Prompt、Tool、版本、Owner、状态 | M13/M01 |
| WorkforcePosition/Team | 岗位、团队、Lead, Specialist、能力、范围和成本中心 | M13/M01 |
| AgentLifecycle | 配置、训练、启用、暂停、转岗、降权、退休、退出 | M13 |
| Runtime/Workload/SLA | 运行、队列、并发、失败、重试、预算、时效和资源 | M13/M12 |
| Performance/Cost/Exit | 质量、绩效、成本、熔断、人工接管和退出证据 | M13/M02 |

## 六 接口与协作

- M01：引用 Agent identity、岗位、授权和 Guard；不得修改权限事实
- M02：记录 Agent Result、Evidence、Audit、Trace、Cost 和退出证据
- M14：提供研发 Agent 的岗位/团队/能力上下文，接收工程任务和结果
- M03–M10：提供各业务中心的 Agent 入口、工作投影、专业验收和反馈

## 七 安全控制

- 每个 Agent 使用受控身份、最小权限、租户和成本边界；工具、网络、文件、数据库和出网白名单
- Prompt Injection、间接注入、不可信内容、记忆污染、工具滥用、数据外发和越权测试
- 生产写入、发版、删除、付款、设备动作、权限提升和外部发送必须人审/双人/业务 Owner
- 预算、超时、并发、速率、熔断、隔离、凭证撤销、人工接管和证据保全可执行

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W01–W04 | G0 | 确认 M13 编号、边界、Owner、Must Not、P0-01/P0-02/P0 同步和安全风险 |
| W05–W16 | G1/G3 | 完成 AgentIdentity、Registry、岗位、生命周期、Runtime、Result/Evidence 契约 |
| W21–W28 | G5/G6 | 完成三中心接入、Workforce 最小闭环、绩效成本和 M14 协作 |
| W29–W36 | G7/G8 | 完成 Agent 红队、工具治理、灾备、熔断、验收、运营和复制 |

## 九 验收标准

- Agent 生命周期可登记、启用、暂停、撤权、转岗和退出，且每一步有证据
- 高风险工具调用 100% 有策略判定、审批/人审、审计和可熔断
- Agent 工作量、SLA、质量、成本和版本可比较、可回放、可复核
- M13 与 M01/M02/M12/M14 责任边界无重叠，业务结果由专业中心验收

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/Hub智能体/AEOS_Hub_M13智能体员工管理中心定位与编号决议_V1.0.md | AVAILABLE / HASHED | 5050F1EBE4D2E0B9037BCE07B04ED33AF4411573CF7212BAAA0F15FBEC385F4A |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/Hub智能体/V1.2执行版.md | AVAILABLE / HASHED | BC82BD32E08E39930A59EECB4863302364CA7D2ABE66CA8A8FA3A6380B9A20E6 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/销售自治中心/AEOS_M05_M10_Agent_标准与总体方案_归档资料包_2026-10-10/AEOS_Agent_分层装配与治理规范_V1.0.md | AVAILABLE / HASHED | FA578EF157EE467C7E7D7C0843FC9971ADEB8FA2D8821C577E13E0514E68178A |

M13 定位与编号已纳入当前方案，但正式 P0 同步签批、Agent 工具注册、运行证据和安全红队仍是 G0/G7 放行条件。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

# M14 NOMI 系统研发自治中心 最新方案

**方案版本：** V7.2.2  
**方案状态：** 当前执行候选，待对应 Owner 与 Gate 签批  
**英文名称：** NOMI System Development Autonomous Center  
**建议起始日：** 2026-10-19（PMO 签发后生效）

## 一 当前定位

AEOS 的系统开发自治管理平台，负责系统如何被规划、研发、验证、发布、运行和持续改进。M14 管系统研发工作，不管人的组织事实和业务专业事实。

## 二 当前目标

建立 System → Product/Repo → Requirement/Design → Change/Task → Build/Test → Artifact/Release → Deploy/Rollback → Incident/Debt 的全链路工程管理闭环。

## 三 Own 范围

- System、Product、Component、Repository、Branch、Environment、Criticality 和 Engineering Owner
- Requirement、Design、Task、Change、PR、Review、Approval 和计划
- Build、Test、Defect、Vulnerability、Artifact、Release、Deploy、Rollback
- 开发 Agent 编排、工程结果、技术债、性能、可靠性、安全整改和交付状态

## 四 Must Not 边界

- 不拥有 Person/Org/Position、Permission/Policy/Guard 的权威事实
- 不拥有 Customer、Order、Finance、Quality 等业务对象和业务验收
- 不自行授予开发 Agent 生产权限，不绕过 M12 扫描、质量、发布和审计
- 自动化测试通过不替代现场、法规、工艺或业务责任人验收

## 五 核心对象与事实 Owner

| 对象域 | 定义 | Owner |
| --- | --- | --- |
| System/Product/Repo | 系统、产品、组件、仓库、分支、环境、Owner、关键性 | M14 |
| Requirement/Design/Task | 需求、设计、任务、依赖、工期和责任 | M14/M04 |
| Change/PR/Approval | 变更、代码审查、审批、影响和回滚 | M14/M01 |
| Build、Test、Vulnerability | 构建、测试、质量、漏洞、缺陷和扫描结果 | M12/M14 |
| Artifact、Release、Deploy、Rollback | 制品、发布、部署、环境、回滚和恢复 | M12/M14 |
| Incident/TechnicalDebt | 事件、技术债、整改、风险和持续改进 | M14/M00 |

## 六 接口与协作

- M13：接收研发 Agent 身份、岗位、团队、能力、工作量和成本上下文
- M12：调用构建、测试、扫描、SBOM、签名、发布、观测和恢复门禁
- M01：获得服务/Agent/环境授权；不得自行授予生产权限
- M02：记录工程 Object/Event/Result/Evidence/Audit/Trace 并支持回放
- M04/M03：接收研发专业验收和经营管理引用，不替代其事实 Owner

## 七 安全控制

- 仓库、分支、PR、构建、制品和环境最小权限；短时凭证、分支保护和双人复核
- SAST、SCA、Secret Scan、容器/IaC 扫描、SBOM、制品签名、构建来源和部署证明
- 开发 Agent 工具白名单、沙箱、资源预算、出网限制、人工审批、异常熔断和生产隔离
- 发布、部署、数据迁移、权限变更、回滚和生产运维动作必须审计且可恢复

## 八 36 周落地安排

| 周期 | Gate | 当前必须完成 |
| --- | --- | --- |
| W01–W04 | G0 | 确认 M14 编号、边界、Owner、NOMI 来源证据、M13 协作和 No-Go |
| W05–W16 | G1/G3 | 完成 System/Repo/Change/Task/Build/Test/Release/Object ID 与契约、流水线门禁 |
| W17–W28 | G4–G6 | 跑通研发真实闭环并接入 M04、M13、M02、M12 和业务验收 |
| W29–W36 | G7/G8 | 供应链、红队、灾备、回滚、技术债、运营移交和终验 |

## 九 验收标准

- 需求到任务、代码/变更、构建、测试、漏洞、制品、发布、部署和回滚 100% 可关联
- 不可追溯、未签名、未扫描、未审批或不可回滚的制品不得发布
- 开发 Agent 无法绕过 M01 权限、M02 Evidence 和 M12 安全质量门禁
- M14 原始方案/正式来源、版本和 SHA-256 完成证据登记后再进入正式标准矩阵

## 十 当前来源与证据状态

| 来源 | 状态 | SHA-256 |
| --- | --- | --- |
| AEOS_执行前评审方案_20261014_V7.2.2/01_执行前评审总方案/AEOS_V7.2.2_执行前评审总方案.docx | AVAILABLE / HASHED | 9463B9DB83BF01437A782F4DC4F5F56511C577645C9102F14180AC9A379A3549 |
| AEOS_最终资料归档_20261014_V7.2.2/03_原始资料镜像/研发自治中心/V1.1版/AEOS_研发自治中心_PLM-2迭代解决方案与行动计划_V1.1_2026-09-23.docx | AVAILABLE / HASHED | A9A63576904908CC1EFBD5B30BD2424457D05284E60785C714C4BAE21A701026 |
| AEOS_最终资料归档_20261014_V7.2.2/02_标准与治理/本轮核查与更新候选/03_GitHub与ChatGPT项目对照.md | AVAILABLE / HASHED | A332431D86807730E24A9EF380754D134A4B4C58B6A0F13F1C2C79F6C03536F1 |

M14 已按当前架构决策纳入 M14；NOMI 的正式方案文件、来源、版本和 SHA-256 仍需由 M14 Owner 登记并提交 G0/G6 评审。 对应正式文件仍须按 System Registry V1.3 候选字段登记。

## 十一 执行输入

本方案执行输入固定为：AEOS V7.2.2 当前评审基线、9 个月/36 周计划、M01/M02/M12 安全与证据门禁、M13 Hub 与 M14 NOMI 当前边界、对应模块领域资料和经登记的 GitHub/ChatGPT 证据。

## 十六 跨系统最终放行条件

- M00–M14 均有当前方案、Owner、事实边界、接口、验收标准和 Evidence 位置。
- P0-01/P0-02 与 M13/M14 当前边界完成签批；P0-03/P0-04/P0-05 具备正式文件、来源、版本和 SHA-256。
- POMS V2.2 具备具体文件、来源、版本、日期/状态、主格式和 SHA-256，或由 PMO 明确其候选依赖处置方式。
- M14 NOMI 具备正式方案来源、版本和 SHA-256，且其工程链路接入 M12 安全质量门禁。
- Critical 漏洞为零；High 漏洞关闭或正式风险接受；身份、租户、Agent、供应链、灾备、回滚和人工接管测试通过。
- G0–G8 每个 Gate 都具备通过、保持或 No-Go 结论、责任人、截止时间和完整性清单。

## 十七 统一命名与对象代码

# AEOS 对象代码与闭环规范 V1.0

**状态：** CANDIDATE / G1 前置  
**适用范围：** API、数据库、Event Envelope、Result、Evidence、Decision、Action、Verification 和跨模块 Adapter

## 一 ID 命名

| field_name | 语义 | 事实 Owner | 使用要求 |
| --- | --- | --- | --- |
| tenant_id | 租户 | M01 | 所有跨租户对象和事件的隔离边界 |
| system_id | 系统 | M00 | System Registry 的系统唯一标识 |
| object_id | 对象 | M02 | Object/BusinessObject 的通用唯一标识 |
| event_id | 事件 | M02 | 状态变化、来源、主体和时间 |
| goal_id | 目标 | M03/业务中心 | 目标和指标关联 |
| decision_id | 决策 | M03/业务中心 | 决策案例和审批关联 |
| action_id | 行动 | 专业中心/M03/M14 | 行动、执行、回执和升级关联 |
| result_id | 结果 | 专业中心/M02 | 可验证业务或工程结果 |
| verification_id | 验证 | 专业中心/M02 | 验证动作和验证结论 |
| evidence_id | 证据 | M02 | 文件、测试、审批、回执、来源和哈希 |
| trace_id | 链路 | M02/M12 | 跨服务、跨模块和跨 Agent 追踪 |
| person_id | 人员 | M01 | 人员身份引用 |
| org_id | 组织 | M01 | 组织身份引用 |
| position_id | 岗位 | M01 | 岗位身份引用 |
| agent_id | 智能体 | M01/M13 | Agent 身份引用 |
| team_id | 团队 | M01/M13 | 组织或 Agent Team 引用 |
| task_id | 任务 | 专业中心/M14 | 业务任务或工程任务 |

统一要求：

- 数据库、Event、内部 API 统一使用 snake_case。
- React/TypeScript ViewModel 可以使用 camelCase，但必须经过 Adapter 转换。
- 禁止在同一契约中混用 `objectId`、`object_id`、`ObjectID`。

## 二 Owner 字段

| field_name | 中文 | 定义 | 责任 |
| --- | --- | --- | --- |
| fact_owner | 事实 Owner | 对一个关键 Object/Result 只能有一个 | 负责事实定义、专业结果和最终事实责任 |
| record_owner | 记录 Owner | 通常为 M02 或产生记录的域 | 负责记录、证据、审计和留存 |
| processor | 处理者 | 执行计算、转换或动作的服务/Agent/人员 | 不自动获得事实 Owner 权限 |
| consumer | 消费者 | 读取或引用结果的模块 | 只能按契约消费，不复制事实 |
| verifier | 验证者 | 负责验证结果的人或岗位 | 对 Verification 结论负责 |

每个关键 Object/Result 必须有且只有一个 `fact_owner`；`record_owner`、`processor`、`consumer`、`verifier` 可以同时存在，但不得替代事实 Owner。

## 三 AEOS 核心闭环

```text
Object
  ↓
Event
  ↓
Exception       optional
  ↓
Decision        optional
  ↓
Action
  ↓
Result
  ↓
Verification
  ↓
Evidence
  ↓
Value
  ↓
Learning
```

`Fact` 是 Object 当前被验证的事实状态，不是独立流程节点。

## 四 对象命名

- 对象名称采用 PascalCase，例如 `AgentRegistry`、`DecisionCase`、`TechnicalDebt`。
- 禁止用 `/` 把多个对象写成一个 schema、API 或 Event 名称；`Result`、`Metric`、`Value` 必须分别建模。
- 对象实体统一使用 `Verification`；动作统一使用 `verify`。
- 文档中可以用“对象组”表达多个对象，但 schema、数据库、API 和 Event 必须拆分。

## 五 Event Envelope 最低字段

```json
{
  "event_id": "evt_...",
  "tenant_id": "ten_...",
  "system_id": "M02-EDP",
  "object_id": "obj_...",
  "event_type": "object.updated",
  "actor_id": "agent_...",
  "trace_id": "trace_...",
  "occurred_at": "2026-10-15T00:00:00Z",
  "schema_version": "v1",
  "evidence_ids": []
}
```