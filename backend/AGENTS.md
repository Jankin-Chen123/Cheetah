# 后端开发约定

本文件补充根目录 `AGENTS.md`，不替代它。

- 使用 Python 3.12、FastAPI、Pydantic、SQLAlchemy 与 PostgreSQL；在本目录通过 uv 管理依赖和锁文件。
- A 维护 `core/`、启动入口与统一迁移；A/B 分别维护 `modules/intake/` 和 `modules/outreach/`。公共变更先同步合同，禁止新增另一套鉴权、任务或产物格式。
- 所有业务路由统一由 `app.main:create_app` 挂到 `/api/v1`。未实现的业务不添加伪成功接口。
- 初始化健康检查不是业务就绪承诺。数据库连接失败只返回稳定错误码，不透传 SQL、连接串和密钥。
- 业务实体、产物与文件必须进行对象归属校验；在鉴权实现前不要暴露真实业务入口或测试候选人数据。
- 使用数据库事务保证产物与待交接事件一致；不要用进程内临时任务承担外呼可靠性。
- 外部超时先核对实际状态，自动重试不等于自动重拨。报告审核绑定不可变版本。
- 更改 `core/contracts.py` 后更新导出 Schema、合同文档、样例与对应消费方。
- 检查：`uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest`、`uv run python scripts/export_contract_schema.py --check`。
- 检查需要数据库、外部接口或 Docker 时说明实际验证环境；仅单元测试通过不能宣称真实电话已可用。
