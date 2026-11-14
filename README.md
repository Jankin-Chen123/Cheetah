# Cheetah 猎报

**招对人，快人一步。**

面向猎头顾问的 AI 招聘工作台，将岗位需求、简历与证据、候选人沟通、评估与推荐串成可追溯的工作流，让专业判断更快变成有据可循的推荐。

![Cheetah 猎报品牌封面：招对人，快人一步。](docs/assets/cheetah-cover.png)

*品牌概念图，非产品截图。*

[快速体验](#快速体验) · [功能与进度](#功能与进度) · [本地开发](#本地开发) · [技术架构](#技术架构) · [项目文档](#项目文档)

## 为什么做猎报

一份好机会与一位合适的人之间，常常隔着许多细碎的工作：听懂需求、整理标准、翻阅简历、核实经历、沟通意向，再把判断写成值得信赖的推荐。

Cheetah 希望减少这些环节中的信息搬运与等待，让猎头把更多时间留给深入沟通、专业判断与关系建立。

- **先看清需求**：将沟通材料整理成岗位画像、招聘 JD 和面试评估标准，关键标准由人确认。
- **让材料支撑判断**：结构化简历、记录公开研究依据，区分候选人自述、团队成果与个人贡献。
- **把未知留在台面上**：信息不足、证据冲突和未评估分别表达，缺失信息不直接算作负面事实。
- **让推荐可以复核**：内部评估与对外推荐分开，保留产物版本、修订依据与具体版本的审核记录。

英文 Cheetah 意为“猎豹”；中文“猎报”的“猎”来自猎头，“报”承载报告、报名与报来好消息的期待。更多故事见[品牌说明](docs/Cheetah_品牌故事与文案_V1.md)。

## 从需求到推荐

产品围绕以下工作链路设计：

```text
岗位沟通材料 → 岗位画像与标准确认
                     ↓
简历导入 → 独立人才库 → 职能分流 → 岗位研究与初筛
                                           ↓
                                  沟通准备与候选人面试
                                           ↓
                                  内部评估 → 推荐草案
                                              ↓
                                        人工审核与导出
```

人才可以先入库，再关联相关岗位；同一份简历的结构化结果可复用。职能分流只表示进入相关岗位的待初筛队列，不代表胜任、通过或录用。

**当前为本地开发与集成阶段。** 初筛、面试与报告模块已经在同一工程整合，但真实初筛事件到面试案例的自动交接尚未接通，完整真实业务闭环仍待验收。演示区使用虚构样例，预置电话状态、转写和报告不是真实通话结果。

## 功能与进度

| 模块 | 当前可用范围 | 接入与验证边界 |
| --- | --- | --- |
| 官网与账号 | 官网、注册、登录、会话恢复、退出；账号工作空间与演示区隔离 | 暂无团队邀请、自助找回密码与邮箱验证 |
| 岗位与标准 | 文字建岗、异步分析、岗位画像与面试表、人工修订、本机版本、PDF / Word 导出 | 录音 ASR、人工版本回写、完整规则发布界面待接入；本机确认不等于服务端规则发布 |
| 人才库与分流 | TXT、文本 PDF、DOCX 或文字导入；九模块简历提取、多职能标签、关联相关岗位、人工分类修订 | 扫描件 OCR 未支持；分类质量需授权标注样本评测 |
| 研究与初筛 | 有界公开研究、证据记录、七维规则评估、达标 / 信息不足 / 暂不推荐分支、任务恢复与更正失效 | 搜索默认禁用，按配置与已发布规则启用；真实端到端流程及专业质量待验收 |
| 面试与沟通 | 持久化案例、提纲、受限邀请、独立候选人语音页面、回答更正与停止流程 | 开发案例入口消费隔离 fixture；真实初筛事件消费、麦克风与语音全链路、真实电话待验收 |
| 评估与推荐 | 内部评估、推荐产物、具体版本审核与导出；账号区列表读取持久化案例 | 合并与本地测试不等于真实模型质量、报告可对外交付或线上可用 |

模型结构化输出、工具调用以及 DeepSeek 搜索和正文读取曾分别完成单接口实测；它们不代表完整业务链路通过。最新集成范围见[主分支整合说明](docs/branch-integration.md)，各模块的验证证据与限制见下方文档。

## 快速体验

只看官网和交互演示，无需数据库、模型密钥或后端。需要 **Node.js 24 与 npm**：

```powershell
git clone https://github.com/Jankin-Chen123/Cheetah.git
cd Cheetah/frontend
npm ci
npm run dev
```

- [官网](http://127.0.0.1:5173/#home)：了解产品与进入账号入口。
- [演示工作台](http://127.0.0.1:5173/#demo/overview)：查看岗位、人才库、电话状态与推荐审核交互。

前端独立运行时可能显示“基础服务未连接”。演示区保持隔离，不会调用真实外呼；注册、账号数据与服务端任务需要下述后端环境。

## 本地开发

需要 **Python 3.12、uv、Node.js 24、npm、Docker Compose**。后端与两个 worker 使用同一数据库和同一版本代码。

### 1. 配置与数据库

以下从仓库根目录执行；已存在本地 `.env` 时保留并检查现有配置：

```powershell
Copy-Item .env.example .env
```

替换示例密码，并同步 `.env` 中的 `POSTGRES_PASSWORD` 与 `CHEETA_DATABASE_URL`；默认示例用于连接本机 PostgreSQL。macOS / Linux 可用 `cp .env.example .env` 复制文件。

```powershell
docker compose up -d db
cd backend
uv sync --locked --python 3.12
uv run alembic upgrade head
```

当前迁移唯一 head 为 `0006_merge_intake_outreach`。迁移必须显式执行，API 与 worker 不在启动时创建业务表；已有分支数据库的兼容说明见[整合说明](docs/branch-integration.md)。

### 2. 启动 API 与任务执行器

在 `backend/` 分别打开三个终端：

```powershell
# 终端一：HTTP API 与语音 WebSocket 入口
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# 终端二：岗位、人才解析、研究与初筛任务
uv run python -m app.worker
```

```powershell
# 终端三：面试提纲、沟通与面试后处理任务
uv run python scripts/run_interview_worker.py
```

若启用 A03 Pi 研究，还需在 `backend/agents/a03/` 安装依赖：

```powershell
npm ci --ignore-scripts
```

模型、搜索与语音服务按需配置到本机 `.env`。A03 外部研究默认关闭，需配置提供者并发布相应规则后才执行；旧规则不会自动切换。详见 [A03 Pi Agent](docs/a03-pi-agent.md) 与[初筛 Agent V2](docs/intake-agents.md)。

仅在隔离测试中使用模拟分析时，显式设置 `CHEETA_ALLOW_MOCK=true`，并在对应请求中选择 `execution_mode=mock`。模拟不会替代真实模型验收。

### 3. 启动前端与创建账号

在 `frontend/` 执行：

```powershell
npm ci
npm run dev
```

打开[官网](http://127.0.0.1:5173/#home)注册账号。注册默认开启，每次注册建立独立机构；如关闭注册，可在 `backend/` 手动创建本地账号，密码通过隐藏输入读取：

```powershell
uv run python scripts/create_user.py dev-user --organization local-dev --display-name "本地开发"
```

没有默认账号或默认密码。独立候选人面试页位于 `/candidate`，需要本次面试的受限邀请；`/goal` 是开发验收入口。系统不会自动发送邀请或发起外部电话，邀请凭据不应粘贴到公开问题、截图或日志中。

| 入口 | 地址 |
| --- | --- |
| 前端 | [http://127.0.0.1:5173](http://127.0.0.1:5173) |
| API 文档 | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |
| 存活检查 | [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health) |
| 数据库就绪检查 | [http://127.0.0.1:8000/api/v1/health/ready](http://127.0.0.1:8000/api/v1/health/ready) |

前端通过同源 `/api/v1` 访问服务，开发代理与 Nginx 同时转发 WebSocket。健康检查成功仅说明对应基础依赖可用，不表示模型、搜索、语音和全部业务就绪。

### 使用完整应用容器

在仓库根目录完成 `.env` 配置后：

```powershell
docker compose build
docker compose up -d db
docker compose run --rm backend /app/.venv/bin/alembic upgrade head
docker compose up -d
```

入口为 [http://localhost:8080](http://localhost:8080)，账号可从官网注册；关闭注册时可用 `docker compose run --rm -it backend /app/.venv/bin/python scripts/create_user.py dev-user --organization local-dev --display-name "本地开发"` 预置。

Compose 包含数据库、API、初筛 worker、面试 worker 和前端。当前配置用于本地开发，整套应用容器运行与生产部署仍需独立验收；开发 fixture 未打包时 `/goal` 样例入口会明确返回未就绪。更多配置见[容器数据库说明](docs/container-database.md)。

## 技术架构

前后端分离，后端采用同一 FastAPI 工程、同一 PostgreSQL 数据库与持久化后台任务。九个 Agent 表示业务职责，不是九个独立服务。

| 层次 | 技术与职责 |
| --- | --- |
| 前端 | React 19、TypeScript、Vite、Ant Design；官网、猎头工作台与候选人面试页 |
| API 与数据 | Python、FastAPI、Pydantic、SQLAlchemy、Alembic、PostgreSQL 17 |
| 需求与初筛 | A01 / A02 岗位标准、A04 简历结构化、A03 公开研究、A05 规则评估 |
| 有界研究 | Pi Agent Core、pi-web-access；按对象规划、搜索、读取原文、记录证据与停止 |
| 沟通与推荐 | 面试任务执行器、WebSocket 与语音适配、访谈整理、评估、推荐审核 |
| 共同基础 | 会话与对象权限、来源与证据、产物版本、幂等、防重、预算、恢复与审计 |

```text
frontend/                     官网、猎头工作台、候选人面试页
backend/
  app/core/                   公共配置、数据库、鉴权与合同
  app/modules/intake/         岗位、人才库、研究与初筛（D01—D06）
  app/modules/outreach/       面试、评估与推荐（D07—D10）
  app/integrations/voice/     语音适配
  agents/                     Pi 研究执行器与专业资源
  migrations/                 显式数据库迁移
  tests/                      业务、权限、恢复与合同测试
docs/                         产品、接口、接入与验证说明
```

初筛与面试分别使用 `/api/v1/tasks/{id}` 和 `/api/v1/interview-tasks/{id}`。HTTP 读模型、内部事件与前端演示模型分别维护，实际字段以当前实现的 OpenAPI 为准。

## 开发检查

后端，在 `backend/` 执行：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python scripts/export_contract_schema.py --check
uv run python scripts/export_http_schema.py --check
uv run python scripts/export_goal_openapi.py --check
uv run python scripts/export_search_schema.py --check
uv run python scripts/export_a03_schema.py --check
uv run python scripts/export_intake_schema.py --check
```

前端，在 `frontend/` 执行：

```powershell
npm ci
npm run check
npm test
```

A03 执行器，在 `backend/agents/a03/` 执行：

```powershell
npm ci --ignore-scripts
npm run check
npm test
```

[CI 配置](.github/workflows/ci.yml)覆盖前后端检查、PostgreSQL 测试与合同快照一致性。测试通过不等于真实供应商、专业筛选质量或线上部署验收；每次交付的实际结果见对应模块说明。

## 项目文档

| 想了解什么 | 阅读入口 |
| --- | --- |
| 产品定位与品牌 | [产品需求文档](docs/Cheetah_产品需求文档_V0.5.md) · [品牌故事与文案](docs/Cheetah_品牌故事与文案_V1.md) |
| 当前整合状态 | [主分支整合说明](docs/branch-integration.md) · [前端交付范围](docs/frontend-delivery.md) |
| 岗位与人才流程 | [材料创建岗位](docs/job-material-workflow.md) · [人才入库与分流](docs/talent-routing.md) |
| 初筛与研究 | [初筛 Agent V2](docs/intake-agents.md) · [A03 Pi Agent](docs/a03-pi-agent.md) · [后端 A 交付](docs/backend-a-delivery.md) |
| 账号与环境 | [官网与账号](docs/website-auth.md) · [数据库与容器](docs/container-database.md) |
| 当前接口快照 | [整合运行时 OpenAPI](docs/api/openapi.goal-local.json) · [初筛接口快照](docs/api/openapi.implemented.v1.json) |
| 接口设计与联调 | [接口总文档](docs/api/README.md) · [模型映射](docs/api/models.md) · [接入与验收](docs/api/integration-guide.md) |
| 交接与协作 | [交接合同](docs/contracts/README.md) · [协作规则](AGENTS.md) · [首日开发计划](docs/Cheetah_一天极限开发计划_V0.1.md) |

`docs/api/` 同时包含规划设计与实现快照；`planned`、`integration-draft` 不代表已实现，早期模块文档也可能落后于当前整合状态。修改接口时须同步模型、生成快照、样例与消费方。

## 数据与使用边界

真实、模拟和人工来源贯穿下游保留；更正产生新版本并使受影响旧结果失效。重新计算不会默认重拨，重新生成不会默认重新交付。

真实沟通前须核验联系前提、当前授权、时段、预算和已有任务；候选人要求结束时由程序停止。未达标不生成对外推荐，未批准的具体版本不得对外交付。

本地 `.env`、真实简历、录音、转写、联系方式、密钥、日志与数据库不得进入公开仓库。账号与本机材料隔离不替代服务端权限校验，也不代表已达到生产使用要求。
