# Goal 本地集成增量（进行中）

A08指标门禁增量：D09 content保留上游indicator_evidence；若任一记录INSUFFICIENT而模型给对应维度分数，内部步骤拒绝MODEL_OUTPUT_INVALID，需提取复核后显式重算，不自动给零分。SUFFICIENT不强迫评分。旧无矩阵产物仍按原暂定合同处理，不代表新版A08正式验收。前端指标预检表已接代码，运行验证范围见A08接入差异。

A07指标矩阵增量：D08通用content新增indicator_definitions与indicator_evidence。后者逐项保留dimension_id、真实字段路径indicator_ref、answer_ids、SUFFICIENT/PARTIAL/INSUFFICIENT预检、非空sufficiency_reason和gaps；仅绑定已确认案例标准时要求完整覆盖。充分性不是分数，引用存在不等于语义支持。新evidence_direction缺省UNCLASSIFIED，兼容旧UNKNOWN。外层HTTP和通用OpenAPI产物content仍不变；该增量未完成Final Package全部合同。

2026-11-14 A07 Final Package接入增量：产物通用content内D08 facts新增可选evidence_kind（PAST_BEHAVIOR/SITUATIONAL/FACT_ONLY/GENERAL_CLAIM/UNKNOWN）及evidence_direction（SUPPORTING/LIMITING/NEUTRAL/UNKNOWN），旧内容缺省UNKNOWN；精确quote/answer_id校验保持。D08 preparation_refs仅为准备稿引用，不证明实际执行版本，extraction_limitations在D09内部继承并可读展示。通用产物HTTP外层与OpenAPI路径不变，仍使用不透明content对象；未宣称完成新版A07指标矩阵或正式许可交接。

## 面试后处理增量 2026年11月14日

暂定业务口径见 [面试后处理规则](../面试后处理暂定业务规则_V0.1.md)。D08/D09/D10 同步与 worker 共用中文业务指令，产物 provenance.prompt_version 记录 post-interview.v0.1。此次指令替换已通过10项相关隔离测试，尚未以真实模型专业样本验证语义质量；不能将程序结构验证视为业务准确率证明。

持续 worker 每轮在事务中核对 ended 案例，按 D08→D09→达标 D10 登记持久化步骤。无回答、仍在请求停止、更正待重算或已有失效历史结果时不自动重启该阶段；失败步骤不自动换 revision 重试。步骤业务键和案例行锁防止重复轮询建重。进程重启后继续读取已提交产物及任务，D09 不推荐/信息不足不生成 D10。该调度不批准、不导出、不重新拨号；更正及标准变更后的重算继续显式操作。

D08 的事实必须包含非空陈述、非空原话及存在的回答 ID；原话须为该回答的精确子串。coverage 按成功提取的 responsibility/results 事实标记 full 或 partial，只说明提取覆盖，不代表事实已独立核实或所有岗位维度已覆盖。

D08—D10 来源继承从案例 snapshot.source_modes、回答 source_mode 和上游产物 provenance 合并，内部 real 映射为 HTTP/产物 live；缺失来源保留 unknown，不默认人工或真实。fixture_only 沿案例和上游产物保留，任一虚构来源继续包含 mock。模型执行的 source_mode=live 与输入来源分别记录，不覆盖输入性质。Markdown 对虚构/模拟和来源未确认分别追加程序生成提示，不依赖模型自行保留。

D09 在现有内容上保留上游 gaps/conflicts 字符串数组；D10 的 unknowns 合并模型输出及这两组上游限制并去重，避免推荐时遗漏待核实项。推荐亮点拒绝空白文本及引用空白回答。引用存在仅证明来源可定位，不证明模型概括必然准确，仍须逐版本人工审核。

`POST /calls/{case_id}/evaluation-standard` 接收 `expected_revision`、`standard`（a02.v1）、`threshold`（1—10）及 `report_template_version`。要求登录、Origin/CSRF、案例归属、岗位匹配和已确认标准；服务端将 confirmed_by 设为当前账号。返回 revision 与 standard_version；无归属404，版本或业务前提冲突409，结构不合法422。重复旧 revision 不重复执行，响应不明时读取案例确认。既有标准只能绑定更高 version；更改权重、锚点或门槛均应升版本。

