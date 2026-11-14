> 2026-11-15 整合说明：A 与 personal/dev 的面试/报告路由已注册到同一应用，账号统一采用官网账户。历史段落中的“B 尚未接入”不再代表路由缺失，但真实初筛 1.1 outbox → 面试案例消费仍未实现。实际协议、独立任务路径及迁移见 [整合说明](../branch-integration.md)，机器快照包含当前 A/B 全部路由。

# Cheetah 猎报 · 前后端接口对接文档 V0.1

当前 Goal 分支新增的本地集成接口与限制见 [Goal 本地增量](goal-local.md)。下文保留原平台设计基线；其中“仅健康检查已实现”的描述不再覆盖该分支新增代码，新增实现以运行时 OpenAPI、源代码和实际测试为准。

更新时间：2026-11-13。统一前缀：`/api/v1`。面向前端 F、后端 A 与后端 B。

**完整设计稿仍包含未实现项；A 的本地可联调版本已经实现。** 具体状态与限制见 [后端 A 交付说明](../backend-a-delivery.md)，机器可读的实际运行接口为 [openapi.implemented.v1.json](openapi.implemented.v1.json)。前端岗位产物页已加入文字分析调用，真实模型链路尚未验证；其他页面仍为演示，B 的电话与报告尚未接入；不能把本地测试等同真实模型、联网研究、真实电话或线上验收。

岗位创建新流程见 [从沟通材料创建岗位](../job-material-workflow.md)：只提交沟通文字，生成 D01/D02，网页修改留存与 PDF/Word 导出。录音可本机保存，ASR 和人工版本回写仍待后端对接。

## 文档入口与优先级

初筛 V2 新增 `interview_standard`、`screening_standard` 任务及 `continuation_task_id`；岗位分析主任务在建议步骤完成前保持等待。新增 `a05-evidence` v1 配置和 `screening_rubric`，保留已发布旧谓词规则。D01/D03 增加完整表单，D05/D06 增加画像、结构化评估与程序计分。具体口径见 [初筛 Agent V2](../intake-agents.md)，字段以实际 OpenAPI 快照为准。

| 文件 | 用法 |
| --- | --- |
| [openapi.v1.json](openapi.v1.json) | OpenAPI 3.1，可导入支持该版本的 Swagger Editor、Apifox、Postman 等工具；含逐接口请求、响应、字段约束、错误与样例 |
| [models.md](models.md) | 对象关系、字段语义、状态迁移、来源与前端映射 |
| [integration-guide.md](integration-guide.md) | 接入顺序、异常处理、验收场景与未冻结项 |
| [examples.json](examples.json) | 全部为虚构的联调数据，包含成功、处理中、失败、信息不足、拒绝、待审核等场景 |
| [search-adapter.md](search-adapter.md) | 可配置搜索适配、归一化 HTTP 协议、次数预算与实际验证边界 |
| [A03 Pi Agent](../a03-pi-agent.md) | Pi 研究循环、完整 D03 对象、D04 范本、插件与工具合同、配置和限制 |
| [A/B 事件合同](../contracts/README.md) | 已存在的内部交接模型及 Schema，不是浏览器调用接口 |

当前运行行为以实际后端源代码为准；现有 A/B 事件以 `backend/app/core/contracts.py` 为唯一模型入口。待实现 HTTP 接口以本目录的 OpenAPI 和文字语义共同评审，冻结后实现到 Pydantic/OpenAPI；出现冲突先修正文档，不能各自采用不同解释。OpenAPI 的 `x-implementation-status` 区分 `implemented`、`planned` 和 `integration-draft`；服务运行时 `/openapi.json` 仅包含实际已注册的 A 与健康检查端点；`openapi.implemented.v1.json` 从同一应用生成，完整设计稿保留 B 的 planned/integration-draft。

## 1. 通用协议

账号入口新增 `/auth/register`，详见 [官网与账号交付](../website-auth.md)。注册与登录不要求预先存在 Cookie／CSRF，但必须验证 Origin；其他写操作继续校验会话与 CSRF。本轮不修改 A/B 内部事件合同。

### 1.1 URL、命名、时间与空值

- 开发环境前端经 Vite 的 `/api` 同源代理；受控环境经 Nginx 同源代理。组件不直接配置 A/B 的地址。
- JSON 采用 `snake_case`；前端视图模型可以转换为 `camelCase`。ID 由服务端生成不可猜测字符串，样例中 `fixture-*` 仅用于联调，不能作为生产 ID 规则。
- 时间为带时区的 RFC 3339，例如 `2026-11-13T02:20:00Z`；前端用 `Asia/Shanghai` 展示。电话号码、内部主机和访问令牌不作为列表 ID 或 URL 参数。
- 业务已知为空或未知时用 `null` 并配合 `unknown_fields` / `gaps` / `reason`；不能用空字符串、“无”或 `0` 冒充已知事实。计数确实为零可用 `0`；未评估分数必须是 `null`。
- 所有已发布规则、产物和报告内容引用都带版本；不得用“最新”替代历史任务输入。成功响应直接返回资源，不额外套 `{data: ...}`；异步命令例外返回 `TaskAccepted`。
- 业务响应、文件及报告默认 `Cache-Control: no-store`。正常响应包含 `X-Request-ID`；异步接受不等于业务成功。

