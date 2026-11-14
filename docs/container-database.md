# PostgreSQL 容器与迁移

项目使用同一个 PostgreSQL 17 数据库。`compose.yaml` 的 `db` 服务使用官方镜像和 `postgres_data` 命名卷；API、worker 共用数据库。数据库、API 和前端的主机端口默认只绑定 `127.0.0.1`。后续服务器部署可复用同一套 Compose，通过服务器反向代理提供 HTTPS；当前没有执行生产部署。

## 本地配置

根目录 `.env` 保留模型配置，并增加本地数据库名称、账号、随机密码、主机端口和主机侧连接地址。`.env` 不进入 Git。`.env.example` 只保留占位密码，不可直接当作实际凭据。

- `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`：数据库容器初始化参数。
- `POSTGRES_HOST_PORT`：默认 5432，只映射到本机回环地址。
- `CHEETA_DATABASE_URL`：主机上运行 API、worker、迁移时使用的连接地址。
- 容器里的 API/worker 使用服务名 `db:5432`，由 Compose 注入连接地址；不能在容器里用 localhost 连接另一个容器。
- 模型端点、密钥、输出上限、超时和允许的浏览器 Origin 统一传入 backend/worker；密钥不作为构建参数写入镜像。

首次初始化已有数据卷后，修改 `POSTGRES_PASSWORD` 不会修改数据库内部密码。已有数据卷必须继续使用匹配的凭据；不能删除卷来解决一般连接问题。

## 启动与显式迁移

在项目根目录运行：

```powershell
docker compose config --quiet
docker compose up -d db
docker compose ps db
```

API/worker 在主机运行时，在 `backend/` 执行：

```powershell
uv sync --locked
uv run alembic upgrade head
uv run alembic current
```

完整应用使用容器时，先构建并显式迁移，再创建本地账号和启动：

```powershell
docker compose build backend worker frontend
docker compose run --rm backend /app/.venv/bin/alembic upgrade head
docker compose run --rm -it backend /app/.venv/bin/python scripts/create_user.py dev-user --organization local-dev --display-name "本地开发"
docker compose up -d backend worker frontend
```

密码通过交互输入；没有默认登录账号。应用启动不会自动创建业务表，也不会因数据库健康就宣称模型、搜索或电话已经就绪。

## 保存与迁移数据

容器重启、重建或普通 `docker compose down` 不删除命名卷。需要暂时关闭时使用 `docker compose stop`。不要使用 `down -v` 或清理卷来解决一般启动问题。

迁往服务器时，复制代码并在服务器单独准备受限 `.env`，再执行显式迁移。已有数据使用 `pg_dump`/`pg_restore` 做逻辑备份和恢复；不能把运行中的数据目录直接复制成备份。部署前分别核对数据恢复、HTTPS、Origin、访问权限和实际接口，不把本机容器检查视为线上验收。

## 搜索范围

按当前业务要求，`CHEETA_SEARCH_ALLOWED_DOMAINS=[]` 表示可检索公开网站，不再要求逐个配置公司域名。本机、内网、云元数据地址、携带凭据的链接仍不可作为研究来源。本地已按用户要求配置 DeepSeek 原生搜索及正文读取，复用其提供的模型 API 账户；相关密钥和私有服务地址只在 `.env`。Compose 会把搜索提供者、密钥及基址传入 API/worker。

## 本地实际验证（2026-11-14）

Docker Desktop 引擎已恢复，`db` 容器为 healthy。使用 PostgreSQL 17 官方容器执行显式迁移至 `0003_pi_research`；重启容器后实际连接数据库，迁移记录仍为同一 head。Compose 已检查数据库命名卷、本机端口绑定、API/worker 共用数据库及模型配置传入。

数据库容器首次验收时，后端全量测试 131 项通过。Pi 插件另通过无凭据合同检查，以及空域名列表下拒绝本机地址的检查。随后已单独实测 DeepSeek 搜索与正文读取；完整 API/worker/前端镜像和服务器部署尚未验收，没有创建默认业务登录账号。
