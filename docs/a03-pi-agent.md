# A03 简历背景与专业成果研究 Agent

2026-11-14，分支 `Jankin`。本页记录实际实现与验收边界。提示词与报告结构依据用户提供的 A03 系统提示词 V1.0 和《候选人背景信息与专业成果研究报告 V1.0》；桌面原件没有被修改。原始提示词副本保存于 `backend/agents/a03/resources/a03-source-v1.md`，报告范本转化为 Python 字段模型和五部分 Markdown 渲染器，没有把占位行当作对象数量上限。

## 架构和执行

FastAPI 继续负责账号、权限、规则、任务和产物。Python worker 领取 research 任务后，在已发布规则引用 `pi-research`, version 1 时启动 Node.js 24 的 Pi 研究执行器。它是同一后端的内部执行模块，没有独立数据库、公开服务或浏览器凭据。

Pi 采用 `@earendil-works/pi-agent-core@1.5.2`，由真实的 Pi 循环组织模型消息、工具调用和观察结果；没有自行写一个模拟 Agent 循环。模型通过宿主转接至现有可配置 HTTPS Chat Completions 端点，需支持标准 function tool calls。原先岗位／简历单次提取继续使用原封装。`pi-ai` 用于 Pi 类型和响应流；当前不启用其自动凭据发现或供应商自动重试。

流程：

1. A04 单次模型提取全部声明的公司、项目、比赛、论文、专利、软著、开源、认证，逐字段校验原文引用，生成 D03.research_objects。
2. A03 读取 D03 及绑定规则的 D01，复用原始称谓、期间、描述和成果数据；旧 D03 只有平铺字段时走明确标记的 legacy_fields 输入路径，不声称履历完整。
3. Agent 加载专业 skill，设定对象、目标字段、优先级和理由。
4. Agent 搜索来源、读取正文、观察差异，决定是否调整查询、补充消歧或转向其他目标。计划、调用、观察结果与对话均持久化。
5. 提交逐对象发现；程序检查对象范围、引用、身份线索、时间、个人成果归属和证据种类。
6. Agent 提交结束意图，或程序因充分性、无新增信息、预算、工具异常和时限停止。所有对象进入 D04，包括未执行的对象。程序按范本生成结构化报告与 Markdown，不直接交付未经校验的模型自由文本。
7. 当前初筛仍由 A05 的已发布谓词核验；A03 不评分、不推荐、不拨号。D04 的全部来源和缺口可供下游读取，尚未实现模型驱动的 A05 综合评估。

“单轮”指一次有明确授权和总预算的研究任务，内部允许多次模型决策、搜索和读取来源。结束后不会因为 A05 信息不足自动重新开启第二轮；更正后的显式重算产生新代次。

## 插件复用与选型