标准和评估模板快照保存在案例会话中，旧绑定进入 evaluation_binding_history。更换绑定使 D09/D10 及其审批失效，保留 D08，不触发拨号、重算或交付。D09 使用 score_scale=1-10、整数分与原权重；旧五分制默认及快照哈希兼容。十分制综合 score 为加权十分制分值；total_score 为百分制总分，未完整评估时均为 null。dimensions 含 label/indicators/scoring_anchors/weight_percent/weighted_score，折算为实际分÷量表上限×权重百分数，未评估折算为 null；scored_weight_percent 单独记录已评估权重，不重分配缺失权重。

本地工作台提供动态维度表单、五档行为锚点、来源引用、版本、推荐门槛和明确确认勾选；提交后由服务端执行上述绑定校验，并可查看绑定历史。评估表展示六列业务字段及证据依据。岗位标准自动生成及面试前自动绑定尚未完成；表单不预填未经确认的专业标准，来源引用是否正确仍由审核者核对。

本地工作台提供 D08 原话和回答引用、D09 逐维依据及缺失冲突的可读展示，并保留原始结构查询。D09 默认仍为零至五分演示量表；显式绑定 A02 后按十分制解释，历史分数不自动换算。

验证：后处理相关19项隔离测试通过，前端静态检查、类型检查及构建通过；浏览器视觉验收及真实业务样本质量评审尚未完成。

浏览器增量：在5174本地页面使用独立虚构批次，完成登录、导入、动态维度与五档锚点填写、明确确认和标准绑定，服务端返回revision=3/standard_version=1，页面显示服务端确认人，无pageerror。截图与结果存work/postcall-standard-browser*；报告审批下载完整链仍未因此通过。修复旧请求迟到401可能清空新登录CSRF的竞态，新增回归测试；前端14项测试、静态检查和构建通过。

正式 `#live` 工作区已复用标准确认表单及 D08/D09 可读展示，保留原始内容与引用；退出使用 POST，首次结束后在自动报告步骤间继续轮询。该入口本轮静态检查与构建通过，完整浏览器审核下载及更正流程仍待验证。

正式工作台浏览器补证：独立虚构案例回放前述真实模型输出（provenance.browser_test_replay=true），完成未批下载禁用、批准具体v1、下载1471字节Markdown、保存回答更正、旧D10/审批失效及刷新恢复，无pageerror。记录为work/postcall-report-browser-result.json及两张截图。此证据验证持久化接口和页面版本门禁，不代表从真实通话自动生成的连续闭环，也不是专业内容批准；测试审核意见明确仅用于流程验收。该次全后端131项测试及OpenAPI/内部合同快照通过；全局ruff仍报告通话调优区域router.py长行、test_model_first_dialogue.py格式问题，未修改这些通话内容以通过检查。

当前增量沿用统一 `/api/v1`，原 `openapi.v1.json` 仍是待冻结的完整平台设计稿。新增本地验收 DTO 与草案的 Call/Report/Session 尚有差异，不能把它们当作原草案全部实现。精确机器合同见运行时 `/openapi.json`；下一轮须同步静态合同与消费方。

已实现本地接口的独立生成快照见 [openapi.goal-local.json](openapi.goal-local.json)。在 backend 执行 `python -m uv run python scripts/export_goal_openapi.py --check` 校验与代码一致；它不覆盖原平台设计稿，电话列表/详情、产物元信息及活动/失败步骤已有显式读 DTO；会话与各D产物内容仍由独立业务模型校验，其他响应类型继续审计。

新增行为：

