# Cheeta

面向猎头的网页端 Agent 自动化工作流：梳理 HR 招聘需求，批量分析与初筛简历，安排 AI 电话沟通，生成内部评估和候选人推荐报告。

**当前为工程初始化版本。** 已建立前后端骨架、健康检查、公共交接合同、数据库迁移入口和自动检查配置。登录、业务任务执行、模型检索、真实电话、报告审核与导出尚未实现。

## 架构与分工

前后端分离，后端两条业务线在同一 FastAPI 工程和 PostgreSQL 数据库内并行开发：

| 范围 | 目录 | 负责产物 |
| --- | --- | --- |
| 前端 | `frontend/` | 猎头工作台与用户交互 |
| 后端 A | `backend/app/modules/intake/` | 需求、岗位规则、简历、研究、初筛，D01—D06 |
| 后端 B | `backend/app/modules/outreach/`、`backend/app/integrations/voice/` | 电话、访谈、评估与推荐，D07—D10 |
| 公共基础 | `backend/app/core/` | 配置、数据库、健康检查、交接合同；后续补充鉴权、任务和证据 |

九个 Agent 是逻辑职责，不要求九个独立服务。A/B 通过版本化产物和持久化事件交接；当前仅实现合同，不包含任务执行器。

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

当前没有业务表迁移，后续由 A/B 按共享迁移约定添加。不要在两个模块分别自动创建或改写共享表。

运行完整骨架：

```powershell
docker compose up --build -d
```

容器入口为 [http://localhost:8080](http://localhost:8080)，通过同源 `/api/v1` 访问后端；数据库和 API 端口仅绑定本机。容器配置用于开发验证，不代表生产配置或已完成业务鉴权。

## 检查命令

```powershell
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python scripts/export_contract_schema.py --check
```

```powershell
cd frontend
npm ci
npm run check
```

后端新增或修改交接模型后，运行 `uv run python scripts/export_contract_schema.py` 更新 JSON Schema，并检查样例和消费方。CI 对后端检查、前端构建和合同一致性分别执行验证。

## 已实现接口

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/health` | API 存活状态和初始化阶段；不证明数据库、AI 或电话可用 |
| `GET /api/v1/health/ready` | 实际检查数据库连通性；未配置或无法连接返回 503 |

错误响应包含请求标识。数据库错误不会在响应中返回原始连接串或密码。

## 项目文档

- [协作规则](AGENTS.md)
- [产品需求文档 V0.5](docs/Cheeta_产品需求文档_V0.5.md)
- [一天极限开发计划](docs/Cheeta_一天极限开发计划_V0.1.md)
- [交接合同](docs/contracts/README.md)
- [后端开发约定](backend/AGENTS.md)
- [前端开发约定](frontend/AGENTS.md)

下一步先确认 API 合同与外部语音平台能力，再按开发计划并行推进。真实／模拟来源必须明确，实际外呼前须具备有效联系前提和停止能力；未审核的推荐版本不能对外交付。