### 1.2 登录、会话与对象权限（A 已实现本地版本）

采用同源 HttpOnly 会话 Cookie `cheetah_session`，生产使用 `Secure; SameSite=Lax; Path=/`，退出时失效。前端使用 `credentials: 'same-origin'`，不将会话令牌写进浏览器存储。响应模型不返回密码、Cookie 值或第三方密钥。

登录校验 `Origin` 和预置账户。`GET /auth/me` 返回用户、机构、权限列表与 CSRF token；所有登录后的 POST/PATCH 需要 `X-CSRF-Token`，Cookie 自动携带。登录本身不要求尚未取得的 token，但必须校验来源。CSRF token 不是会话 Cookie，不在日志或 URL 中记录。

机构从会话取值，业务写请求不接受浏览器指定 `organization_id`。每次读写、后台执行、历史版本、证据和附件都重新校验岗位及对象归属。未登录返回 401；已登录但无操作权限返回 403；跨机构或不可见对象统一 404，避免泄露其存在。`permissions` 和 `allowed_actions` 只辅助前端展示，不能替代后端验证。

当前 CORS 允许 Content-Type、Authorization、X-CSRF-Token 和 Idempotency-Key，未开启带 Cookie 的跨域会话。本方案默认同源；若将来改变为跨域，A 必须一并配置明确来源、凭据、CSRF、幂等和导出请求头，不能把当前配置描述为已支持。

### 1.3 分页、搜索与排序

列表统一返回 `{items, total, page, page_size}`，`page` 从 1 开始，默认 1；`page_size` 默认 20，上限 100。`total` 指完成权限和过滤后的总数。空列表返回 200 和 `items: []`；不存在的对象返回 404。

搜索参数为 `q`，最长 100 字符；服务端去首尾空白、参数化查询，不把搜索词解释为命令。首版默认 `created_at DESC, id DESC` 保持稳定顺序；时间线默认 `created_at ASC, id ASC`。筛选名称与枚举见 OpenAPI；不存在的枚举返回 422。不使用前端只过滤一页结果来冒充全量过滤。统计与待办由聚合接口提供，不能用第一页长度当总数。

### 1.4 并发、版本与请求防重

| 字段／机制 | 作用 | 不能替代 |
| --- | --- | --- |
| `revision` / `expected_revision` | 可变资源行的乐观锁；同一行修改后递增 | 内容版本、授权有效性 |
| `draft_revision` / `expected_draft_revision` | 岗位规则草案修改冲突检测 | 已发布规则包版本 |
| `version` / `expected_version` | 不可变规则、产物、报告内容版本，正整数 | HTTP 重复请求识别 |
| `Idempotency-Key` | 业务 POST 的重复提交或响应丢失重试 | 事件、电话业务、拨打尝试防重 |
| `X-Export-Request-ID` | 同一次文件下载请求的审计去重 | 批准、交付或导出权限 |

规划的业务 POST 必须带 `Idempotency-Key`（8—128 个 ASCII 安全字符，由前端每个用户意图生成并在重试时复用）。作用域为机构、操作者、方法、规范路径和 key；服务端保存规范请求摘要、状态码、资源／任务 ID 及必要响应，至少覆盖配置的重试窗口（首日建议 24 小时，正式值须冻结）。同 key 同请求返回原响应与 `Idempotency-Replayed: true`；处理中返回 409 `REQUEST_IN_PROGRESS`；同 key 不同内容返回 409 `IDEMPOTENCY_KEY_REUSED`。过期 key 不能代替数据库业务唯一约束。后续状态变化后重放也不重新执行，客户端再 GET 当前资源。

PATCH 使用期望 revision，响应丢失后先 GET 核对，不能自动重放并绕过冲突。所有冲突返回 409 `VERSION_CONFLICT`，含可读取的当前 revision/version，不回显他人的编辑文本。前端保留未提交输入，重新读取后由用户决定如何合并。

数据库中同时防重：事件 ID、步骤任务输入版本、电话业务键、候选人有效联系占用、外部拨打 request ID。新规则、提纲或事件版本不等于新一次拨号许可；重复事件不能建立第二个电话业务任务。

### 1.5 异步任务与轮询

模型、研究、批次处理、重算和报告生成返回 202：

