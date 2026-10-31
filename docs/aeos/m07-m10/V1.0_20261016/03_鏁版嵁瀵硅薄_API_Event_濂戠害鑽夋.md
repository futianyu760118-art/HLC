# 数据对象与 API/Event/Result/Evidence 契约草案
> **控制状态：执行候选 / 尚未获各 Owner 与 Gate 批准。** 本包是供研发、评审、拆解任务使用的工程设计输入，不等同已冻结的 AEOS 标准。
> **来源等级：** [B] 上传的 AEOS V7.2.2 合订版；[C] 已核查 HLC 仓库代码（关键文件片段）；[D] 2026-10-15 V3.0 DEMO/讨论；[P] 本次新增的设计建议；[V] 生产部署或外部开源组件待验证。

## 1. 数据所有权与最小化
M01 owns `CanonicalIdentity`、任职和权限；M07 owns HR/后勤 Request、人才能力、培训及绩效专业记录；M10 owns 个体工作面配置、通知/会话状态与本地待提交输入；M02 owns Event/Evidence/Trace 标准；M13 owns Agent Registry/Lifecycle。[B]

## 2. 建议的对象结构（需 G1 受控冻结）
```json
{
  "WorkItemProjection": {"work_item_id":"wi_demo_001","tenant_id":"t_demo","assignee_person_id":"p_demo","source_system":"M07","source_object_type":"LogisticsRequest","source_object_id":"lr_demo_001","position_context_ref":"position_demo","title":"确认维修工单","priority":"high","due_at":"2026-10-20T09:00:00+08:00","display_status":"pending","allowed_action_refs":["acknowledge"],"source_version":3},
  "ResultReference": {"result_id":"res_demo","source_system":"M07","source_object_id":"lr_demo_001","verification":"verified","evidence_refs":["ev_demo"],"trace_id":"trace_demo"}
}
```

`person_id` 不等于 HLC `employee.id`，必须建立 `ExternalIdentityMapping(tenant_id, person_id, external_employee_id, status, valid_from/to, source_version)`；仅由可信同步流程维护。`RoleTemplateRef` 引用 M01 受控 position refs，**不能以 HLC 的 `jobTitle` 作为授权事实**。[C/P]

## 3. 端点清单（拟建 API，非 HLC 已存在地址）
| 方法 | 建议路径 | 服务 Owner | 作用 | 授权与幂等 |
|---|---|---|---|---|
| GET | `/api/v1/poms/me/workspace` | M10 | 获取我的 ui_manifest 与导航 | M01 授权、短 TTL |
| GET | `/api/v1/poms/me/work-items` | M10 | 聚合待办引用/分页/过滤 | 租户+person+对象级 Guard |
| GET | `/api/v1/poms/me/results` | M10/M02 | 查询本人可见 ResultRef | 仅 Evidence 引用，不内联敏感内容 |
| POST | `/api/v1/hlc/service-requests` | M07 | 发起后勤或 HR 服务 | M01 Guard + Idempotency-Key |
| GET | `/api/v1/hlc/service-requests/{id}` | M07 | 查询业务请求详情 | 业务对象字段级授权 |
| POST | `/api/v1/hlc/service-requests/{id}/transitions` | M07 | 状态转换、审批、拒绝、转派 | Guard、If-Match、幂等、审计 |
| POST | `/api/v1/hlc/service-requests/{id}/evidence-refs` | M07/M02 | 建立业务与 Evidence 引用 | 校验附件及授权 |
| POST | `/api/v1/integrations/m07/workitem-events` | Adapter | 接入投影事件 | 服务凭证、签名/去重 |
| POST | `/api/v1/agents/personal/sessions` | M13/M10 | 创建受控个人 Agent 会话 | agent_id、Tool allowlist、预算 |

## 4. 示例提交
```http
POST /api/v1/hlc/service-requests
Authorization: Bearer <M01 issued token>
Idempotency-Key: unique-client-generated-id
Content-Type: application/json

{"type":"logistics_repair","subject":"车间工作灯故障报修","description":"现场照明灯不亮，等待检查","site_ref":"site_demo","attachments":["upload_ref_demo"],"client_request_id":"req_001"}
```
**HTTP 约束**：201 + resource id；重复 Idempotency-Key+同 body 返回原结果；相同 key 不同 body 返回 409；非法状态跳转 409；未认证 401；未授权 403；字段验证 422；版本冲突 409/412。响应带 `trace_id`, `object_version`, `policy_decision_ref`，敏感字段按权限裁剪。[P]

## 5. 事件 Envelope
```json
{"event_id":"evt_demo","event_type":"hlc.request.status_changed.v1","occurred_at":"2026-10-16T15:00:00+08:00","producer":"M07","tenant_id":"tenant_demo","actor_ref":"person_demo","object_ref":{"type":"LogisticsRequest","id":"lr_demo_001","version":2},"previous_state":"ASSIGNED","new_state":"IN_PROGRESS","trace_id":"trace_demo","idempotency_key":"transition_demo","result_ref":null,"evidence_refs":[]}
```
Outbox 与业务状态更新在同一事务；消费者按 `event_id` 去重，记录 offset；事件至少一次投递，不保证唯一投递；避免 POMS 自行写业务状态。事件 schema 需版本化，兼容变更在 G1 确认。[B/P]

## 6. UI Manifest 示例
```json
{"tenant_id":"tenant_demo","person_id":"person_demo","policy_version":"candidate-v1","expires_at":"2026-10-16T16:00:00+08:00","position_refs":["pos_hr","pos_logistics_delegate"],"industry_pack_ref":"lighting_demo","widgets":[{"id":"future_todos","visible":true},{"id":"past_results","visible":true},{"id":"personal_agent","visible":true}],"actions":["hlc.service_request.create","hlc.request.acknowledge"]}
```
服务端签发/授权，不能相信客户端修改。代理任职要有明确起止日期和 Scope；离职撤权应使已有工作面/Token/Agent 会话失效。[B/P]