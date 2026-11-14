# Cheetah 猎报

**招对人，快人一步。**

Cheetah 意为“猎豹”；中文名“猎报”，“猎”取自猎头，“报”取自报告与报名。以猎豹的敏捷与专注为意象，让专业判断更快变成有据可循的推荐。

面向猎头的网页端 Agent 自动化工作流：梳理 HR 招聘需求，批量分析与初筛简历，安排 AI 电话沟通，生成内部评估和候选人推荐报告。

**当前为前端交互演示与后端 A 本地开发版本。** 前端已实现工作台、岗位与规则草案、简历暂存校验、候选人产物与证据查看、模拟电话状态、模拟报告版本审核与 Markdown 下载。所有样例均为虚构。岗位材料、录音和 D01/D02 人工版本保存在本机，支持刷新恢复及 PDF/Word 导出；候选人、电话与推荐演示仍为页面内存。后端 A 已实现预置账号会话、对象权限、岗位和规则版本、PDF/TXT/文本批次、持久化任务、D01—D06、三分支初筛与事务交接事件。搜索支持可配置的有界适配，默认禁用；模型 JSON 输出、工具调用及 DeepSeek 搜索、正文读取已分别实测；完整业务流程与专业质量仍待验收。电话与服务端报告由后端 B 负责，尚未接入。前端岗位产物页已接入会话、文字建岗、异步分析和产物查询调用；真实模型端到端尚未验证，录音 ASR 与人工版本回写后端待接入。其余业务页仍为演示。详见[材料创建流程](docs/job-material-workflow.md)。

## 架构与分工

初筛 Agent 已按业务资料补充完整表单：A01、A02、A05 岗位规则建议依次持久化执行，A04 提取九模块简历并派生研究清单，A03 使用 Pi 进行有界研究，A05 按发布的七维规则输出 D05/D06。新增 DOCX 文本读取及表单报告；完整真实业务流程及专业筛选质量尚未验收。规则启用方式、模板差异和验证边界见 [初筛 Agent V2](docs/intake-agents.md)。

前后端分离，后端两条业务线在同一 FastAPI 工程和 PostgreSQL 数据库内并行开发：

| 范围 | 目录 | 负责产物 |
| --- | --- | --- |
| 前端 | `frontend/` | 猎头工作台与用户交互 |
| 后端 A | `backend/app/modules/intake/` | 需求、岗位规则、简历、研究、初筛，D01—D06 |
| 后端 B | `backend/app/modules/outreach/`、`backend/app/integrations/voice/` | 电话、访谈、评估与推荐，D07—D10 |
| 公共基础 | `backend/app/core/` | 配置、数据库、健康检查、交接合同、鉴权、任务、产物和证据 |

九个 Agent 是逻辑职责，不要求九个独立服务。A/B 通过版本化产物和持久化事件交接；当前 A 已有独立持久化任务执行器与 outbox；B 尚未接入消费，达标不代表已经创建电话或获得拨号授权。

## 本地启动

需要 Python 3.12、uv、Node.js 24 与 npm。数据库和容器启动另需 Docker Compose。

在仓库根目录复制本地配置，替换示例密码；本地配置不会进入 Git：

```powershell
Copy-Item .env.example .env
```

启动后端：

```powershell
cd backend
uv sync --locked
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

另开终端启动前端：

```powershell
cd frontend
npm ci
npm run dev
```

打开前端 [http://127.0.0.1:5173](http://127.0.0.1:5173)，API 文档为 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。前端开发代理将 `/api` 转发给本地后端。

未运行数据库时后端仍可启动，存活检查返回成功；数据库就绪检查返回 503，不会把未连接状态冒充就绪。

## 数据库与容器

数据库采用 PostgreSQL 17 容器及命名卷，主机和容器内连接地址分别配置。启动、显式迁移、数据保存和后续服务器部署准备见 [容器数据库说明](docs/container-database.md)。

在根目录启动本地数据库：

```powershell
docker compose up -d db
cd backend
uv run alembic upgrade head
```

当前包含 `0001_intake_baseline` 和增量 `0002_bounded_research` 迁移。必须显式升级到 head；API 和 worker 均不会在启动时建表。需要使用预置账号时，可先创建本地账号（也可启动后从官网注册）：

```powershell
uv run python scripts/create_user.py dev-user --organization local-dev --display-name "本地开发"
```

密码通过隐藏输入读取，不存在默认账号或密码。另开终端在 `backend/` 运行 `uv run python -m app.worker` 执行队列任务；也可用 `--drain` 处理当前队列后退出。仅隔离演示时在本地 `.env` 显式设置 `CHEETA_ALLOW_MOCK=true`，并在请求中选择 `execution_mode=mock`。模拟分析采用受限字段解析，不代表真实 AI。

完整应用容器运行前先显式迁移并预置账号，再启动服务（整套应用容器仍需独立验收）：

```powershell
docker compose build
docker compose run --rm backend /app/.venv/bin/alembic upgrade head
docker compose run --rm -it backend /app/.venv/bin/python scripts/create_user.py dev-user --organization local-dev --display-name "本地开发"
docker compose up -d
```

容器入口为 [http://localhost:8080](http://localhost:8080)，通过同源 `/api/v1` 访问后端；数据库和 API 端口仅绑定本机。容器配置用于开发验证，不代表生产配置或已完成业务鉴权。

## 检查命令

```powershell
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python scripts/export_contract_schema.py --check
uv run python scripts/export_http_schema.py --check
uv run python scripts/export_search_schema.py --check
uv run python scripts/export_a03_schema.py --check
uv run python scripts/export_intake_schema.py --check
```

```powershell
cd frontend
npm ci
npm run check
npm test
```

后端新增或修改交接模型后，运行 `uv run python scripts/export_contract_schema.py` 更新 JSON Schema，并检查样例和消费方。CI 对后端检查、前端构建和合同一致性分别执行验证。

## 已实现接口与验证边界

A 接口覆盖登录／退出、岗位与规则、批次和单份替换、候选人／产物／证据／文件查询、任务状态与受控重试、初筛人工复核、D03 白名单更正与显式重算，以及工作台和待办。所有业务接口要求会话；写入校验 Origin、CSRF，业务 POST 还需幂等 key。跨机构或无岗位归属的对象统一不可见。

可导入的实际接口见 [运行时 OpenAPI 快照](docs/api/openapi.implemented.v1.json)，完整规划见 [接口设计稿](docs/api/README.md)。来源、支持的谓词和配置、启动／联调步骤与验收结果见 [后端 A 交付说明](docs/backend-a-delivery.md)。静态合同与模拟闭环不证明专业筛选质量、真实模型、联网研究、外呼或线上部署可用。

健康检查保留原协议：`/api/v1/health` 仅存活；`/health/ready` 仅探测数据库连接，不代表迁移、模型、搜索、电话和全部业务就绪。业务错误均带请求标识，并隐藏敏感输入与连接信息。

## 官网与账号

默认打开官网（`#home`），可进入登录（`#login`）、注册（`#register`）或无需账号的演示区（`#demo/overview`）。注册成功进入账号工作空间（`#app/overview`），支持刷新恢复、退出与过期拦截；本机岗位数据按账号隔离。后端须先完成迁移并启动，不必预置账号即可注册。