```json
{
  "task_id": "fixture-task-analysis-001",
  "resource_type": "job",
  "resource_id": "fixture-job-001",
  "poll_after_ms": 3000
}
```

响应可有 `Location: /api/v1/tasks/{task_id}`。任务由服务端持久化，不能只依赖浏览器或进程内回调。`POST /jobs` 仅创建岗位和空草案，前端随后显式调用 `/analyze` 并展示任务；创建本身不宣称 D01/D02 已生成。批次响应另外包含 `batch_id` 与逐份接收结果。

前端约 3 秒轮询活动任务；离开页面取消请求，终态停止。隐藏页面降低或暂停轮询；恢复可见后读一次服务端快照。`waiting_conditions/awaiting_external/reconciling` 显示原因，不显示伪百分比；等待状态使用服务端 `poll_after_ms`，默认 10 秒，人工待办只在页面可见时低频刷新。`completed/failed/cancelled` 是任务终态。网络离线不写成业务失败；刷新后从资源的任务引用恢复，不凭本地缓存推进。

超时和 5xx 后先查询资源或重放同幂等 key，绝不为外呼、批准或重生成创建新 key 后盲重试。响应字段 `retryable` 仅指指定的内部步骤；没有通用“重拨”接口。

### 1.6 来源与模拟隔离

HTTP 统一 `source_mode: live | mock | manual`，与现有事件合同一致。前端现有 `real` 必须在接入层映射为 `live`。`source_modes` 分材料、模型、研究与电话记录；未执行阶段用 `null`，不默认 `live`。**旧 1.0 `screening.passed` 事件的四项来源均为非空枚举，HTTP 的可空读模型不能原样塞进事件。** 达标交接发生在电话之前，而现有事件仍要求非空 `phone`，这一语义缺口需 A/B 冻结：明确执行模式与已发生来源的区别，或单独升级事件模型。本轮不擅自改已实现 Schema，也不将未拨电话自动补成 `live`；A 已通过新增 1.1 合同解决该语义：phone 为 null，另列计划执行模式；B 仍须接入 1.1 并重新检查联系前提，见合同说明。现有 fixture 的 `phone=mock` 仍仅表示测试样例，不能证明发生了通话。

产物另含 `inherited_source_modes`，下游真实模型或人工修改不会清除上游 `mock`。请求不能自行指定 `source_mode=live` 来获得可信标记；模型／电话真实模式由服务端配置和调用记录决定。`execution_mode` 只用于受权限保护的 live/mock 执行选择，mock 结果及其下游始终保持模拟。`fixture_only=true` 的样例不准进入真实执行路径，测试规则不准驱动真实拨号。

列表 `source_scope` 采用互斥的汇总过滤：fixture 或任意当前／继承／阶段来源含 mock 则归 mock；其余含 manual 则归 manual；其余已存在来源均为 live 才归 live。null 不证明执行过任何阶段。`all` 包含全部可见数据。不得把“人工修改过的模拟报告”过滤成纯人工或真实报告。

## 2. 错误协议

统一形状：

```json
{
  "code": "VERSION_CONFLICT",
  "message": "内容已更新，请重新读取当前版本",
  "request_id": "fixture-request-conflict-001",
  "details": {
    "current_revision": 4,
    "current_version": 2,
    "fields": []
  }
}
```

`message` 可用于用户提示，客户端按 `code` 分支；`details` 可以是对象、验证问题数组或 `null`。不得在异常中回显密码、原始简历、转写、Cookie、连接串、私有地址或第三方原始异常。422 的问题项只包含字段路径、错误类型及安全说明，不包含原始输入值。

| HTTP | `code` | 前端行为 |
| --- | --- | --- |
| 401 | `AUTH_REQUIRED` / `SESSION_EXPIRED` | 停止轮询，清理身份态，回登录；不自动换演示数据 |
| 403 | `PERMISSION_DENIED` / `CSRF_INVALID` | 提示无权限或重新取得会话信息；不重复操作 |
| 404 | `NOT_FOUND` | 对象不可见或不存在，不泄露其机构 |
| 409 | `VERSION_CONFLICT` | 刷新版本，保留用户未提交输入 |
| 409 | `RULES_NOT_PUBLISHED` / `RULES_INCOMPLETE` | 引导补充并确认标准；不启动处理 |
| 409 | `PRECONDITION_NOT_MET` / `CONTACT_NOT_AUTHORIZED` | 展示缺少的联系、时段等前提 |
| 409 | `EXTERNAL_RESULT_UNKNOWN` | 显示待核对；不能重拨 |
| 409 | `ACTIVE_CONTACT_EXISTS` / `CALL_TASK_EXISTS` | 使用已有任务／等待联系占用释放 |
| 409 | `REPORT_NOT_APPROVED` / `REPORT_EXPIRED` / `RECOMMENDATION_NOT_ELIGIBLE` | 阻止导出，查看最新 D09/D10 与待办 |
| 409 | `INVALID_STATE_TRANSITION` / `TASK_NOT_RETRYABLE` | 重新读取，不自动重试 |
| 409 | `REQUEST_IN_PROGRESS` / `IDEMPOTENCY_KEY_REUSED` | 等待原请求或修复错误 key 的使用 |
| 413 | `PAYLOAD_TOO_LARGE` | 提示实际限制，逐份保留合法材料 |
| 415 | `UNSUPPORTED_FILE_TYPE` | 替换当前材料，其他份继续 |
| 422 | `VALIDATION_ERROR` / `PDF_TEXT_UNAVAILABLE` | 定位字段；扫描 PDF 提示暂不支持 OCR |
| 429 | `RATE_LIMITED` / `BUDGET_EXCEEDED` | 按 `Retry-After` 或人工处理；不无限重试或绕过预算 |
| 502/503 | `UPSTREAM_UNAVAILABLE` / `DEPENDENCY_NOT_READY` | 保留已有产物，显示稳定失败原因 |
| 500 | `INTERNAL_ERROR` | 展示 request ID，后台核对；不回显敏感异常 |

