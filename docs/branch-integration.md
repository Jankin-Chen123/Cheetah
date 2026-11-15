# 主分支整合：账号、页面与迁移（2026-11-15）

后续全流程增量已经实现经过核验的1.1 outbox消费、正式面试标准绑定及文字候选人页，下面“尚未消费”是整合当时的历史边界。当前实际验证与未部署状态见 [全流程核验](full-flow-validation-2026-11-15.md)。


保留 main 的官网、注册登录、岗位、人才库、导航及主题。账号区的电话任务与推荐审核沿用当前列表外观，读取持久化面试案例，详情复用 personal/dev 的面试准备、停止、邀请、回答更正、D08/D09/D10、具体版本审核与导出。预览区仍使用隔离的原有数据。

新增 `/candidate#call=…&token=…` 独立候选人语音面试页，邀请凭据只放 URL fragment；`/goal` 保留开发验收入口。项目所有审核操作统一使用官网注册或显式预置的账号，不再提供 CHEETA_LOCAL_PASSWORD 开发登录。候选人页只接受本次面试的受限邀请，不依赖审核账号 Cookie。不会自动发送邀请、邮件或发起外部电话。

初筛任务继续使用 `/api/v1/tasks/{id}`；面试模型任务调整为 `/api/v1/interview-tasks/{id}` 与 `/{id}/retry`，避免两个任务模型使用同一路径。面试步骤仍采用现有 revision/步骤唯一键协议，不应冒充完整平台草案中的通用幂等接口；实际字段见运行时 OpenAPI。WebSocket 已在 Vite 和 Nginx 配置转发。

显式执行 `uv run alembic upgrade head`，唯一 head 为 `0006_merge_intake_outreach`。兼容空库、原 main 数据库和原 personal/dev 数据库；两个旧分支的业务记录保留。旧面试开发会话若存在，移入 `legacy_outreach_login_sessions`，不作为官网账号登录凭据。旧面试案例仍保留原所有者/机构，不自动转让给新注册账号；需要迁移归属时另行核对授权。

API、初筛 worker 和面试 worker 均使用同一版本代码与同一数据库。面试 worker 启动命令：`uv run python scripts/run_interview_worker.py`；Compose 新增同名职责的 `interview-worker` 服务。迁移不会在应用启动时执行。本次不修改本机业务数据库、不运行真实模型、语音或 SMTP、不部署。

**当前上游边界仍保留：** personal/dev 的开发案例入口只消费隔离的旧版 mock fixture；main 的真实 `screening.passed` 1.1 outbox 尚未接入面试案例消费器。合并代码和页面不等于真实简历初筛自动进入通话已验收。真实模型专业质量、麦克风/语音服务全链路、真实电话及线上部署需另行验收。


## 本地验证

后端 PostgreSQL 隔离测试 schema 全量 397 项通过，包含共享账号、跨所有者隔离、禁用/过期会话、两类任务路径和从两个分支升级的迁移验证；前端检查、构建和 50 项测试通过，A03 类型检查及依赖合同测试通过。五个原有 Schema 导出检查通过，新增 Goal 快照检查纳入 CI。浏览器在独立 SQLite 数据库和虚构账号上验证登录、电话列表与详情、生成受限邀请及语音页面加载、缺少邀请时阻止进入及 390px 无横向溢出；没有启动真实麦克风、模型、语音或邮件。

原分支中的 /goal 开发样例导入需要仓库 docs 下的 fixture，当前运行镜像未包含该文档时明确返回 503 FIXTURE_NOT_PACKAGED；不返回伪成功。

Compose 配置解析与临时 Nginx 容器中的配置检查通过；未运行整套应用容器。
