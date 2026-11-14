# Cheetah 猎报

**招对人，快人一步。**

Cheetah 意为“猎豹”；中文名“猎报”，“猎”取自猎头，“报”取自报告与报名。以猎豹的敏捷与专注为意象，让专业判断更快变成有据可循的推荐。

面向猎头的网页端 Agent 自动化工作流：梳理 HR 招聘需求，批量分析与初筛简历，安排 AI 电话沟通，生成内部评估和候选人推荐报告。

**当前 personal/dev 包含两种入口。** 原工作台仍使用内存中的虚构演示数据；`/goal` 已接本地登录、PostgreSQL 电话任务、方法检索、实际文字回答、模型步骤及具体版本审核导出。已用虚构输入完成真实模型 D08→D09→D10、浏览器具体版本审批/下载/更正/重登录，以及指定客户分享与 Word 下载核读；A10 已取得独立复核及人工核读合格的准备稿。真人麦克风完整流程和专业表单全面审计仍待验收，真实电话线路未接入。准确启动、迁移、原文和结构化方法导入、worker 与验收状态见 [Goal 验收说明](docs/Goal_验收说明.md)；已实现接口与完整平台草案的差异见 [本地 API 增量](docs/api/goal-local.md)。本机使用 8001/5174，勿停止占用默认端口的其他项目。

## 架构与分工

前后端分离，后端两条业务线在同一 FastAPI 工程和 PostgreSQL 数据库内并行开发：

| 范围 | 目录 | 负责产物 |
| --- | --- | --- |
| 前端 | `frontend/` | 猎头工作台与用户交互 |
| 后端 A | `backend/app/modules/intake/` | 需求、岗位规则、简历、研究、初筛，D01—D06 |
| 后端 B | `backend/app/modules/outreach/`、`backend/app/integrations/voice/` | 电话、访谈、评估与推荐，D07—D10 |
| 公共基础 | `backend/app/core/` | 配置、数据库、健康检查、交接合同；后续补充鉴权、任务和证据 |

九个 Agent 是逻辑职责，不要求九个独立服务。后半段已有持久化模型步骤执行器；真实上游 A 的业务链尚未接通，开发入口只导入明确虚构的已达标合同与快照。

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
$env:CHEETA_ALLOWED_ORIGINS='["http://127.0.0.1:5174","http://localhost:5174"]'
python -m uv run uvicorn app.main:app --host 127.0.0.1 --port 8001
```

另开终端启动前端：

```powershell
cd frontend
npm ci
 $env:CHEETA_DEV_API_TARGET='http://127.0.0.1:8001'
npm run dev -- --port 5174 --strictPort
```

打开前端 [http://127.0.0.1:5174](http://127.0.0.1:5174)，API 文档为 [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)。前端开发代理将 `/api` 转发给本地后端。

未运行数据库时后端仍可启动，存活检查返回成功；数据库就绪检查返回 503，不会把未连接状态冒充就绪。

## 数据库与容器

在根目录启动本地数据库：

```powershell
docker compose up -d db
cd backend
uv run alembic upgrade head
```

当前业务迁移至 `0005_model_steps`，须显式运行迁移。不要在两个模块分别自动创建或改写共享表。

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
npm test
```

后端新增或修改交接模型后，运行 `uv run python scripts/export_contract_schema.py` 更新 JSON Schema，并检查样例和消费方。CI 对后端检查、前端构建和合同一致性分别执行验证。

## 已实现接口

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/health` | API 存活状态和初始化阶段；不证明数据库、AI 或电话可用 |
| `GET /api/v1/health/ready` | 实际检查数据库连通性；未配置或无法连接返回 503 |

错误响应包含请求标识。数据库错误不会在响应中返回原始连接串或密码。

本地 `/goal` 工作台另接入了 AI 面试准备、候选人许可与会话、D08/D09 后处理、D10 版本审核及下载。内部 D07—D09 Word 与客户 D10 Markdown/Word 分开。具体请求以 [运行时 OpenAPI 快照](docs/api/openapi.goal-local.json) 和 [本地接口补充](docs/api/goal-local.md) 为准。当前验收范围及尚待验证的完整链路见 [AI 面试验收](docs/Goal_验收说明.md)。本地验收 worker 必须用 `--case-id` 限定到隔离案例。

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

下一步先确认 API 合同与外部语音平台能力，再按开发计划并行推进。真实／模拟来源必须明确，实际外呼前须具备有效联系前提和停止能力；未审核的推荐版本不能对外交付。


文本模型可通过`.env`的`CHEETA_TEXT_PROVIDER=ark`选择火山方舟，配置`CHEETA_ARK_API_KEY`和`CHEETA_ARK_MODEL`；语音ASR/TTS继续使用独立的百炼配置。`CHEETA_DIALOGUE_UNDERSTANDING_ENABLED=true`开启先理解后检索与工作记忆；向量模型配置见`.env.example`和[本地API增量](docs/api/goal-local.md)。开发知识预览可提前运行`uv run python scripts/warm_method_index.py --preview`，只建缓存、不自动审核方法。