A 已使用其中的稳定业务码；B 专用业务码仍为规划。当前未知路径的框架 404 为 `HTTP_404`，422 为 `VALIDATION_ERROR`，`/health/ready` 的 503 使用自身状态对象而非 Error；接入时须兼容这一实际差异。A 已统一包装未知异常 500 和数据库暂不可用 503，并阻止原始异常值进入响应或默认请求错误日志。

## 3. 接口清单

下表路径省略 `/api/v1`。这是完整设计清单；A 的实际路径、受支持字段及验证见独立运行快照和交付说明，B 仍待开发。A 公共基础统一鉴权、任务、证据与迁移；B 通过公共模型写入后半段产物，前端始终只连一个后端。

### 3.1 基础、登录与工作台

| 方法与路径 | 主责 | 请求 → 成功返回 | 约束 |
| --- | --- | --- | --- |
| `GET /health` | A | 无 → 200 `Health` | **已实现**；`service` 当前仍是 `cheeta-api`，品牌改名未修改此协议常量 |
| `GET /health/ready` | A | 无 → 200/503 `Readiness` | **已实现**；实际检测数据库，不能扩展解释为全部业务就绪 |
| `POST /auth/register` | A | `RegisterInput` → 201 `Session` + Cookie | **本地已实现**；Origin 必填；账号唯一；每次注册创建独立机构；409 `USERNAME_TAKEN`、403 `REGISTRATION_DISABLED`、429 `RATE_LIMITED` |
| `POST /auth/login` | A | `LoginInput` → 200 `Session` + Cookie | 登录失败 401；不存密码；不使用业务幂等 key |
| `GET /auth/me` | A | Cookie → 200 `Session` | 恢复会话、权限、CSRF 与运行能力；失效 401 |
| `POST /auth/logout` | A | Cookie + CSRF → 204 | 清除会话；本身幂等；无业务 key |
| `GET /workspace/summary` | A 聚合，B 供摘要 | 无 → 200 `WorkspaceSummary` | 计数附 `as_of`，按权限与 live/mock 范围聚合 |
| `GET /todos` | A 聚合，B 注册待办 | 类型、岗位、分页 → 200 `TodoPage` | 规则确认、未知、证据冲突、报告审核、外部待核对等 |

### 3.2 岗位、规则与简历

| 方法与路径 | 主责 | 请求 → 成功返回 | 约束 |
| --- | --- | --- | --- |
| `GET /jobs` | A | q/status/rule_status/分页 → 200 `JobPage` | 岗位启停与规则发布是两套状态 |
| `POST /jobs` | A | `CreateJobInput` → 201 `Job` | 建岗位、原始材料 v1 与空草案；Location 指向详情；不自动分析 |
| `GET /jobs/{job_id}` | A | ID → 200 `Job` | 当前规则引用、草案 revision、任务与汇总 |
| `PATCH /jobs/{job_id}` | A | `UpdateJobInput` → 200 `Job` | 更新展示字段或启停；原始业务事实修改须走新材料与影响分析，不能静默覆盖 |
| `POST /jobs/{job_id}/analyze` | A | 期望 revision、执行模式 → 202 `TaskAccepted` | 生成 D01/D02 草案，不自动发布 |
| `GET /jobs/{job_id}/rules/draft` | A | ID → 200 `RuleDraft` | 未完成标准仍可读取，有 `validation_issues` |
| `PATCH /jobs/{job_id}/rules/draft` | A | `SaveRuleDraftInput` → 200 `RuleDraft` | 期望草案 revision；整体替换 `content`，不采用不明确的数组合并 |
| `POST /jobs/{job_id}/rules/publish` | A，B 评审后半段标准 | `PublishRulesInput` → 201 `RulePack` | 校验 D01/D02、初筛／面试／推荐与执行配置；保存不可变快照 |
| `GET /jobs/{job_id}/rules/versions` | A | 分页 → 200 `RulePackPage` | 版本从 1 开始；草案 revision 不混入 |
| `GET /jobs/{job_id}/rules/versions/{version}` | A | 精确版本 → 200 `RulePack` | 任务实际引用版本可回看，内容不可原地编辑 |
| `POST /jobs/{job_id}/resume-batches` | A | multipart 文件或 JSON 文本 → 202 `BatchAccepted` | 只接受规则已发布且岗位启用；逐份接收／失败／复用 |
| `GET /batches/{batch_id}` | A | ID → 200 `Batch` | 各项计数、总体状态与任务引用 |
| `GET /batches/{batch_id}/items` | A | 分页 → 200 `BatchItemPage` | 单份错误、文件／关联／步骤任务 ID 与可恢复操作 |
| `POST /batches/{batch_id}/items/{item_id}/replace` | A | multipart 单文件、期望 revision → 201 `BatchItem` | 仅替换校验失败项，旧项保留审计；解析失败用任务重试，不覆盖已成功材料 |