| 路径 | 实际范围 |
| --- | --- |
| POST /auth/login、GET /auth/me、POST /auth/logout | development 本地账户、持久化 Cookie 会话、Origin/CSRF；尚非完整平台账户权限 |
| POST /dev/fixture、POST /dev/screening-passed | 明确虚构、测试规则、mock 来源的合同消费，唯一电话业务任务 |
| GET /calls、GET /calls/{id} | 按机构及本地 owner 读取持久化任务、问答与产物；列表分页待完善 |
| GET /calls/{id} 的 failed_tasks | 最近 20 个失败内部步骤，含 input_revision/error_code/retry_count；页面显式人工重试，服务端复核版本、停止与上限 |
| GET /knowledge/entries | 开发管理分页，含未审核素材和出处；structured_only=true 只列结构化方法 |
| GET /knowledge/search | 标签匹配；默认已审核启用且最新文档版本，显式 preview 隔离 |
| POST /knowledge/{id}/curate、/enabled | 完整方法字段人工整理/批准及启停；批准内容禁止原地修改 |
| POST /calls/{id}/outline、/followup | 检索后模型生成并校验方法与回答引用；缺配置明确失败 |
| POST /calls/{id}/answers | 实际文字回答、证据 ID、时间与问题关联持久化 |
| POST /calls/{id}/answers/{answer_id}/corrections | 新回答版本与历史、同事务下游失效 |
| POST /calls/{id}/cancel | 请求停止，状态仍 requested |
| POST /calls/{id}/mock-start、/mock-confirm-stop、/mock-callback | 显式开发模拟；尝试防重、序号与终态保护；不调用真实号码 |
| POST /calls/{id}/minutes、/evaluation、/recommendation | 返回 202 持久化模型任务；D08—D10 独立版本、实际回答引用、演示规则与达标门禁 |
| POST /reports/{id}/review | 当前有效达标 D09 与具体 D10 version/revision 校验、审计 |
| GET /reports/{id}/export?version= | 当前有效批准 D10；X-Export-Request-ID 必填，审计去重 |

写操作均检查登录、Origin 与 CSRF。机构与操作者从会话取得；跨机构/无 owner 归属对象返回 404。新增命令目前以 revision/业务唯一约束为主要防重，尚未完整实现通用 Idempotency-Key 协议，不能宣称满足草案全部幂等条件。

模型命令返回 202，后台 worker 使用短事务领取、事务外模型调用、短事务验证输入 revision 后保存；GET /tasks/{id} 查询状态。每 case 请求次数先独立持久化预留，失败也计数；running 中断超时标记需核对，不自动重试。停止或输入更正后旧结果不得落库。已实现请求/输出 token 上限，尚非按账单金额精确计费的预算。真实文字及合成音频已有小规模证据，充值后 qwen-plus 文字权限已恢复，最新推荐、不推荐和信息不足链已有实际模型证据；具体范围见验收说明。

所有新增输出保留 fixture/mock 继承来源。原始 DOCX、全文和本地库不进入公开测试。现有测试与 PostgreSQL 检查范围见 [Goal 验收说明](../Goal_验收说明.md) 和本地 `work/goal-progress.md`，不代表真实电话或业务质量通过。

开发样例POST /dev/fixture接受{batch}（1—64个ASCII字母数字、下划线、短横线），默认default；同批次复用，独立验收请填写新批次。仍仅development且检查登录/Origin/CSRF，所有内容保持虚构来源。


保存新增实际回答与使已有D08—D10失效在同一事务完成；旧批准不再用于导出，D07提纲保留。更正仍保留新版本与历史。



新增前置确认：GET /calls/{id}/briefing返回服务端岗位/薪资/公司材料及sha256；POST /calls/{id}/preflight携带expected_revision/action/statement，interest另含interested、mock_email另含email/request_id、confirm另含material_sha256。均检查会话/归属/CSRF，模拟邮件限development+fixture+.test；status=simulated不代表实际发送。新案例session.preflight_required阻止未确认普通回答，历史案例不补写同意。页面入口已接，真实邮件未接入、端到端验证待完成。

候选人邀请底层（尚未完成候选人页面）：POST /calls/{id}/invitation，expected_revision/action=issue或revoke/lifetime_seconds(60—86400，默认3600)。沿用登录、CSRF、归属及版本锁。仅issue响应返回原始token且no-store，数据库只存sha256；重发使旧令牌失效。尚未挂候选人消费路由，不能称受限链接完整可用。

GET /candidate/calls/{id}接受Authorization: Bearer邀请令牌（不接受URL令牌），返回受限材料、意愿确认状态、确认后当前问题及revision/status；不返回内部产物、回答、检索快照或令牌hash。no-store/no-referrer。消费写接口与网页语音待接。

POST /candidate/calls/{id}：Bearer+Origin、expected_revision、action(interest/confirm/answer/stop)、statement；interest需interested，confirm需material_sha256（GET返回）。回答沿用前置门禁与同事务D08—D10失效，stop程序直接结束并确认模拟尝试；不提供报告审批能力。候选人页面与动态追问自动入队仍待接。

候选人音频转写开发接口：POST /candidate/calls/{id}/transcription，Bearer+Origin，expected_revision、pcm_base64（16kHz单声道S16LE，最多10秒）。前置确认后调用真实模型仅转写，返回text/model/source_mode/revision，候选人确认后另存回答；预算预留持久化，迟到停止/版本变化409。尚未完成并发防重及页面接线，不作为语音验收。

