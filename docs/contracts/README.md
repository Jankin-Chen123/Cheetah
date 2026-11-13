# A/B 交接合同

当前实现的是合同模型及其验证，不包含初筛执行、持久化事件消费或真实电话功能。

| 文件 | 用途 |
| --- | --- |
| `../../backend/app/core/contracts.py` | Python 合同模型的唯一维护入口 |
| `screening-passed.v1.schema.json` | 从模型导出的 JSON Schema，供前端及其他消费方使用 |
| `day1_screening_passed.example.json` | 明确标注模拟来源的样例，不含真实联系方式，联系授权为空 |

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
