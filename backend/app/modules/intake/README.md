# 后端 A：需求到初筛

负责岗位、规则草案与发布、简历批次、研究状态、D01—D06，以及达标事件的持久化登记。当前可执行范围和限制见 [后端 A 交付说明](../../../../docs/backend-a-delivery.md)。

`router.py` 管理岗位与规则；`batches.py` 管理批次和替换；`queries.py` 提供对象权限下的公共读取；`corrections.py` 管理复核和 D03 更正；`workspace.py` 聚合实际状态。后台入口为 `python -m app.worker`，与 API 分开启动。公共表由统一 Alembic 迁移创建。

实际 HTTP 合同由 Pydantic 请求／响应模型导出到 `docs/api/openapi.implemented.v1.json`，前端对应 `src/api/generated.ts`。完整设计稿保留未实现的 B 路径，不能将草案视为已运行。

初筛按已发布的结构化谓词核验，缺失、冲突及未满足的证据类型进入 unknown；仅明确数值／等值不符才可拒绝。`research.py` 通过可配置适配器执行固定公司／项目查询，保存来源、冲突、缺口与停止原因，默认禁用；协议见 [研究适配器](../../../../docs/api/search-adapter.md)。搜索摘要为 U／待核实，不自动满足 public_web 要求。模拟解析仅识别显式 `字段：值`，不代表真实模型能力；真实模型与检索供应商均未验收。

D06 与 1.1 达标事件同事务保存。B 尚未消费事件；B 必须在消费事务中调用 `validate_handoff` 并另行执行电话业务级防重、当前联系前提和权限核验。重算和复核保持 application 业务键不变，不提供重拨或对外交付入口。

新增 pi-research v1 规则选择 Pi 研究循环。`a03_runtime.py` 承接模型、工具与账本，`a03_state.py` 校验证据，`a03_contracts.py` 维护报告字段／工具模型，`a03_report.py` 渲染用户范本。执行器及版本化资源位于 `backend/agents/a03`。D03 支持完整研究对象和对象级更正；详见 [A03 Pi 开发说明](../../../../docs/a03-pi-agent.md)。bounded-research 仍是旧固定计划，不能将其称为自主研究。
