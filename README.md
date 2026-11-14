# Cheetah 猎报

**招对人，快人一步。**

Cheetah 意为“猎豹”；中文名“猎报”，“猎”取自猎头，“报”取自报告与报名。以猎豹的敏捷与专注为意象，让专业判断更快变成有据可循的推荐。

面向猎头的网页端 Agent 自动化工作流：梳理 HR 招聘需求，批量分析与初筛简历，安排 AI 电话沟通，生成内部评估和候选人推荐报告。

**当前为前端交互演示与后端 A 本地开发版本。** 前端已实现工作台、岗位与规则草案、简历暂存校验、候选人产物与证据查看、模拟电话状态、模拟报告版本审核与 Markdown 下载。所有样例均为虚构，修改仅存于当前页面内存，刷新重置。后端 A 已实现预置账号会话、对象权限、岗位和规则版本、PDF/TXT/文本批次、持久化任务、D01—D06、三分支初筛与事务交接事件。搜索支持可配置的有界适配，默认禁用；模型与搜索均未做真实供应商验收。电话与服务端报告由后端 B 负责，尚未接入。前端业务页尚未调用这些 A 接口。

## 架构与分工

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

打开前端 [http://localhost:5173](http://localhost:5173)，API 文档为 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。前端开发代理将 `/api` 转发给本地后端。

未运行数据库时后端仍可启动，存活检查返回成功；数据库就绪检查返回 503，不会把未连接状态冒充就绪。

## 数据库与容器

在根目录启动本地数据库：

```powershell
docker compose up -d db
cd backend
uv run alembic upgrade head
```

当前包含 `0001_intake_baseline` 和增量 `0002_bounded_research` 迁移。必须显式升级到 head；API 和 worker 均不会在启动时建表。首次启动前先创建本地预置账号：

```powershell
uv run python scripts/create_user.py dev-user --organization local-dev --display-name "本地开发"
```

密码通过隐藏输入读取，不存在默认账号或密码。另开终端在 `backend/` 运行 `uv run python -m app.worker` 执行队列任务；也可用 `--drain` 处理当前队列后退出。仅隔离演示时在本地 `.env` 显式设置 `CHEETA_ALLOW_MOCK=true`，并在请求中选择 `execution_mode=mock`。模拟分析采用受限字段解析，不代表真实 AI。

容器运行前先显式迁移并预置账号，再启动服务（本轮未实际运行 Docker）：

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

A03 新增基于 Pi 的研究执行模式：完整 D03 对象、目标规划、工具循环、逐项证据校验和五部分 D04。需要 Node.js 24、安装 `backend/agents/a03` 依赖、显式升级到 `0003_pi_research`，并发布 pi-research v1 规则。默认禁用外部研究；配置、插件复用与实际测试边界见 [A03 Pi Agent](docs/a03-pi-agent.md)。旧规则不会自动切换，真实模型／搜索供应商仍未验收。

下一步由 F 接入实际 A 接口，B 接入并核验 1.1 交接事件；真实模型、搜索及语音能力须分别验证。真实／模拟来源必须明确，实际外呼前须具备有效联系前提和停止能力；未审核的推荐版本不能对外交付。