开发前检查了 [Pi 官方包目录](https://pi.dev/packages)、[Pi Packages 协议](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md)、[pi-web-access](https://github.com/nicobailon/pi-web-access)、[pi-docparser](https://github.com/maxedapps/pi-docparser) 和 [pi-skills](https://github.com/badlogic/pi-skills)。

| 功能 | 选择 | 原因与范围 |
| --- | --- | --- |
| Agent 循环 | pi-agent-core 1.5.2 | 直接使用 Pi 工具循环，工具与状态持久化由宿主管理；不增加编码 CLI 的文件、shell 和自动扩展发现 |
| 搜索与来源读取 | pi-web-access 0.47.0，经 MCP stdio 调用 | 复用已实现的搜索适配和抓取；npm 当时已发布版本为 0.47.0，仓库主分支的 0.48.0 尚不能安装，故未按主分支版本声明锁定 |
| 文档解析 | 暂保留当前 PDF/TXT 提取；pi-docparser 为后续候选 | 本任务核心是 A03 调研，避免同时改变 OCR、Office 依赖与文件接入范围；扫描件／DOCX 暂不支持 |
| 专业研究方法 | 项目自有四个 skills | 领域规则来自用户材料，通用搜索插件不能替代主体、时间和成果归属判断 |

后续新增通用能力先查现有插件，再核对版本、SDK／后台兼容、来源处理与许可证；适用则复用并固定版本。当前插件 MCP 启动、工具注册和无网络参数拒绝已实际测试，外部搜索提供者尚未验收。未配置第三方账号或读取个人 Pi 登录信息。

## 提示词和工具

专业资源在 `backend/agents/a03/resources/`。运行时使用原始专业提示词、system-v1 执行约定和证据策略；记录完整资源内容的 SHA-256。恢复时资源、端点、模型、来源范围或限额改变会拒绝继续旧任务，不能静默换策略。技能元数据采用标准 name/description/metadata，正文通过受控 load_skill 工具按需读取。

| Skill | 用途 |
| --- | --- |
| evidence-quality | E1/E2/E3/U、原文、主体、期间、冲突和归属；核心策略始终进入系统上下文 |
| company-research | 任职公司和项目，先复用再定向核实，区分历史与当前背景 |
| professional-achievements | 比赛、论文、专利、软著、开源、认证的正式记录和身份 |
| report-handoff | 全对象覆盖、五部分 D04、A05/A06 关键待核实事实和停止原因 |

Agent 只有六个工具：load_skill、set_research_plan、search_public_sources、read_public_source、record_object_findings、finish_research。没有任意文件读取、shell、自动插件下载、电话或外部消息工具。Plugin 提供者、查询数量、代理和凭据不由模型参数控制。

## 输入、输出和证据

D03.research_objects 每条含 object_id、kind、原始 name/period、parent_object_id、facts。每个事实保存 value、quote、status、evidence_refs、source_type。程序核对引用是否出现在材料中及是否包含提取值；这不能证明复杂语义或实体归因完全正确。

D04.structured_content.report 是类型化的完整报告，含系统分配的候选人／关联／岗位 ID、精确 D03/D01 引用、全部研究对象、字段、目标、来源、缺口、问题、执行统计和停止原因。`content_markdown` 同时生成：一、任务概览；二、逐公司；三、逐项目；四、实际声明的专业成果；五、结论、交接、来源和消耗。没有的类型只说明未提供，不创建虚构对象。

每字段并列 A04 原始信息和 A03 公开发现，原始 E2 不被覆盖。程序的保守证据门槛如下：

- E1 必须来自实际读取的来源正文，断言直接摘录支撑引文，资料日期在正文中存在；解释性改写使用 E3。
- 主体确认要求原名加至少一个已有非名称线索有正文依据，如地点、产品或登记标识；仅名字相同不通过。该门槛仍不能替代复杂实体的专业核实。
- 任职期间适用性单独记录 confirmed/current_only/unknown；声称历史适用时，期间与 D03 一致且引用中需有该期间。
- 缺失引用、假引文、摘要冒充正文、无日期、冲突、个人贡献／成果归属自动认领会降为 U 并保存校验说明。E3 需有公开引文或实际存在的 A04 字段依据。
- 对象的核心字段、目标和身份未充分支持时，不因模型说“完成”就标 completed；其余对象保留未执行或待核实。查不到不等于经历虚假。
- 搜索只允许已有对象名及必要职业线索；默认拒绝候选人姓名、邮箱、明显电话号码及新造对象。不发送整份简历给搜索插件。

程序验证引用与结构，不保证来源说法真实，也不能完全检测语义误解、同名误归、来源日期与事实日期的差异。真实供应商和经授权样本上的专业准确性仍需独立评估。

## 配置与启动

先按 README 初始化 Python 环境、数据库和账号，再安装 Node.js 24 依赖：

```powershell
cd backend/agents/a03
npm ci --ignore-scripts
npm run check
npm test
cd ../..
uv run alembic upgrade head
uv run python -m app.worker
```

新增迁移 `0003_pi_research`，保存 research_runs 和 research_actions；应用启动仍不自动建表。旧 unavailable/bounded-research 规则保持原语义，新 Agent 需要显式发布 pi-research v1，不会悄悄升级已绑定的旧任务。

| 配置 | 含义与默认 |
| --- | --- |
| CHEETA_MODEL_ENDPOINT / MODEL_NAME / MODEL_API_KEY | 保留现有配置；Pi 路径要求支持工具调用，不支持时明确失败，不降级固定脚本 |
| CHEETA_A03_WEB_BACKEND | disabled（默认）、normalized 或 pi_web_access |
| CHEETA_A03_PLUGIN_PROVIDER | 当前集成 brave、tavily、exa，默认 brave；显式单提供者，不自动选择免费或其他账号 |
| CHEETA_A03_PLUGIN_API_KEY | 所选搜索提供者凭据，仅本地／服务端配置，不放浏览器或 Git |
| CHEETA_SEARCH_ALLOWED_DOMAINS | 允许公开来源的 JSON 数组；未配置时不联网 |
| CHEETA_A03_MAX_TURNS | 最多 16 个模型回合，可配 1—40 |
| CHEETA_A03_MAX_SEARCHES / MAX_PAGES | 每候选人最多 12 次查询／12 次页面读取，可下调 |
| CHEETA_A03_PER_OBJECT_SEARCHES | 每对象最多 3 次查询，可配 1—8 |
| CHEETA_A03_MAX_SECONDS | 一次研究任务 300 秒，恢复也沿用原起点 |
| CHEETA_A03_NO_PROGRESS_LIMIT | 连续 2 次无新增有效来源时停止 |
| CHEETA_A03_NODE_BINARY | node；服务端可指定 Node.js 24 绝对路径 |

normalized 复用现有搜索协议，还需 CHEETA_A03_FETCH_ENDPOINT。宿主 POST `{url,allowed_domains}`，端点返回 `{url,text,source_date}`；必须返回实际来源原文，不能返回模型总结冒充原文。端点需 HTTPS、支持 Idempotency-Key，服务端自行执行 DNS／来源限制和访问控制。响应上限 1 MB，正文保存上限 60,000 字符。

pi_web_access 启动独立 MCP 子进程，只传入任务所需临时配置，不读取个人 ~/.pi 凭据或浏览器 cookie。配置固定搜索提供者、允许来源、同源重定向和禁止第三方托管抓取后备；抓取用 raw 模式保留原文，不触发 GitHub 自动克隆或模型生成的网页回答。插件自己可能有内部请求行为，工具次数不是供应商账单或精确底层 HTTP 次数，金额保持 null。

未配置、无对象或 mock 材料不能进入 live 研究时，生成明确的未执行报告。live 路径的专业模型和搜索供应商未真实联调；不会因本地测试而宣称已联网。

## 恢复和更正

每次模型／外部工具请求先提交持久化意图，预留模型调用／Token 或查询次数预算。已知响应先保存再执行后续整理；Pi 对话按最终消息保存。重启时恢复尚未登记完成的工具结果，已知查询不会再次发出。结果不明转 reconciling，保留预留额度，禁止通用重试；不能把重启当作新的查询授权。

对象事实可通过原更正入口更新 `/research_objects/{object_id}/name`、`/period` 或 `/facts/{已有字段}`；值仍为带 status/quote 的 Fact。只允许已有对象，不允许修改权限、ID 或工具。旧 D03/D04 及受影响下游失效，新版本保留其他对象和原证据链，之后显式 research→screening 重算。未提供删除／新增对象的公共更正命令。

## 实际验证

使用实际安装的 Pi npm 包和独立 Node 子进程，模型／搜索响应来自虚构 HTTP transport；没有真实简历、搜索账单、真实供应商调用或电话。

- 多对象提取与引文校验；自设目标、观察结果后修改查询、读取正文、报告五部分与全部对象覆盖。
- 假引文、摘要、日期与身份依据不足降为 U；个人贡献不自动确认；搜索联系人和新造主体被拒绝。
- 模型轮数上限、禁用提供者、未知查询不重试；原已知响应后中断恢复时不重复查询。
- 对象事实更正、原版本失效、其他对象和来源保留；统一迁移升级／降级／再升级。
- Pi TypeScript 检查、真实插件 MCP 启动和参数合同检查；没有据此推断真实搜索提供者可用。

完整工程回归使用本机 PostgreSQL 17.6。真实业务效果、跨语言网络与容器部署、Linux CI、外部提供者和专业核验未验收。线上试用前需用经授权样本比较对象提取覆盖率、同名误归率、证据支持率、未知保留、耗时与费用；格式和自动化通过不能替代这些指标。

本轮实际结果：PostgreSQL 全集 79 项通过；Pi 的清洁 npm ci、TypeScript 检查和真实插件 MCP 检查通过；运行依赖 npm audit 未发现已知漏洞。前端静态检查、构建和原有 12 项演示测试通过，仍有既有包体积提示；没有将页面演示视为业务联调。Ruff、四个 Schema 导出器、虚构样例、本地文档链接及 Git 差异空白检查通过。提供者未返回有效 Token 用量时报告保持 null，预算可以按预留量保守记账，另列 charged_tokens，金额仍为 null。