注册默认开启，可用 `CHEETA_REGISTRATION_ENABLED=false` 关闭；默认每个直接连接来源每 10 分钟最多 5 次尝试，通过 `CHEETA_REGISTRATION_ATTEMPT_LIMIT` 调整。每次注册建立独立机构，不支持自行加入已有团队。候选人、电话与推荐真实页面仍待接入。账号验证不需要模型服务。详见 [官网与账号交付](docs/website-auth.md)。

## 项目文档

- [品牌故事与文案](docs/Cheetah_品牌故事与文案_V1.md)
- [协作规则](AGENTS.md)
- [产品需求文档 V0.5](docs/Cheetah_产品需求文档_V0.5.md)
- [一天极限开发计划](docs/Cheetah_一天极限开发计划_V0.1.md)
- [交接合同](docs/contracts/README.md)
- [前后端接口对接文档与 OpenAPI 草案](docs/api/README.md)
- [后端开发约定](backend/AGENTS.md)
- [前端开发约定](frontend/AGENTS.md)
- [前端演示范围与接入说明](docs/frontend-delivery.md)

搜索配置、标准 HTTP 协议和接入方法见 [可配置研究适配器](docs/api/search-adapter.md)。未配置或规则禁用时 D04 明确未执行；已收集摘要仍为待核实证据，不自动确认主体、历史适用性或个人贡献。

研究来源默认不限制公开网站域名：`CHEETA_SEARCH_ALLOWED_DOMAINS=[]`。非空域名列表才收窄来源；本机、内网和携带凭据的链接仍不作为公开研究来源。搜索提供者默认仍禁用，需配置实际搜索接口。

A03 新增基于 Pi 的研究执行模式：完整 D03 对象、目标规划、工具循环、逐项证据校验和五部分 D04。需要 Node.js 24、安装 `backend/agents/a03` 依赖、显式升级到 `0003_pi_research`，并发布 pi-research v1 规则。默认禁用外部研究；配置、插件复用与实际测试边界见 [A03 Pi Agent](docs/a03-pi-agent.md)。旧规则不会自动切换。模型与 DeepSeek 搜索、正文读取已分别实测，完整真实候选人研究与专业质量仍待验收。

下一步由 F 接入实际 A 接口，B 接入并核验 1.1 交接事件；真实模型、搜索及语音能力须分别验证。真实／模拟来源必须明确，实际外呼前须具备有效联系前提和停止能力；未审核的推荐版本不能对外交付。

## 人才入库与岗位分流

登录后的简历上传先进入独立人才库，复用 A04 一次提取，按职能多标签关联相关的已发布岗位。无岗位或方向不明的人才保留；分流只标记待深度初筛，不作通过、淘汰或录用判断。新岗位发布后可关联已有相关人才。岗位候选人详情可显式启动既有 A03/A05 流程。运行前显式迁移到 `0004_talent_routing`，API 和 worker 均需使用当前代码。接口、兼容路径和实际验证边界见 [人才入库与职能分流](docs/talent-routing.md)。


## 主分支整合（2026-11-15）

保留 main 的前端效果，接入 personal/dev 的面试和报告模块及独立候选人语音页面；统一官网账号、区分初筛与面试任务路径，显式迁移到 `0006_merge_intake_outreach`。实现范围、兼容方案及真实上游未接入等边界见 [整合说明](docs/branch-integration.md)。