岗位创建示例（仅虚构输入）：

```json
{
  "title": "产品经理（虚构）",
  "company": "测试企业（虚构）",
  "location": null,
  "salary": null,
  "material_text": "【虚构需求】负责企业协作产品；薪资与试用期目标未提及。"
}
```

`RuleContent` 保留现有前端的三段标准文本，但正式执行不能只靠自由文本。还须有条件 ID、三态初筛判定口径、面试维度与未评估处理、推荐覆盖／门槛、研究／电话／方法配置引用，见模型及 OpenAPI。缺配置允许保存草案，发布返回 `RULES_INCOMPLETE`，前端不能以“文本非空”代替正式发布校验。新规则只用于后续流程，应用历史候选人需显式重算并审计。

文件批次使用 `multipart/form-data`：重复字段 `files`，外加 JSON 字符串 `manifest`，数组顺序一一对应：

```json
{
  "items": [
    {"client_item_id": "fixture-upload-001", "filename": "fictional-resume.txt"}
  ]
}
```

文本批次使用 `application/json`：`{"items":[{"client_item_id":"fixture-text-001","name":"虚构材料","text":"【虚构简历】仅供联调"}]}`。一次请求不能混用两个 content type；混合导入由前端发两个独立批次。浏览器设置 multipart 边界，不手动写死 `Content-Type`。

首日草案采用当前演示默认每批最多 10 份、每份非空且不超过 5 MiB（5,242,880 bytes）、文本最多 30,000 字符，作为可配置测试限制，不是产品容量承诺。`Session.capabilities.import_limits` 返回实际限制。后端重新检查扩展名、MIME、文件签名、解压／解析资源限额与文本 PDF 可提取性，不能只信浏览器校验。全请求超过网关限制返回 413；已能逐份识别的格式或解析问题记到对应 `BatchItem.error`，不回滚其他合法份。全部单份校验失败仍建立失败批次供修正，但不调 AI。

后端自行计算原始文件 SHA-256，按机构＋岗位＋内容摘要复用已有材料／关联／任务；改文件名不能绕过。文本仅对换行统一为 LF 并去首尾空白后按 UTF-8 摘要，规则须在实现中固定。不要仅因同名或相似经历自动合并候选人。批次接收返回逐份 `accepted/duplicate/invalid`；duplicate 附已有关联 ID，不再次筛选或建电话。单份替换保留 `replaces_item_id`，不能通过全批重传冒充单份恢复。

### 3.3 候选人、产物、证据与任务

| 方法与路径 | 主责 | 请求 → 成功返回 | 约束 |
| --- | --- | --- | --- |
| `GET /applications` | A 聚合，B 供摘要 | job_id/q/screening_result/分页 → 200 `ApplicationPage` | 跨有权限岗位的工作台列表；每行是岗位关联，不是去重候选人总数 |
| `GET /jobs/{job_id}/applications` | A | 同上（岗位在路径） → 200 `ApplicationPage` | 与全局列表相同字段，避免 F 两套模型 |
| `GET /applications/{application_id}` | A，B 供摘要 | ID → 200 `Application` | 阶段、等待原因、实际规则、初筛、评估、电话与报告引用 |
| `GET /applications/{application_id}/timeline` | A/B 按事件写 | 分页 → 200 `TimelinePage` | 原始结论、覆盖、修订、审核与下载记录；不能只拼 UI 文案 |
| `GET /applications/{application_id}/artifacts` | A 公共读取 | type/status/分页 → 200 `ArtifactPage` | 返回产物元信息与不可变引用，不塞全部内容到列表 |
| `GET /artifacts/{artifact_id}` | A 公共读取 | 必填 version → 200 `Artifact` | D01—D10 共用查看器；按精确版本查内容和证据 |
| `GET /evidence/{evidence_id}` | A 公共读取 | 必填 version → 200 `Evidence` | 证据分类、来源位置、原文、时间与更正关系 |
| `GET /files/{file_id}` | A | 必填 version → 200 二进制 | 校验有效授权、删除与归属；响应 attachment，不提供无权限直链 |
| `GET /tasks/{task_id}` | A 公共读取，B 注册类型 | ID → 200 `Task` | 持久化状态、失败类型、输入引用、预算与允许的内部重试 |
| `POST /tasks/{task_id}/retry` | A/B 各自步骤 | expected_revision/reason → 202 `TaskAccepted` | 仅可重试内部计算，保持输入快照，执行尝试另记；不能重拨 |

