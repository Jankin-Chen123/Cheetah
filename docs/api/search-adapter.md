# 可配置研究适配器 v1

2026-11-14。当前提供有界研究执行和标准 HTTP 客户端，不绑定具体模型或搜索供应商。真实供应商尚未选择或验收；下列协议不是宣称能够直接调用任意厂商的 API。

## 模式与配置

默认 `CHEETA_SEARCH_PROVIDER=disabled`。服务器配置支持 `http_json`，或由受信代码注册的其他适配器。密钥只放本地 `.env` 或部署环境，不进入浏览器、原始材料、错误响应或 Git。

研究是否执行还取决于已发布规则包的 `research_config_ref`：

| 引用 | 行为 |
| --- | --- |
| `unavailable`, version 1 | 不发出搜索请求；后续配置提供者也不会让旧规则开始联网 |
| `bounded-research`, version 1 | 可使用已配置适配器；固定公司／项目问题，每个任务最多 2 次查询，每次最多 5 条结果 |

选择 http_json 时需配置 CHEETA_SEARCH_ENDPOINT（HTTPS），可选 CHEETA_SEARCH_API_KEY（Bearer）。CHEETA_SEARCH_ALLOWED_DOMAINS 默认为空数组 `[]`，表示不按业务域名限制，可检索公开网站；填写非空 JSON 域名数组才收窄范围。没有明确公司／项目名称、查询限额为零或提供者禁用时保存“未执行”与停止原因，不伪造搜索结果。配置格式不合法时任务明确失败。

服务端可下调 research_query_limit、search_result_limit、search_timeout_seconds。查询数硬上限为 2、结果数为 5、单请求超时不超过 30 秒；岗位搜索预算默认 20 次，原子预留。金额和账单仍未知，次数预算不能冒充费用结算。

任务在首次执行前保存查询计划与配置摘要；更改提供者、端点、来源范围或执行限额后，不会悄悄用不同配置继续旧任务。摘要不包含密钥；轮换凭据不会改变规则或材料快照。

## 标准 HTTP 协议

http_json 将 POST 发到配置的完整端点，不跟随重定向。`Idempotency-Key` 为持久化请求 ID（同一任务／查询序号保持不变）；如果设置密钥，再带 Authorization: Bearer。请求体由 [SearchRequest Schema](../contracts/search-request.v1.schema.json) 定义：

```json
{
  "protocol_version": "1.0",
  "query": "\"虚构企业\" company official background 2020-2022",
  "limit": 5,
  "allowed_domains": ["example.com"]
}
```

请求只取简历中明确陈述的公司／项目标签和历史期间，不上传整份简历、候选人姓名或联系方式。标签中的邮箱或明显号码不用于查询。材料文字是查询数据，不能改变 HTTP 方法、端点、来源范围或业务规则。

不限制公开网站范围时，请求中的 `allowed_domains` 为 `[]`。适配端必须将空数组解释为不设置业务域名过滤，并继续阻止本机、私有网段、云元数据地址和非公共 DNS 解析结果；旧版仅接受非空数组的桥接服务需同步更新此合同。Pi 插件使用空 domainFilter/domainPolicy.allow，仍执行其 DNS 和地址检查。

200 响应由 [SearchResult Schema](../contracts/search-result.v1.schema.json) 定义：

```json
{
  "results": [
    {
      "url": "https://example.com/fictional-company",
      "title": "虚构搜索来源，仅供联调",
      "snippet": "Founded in 2010.",
      "published_at": null,
      "assertions": [
        {"field": "founded_year", "value": "2010", "quote": "Founded in 2010."}
      ]
    }
  ]
}
```

published_at 必须带时区，未知为 null；不是从本次检索时间猜测。assertions 可省略，仅支持 registered_name/business/founded_year/project_description；quote 必须出现在原摘要内，value 必须出现在 quote 内，否则不采用该陈述。响应最大 1 MB、至多 5 条结果；程序同时遵守本任务更低的配置限额。

如果选择的供应商不符合此协议，应在受信服务端适配它的请求／响应，不能仅替换 URL 后假定可用。现有项目没有新增代理服务，也没有创建任何第三方账号。

## 自定义适配器

`app.integrations.search.SearchAdapter` 约定 `source_mode`（live/mock）与 `search(query, request_id=...) -> SearchResult`。通过 `register_search_adapter(name, factory)` 注册；注册应放在 API 与 worker 都加载的受信启动模块。不能从简历、网页或浏览器参数加载模块或代码。

source_mode 必须反映实际执行来源。隔离 mock 材料不会发给 live 搜索适配器；测试使用独立 mock 适配器，来源标识贯穿 D04、后续产物与 1.1 达标事件。配置能力标志仅表示适配器已选择，不代表真实供应商已经验收。

## 研究产物与安全边界

D04 保存已声明主体、逐主体执行状态、来源范围、时间、原始摘要证据、来源陈述差异、未知项及停止原因。只得到公司资料时，不会补造项目研究。拒绝私有地址、嵌入凭据、访问令牌参数和 fragment 链接；仅在显式配置域名列表时拒绝列表以外的网站。

搜索摘要全部标为 U（待核实），不自动确认同名主体、历史适用性或个人贡献；多来源陈述不同则分别保留，不虚构一致结论。没有主体核实的 public_web 条件仍为 unknown，不会因“搜到了网页”而自动达标。后续专业核验接口和真实业务效果需单独评审。

搜索请求、预算与已知响应持久化。外部结果未知时进入 reconciling，保留预留额度且禁止通用重试；不会自动再次 POST 搜索。已知结果保存后内部整理失败，可以恢复并复用原响应。若有权威渠道确认迟到响应，内部 settle_search 可登记原请求结果并恢复内部步骤；这不是新的查询。当前未定义供应商通用状态查询端点，不伪造“已核对”。

## 迁移与检查

运行 `uv run alembic upgrade head`，新增 `0002_bounded_research`；不修改已交付的 0001。升级会从既有不可变引用回填已知来源，保留 mock，不给未执行研究或电话补 live。已有产物正文保留。

```powershell
uv run python scripts/export_search_schema.py --check
uv run pytest tests/test_research.py tests/test_migrations.py
```

这些验证使用虚构材料和 HTTP MockTransport／mock 适配器。真实模型与搜索提供者、额度、专业质量及生产部署尚未验收。
