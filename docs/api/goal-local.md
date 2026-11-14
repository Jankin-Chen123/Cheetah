# Goal 本地集成增量（进行中）

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

本地已配置TEXT_PROVIDER=ark，ARK_MODEL=doubao-seed-2-1-lite-260915，关闭深度思考；ARK_EMBEDDING_MODEL=doubao-embedding-vision-251215，调用/embeddings/multimodal的文本输入。Key仅本地.env；百炼ASR/TTS配置独立保留。不增加SDK或服务，不修改公共交接事件合同。统一文本调用入口保留原Python导入路径以兼容现有D07—D10消费方；Ark不可用时明确记录错误，不悄悄切回百炼。

打开DIALOGUE_UNDERSTANDING_ENABLED后：模型先识别意图和上下文，构造完整检索查询。岗位反问、解释、更正等可直接回应，跳过检索和第二次生成；项目经历、归因、职责边界等专业追问进入混合检索。检索先过滤启用/审核/版本/冲突与预览权限（不再用固定标签截前8条），当前候选池上限100。关键词词项重合与真实向量余弦结果经RRF融合，低相关不塞入，最多返回3条。当前余弦门槛0.35为工程初值，未做业务大样本校准。

向量缓存以模型/地址/文本摘要为键，只存向量，不存候选人原文；文档改变会生成新缓存。源材料资格在读取与结果提交时重新检查，缓存不赋予审核权限。向量服务失败标记lexical_degraded及error_code，继续模型对话，不冒充语义成功。`uv run python scripts/warm_method_index.py --preview`只在development可用，本机预热17条符合筛选条件的方法，未批准或修改知识内容。

工作记忆按key增量更新，最多20项；单轮最多3项更新。每项需要已知answer_id及逐字原文quote，无法核对的摘要不保存；未知不推断为没有经验，事实更正替换对应旧值。人工更正清空旧记忆供重建。生成模型仅接收精简方法摘录；短方法别名映射回真实引用，未验证引用不会成为证据。生成失败/完全重复回复仍保留明确的程序来源。

候选人decision_task新增可空phase（understanding/retrieval/responding/completed），页面按阶段提示等待。任务持久化timings中的understanding_ms/retrieval_ms/response_ms/total_ms以定位长尾，均为服务端阶段耗时，非浏览器实际出声时间。模型慢响应不再仅因60秒页面轮询阈值而中断对话。知识库、事实和版本审批边界未放宽。

本轮真实验证：Ark文本及2048维向量均可调用；同义表达的低词项重合查询命中个人贡献方法；17条真实本地方法的隔离复制库完成“理解→混合检索→模型追问”，无降级。D08/D09真实模型调用成功；样例D09不符合推荐门槛时D10被CURRENT_ELIGIBLE_INPUT_REQUIRED阻断，未批准/导出/发送报告。语言矩阵、连续对话、语音HTTP原始记录仅work/。不能把条件检查通过当成对全部自然语言或真人麦克风体验的保证；复杂检索轮次仍有数秒至十余秒时延，知识相似度阈值与回复冗长度还需持续校准。
