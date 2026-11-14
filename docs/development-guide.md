# 开发与本地运行

[返回产品介绍](../README.md)

本页保留项目的环境准备、启动、技术架构与检查命令。当前整合范围与验证记录见[主分支整合说明](branch-integration.md)。

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

当前迁移唯一 head 为 `0006_merge_intake_outreach`。迁移必须显式执行，API 与 worker 不在启动时创建业务表；已有分支数据库的兼容说明见[整合说明](branch-integration.md)。

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

模型、搜索与语音服务按需配置到本机 `.env`。A03 外部研究默认关闭，需配置提供者并发布相应规则后才执行；旧规则不会自动切换。详见 [A03 Pi Agent](a03-pi-agent.md) 与[初筛 Agent V2](intake-agents.md)。

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

Compose 包含数据库、API、初筛 worker、面试 worker 和前端。当前配置用于本地开发，整套应用容器运行与生产部署仍需独立验收；开发 fixture 未打包时 `/goal` 样例入口会明确返回未就绪。更多配置见[容器数据库说明](container-database.md)。

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

[CI 配置](../.github/workflows/ci.yml)覆盖前后端检查、PostgreSQL 测试与合同快照一致性。测试通过不等于真实供应商、专业筛选质量或线上部署验收；每次交付的实际结果见对应模块说明。

## 部署与协作

服务器配置与镜像发布见[服务器部署说明](server-deployment.md)；开发时遵守[项目协作约定](../AGENTS.md)，接口以[接入与验收指引](api/integration-guide.md)及当前实现为准。
