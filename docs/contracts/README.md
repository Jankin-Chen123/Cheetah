# A/B 交接合同

当前 A 已执行 D01—D06 并事务登记 outbox，事件消费和真实电话属于尚未接入的 B。A 新产出的事件为 1.1；旧 1.0 模型与样例保留兼容，不能将其非空 phone 字段解释为电话已发生。

浏览器与统一 API 的 HTTP 字段、状态、错误码及对接流程见 [前后端接口文档](../api/README.md)，机器可读设计稿见 [OpenAPI 3.1 草案](../api/openapi.v1.json)。HTTP 草案与这里已存在的内部事件合同分别管理；后者仍以 Python 模型为唯一维护入口，不能把 HTTP 读模型直接替换事件载荷。

| 文件 | 用途 |
| --- | --- |
| `../../backend/app/core/contracts.py` | Python 合同模型的唯一维护入口 |
| `screening-passed.v1.schema.json` | 从模型导出的 JSON Schema，供前端及其他消费方使用 |
| `day1_screening_passed.example.json` | 明确标注模拟来源的样例，不含真实联系方式，联系授权为空 |

## 1.1 合同与 B 接入

`screening-passed.v1.1.schema.json` 和 `day1_screening_passed.v1.1.example.json` 均已提供。Schema 从 `ScreeningPassedEventV11` 导出：`source_modes.phone=null` 表示尚未通话，`source_modes.research=null` 表示尚未执行检索；新增 `phone_execution_mode=live/mock` 只表示计划模式。测试规则、上游模拟或 fixture 必须保持 `fixture_only=true` 且计划模式为 mock；不存在把未知来源补成 live 的路径。

B 消费前必须校验 `protocol_version`；不能用旧 1.0 DTO 强行读取 1.1。消费事务应锁定 outbox 记录，再调用 `app.modules.intake.service.validate_handoff` 核对当前岗位、账号、关联、绑定规则、D01—D06 和证据状态。在同事务中按 `business_dedup_key=application:{id}` 创建或复用唯一电话业务任务，再登记消费。新 D06 会产生新事件 ID，但业务键不变，不能因此再次拨打。

目前未实现 B 消费器；不能将 outbox 中出现达标事件说成已创建电话任务。`intake.invalidated` 是 A 的更正／复核通知：B 须失效待处理输入、阻止交付，检查当前联系状态并按其停止流程处理。A 不把“本地失效”写成“电话已挂断”，也不会重新交付或召回文件。

## 交接语义

A 在 D06 已保存且按发布规则核验达标后，与结果一致地登记 `screening.passed` 事件。B 接收后创建或关联唯一电话业务任务，但必须重新检查当前版本、权限、已有电话和联系前提。接收达标事件不等于被授权拨号。

P0 路径必须包含 D01—D06 的不可变版本引用。P1 前置筛选导致 D04 未执行时需要另行修订合同与消费逻辑，不能直接绕过当前校验。事件版本防重不能替代电话业务和正在进行的联系防重。

`fixture_only=true` 的样例只供测试使用，不得送入真实拨打路径。来源标识必须保留到下游，不能因为后续真实模型调用就清除上游模拟来源。

## 修改方式

修改模型后，在 `backend/` 执行：

```powershell
uv run python scripts/export_contract_schema.py
uv run pytest
uv run python scripts/export_contract_schema.py --check
```

公共字段变更同步更新接口、样例、前端及 B 消费方。对外兼容性破坏需升级合同版本，不能只改生成文件。

## 搜索适配协议

[search-request.v1.schema.json](search-request.v1.schema.json) 与 [search-result.v1.schema.json](search-result.v1.schema.json) 从 `backend/app/integrations/search.py` 导出，供配置的归一化 HTTP 适配端使用；它们不是新增的浏览器 API，也不代替 A/B 事件。请求、来源过滤、预算、未知结果及厂商扩展见 [研究适配器](../api/search-adapter.md)。

修改 Python 模型后运行 `uv run python scripts/export_search_schema.py`，检查用 `--check`。真实提供者仍未选择或验收；搜索实际来源按执行记录进入 1.1 交接，未执行仍为 null。

## A03 Pi 与 A04 对象合同

[a04-profile.v1.schema.json](a04-profile.v1.schema.json) 定义 A04 的多对象提取输出；[a03-report.v1.schema.json](a03-report.v1.schema.json) 定义按用户范本组织的 D04。六个 a03-tool-*.v1.schema.json 对应受控工具参数，由 `a03_contracts.py` 生成；Pi 不接受材料自行添加工具或加载任意 skill 路径。

变更后运行 `uv run python scripts/export_a03_schema.py` 并用 `--check` 验证，同时更新 HTTP Schema、完整接口草案和前端类型。它们不是新增 A/B 事件版本；事件仍为 1.1，引用新产物精确版本及实际来源。配置和验证边界见 [A03 Pi Agent](../a03-pi-agent.md)。
