# 后端 A 本地开发交付与联调

业务资料驱动的初筛 V2 已补充：A01 全字段及 JD、A02 独立能力标准、A04 九模块和研究清单、A05 七维证据评分与合并报告；A03 保留 Pi 工具循环。新增 DOCX 文本读取、更正后的完整表单保留、岗位建议任务链及资源指纹。新规则显式使用 `a05-evidence`，旧规则保持原行为。详见 [实现与边界](intake-agents.md)。

更新：2026-11-14；开发分支：`Jankin`。本页前述为第一轮固定流程的工程交付；A03 随后按用户新资料增加 Pi 研究执行模式，详见 [A03 Pi 开发与验证](a03-pi-agent.md)。不能将第一轮任务完成表解释为九个 Agent 的专业能力已经完整实现；真实供应商、专业准确性和产品闭环均未验收。

## 实现范围

| 工作包 | 当前行为 | 仍需完成的真实集成 |
| --- | --- | --- |
| BEA-01 公共基础 | 会话、CSRF、对象归属、统一错误、请求标识、HTTP DTO、精确版本读取 | 前端业务页接入；正式账号和组织管理 |
| BEA-02 持久化 | 统一 Alembic 迁移；独立 worker；领取租约、失效执行者阻断、有限内部重试；outbox | B 注册任务与消费器；生产运行与监控 |
| BEA-03 登录与模型封装 | 预置账号 CLI、scrypt 密码、数据库内散列会话、登录限流；HTTPS 结构化请求、超时、输出和 Token 上限 | 实际供应商、额度、结构化输出和账单验证；没有真实模型调用证据 |
| BEA-04 岗位与规则 | D01/D02；草案并发 revision；发布不可变快照；初筛、面试、推荐分别校验 | 正式专业规则和 B 执行配置评审 |
| BEA-05 简历 | PDF/TXT/文本；逐份校验；内容 SHA-256 去重；同名不同内容不合并；单份替换与内部恢复 | 经授权代表性真实版式和性能验收；扫描件 OCR、DOCX 暂不支持 |
| BEA-06 有界研究 | 可配置搜索适配器、标准 HTTP 客户端；固定公司／项目问题、来源与时间、陈述差异、缺口和停止原因；默认禁用 | 实际供应商验收、主体／历史适用性的专业核实；当前摘要均为待核实证据 |
| BEA-07 初筛 | D05/D06；按已发布谓词与来源条件核验；passed/unknown/rejected/manual_review | 专家标注样本和专业效果验证；当前不能代替招聘判断 |
| BEA-08 交接 | D06 与 1.1 screening.passed 同事务；业务键稳定；消费前有效性校验接口 | B 的唯一电话任务、跨岗位联系防重、授权与停止；A 事件不等于电话已创建 |
| BEA-09 联调与预算 | 模型调用数／Token、搜索次数原子预留；结果不明保留预算；更正失效；工作台、待办、接口和恢复测试 | 金额／账单核对、真实研究、B/F 全链路、Docker 与线上验收 |

未实现的能力没有伪成功接口。D07—D10 仅保留公共合同与查询兼容，不生成电话、访谈、评分或推荐样例冒充真实结果。

## 本地启动

需要 Python 3.12、uv、PostgreSQL 17。先在根目录从 `.env.example` 创建本地 `.env`，修改占位数据库密码；本地配置不提交。