播报选型修正：通用omni对话输出未逐字朗读，已加不一致拒绝。后续专用Qwen-TTS Realtime按官方客户端事件实现：session.update(voice/mode/language_type/response_format/sample_rate)，input_text_buffer.append(text)，commit/finish。官方依据：https://help.aliyun.com/zh/model-studio/qwen-tts-realtime-client-events 。尚未核实当前业务空间TTS模型权限，不将官方支持当本项目已接通。

TTS现行官方接入纠偏（2026-11-14）：https://help.aliyun.com/zh/model-studio/realtime-tts-user-guide 当前推荐qwen-audio-3.1-tts-flash、longanhuan_v3.1，业务空间wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference，Python client.audio.tts.connect/send_text/flush/stop/audio_chunks。与旧Qwen-TTS Realtime的session.update协议不能直接混用。后续核对qwen-audio-tts-client-events并沿现有websockets实现，避免无必要引入SDK；未核实权限前不声称可用。

POST /candidate/calls/{id}/speech接受expected_revision，Bearer/Origin/前置确认后只朗读服务端current_question；同版本缓存ModelStep音频，不允许候选人提交任意朗读文本。返回pcm_base64/sample_rate/model/source_mode，停止或版本改变拒绝迟到结果；执行中或失败不得直接重发。专用TTS原业务空间实际短句合成及ASR回读一致已验证，候选人HTTP播放仍待。

候选人WebSocket：/api/v1/candidate/calls/{id}/stream，Origin白名单，首条JSON token/expected_revision（10秒内），ready后发送16kHz单声道S16LE二进制帧，每帧最多32768字节、总10秒；文本finish提交。回传transcript_delta、transcript_completed(text/transcription_task_id)，异常通用error并保留需核对任务；GET候选人当前版本可恢复完成草稿。真实模型经Vite代理已验证，浏览器采集仍待验收。
# 2026-11-14 自动网页语音通话增量

候选人 `/candidate` 改为通话房间，点击一次接通并授权麦克风后自动播报、流式转写、停顿提交、等待持久化 worker 追问并继续播报。字幕辅助查看，不要求逐轮录音、上传、保存。静音只控制采集，挂断立即释放本地音频并向服务端提交停止。当前是轮流说话，尚不支持在 AI 播报时语音打断；可随时点击挂断。

- `GET /candidate/calls/{id}` 新增 `spoken_prompt: string|null`：服务端根据意愿/材料确认阶段生成开场白、材料说明或当前面试题；停止后返回结束文案。该字段不是模型生成结果。
- `POST /candidate/calls/{id}/speech` 保留 `{expected_revision}`；现在允许意愿及材料确认阶段播报服务端 `spoken_prompt`，仍使用真实专用 TTS、任务防重、预算及版本复核，停止后禁止合成。
- WebSocket `/candidate/calls/{id}/stream` 允许意愿确认阶段使用；Origin、邀请、版本、停止、预算、唯一转写任务仍校验。PCM 上限由 10 秒增加至 120 秒（3,840,000 字节），输入超时125秒、总超时150秒。旧分段 HTTP 转写接口仍限制10秒。
- `POST /candidate/calls/{id}` 新增 `action:"voice"`，必须提交当前版本、已完成的同任务转写 ID，以及与原转写完全一致的 `statement`。服务端判断明确意愿：肯定进入材料说明，再肯定才确认材料并进入面试；否定结束；含糊再次确认。语音来源保留 ASR 任务引用。意愿判断采用保守规则，不宣称通用语义模型。
- 正式回答自动保存并在同事务登记追问任务；证据标记 `submission_mode:automatic_voice`、`candidate_confirmed:false`，不能把自动转写称为候选人逐字人工确认。原手动确认接口兼容保留。
- 页面约1.5秒静音判定交棒；单轮最长2分钟。断线后只恢复已持久化完成转写；结果不明暂停并要求核对，不自动重发音频。浏览器刷新需再次点击恢复通话，遵循浏览器音频授权。

隔离测试覆盖意愿模糊/同意/拒绝、未确认不泄露正式问题、前置阶段流式转写、同版本重放409、自动回答证据来源、追问单任务和挂断。浏览器麦克风端到端验收仍待实际操作，不以单元测试替代。


