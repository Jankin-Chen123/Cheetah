# Goal 本地集成增量（进行中）

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