```powershell
cd backend
uv sync --locked
uv run alembic upgrade head
uv run python scripts/create_user.py dev-user --organization local-dev --display-name "本地开发"
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

密码通过隐藏输入读取，无默认账号。另开终端：

```powershell
cd backend
uv run python -m app.worker
```

`--once` 处理一个任务；`--drain` 处理当前可执行队列后退出。数据库表由显式迁移创建，API 和 worker 启动时不自动建表。原始材料、产物、任务、证据、会话及事件均在数据库内持久化。

隔离演示须显式设置 `CHEETA_ALLOW_MOCK=true`，并在 analyze／resume-batches 请求中选择 `execution_mode=mock`。模拟解析只识别显式 `字段：值`，例如 `工作年限：5`；其来源始终保留 mock。模式缺省 live，未配置模型时任务明确失败，不会自动降级为模拟。

模型配置保留现有服务端 HTTPS 结构化封装，字段见 `.env.example`；密钥不进入浏览器、响应或 Git。供应商协议尚未真实验收。按用户决定，搜索先提供可配置适配，不绑定厂商；配置、归一化 HTTP 协议与受信代码扩展见 [研究适配器](api/search-adapter.md)。默认 disabled，且规则需发布 bounded-research v1 才允许执行；旧 unavailable v1 规则不因配置变化开始联网。每任务最多 2 次查询、每次最多 5 条结果，支持下调和岗位次数预算。没有配置、允许来源或明确主体时 D04 明确未执行；搜索摘要均为 U／待核实，不能自动满足 public_web 条件或确认个人贡献。

数据库包含增量 `0002_bounded_research`：新增搜索账本、预算与阶段来源，保留 0001 的已存正文并回填可证明的来源，不给未执行阶段补 live。

Docker 配置已添加独立 worker 和账号脚本；须先执行迁移，再启动全部进程。当前环境没有 Docker，本轮未运行容器或生产部署。CI 已配置 PostgreSQL 服务，但尚无远端 GitHub Actions 执行证据。

## HTTP 对接

实际接口导入 [openapi.implemented.v1.json](api/openapi.implemented.v1.json)，完整规划仍见 [设计稿](api/openapi.v1.json)。后端公共读取模型在 `backend/app/core/http_models.py`，写请求在 intake schemas；内部事件单独维护，不复用 HTTP 可空读模型。

1. 登录必须来自配置允许的 Origin。取得 HttpOnly Cookie 与 CSRF；后续写入同时校验二者，机构和操作者来自会话。
2. 业务 POST 必须有 Idempotency-Key。相同请求重放原响应，不同内容返回 409；即使重放也重新检查对象可见性。默认回放窗口 24 小时，可配置 24—168 小时；到期在同 key 再次访问时清理，不代表业务材料的保存周期已经确定。
3. 创建岗位后显式 analyze，202 只表示接受。轮询任务，读取 Job 的 d01_ref/d02_ref 和规则草案，按当前 draft_revision 保存并发布。发布会消耗该草案 revision，并生成新的不可变 D02 和 RulePack。
4. 三段标准文本、结构化初筛谓词、证据来源、面试维度及证据要求、推荐条件和受支持的配置引用缺一不可。没有已发布规则，不能导入处理或筛选。
5. 上传返回逐份 receipt。BatchItem.state 和互斥批次计数来自实际状态；有一份失败，其他材料继续。替换只针对 invalid 项，保留 replaces_item_id；默认列表及计数使用替换链当前项，旧行仍留库。
6. GET artifact／evidence／file 需精确版本。未经授权、跨机构、无岗位归属或被限制的材料不可读取；历史版本也不能绕过。原始文件受限后，候选人查询、聚合、批次展示和 worker 的缓存材料读取同时受限，重复导入也不重新打开旧关联。
7. D06 达标仅登记交接事件；B 必须检查当前状态、联系前提与电话业务键。工作台附 `outreach_summary_connected=false`；当前后半段零计数不是电话已验证可用的证明。

前端 `src/api/generated.ts` 从实际 OpenAPI 生成，健康检查已消费该类型。业务页面仍为原有演示，未完成 F 的真实调用与浏览器联调。

## 规则与来源

`predicate={field,operator,expected}` 支持 equals、contains、gte。required_evidence 保持人工可读要求，独立的 evidence_sources 选择 resume/manual_revision/public_web。草案允许缺项，发布拒绝缺项；推荐阈值和权重由人确认，不预置专业评分规则。

条件证据缺失、冲突、引用不支持取值或来源要求未满足时为 unknown。contains 未命中或带否定含义时也保留 unknown；仅明确的数值／等值不符可触发拒绝或人工复核。简历事实保持候选人自述分类，不将公司成果当作个人贡献。D01 的表单字段与材料冲突时保留冲突，不覆盖成确定事实。

D04.status=not_executed 与 Artifact.status=valid 含义不同：前者是研究未执行，后者仅表示这条说明当前未被失效。金额、未执行用量与阶段来源保持 null；没有实际价格和费用核对，不将调用次数预算说成真实金额预算。

执行过搜索的 D04 当前为 partial，逐主体保存执行状态、时间与来源陈述差异；未自动验证同名主体和任职历史。Artifact.input_refs 统一持久化为 `{kind,id,version}`；共享写入器校验输入归属、有效性并继承来源，调用方漏传标签也不能清除 mock。

1.1 交接的电话来源为 null，另有计划执行模式。测试规则、模拟或继承模拟来源都不能进入真实拨打；B 尚未接入，详见 [交接合同](contracts/README.md)。

## 更正与恢复

当前更正入口仅接受有效 D03 的 `/facts/{白名单字段}`。每项 value 为 `{value,status,quote}`，不允许写规则、权限、提示或工具配置。新证据使用新版本，旧证据失效；受影响 D03—D10、待交接事件和内部任务一起处理。

更正后等待显式 research→screening 重算，使用关联原先绑定的规则；不会重拨、自动批准、重新交付或声称召回旧文件。新 D06 保持相同 application 业务键。人工复核保留原结论、证据、操作者与新版本。

姓名更正同步当前搜索标签，candidate_id/application_id 保持不变。D01 与 D03 显式引用原始材料版本；更正的新版本保留旧引用和证据链。

任务领取有租约和执行令牌，失效执行者不能提交结果。安全内部步骤可有限重试；已发送而结果未知的模型／搜索调用进入 reconciling 并保留预算，不能通用重试。已确认响应先保存用量与结果，进程恢复时可继续内部计算并复用响应；权威渠道的迟到结果可登记原请求以恢复内部步骤。搜索尚无供应商通用状态查询端点，不宣称已完成真实核对。B 的拨号和对外交付不注册到内部重试入口。

## 验证证据与限制

本轮使用本机 PostgreSQL 17.6、Python 3.12、Node.js 24 和虚构材料。自动化覆盖：

- 权限／Cookie／CSRF／限流、同机构其他用户与跨机构拒绝、历史材料限制；
- 幂等重放及并发唯一写入、草案冲突与并发发布、不可变历史规则；
- 实际文本 PDF、TXT、扫描 PDF 拒绝、混合批次、改名去重、单份替换；
- 三种初筛分支、未知引用与来源、D06／outbox 原子回滚、单步恢复；
- 租约接管与旧执行者阻断、预算竞争、外部超时不重复提交；
- 搜索固定计划、允许来源与链接过滤、摘要冲突保留、逐主体部分完成、搜索预算竞争、已知响应复用和迟到结果恢复；
- D03／证据更正失效、显式重算、mock 来源保留、交接引用和账号当前有效性；
- Alembic 升级／降级／再升级与模型一致；独立 API 与 worker 进程、API 重启后的会话、D01—D06 和唯一待交接事件；
- HTTP 实际快照与运行应用一致、全部虚构接口样例校验；前端类型检查、构建与原有演示测试。
- 禁用模拟解析，用 HTTP MockTransport 同时驱动模型与搜索标准封装，从岗位分析、规则发布到简历初筛和有效交接；核对 D01—D06、来源、用量结算和精确引用。该测试的 execution_mode=live 只表示被测协议路径，不代表调用过真实供应商。

复现后端检查：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python scripts/export_contract_schema.py --check
uv run python scripts/export_http_schema.py --check
uv run python scripts/export_search_schema.py --check
```