## 候选人邮件与自然对话增量（2026-11-14）

`POST /candidate/calls/{case_id}/briefing-email` 使用候选人邀请 Bearer 和 Origin 校验。请求 `{email, request_id, consent:true}`；request_id 为8—64位ASCII字母、数字、下划线或短横线。同请求重复返回原 task_id/status/error_code；不同收件人或材料复用请求号返回409。需已表达岗位兴趣、有效邀请、非停止场次。未配置SMTP返回503 MAIL_NOT_CONFIGURED，不产生模拟发送。每场最多三个请求，已有待处理或失败邮件时禁止另建，结果不明不自动重发。返回 queued/running/completed/failed；completed仅表示SMTP接收，不证明最终送达。相同请求可查询处理结果。虚构材料邮件显著标记测试来源。

发件使用CHEETA_SMTP_HOST/PORT/USERNAME/PASSWORD/SENDER，默认465隐式TLS。只需配置一个发件服务，收件地址支持常见邮箱；尚未配置或实际投递验收。密码仅本地.env。

正式对话每轮调用模型理解；知识检索为空不阻断追问，method_entry_ids可为空，非空仍校验真实引用；追问次数作为模型上下文约束，不跳过理解。停止和时长仍由程序执行。双轨字幕独立保留；AI字幕在音频播放开始时整段显示，没有逐字时间戳同步。


后续修复：speech请求新增farewell布尔值，默认false；终态只允许farewell=true播报固定结束问候，不恢复收音或业务。TTS响应timings为可空对象，包含first_audio_ms/total_ms；均为服务端调用耗时，不含浏览器请求及解码。单次真实龙天短句验证首音频1453ms、合成结束2297ms、音频长3.57秒，不代表长段或端到端耗时。候选人预填邮箱并明确勾选授权后，有意愿时自动提交邮件；未配置发件服务仍503，页面显示真实状态。可以继续识别为明确肯定。


## 流式语音与不中断澄清（2026-11-14）

新增POST `/candidate/calls/{case_id}/speech-stream`，请求复用expected_revision（preview/farewell不用于该入口）；校验邀请、Origin、版本与非终态。响应application/x-ndjson，逐行发送`{type:"audio",pcm:"base64 PCM16LE",sample_rate:24000}`，结束`{type:"completed"}`；生成失败发送`{type:"error",code:"SPEECH_UNAVAILABLE"}`。不缓存音频；同revision重复请求409 SPEECH_REQUIRES_RECONCILIATION，防止结果不明自动重试。前端边收边排程播放，打断时取消请求及全部已排程片段。语音服务暂时失败时保留文字与麦克风，不伪造语音成功。

模型输出非法或网络失败时，现场追问保留原回答并使用程序澄清继续对话，后台保存degraded_reason/generator_kind，不当作真实模型理解成功。历史失败的pending对话读取时可转为澄清，原失败任务保留；不重新提交回答、不自动重试外部请求。候选人明确停止、时长等既有程序边界仍执行。预留自定义音色配置TTS_CUSTOM_VOICE_ID/LABEL与TTS_MODEL，模型必须与服务商创建该音色时的目标模型一致；本轮未创建或试听自定义音色。

本机发件服务已配置并验证SMTP加密登录；仅向用户自己的邮箱发出一封无候选人数据的配置测试邮件，SMTP已接收，最终送达待用户确认。授权码仅本地.env，公开文档不含凭据。

本轮真实接口证据：通过5174代理请求speech-stream，第一条audio约735ms，最终completed；这不等于浏览器实际出声延迟。独立短句语音服务首段562ms、整段3625ms，流式无需等待整段。独立模型对姓名类输入约969ms返回有效reply，非完整面试链耗时。SMTP测试邮件已被服务器接收，送达仍须收件人确认。后端104项测试通过，前端静态检查和构建通过；浏览器真实麦克风及自定义音色尚未验收。


### 对话根因修复与实际边界（2026-11-14）

两张用户测试截图中的通用澄清为程序降级：对应conversation的MODEL_RESPONSE_INVALID、followup的MODEL_OUTPUT_INVALID，不代表模型认为候选人表达不清。启用供应商JSON对象输出模式，输入明确区分output_schema与输出示例；当前轮已知的证据ID、维度、空方法引用在模型省略时由服务端附加，并记录server_attached_fields，非空未知引用仍拒绝。模型失败提示改为说明系统处理问题，不把技术故障归因候选人。

