# 录音材料识别（2026-11-15）

后续更新：用户已授权生产部署，标准版音频网址识别在正式网站实测通过；详见[生产更新验收](deployment-validation-2026-11-15.md)。下文“未部署”保留的是上线前阶段的验证记录。

用于岗位沟通录音生成可核对的文字材料，之后继续现有 D01/D02 流程。不会启动麦克风、拨打电话、合成语音或发送邮件。识别文字不是已核实事实，专有名词、数字、说话人及转写错误需要人工核对。

## 两种入口

创建岗位页面选择录音后点击“识别录音为文字”；或者展开“使用音频网址（标准版）”。结果自动回填可编辑文字记录，核对后点击“创建并识别”。纯文字和TXT入口继续可用。没有文字时不再把“保存录音”误显示为已经创建并分析岗位。

| 方式 | 实现 | 条件及本轮验证 |
| --- | --- | --- |
| 标准版音频网址 | 官方 submit/query，资源 volc.seedasr.auc，模型2.0 | 用户提供的Key实测可用；官方公开6.3秒样例音频提交、查询、取回文字及时间戳、浏览器自动回填均通过。标准版服务商须能直接读取HTTPS网址，可能异步等待数小时。 |
| 本地文件直接上传 | 官方 recognize/flash，资源 volc.bigasr.auc_turbo | WAV、MP3、OGG OPUS，当前产品限制20MB、最长2小时。代码和隔离协议测试通过，实际Key调用返回403/45000030 requested resource not granted。开通标准版不代表有极速版资源权限；本轮未宣称真实本地文件识别成功。 |

标准版网址不由本服务下载，不临时公开本机录音。仅接受无需登录的公网HTTPS地址，拒绝内网、URL内嵌登录凭据和明显密钥参数。用户给出的材料网址仅发送到选定语音服务；不额外创建文件托管服务。标准版支持 WAV/MP3/OGG/AAC/M4A/AMR/SPX，最长5小时；两种方式的最终文字仍受岗位材料30,000字限制，超长不静默截断。

## 配置和启动

本机密钥仅存忽略的.env，不进入前端、日志、接口响应、公开样例或仓库。配置占位项见.env.example：

```dotenv
CHEETA_FILE_ASR_PROVIDER=volcengine
CHEETA_VOLC_SPEECH_API_KEY=replace-with-authorized-speech-key
CHEETA_VOLC_FILE_ASR_RESOURCE_ID=volc.bigasr.auc_turbo
CHEETA_VOLC_FILE_ASR_STANDARD_RESOURCE_ID=volc.seedasr.auc
CHEETA_FILE_ASR_BYTE_LIMIT=20971520
CHEETA_FILE_ASR_TIMEOUT_SECONDS=180
CHEETA_FILE_ASR_DAILY_LIMIT=20
```

显式执行 `uv run alembic upgrade head`，新增迁移0007_audio_transcriptions。API不自动建表。普通 intake worker `uv run python -m app.worker` 处理持久化录音识别队列；API、worker须使用同一数据库和版本。不需要设置voice_provider，不将配置存在等同权限已开通。

## 协议和恢复

- POST /api/v1/audio-transcriptions：multipart字段file，Cookie、Origin、CSRF、Idempotency-Key。校验实际文件头、大小与可读WAV时长，同账号相同内容复用同一识别记录。
- POST /api/v1/audio-transcriptions/from-url：JSON audio_url/audio_format，同样鉴权与幂等。只提交一次标准版任务，保存服务商request ID，后续仅查询该ID，不重新提交。
- GET /api/v1/audio-transcriptions/{id}：只读本机构本所有者记录，包含status、revision、transcript、时间戳segments、duration_ms及稳定错误，不返回密钥、原始响应、私人网址或音频字节。
- POST /api/v1/audio-transcriptions/{id}/retry：expected_revision，只有已确定失败且可重试时显式新调用，总尝试上限3。完成、运行中和结果未知均不允许重发。相同意图重放不重复排队。
- queued/running/waiting_provider不代表完成。网络结果不明或进程中断记reconciling；标准版以保存的ID继续安全查询，极速版不自动重发。已知拒绝返回failed和实际原因，不能伪装成功。
- 单账号每日默认20次，数据库锁内检查调用配额。同账号旧任务跨日重试采用保守计数，不因重试重置已有使用量。
- POST /jobs可携带audio_transcription_ref的id/revision，服务端核对归属与已完成版本，保留ASR来源、音频内容哈希和文字是否经过编辑。原始转写不被前端编辑覆盖；D01输入引用保留音频材料ID。

文件与转写属于私有业务数据，保存在数据库。没有对音频增加公开下载路由。现有本机录音缓存不当作已上传或已识别。

## 验证边界

隔离测试覆盖同内容防重、幂等、跨账号、文件格式、大小、配额、已知权限拒绝、静音、网络结果未知、进程恢复、显式重试、标准版一次提交后多次查询，以及人工编辑文字与岗位关联。数据库迁移执行往返验证。浏览器实测标准版文字回填与本地文件的权限错误显示。未部署cheetah.asia，遵循用户“先保留本地修复，暂不上线”的决定。

回归结果：后端全量451通过、3项依环境跳过；最终锁顺序修正后相关22项通过，PostgreSQL独立schema的41项回归全部通过（包含多执行器只调用一次及迁移）。前端53项测试、静态／类型检查与构建通过。六项合同导出检查通过。浏览器390px页面宽390，无横向溢出。密钥未出现在受版本控制的改动中，本机.env处于忽略状态。

参考：[用户提供的标准版提交文档](https://docs.volcengine.com/docs/doubao-voice/task-submission-http-1?lang=zh)、[查询文档](https://docs.volcengine.com/docs/doubao-voice/result-query-http-1?lang=zh)、[本地数据极速版文档](https://docs.volcengine.com/docs/doubao-voice/large-model-recording-file-lite-recognition-api?lang=zh)。