指定专用 PostgreSQL 测试连接 `CHEETA_TEST_DATABASE_URL` 后，测试为每个用例建立随机隔离 schema 并清理，不能指向生产库。未指定时使用临时 SQLite，两个 PostgreSQL 并发测试明确跳过；不能将 SQLite 结果称为 PostgreSQL 并发验证。

真实模型、真实搜索、授权真实简历的专业质量、B 消费与电话、报告审批／交付、Docker、Linux CI 和线上部署均未验收。正式业务规则、联系前提、价格预算及生命周期尚需负责方确认。

### 第一轮实际检查结果（历史记录）

- PostgreSQL 17.6 下 `uv run pytest`：67 项通过，包含并发、增量迁移、研究控制、标准 HTTP 路径和独立进程恢复；仅有第三方测试客户端的 httpx 弃用提示。
- Ruff 静态检查／格式检查、事件 Schema 与实际 HTTP Schema 一致性均通过。
- Node.js 24 下清洁 `npm ci`、`npm run check` 和 12 项原有演示测试通过。构建仍有既有的大包体积提示；没有据此开展额外界面或拆包改造。
- 本地文档链接和 Git 差异空白检查通过。临时数据库、下载和构建产物均被忽略；没有提交或推送。

岗位原始表单事实独立保存，展示改名不会改写重新分析的 D01 依据。未登录请求在数据库未配置时也先返回 401。待交接事件、默认模拟状态和前端演示均不能作为真实接口验收证据。