知识检索当前为标签过滤排序，最多8条（非语义向量检索），正式库要求approved/enabled，预览保留来源；现场模型每轮接收近期8轮回答、岗位材料、提纲问题及可选方法，决定是否使用方法，无匹配可正常生成。不宣称已训练LoRA或达到通用聊天产品质量。启用JSON模式后真实模型在无知识材料的隔离虚构场次正常追问、无degraded_reason；完整语音体验未验收。

有的/有的有的支持明确肯定；能不能结束面试啊等语气词支持程序优先停止，完整复合请求回归通过。结束语说明招聘方确认后续环节，内部报告不自动对外发送。岗位介绍增加简短职责；已授权邮箱在岗位介绍及继续确认之后自动发送，界面轮询同一防重请求确认SMTP接收或未知结果，再进入正式提问，不自动重发。

当前主动结束仍为模型action=end（根据覆盖情况的提示词决策，并非硬性证据充分性认证），或程序时长/轮数边界、候选人明确拒绝/结束。默认60分钟/30轮，可有场次显式策略。模型异常本身不应结束面试。


### 开场顺序与对话测试增量（2026-11-14）

候选人POST动作增加briefing_presented，要求已表达求职意愿，递增revision；preflight读模型增加briefing_presented。候选人页在岗位介绍播报完成后处理已授权邮件、显示发送状态，然后提交briefing_presented，下一轮才询问是否继续。邮件无授权/未配置/失败如实显示，不伪造发送成功。已有确认场次与播报中提前答复保留恢复兼容分支。

开场模型返回intent（interest_yes/interest_no/confirm_yes/question/unclear）与reply；只在明确肯定/拒绝时更新意愿；有意愿且已介绍时才可由模型确认开始。问题、姓名、自我介绍、犹豫不自动授予面试授权。补充按阶段的回归测试。

正式对话改为明确中文的回答优先指令，最新话语独立输入；当前轮关联由服务端维护。模型未验证引用被移除并记录metadata_adjustments，不充当事实证据；具体报告的引用/原文和审批门禁未放宽。完全重复旧问题时转开放补充，generator_kind=program_topic_transition，不冒充模型原文。语义重复、已回答事实的记忆、单次回复多个问题、长尾时延仍需改进，不因结构检查通过而宣布真人体验达标。


## 火山方舟、先理解再检索与工作记忆（2026-11-14）

### 火山语音适配增量（2026-11-14）

语音提供方通过 `CHEETA_VOICE_PROVIDER=bailian|volcengine` 选择。火山独立凭据为 `CHEETA_VOLC_SPEECH_API_KEY`，方舟文本 Key 不用于语音鉴权。火山使用流式识别2.0与语音合成2.0，沿用现有候选人 WebSocket、双轨字幕和 NDJSON PCM 播放接口。音色目录随提供方切换，包含 Vivi、小何、团子、云舟、小天、刘飞六种2.0音色；旧场次保存的异提供方音色在读取时映射至当前目录首项。自定义音色可通过既有 `TTS_CUSTOM_VOICE_ID/LABEL` 选择，火山复刻资源默认 `seed-icl-2.0`，须提前取得有效音色 ID。

火山适配已覆盖分块首音频、协议校验、增量转写、完成事件及独立凭据测试。浏览器本地交棒静音阈值由1.8秒缩短至1.2秒，减少约600毫秒固定等待，也会更早截断长停顿。语音 Key 配置并开通后已切换本地运行配置。六种音色真实合成成功；通过5174代理的候选人试听接口成功，单次首音频1188ms；合成测试音频经候选人WebSocket入口真实识别成功，收到8次增量转写及最终结果。批量音色测试首音频约2.5至11秒，存在长尾；这些结果来自合成音频，真人浏览器麦克风和实际出声时延仍待验收。缺少凭据时明确失败，不自动跨提供方回退。

本地已配置TEXT_PROVIDER=ark，ARK_MODEL=doubao-seed-2-1-lite-260915，关闭深度思考；ARK_EMBEDDING_MODEL=doubao-embedding-vision-251215，调用/embeddings/multimodal的文本输入。Key仅本地.env；百炼ASR/TTS配置独立保留。不增加SDK或服务，不修改公共交接事件合同。统一文本调用入口保留原Python导入路径以兼容现有D07—D10消费方；Ark不可用时明确记录错误，不悄悄切回百炼。

