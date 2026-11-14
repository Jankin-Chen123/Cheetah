# GitHub 镜像与服务器部署

前后端检查通过后，main 的 CI 自动发布两个 GHCR 镜像，标签为
`sha-<完整提交 SHA>`，并将实际 digest 保存为工作流产物。后端、初筛 worker
和面试 worker 使用同一个后端镜像。生产凭据不进入 GitHub、构建参数或镜像。

## 首次部署

1. 在服务器创建独立目录，将 `deploy/compose.production.yaml` 复制为其中的
   `compose.yaml`，单独创建权限为 600 的 `.env`。
2. 设置 `CHEETAH_BACKEND_IMAGE`、`CHEETAH_FRONTEND_IMAGE` 为 CI 发布的
   `ghcr.io/...@sha256:...`，设置新数据库凭据、正式 HTTPS Origin 和所需供应商
   参数。应用通过 `env_file` 读取配置，不依赖构建时注入。
3. 将本地品牌图形单独提供到 `brand/cheetah-mark.png`。品牌源文件按现有
   仓库约定不公开提交；该目录只读挂载到前端容器。
4. 执行 `docker compose config --quiet`、`docker compose pull`、
   `docker compose up -d db`。
5. 显式执行 `docker compose run --rm backend /app/.venv/bin/alembic upgrade head`，
   再执行 `docker compose up -d`。首次部署使用空库，不自动复制本机数据。
6. 复用服务器现有 Nginx，为所选域名单独配置 HTTPS 和反向代理。
   `deploy/nginx-site.conf.example` 是模板，证书路径和域名必须替换。

数据库和 API 不映射主机端口；只有前端绑定本机回环地址，默认 18080。
通过 `CHEETAH_HTTP_PORT` 可调整该端口。数据库采用独立命名卷，业务表不会
在应用启动时自动创建。`CHEETA_ALLOW_MOCK` 在此部署配置中固定为 false。

## 更新、备份与回退

更新前备份当前 `.env`、Compose 和数据库逻辑备份，将文件保存到受限目录。
记录当前镜像 digest，再更新 `.env` 中两个镜像引用，拉取镜像并显式迁移后
重新创建应用容器。不要自动覆盖数据库凭据，不执行 `down -v` 或清理数据卷。

可用旧 digest 回退应用；有数据库迁移时，先核对旧应用是否兼容新 schema。
数据库恢复是独立、有明确目标的操作，不能默认随镜像回退执行。

验证域名、证书、官网、注册登录、Origin/CSRF、未授权访问拦截、数据库迁移
及服务重启状态。就绪检查只证明数据库可连接；真实模型、搜索、语音和完整
业务质量须分别验证，不能由首页或健康检查成功代替。

## 资源和业务边界

此配置限制各服务资源，两个执行器分别串行处理任务。4GB 共用服务器仍需
监测内存；限制不是容量保证。上线不自动触发真实外呼或邮件，不配置缺失
的语音凭据，不导入开发 fixture。当前初筛交接到面试的真实事件消费与完整
真实业务验收边界以整合说明为准。