## 任务 A 完成核对

本表按首日计划 BEA-01—BEA-09 核对后端 A 的工程交付；外部接口按用户决定保留可配置适配。它不将 B/F 的职责或真实供应商验收并入“已完成”。表中源码均在 `backend/`，测试也使用虚构材料。

本表是第一轮固定流程的历史范围。新 Pi 研究模式采用新增的 0003 迁移、完整 D03 研究对象与五部分 D04，不能用下表“固定查询／主体尚未核实”的旧行为代替新模式；新模式也不代表专业质量已经通过。

| 任务 | 当前实现证据 | 验证证据与边界 |
| --- | --- | --- |
| BEA-01 公共合同和启动 | `app/main.py`、`core/auth.py`、`http_models.py`、`openapi.py`；B 路由挂载及 worker 注册入口 | `test_health.py`、`test_permissions.py`、`test_api_contract.py`；接口草案中 34 项 A 操作均有实际注册路径，不能据此推断 B 已实现 |
| BEA-02 持久化和执行器 | `core/models.py`、`tasks.py`、`app/worker.py`；显式 Alembic 迁移 | `test_migrations.py`、`test_reliability.py`、`test_process_restart.py`；验证升级、领取、租约、有限内部恢复和重启保存 |
| BEA-03 登录和模型封装 | `scripts/create_user.py`、`core/auth.py`、`modules/intake/analysis.py` | `test_permissions.py`、`test_model_boundary.py`、`test_http_pipeline.py`；凭据与异常不外泄，输出有界；供应商就绪未验收 |
| BEA-04 D01/D02 与发布 | `modules/intake/router.py`、`schemas.py`、`service.py`；独立初筛／面试／推荐标准、不可变 RulePack | `test_intake.py`、`test_api_contract.py`、`test_reliability.py`；缺项拒绝发布、并发 revision、历史规则和原始表单保护 |
| BEA-05 D03 与批次 | `batches.py`、`analysis.py`、`service.py`；文件／候选人／岗位关联分开 | `test_batches.py`、`test_intake.py`；真实解析虚构文本 PDF、TXT 与文本，逐份失败、去重、替换与恢复；OCR/DOCX 不在首日范围 |
| BEA-06 D04 | `integrations/search.py`、`modules/intake/research.py`；固定主体和期间、来源时间、差异与未知、查询计划和停止原因 | `test_research.py`、`test_http_pipeline.py`；有界适配、部分结果、预算和未知结果控制。未自动核实主体或个人贡献，专业核实与真实提供者验证待后续 |
| BEA-07 D05/D06 | `app/worker.py:screen`、`modules/intake/service.py:screening_decision`；程序按绑定规则及来源核验 | `test_intake.py`、`test_research.py`、`test_corrections.py`；三分支、人工复核、未知不当作不符、研究摘要不冒充已核实证据 |
| BEA-08 可靠交接 | `service.py:publish_handoff/validate_handoff`、1.1 事件模型与 outbox | `test_contracts.py`、`test_handoff_and_restrictions.py`、`test_reliability.py`；D06／事件同事务，防重业务键、当前有效性和来源校验。电话业务任务由 B 创建，未执行 |
| BEA-09 集成和预算 | `core/tasks.py`、`research.py`、`queries.py`、`workspace.py`、`corrections.py`、Compose 和 CI 配置 | 本地 PostgreSQL 全集、标准 HTTP 路径、迁移与独立进程验证；金额结算、B/F 联调、Docker 和远端 CI 未验收 |

公共接口验收覆盖 API-01—08、23、24、26 的 A 部分，以及 API-09 的原子事件登记、API-21 的 D03 更正传播。API-09 的 B 消费、API-10—22 的电话／报告职责、API-25 的前端恢复和全产品 DAY1-17 闭环不在本次后端 A 完成结论内。更正只支持 D03 白名单；D08 更正与电话停止／交付阻断由 B 继续集成。

命令证据：`uv sync --locked`、Ruff 检查和格式检查、PostgreSQL 下 `uv run pytest`、事件／HTTP／搜索三个导出器 `--check` 均通过；前端 Node.js 24 的 `npm ci`、`npm run check` 与 `npm test` 通过。临时数据和依赖目录被 Git 忽略，暂存区为空，未提交、未推送、未部署。