打开DIALOGUE_UNDERSTANDING_ENABLED后：模型先识别意图和上下文，构造完整检索查询。岗位反问、解释、更正等可直接回应，跳过检索和第二次生成；项目经历、归因、职责边界等专业追问进入混合检索。检索先过滤启用/审核/版本/冲突与预览权限（不再用固定标签截前8条），当前候选池上限100。关键词词项重合与真实向量余弦结果经RRF融合，低相关不塞入，最多返回3条。当前余弦门槛0.35为工程初值，未做业务大样本校准。

向量缓存以模型/地址/文本摘要为键，只存向量，不存候选人原文；文档改变会生成新缓存。源材料资格在读取与结果提交时重新检查，缓存不赋予审核权限。向量服务失败标记lexical_degraded及error_code，继续模型对话，不冒充语义成功。`uv run python scripts/warm_method_index.py --preview`只在development可用，本机预热17条符合筛选条件的方法，未批准或修改知识内容。

工作记忆按key增量更新，最多20项；单轮最多3项更新。每项需要已知answer_id及逐字原文quote，无法核对的摘要不保存；未知不推断为没有经验，事实更正替换对应旧值。人工更正清空旧记忆供重建。生成模型仅接收精简方法摘录；短方法别名映射回真实引用，未验证引用不会成为证据。生成失败/完全重复回复仍保留明确的程序来源。

候选人decision_task新增可空phase（understanding/retrieval/responding/completed），页面按阶段提示等待。任务持久化timings中的understanding_ms/retrieval_ms/response_ms/total_ms以定位长尾，均为服务端阶段耗时，非浏览器实际出声时间。模型慢响应不再仅因60秒页面轮询阈值而中断对话。知识库、事实和版本审批边界未放宽。

本轮真实验证：Ark文本及2048维向量均可调用；同义表达的低词项重合查询命中个人贡献方法；17条真实本地方法的隔离复制库完成“理解→混合检索→模型追问”，无降级。D08/D09真实模型调用成功；样例D09不符合推荐门槛时D10被CURRENT_ELIGIBLE_INPUT_REQUIRED阻断，未批准/导出/发送报告。语言矩阵、连续对话、语音HTTP原始记录仅work/。不能把条件检查通过当成对全部自然语言或真人麦克风体验的保证；复杂检索轮次仍有数秒至十余秒时延，知识相似度阈值与回复冗长度还需持续校准。

### 面试问题复核增量（2026-11-14）

录音转写接口与实时WebSocket均跟随VOICE_PROVIDER，火山配置下通过火山识别。正式追问接收已核对来源的完整累积工作记忆；无相关知识且理解阶段已给有效回复时直接复用，省去二次生成。自然语言理解支持stop意图，常见明确停止仍由程序优先执行。D07两种生成入口允许知识库为空，method_entry_ids允许空列表，仍要求有效上游材料、岗位标准及非空引用真实性。

GET候选人状态发现当前revision的转写任务failed时，保留原失败任务与审计引用，递增场次revision，允许下一次新录音；不复用失败结果或再次提交旧回答。running任务与已完成任务不按此处理。页面实时转写失败后核对状态并恢复聆听。中断任务恢复使用started_at或registered_at；转写的恢复等待至少700秒，避免回收仍在进行的10分钟回答。

farewell=true仅允许已结束场次播报固定问候，不依赖已结束场次随后因报告处理变化的revision；普通语音仍执行版本校验。拒绝岗位与结束正式面试使用相应简短告别。语音介绍中提前肯定保留求职意愿，介绍和邮件步骤完成后再次确认，防止越过开场顺序。

24项表达矩阵、8轮连续文本对话与5段火山合成测试音频经5174候选人接口的识别/意愿/解释/结束闭环已运行。五段音频测试未发送岗位邮件；邮件发送时机、防重、SMTP未知结果等由回归测试覆盖，既有单次SMTP接收证据仍有效。实际真人麦克风与回声未验收，模型回复仍存在长尾和质量波动。完整核对见[AI面试修复验收记录](../AI面试修复验收_2026-11-14.md)。

### 推荐报告 Word 导出