未执行的 D08/D09/D10 不返回伪造空产物。`Application.artifact_slots` 每个阶段给出 `not_executed/processing/available/failed/invalidated` 与原因，真实生成后才关联 ArtifactRef。初筛为 `unknown` 时不当成 rejected；通信失败不修改候选人能力结论。候选人卡片先用摘要，点击后按版本读产物及证据，避免一次列表请求返回完整材料。

### 3.4 电话、联系前提与回调

| 方法与路径 | 主责 | 请求 → 成功返回 | 约束 |
| --- | --- | --- | --- |
| `POST /applications/{application_id}/contact-authorization` | B | `ContactAuthorizationInput` → 201 `ContactAuthorization` | 新增授权／撤回版本及证明材料，不接受裸 `authorized:true` |
| `GET /calls` | B | job_id/application_id/status/分页 → 200 `CallPage` | 业务任务；拨打尝试单列，来源为独立字段 |
| `GET /calls/{call_id}` | B | ID → 200 `Call` | 当前通信情况、前提检查、停止请求与核对原因 |
| `GET /calls/{call_id}/attempts` | B | 分页 → 200 `AttemptPage` | 每次请求 ID、服务商状态、结果／费用核对；不暴露密钥 |
| `POST /calls/{call_id}/cancel` | B | expected_revision/reason → 200 或 202 `Call` | 队列取消可同步完成；进行中仅登记停止请求，确认前不是 ended |
| `POST /calls/{call_id}/reconcile` | B | expected_revision/reason → 202 `TaskAccepted` | 仅查询已存在的外部请求，不提交第二次拨打 |
| `POST /integrations/voice/callback` | B | 服务商签名原始负载 → 200 `CallbackReceipt` | **适配草案**，非前端接口；真实平台原始负载与签名映射尚待确认 |

取消与停止约定：业务 `status` 和 `stop_status` 分开。`in_progress + requested` 显示“停止请求中”；只有平台确认结束，才变成 `ended + confirmed`。服务端收到候选人结束意图时应直接取消播放并停止，不能等待浏览器发请求或模型说结束语。网络超时或停止结果不明用 `reconciling/stop_status=unknown`；不把超时写成“已挂断”。

```json
{
  "id": "fixture-call-001",
  "revision": 4,
  "status": "in_progress",
  "stop_status": "requested",
  "reason": {"code": "STOP_CONFIRMATION_PENDING", "message": "已请求停止，等待平台确认", "missing_fields": []},
  "attempt_count": 1
}
```

以上为字段片段，完整 Call 样例见 examples。取消、核对、授权撤回都不创建新的电话任务。撤回是新授权版本：取消排队、阻止待拨、进行中发停止，记录结果，不能删除历史事实或对已经交付的材料声称自动召回。

回调必须先验证服务商原始字节签名、时间戳、重放窗口和来源，再归一化为 `VoiceEvent`；不能先重序列化 JSON 再验签。控制测试适配器使用 OpenAPI 中的归一化样例，真实服务商可能不同，须实现明确适配。匹配已登记 `external_request_id` 与会话，不信任回调任意指定机构或 application。重复回调返回原处理结果；乱序不把终态退回早期状态；冲突记入待核对。保存通信结果和登记提取任务同事务完成，回调不执行长时间模型任务。未验证的事件 401/403，未知请求 404（供应商重试策略需确认），已确认重复返回 200 `disposition=duplicate`。

### 3.5 评估、推荐、审核与下载