`GET /reports/{report_id}/export?version=N&format=docx` 返回可编辑Word，`format=markdown`为默认兼容格式。二者复用对象归属、有效上游、指定内容版本与批准检查；均要求`X-Export-Request-ID`，Word下载审计为`word_download`，Markdown为`markdown_download`。下载不等于外发。客户文件仅使用已保存的content_markdown，不序列化内部评分、EV及审批元数据。旧批准报告不会因新模板实现而自动改内容。

新D10在第一部分匹配线索后增加第二部分职业资料，从upstream_content.D03读取明确的profile、education、employment字段；employment逐条保留period/company/position/department/reports_to/team_scope/responsibilities/achievements，不推断年限、日期、任职或离职原因。没有结构化任职则明确待补充。该字段适配尚不代替完整A09资料共享许可合同。

### 候选人逐项处理许可与会话交接

`POST /candidate/calls/{case_id}/processing-permissions` 使用候选人邀请Bearer、Origin校验及expected_revision，请求purpose为formal_interview/transcription/extraction/evaluation之一，authorized为布尔；响应为当前候选人会话视图（新增processing_permissions状态映射）。服务端生成receipt_id、时间、policy_version和历史，不接受客户端自填审批人或许可时间。撤回使D08—D10及旧批准失效，当前revision改变使迟到模型结果不能落库。候选人界面逐项同意后才开放接通，撤回时停止页面音频采集；此许可不包含向客户分享或发送邮件。

候选人提交的回答记录actor_type、服务端turn_id及选题时execution_ref。结束后限定案例调度从实际回答和许可回执生成a06_session，再执行身份、D07/D02版本、原文和轮次校验。意愿确认不替代处理许可，事后补的正式面试/转写许可不能用来包装旧问答；文本提交标CANDIDATE_TEXT，不冒充电话口述。无许可回执的旧fixture仍保留受限验证路径与明确缺口，显式撤回不可利用fixture例外绕过。

### 指定客户分享许可

审核人使用`POST /calls/{case_id}/client-context`设置client_company_id及明确获准向候选人披露的candidate_client_label，带expected_revision与现有会话/CSRF。更换范围使旧D10与批准失效。候选人使用邀请Bearer与Origin调用`POST /candidate/calls/{case_id}/client-sharing`，提交expected_revision/authorized；scope由服务端当前客户范围生成，不接受浏览器指定他人客户。该许可与四项内部处理许可独立，候选人结束后仍可管理分享许可。

正式D10批准及下载同时要求当前客户范围一致的AUTHORIZED分享回执；没有配置客户的历史fixture保留受限演示，显式撤回不可绕过。页面新增客户范围表单与独立候选人分享选项；下载不触发外发。更换客户或撤回分享不重拨，不修改D08/D09内容。

### 职业事实冲突与报告审批

D10的client_profile.unresolved_conflicts非空时，批准与Markdown/Word导出返回业务冲突（REPORT_FACT_CONFLICT_REQUIRES_CORRECTION），既有批准也不绕过。驳回不受此限制。应更正实际回答或源资料、使受影响产物失效并重算，再单独审核新版本；不能直接清空报告中的冲突字段或沿用旧批准。
# 职业字段确认接口

`POST /api/v1/calls/{case_id}/career-confirmations`：已实现，沿用本地会话、CSRF、机构及对象归属校验。

请求包含 `expected_revision`、`minutes_id`、`minutes_version`、`field_path`、`value`、`answer_id`、`quote`、`reason`，可选 `conflict_index`。字段路径白名单覆盖 `profile` 当前城市/公司/岗位/在职状态，已有 `employment` 任职字段、已有 `education` 教育字段，以及 `qualifications`、`additional_projects_or_results`、`career_preferences` 列表项（允许顺序追加）。不接受任意 JSON 路径。

确认值必须包含于引用原话，原话必须逐字出现在同案例已保存回答中；冲突索引必须属于当前有效 D08。确认记录绑定 D03 引用、D08 ID/版本、回答 ID/版本、操作者和理由。返回 `{revision, confirmation}`。来源变更后不再采用旧确认，不修改 D03、D08 原件；当前 D10 及批准失效，须显式生成新报告并单独审批。无关冲突继续保留。人工确认不等于独立核实，也不更改 D09 分数。

并发、失效来源、非法字段/引文/冲突引用返回 409；请求格式错误 422，非所属对象 404。运行时 OpenAPI 见 `openapi.goal-local.json`。目前代码及局部测试已接入，尚未完成此新增流程的浏览器与真实模型联合验收。