| 方法与路径 | 主责 | 请求 → 成功返回 | 约束 |
| --- | --- | --- | --- |
| `GET /reports` | B | job_id/application_id/status/分页 → 200 `ReportPage` | 每个逻辑 D10 只列当前版本；按当前状态筛选；D09 从产物入口读取 |
| `GET /reports/{report_id}` | B | 可选 version（不传为当前） → 200 `Report` | 内部查看不要求已批准；旧版显示失效 |
| `GET /reports/{report_id}/versions` | B | 分页 → 200 `ReportPage` | 逻辑 report ID 稳定，每版有独立内容／审核记录 |
| `POST /reports/{report_id}/review` | B | `ReviewReportInput` → 200 `Report` | expected_version＋expected_revision＋approve/reject＋reason |
| `POST /reports/{report_id}/revisions` | B | `ReviseReportInput` → 201 `Report` | 人工修订 D10，新版 pending_review，旧版失效；不修正上游事实 |
| `POST /reports/{report_id}/regenerate` | B | expected_version/revision/reason → 202 `TaskAccepted` | 仅重生成 D10；读取当前有效 D09，不重拨、不自动批准或发送 |
| `GET /reports/{report_id}/export` | B | 必填 version，`X-Export-Request-ID` → 200 Markdown 附件 | 仅当前有效、符合推荐条件且已批准的 D10 |
| `GET /reports/{report_id}/deliveries` | B | 可选 version、分页 → 200 `DeliveryPage` | 按报告内容版本过滤；首日只查导出响应记录，不等于向 HR 实际发送 |

审核请求示例：

```json
{
  "expected_version": 1,
  "expected_revision": 2,
  "action": "approve",
  "reason": "仅验证模拟流程：已核对来源、个人贡献表述与待核实事项。"
}
```

审核检查：对象权限、当前报告内容版本、状态 pending_review、产物有效、D09 仍满足推荐门槛、上游未失效。任一条件不满足都不能通过。多人同时审核只有一人基于当前 revision 成功；不能批准客户端上传的任意全文。

修订事务内保存新内容版本、新人工来源、旧版失效和新的待审核状态，保留历史审计。重新生成任务接受时先将旧结果标为不可新交付（expired，当前版本引用保留用于历史查看）；即使生成失败也不能复活旧批准。重试从保留的 D09 恢复。D08 等事实更正使用下一节的更正入口，不能仅改 D10 隐藏错误。

下载成功头：`Content-Type: text/markdown; charset=utf-8`、`Content-Disposition: attachment; filename*=UTF-8''...`、`Cache-Control: no-store`、`X-Export-ID`、`X-Request-ID`。错误仍是 JSON，前端必须先检查状态／Content-Type 再当 Blob 下载。报告不夹带 D09 完整评分、完整转写、电话或非必要原始材料。

沿用开发计划 GET 下载，同时记录审计，因此必须禁缓存，且同一次用户下载意图复用 `X-Export-Request-ID`。内容交付前再次核验版本和批准，生成快照与审计原子登记；请求时已失效返回 409。已返回给客户端的字节不能承诺在后续更正后自动召回；并发更正记录 `affected_delivery_ids`。浏览器请求结束仅代表服务端已发出导出响应，不证明用户已保存文件，更不证明 HR 已收取。失败响应不附 `Content-Disposition`。

### 3.6 更正与复核（PRD 必需，当前 UI 尚无入口）

| 方法与路径 | 主责 | 请求 → 成功返回 | 约束 |
| --- | --- | --- | --- |
| `POST /applications/{application_id}/screening-review` | A | 原 D06 引用、覆盖结论、原因与证据 → 201 `ScreeningReviewResult` | 新 D06，保留原结论和操作者；若变达标仍检查已有电话，不默认重拨 |
| `POST /applications/{application_id}/corrections` | A 公共编排，A/B 按目标写 | `CorrectionInput` → 201 `CorrectionResult` | 新目标版本与影响列表，同事务失效下游、暂停不安全动作 |
| `POST /applications/{application_id}/recompute` | A 公共编排，B 注册后半段 | `RecomputeInput` → 202 `TaskAccepted` | 指定已保存更正与内部步骤；不得包含拨号、授权或对外交付 |

更正只能操作服务端允许的结构化事实路径，不是任意 JSON 写库接口。字段补充不得借简历、网页或转写文本改变系统提示、权限、规则、工具配置或拨号许可。更正返回新引用、失效产物、受阻任务与已导出记录；没有自动重拨、补发或召回的隐含副作用。岗位原始业务材料的新版本上传以及完整数据删除／生命周期管理后续单独评审，不在该候选人更正接口里混做。

## 4. 原接口设计轮次核对范围（2026-11-13，历史记录）

本文与当前前端视图、PRD、首日计划、A/B 事件模型和健康检查源代码交叉核对。新增的聚合、规则历史、全局候选人、精确产物读取、报告修订及更正接口是为补齐现有页面或业务边界提出的草案扩展；不代表后端已同意冻结或实现。

只编写文档、OpenAPI 和虚构样例，不修改运行中服务、真实数据、外部账号或拨打线路。后续实现应把安全状态与并发校验纳入集成测试，具体清单见 [integration-guide.md](integration-guide.md)。

本轮已完成的文档检查：49 项操作与文字清单一一对应，115 个 Schema、36 组独立虚构样例、559 个本地引用和文档相对链接均通过校验；OpenAPI 通过官方 3.1 元 Schema 校验。通过当前 FastAPI 测试客户端核对 health 200、ready 503、使用模拟数据库探测的 ready 200，以及未实现业务路由的 404 响应形状。没有执行真实数据库／模型／搜索／电话／部署验收，不能将这些文档检查视为业务接口已可用。

## A 本地实现补充（2026-11-14）

实际请求／响应模型是 `backend/app/core/http_models.py`、`modules/intake/schemas.py`，实际 OpenAPI 与前端 `src/api/generated.ts` 同步。当前工程补充了以下可审核字段，未放宽原有业务边界：

- `ScreeningCondition.predicate` 支持 field、equals/contains/gte、expected。草案可为空，发布必须完整。contains 未命中或带否定含义时保留 unknown；证据种类不足也不判负面。
- 文本批次与 multipart manifest 可带 `execution_mode`，缺省 live；mock 需要服务端显式允许，测试规则不能进入 live。
- `Task.kind=batch` 是批次汇总任务，不提供通用重试；应修正／重试具体失败项。批次计数按每份材料当前替换版本计算，旧失败项仍留库并由 replaces_item_id 追溯。
- 更正目前支持 `D03` 的 `/facts/{白名单字段}`，每项 value 为 `{value,status,quote}`。D08 与 B 的更正 handler 尚未接入；未实现的目标不能返回伪成功。重算仅支持按顺序 research、screening，并校验当前关联的 RulePackRef。
- 工程预算限制模型调用数、Token 与搜索次数；Task.budget 的 model_calls/model_tokens/search_calls 各含 limit/reserved/used。尚无真实价格／账单核对，金额字段保持 null。研究未执行、电话未执行的阶段来源为 null。B 摘要尚未接入，工作台附 `outreach_summary_connected=false`，当前零计数不代表已验证电话能力。

`openapi.v1.json` 保留完整设计目标和规划状态；不可将其中所有端点一并视为已实现。现有演示与接口样例仍仅为虚构数据，实际验证矩阵见交付说明。

`ScreeningCondition.required_evidence` 保持人工可读证据要求；新增 `evidence_sources` 单独声明程序核验来源（resume/manual_revision/public_web）。二者不可混用；发布时需与 predicate 一并完整确认。面试维度也必须有明确证据要求。Job 补充可空 d01_ref/d02_ref，供发布时读取精确版本。

搜索默认 disabled，可配置标准 HTTP 适配器或在受信服务端注册厂商适配器；当前没有绑定或验收真实供应商。规则引用 unavailable v1 禁用搜索，bounded-research v1 允许固定公司／项目计划。D04 保存部分收集结果及来源陈述差异，摘要均为 U／待核实，不自动满足 public_web 条件。外部结果不明保留预算且禁止再次提交，已知响应可复用恢复；详见研究适配器文档。Session.capabilities 的 model_configured/search_configured 只表示配置，不能当作供应商就绪。

创建岗位及异步接受响应提供 Location；幂等重放保持相同查询地址。产物 input_refs 统一为 `{kind,id,version}`，受限原始文件同样阻止通过候选人、聚合、重复导入和 worker 缓存绕过。

新增研究规则引用 `pi-research`, version 1。D03Content.research_objects 按实际声明数量保存公司、项目、比赛／奖项、论文、专利、软著、开源和认证；每字段有原文、状态、证据引用和来源。D04Content.report 可空，Pi 模式下为完整类型化研究报告，旧 bounded-research 的 report 为 null。运行时 OpenAPI、完整草案和前端生成类型同步维护。更正支持 `/research_objects/{已有object_id}/name`、`/period`、`/facts/{已有字段}`，仍拒绝越权和任意 JSON 写入。

Pi 模式的 E1 经过实际来源正文、精确摘录、日期和身份线索检查；E3 保留推断依据，E2 不被覆盖，无法支持的发现降为 U。当前 A05 判定函数仍使用 D03 谓词，不能将带有 D04 引用误称为已做模型综合匹配。真实提供者与专业准确性未验收，详见 A03 文档。

## 人才库独立入库与职能分流（2026-11-14）

新增 `/talent-imports`、`/talents`、`/talent-directions`、分类修订与显式 `/applications/{id}/start-screening`。岗位创建/更新增加 `routing_directions`；发布或修改方向后关联库中相关人才。新增 `talent_parse` 任务、`talent` 资源、`matched` 阶段。未匹配不是拒绝，未知不丢弃。全部仍执行通用会话、对象权限、CSRF、幂等与版本约定。具体字段和旧岗位批次兼容边界见 [人才入库与职能分流](../talent-routing.md)，实际 OpenAPI 和虚构样例已同步。
