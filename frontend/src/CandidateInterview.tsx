import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Select, Input, Checkbox } from 'antd'
import { AudioOutlined, AudioMutedOutlined, PhoneOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons'
import { candidateRequest, candidateSpeech, streamCandidateSpeech, sendBriefingEmail, chooseCandidateVoice, practiceCandidate, type CandidateSession } from './api/candidate'
import { openCandidateStream } from './api/streaming'
import { createCallMicrophone } from './api/callAudio'
import './candidate-call.css'

const ended = (value: CandidateSession) => ['ended', 'cancelled'].includes(value.status) || value.stop_status !== 'none'
const wait = () => new Promise(resolve => setTimeout(resolve, 400))

export default function CandidateInterview() {
  const [access, setAccess] = useState(() => {
    const params = new URLSearchParams(window.location.hash.slice(1))
    return { caseId: params.get('call') ?? '', token: params.get('token') ?? '' }
  })
  const [session, setSession] = useState<CandidateSession | null>(null)
  const [email, setEmail] = useState('')
  const [autoMail, setAutoMail] = useState(false)
  const mailTriggered = useRef(false)
  const [mailStatus, setMailStatus] = useState('')
  const [sendingMail, setSendingMail] = useState(false)
  const mailRequest = useRef<string | null>(null)
  const goodbyePlayed = useRef(false)
  const [phase, setPhase] = useState('准备接通')
  const [error, setError] = useState(() => !access.caseId || !access.token ? '请使用邀请人生成的完整候选人链接进入。' : '')
  const [connected, setConnected] = useState(false)
  const [muted, setMuted] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [subtitle, setSubtitle] = useState('接通后，AI会先语音询问您是否考虑新的工作机会。')
  const [aiSubtitle, setAiSubtitle] = useState('')
  const [candidateSubtitle, setCandidateSubtitle] = useState('')
  const [history, setHistory] = useState<string[]>([])
  const [setting, setSetting] = useState(false)
  const generation = useRef(0)
  const live = useRef<ReturnType<typeof openCandidateStream> | null>(null)
  const audio = useRef<AudioContext | null>(null)
  const source = useRef<AudioBufferSourceNode | null>(null)
  const mutedRef = useRef(false)
  const running = useRef(false)
  const microphone = useRef<Awaited<ReturnType<typeof createCallMicrophone>> | null>(null)
  const turnCallbacks = useRef<{ start: (frames: Uint8Array[]) => void; frame: (frame: Uint8Array) => void; end: () => void } | null>(null)
  const playing = useRef(new Set<AudioBufferSourceNode>())
  const speechGeneration = useRef(0)
  const speechAbort = useRef<AbortController | null>(null)
  const practiceNonce = useRef<string | null>(null)
  const abortListen = useRef<(() => void) | null>(null)
  const release = useCallback(() => {
    speechGeneration.current++; speechAbort.current?.abort(); speechAbort.current = null
    turnCallbacks.current = null
    void microphone.current?.close(); microphone.current = null
    live.current?.cancel(); live.current = null
    abortListen.current?.(); abortListen.current = null
    playing.current.forEach(node => node.stop()); playing.current.clear()
    source.current?.stop(); source.current = null
    void audio.current?.close(); audio.current = null
  }, [])
  const invalidate = useCallback(() => {
    generation.current++; running.current = false; release()
  }, [release])
  useEffect(() => {
    let active = true
    if (!access.caseId || !access.token) return
    void candidateRequest(access.caseId, access.token).then(value => {
      if (active) { setSession(value); setSeconds(value.elapsed_seconds); if (ended(value)) { setPhase('通话已结束'); setSubtitle('本场已结束。点击“开始新一轮体验”即可重新测试，旧记录会保留。') } }
    }).catch((reason: Error) => { if (active) setError(reason.message) })
    return () => { active = false; invalidate() }
  }, [access, invalidate])
  useEffect(() => {
    if (!connected) return
    const timer = setInterval(() => setSeconds(value => value + 1), 1000)
    const epoch = generation.current
    const heartbeat = setInterval(() => {
      void candidateRequest(access.caseId, access.token).then(value => {
        if (epoch !== generation.current) return
        setSession(value)
        if (ended(value)) { setSession(value) }
      }).catch(() => { /* The active transport reports connection failures. */ })
    }, 10000)
    return () => { clearInterval(timer); clearInterval(heartbeat) }
  }, [connected, access, invalidate])
  function listen(value: CandidateSession, epoch: number) {
    return new Promise<{ text: string; taskId: string } | null>((resolve, reject) => {
      abortListen.current = () => reject(new Error('通话已取消'))
      const playbackEpoch = ++speechGeneration.current
      turnCallbacks.current = {
        start: frames => {
          if (epoch !== generation.current) return
          speechGeneration.current++; speechAbort.current?.abort()
          playing.current.forEach(node => node.stop()); playing.current.clear()
          source.current?.stop(); source.current = null
          setPhase('正在聆听'); setSubtitle('您正在说话…')
          live.current = openCandidateStream(access.caseId, access.token, value.revision,
            text => { if (epoch === generation.current) setCandidateSubtitle(text) },
            (text, taskId) => {
              abortListen.current = null; live.current = null; microphone.current?.disarm()
              turnCallbacks.current = null; resolve({ text, taskId })
            },
            message => {
              abortListen.current = null; live.current = null; microphone.current?.disarm()
              turnCallbacks.current = null; reject(new Error(message))
            }, true, true)
          for (const frame of frames) live.current.pushFrame(frame)
        },
        frame: frame => live.current?.pushFrame(frame),
        end: () => { setPhase('正在识别回答'); void live.current?.finish() },
      }
      microphone.current?.arm()
      void speak(value, epoch, playbackEpoch).then(async () => {
        if (epoch === generation.current && playbackEpoch === speechGeneration.current &&
          value.preflight.interested && !value.preflight.confirmed && !value.preflight.briefing_presented) {
          microphone.current?.disarm(); turnCallbacks.current = null
          setPhase('正在处理岗位资料邮件')
          if (autoMail && email && !mailTriggered.current) {
            mailTriggered.current = true; await emailMaterials()
          } else setMailStatus('未提供已授权的收件邮箱，岗位资料可在页面查看。')
          if (epoch !== generation.current) return
          await candidateRequest(access.caseId, access.token, { action: 'briefing_presented',
            expected_revision: value.revision, statement: '岗位介绍播放完成，邮件状态已提示' })
          abortListen.current = null; resolve(null); return
        }
        if (epoch === generation.current && playbackEpoch === speechGeneration.current) {
          setPhase('正在聆听'); setSubtitle('请直接说话，也可以在AI说话时打断。')
        }
      }).catch(reason => {
        if (epoch === generation.current && playbackEpoch === speechGeneration.current) reject(reason)
      })
    })
  }
  async function speak(value: CandidateSession, epoch: number, playbackEpoch: number) {
    if (!value.spoken_prompt) throw new Error('面试问题尚未就绪，请联系邀请人生成 D07。')
    setPhase('AI正在准备语音'); setSubtitle('正在合成面试官语音…')
    const controller = new AbortController(); speechAbort.current = controller
    let cursor = audio.current?.currentTime ?? 0
    try {
      await streamCandidateSpeech(access.caseId, access.token, value.revision, controller.signal, buffer => {
        if (epoch !== generation.current || playbackEpoch !== speechGeneration.current || !audio.current) return
        const context = audio.current
        setPhase('AI正在说话'); setAiSubtitle(value.spoken_prompt ?? '')
        const node = context.createBufferSource(); node.buffer = buffer; node.connect(context.destination)
        playing.current.add(node); node.onended = () => { playing.current.delete(node) }
        cursor = Math.max(cursor, context.currentTime + 0.04)
        node.start(cursor); cursor += buffer.duration
      })
      while (epoch === generation.current && playbackEpoch === speechGeneration.current && playing.current.size) {
        await new Promise(resolve => setTimeout(resolve, 40))
      }
    } catch (reason) {
      if (controller.signal.aborted) return
      setAiSubtitle(value.spoken_prompt)
      setSubtitle('语音暂时未能播放，请看面试官文字并直接回答，麦克风仍在聆听。')
      if (reason instanceof Error) console.debug('Speech unavailable; continuing with text.')
    }
  }

  async function farewell(value: CandidateSession) {
    if (goodbyePlayed.current) return
    goodbyePlayed.current = true
    microphone.current?.disarm()
    const text = value.spoken_prompt ?? '本次沟通已结束，感谢您的时间，再见。'
    setAiSubtitle(text); setSubtitle('感谢您的参与，再见。')
    try {
      const buffer = await candidateSpeech(access.caseId, access.token, value.revision, false, undefined, true)
      const context = audio.current ?? new AudioContext()
      audio.current = context; await context.resume()
      const node = context.createBufferSource(); node.buffer = buffer
      node.connect(context.destination); source.current = node
      await new Promise<void>(resolve => { node.onended = () => resolve(); node.start() })
      if (source.current === node) source.current = null
    } catch { setSubtitle('本次沟通已结束，感谢您的时间，再见。（语音未能播放）') }
  }
  async function connect() {
    if (running.current) return
    running.current = true
    const epoch = ++generation.current
    setError(''); setPhase('正在连接麦克风')
    try {
      const context = new AudioContext(); audio.current = context; await context.resume()
      const capture = await createCallMicrophone({
        start: frames => turnCallbacks.current?.start(frames),
        frame: frame => turnCallbacks.current?.frame(frame),
        end: () => turnCallbacks.current?.end(),
      })
      if (epoch !== generation.current) { await capture.close(); return }
      microphone.current = capture; capture.setMuted(mutedRef.current)
      setConnected(true)
      let value = await candidateRequest(access.caseId, access.token)
      if (!ended(value)) value = await candidateRequest(access.caseId, access.token, { action: 'begin', expected_revision: value.revision, statement: '候选人接通网页语音面试' })
      if (epoch !== generation.current) return
      setSeconds(value.elapsed_seconds)
      while (epoch === generation.current) {
        setSession(value)
        if (value.preflight.interested && value.preflight.confirmed && autoMail && email && !mailTriggered.current) {
          mailTriggered.current = true
          await emailMaterials()
        }
        if (ended(value)) { await farewell(value); setPhase('通话已结束'); setSubtitle('本次沟通已结束，感谢您的时间。'); break }
        let polls = 0
        while (value.decision_status === 'pending' && !ended(value)) {
          if (value.decision_task && ['failed', 'cancelled'].includes(value.decision_task.status)) throw new Error(`对话任务未完成（${value.decision_task.error_code ?? value.decision_task.status}），请联系邀请人核对。`)
          setPhase('AI正在思考'); setSubtitle(value.decision_task?.phase === 'retrieval' ? '正在查找与本轮交流相关的资料…' : value.decision_task?.phase === 'responding' ? '正在组织回复…' : '正在理解您的回答和上下文…')
          if (++polls > 150) setSubtitle('当前模型服务响应较慢，正在继续等待。您的回答已保存，您也可以随时挂断。')
          await wait()
          if (epoch !== generation.current) return
          value = await candidateRequest(access.caseId, access.token)
          if (epoch !== generation.current) return
          setSession(value)
        }
        if (ended(value)) continue
        if (value.transcription && value.transcription.status !== 'completed') {
          throw new Error('上一轮转写结果需要核对，请联系邀请人检查，系统不会重复提交。')
        }
        let result: { text: string; taskId: string } | null
        if (value.transcription?.text) {
          result = { text: value.transcription.text, taskId: value.transcription.task_id }
        } else {
          result = await listen(value, epoch)
        }
        if (epoch !== generation.current) return
        if (!result) { value = await candidateRequest(access.caseId, access.token); continue }
        setCandidateSubtitle(result.text)
        setHistory(previous => [...previous.slice(-39), `AI：${value.spoken_prompt ?? ''}`, `您：${result.text}`])
        setPhase('正在处理回答')
        value = await candidateRequest(access.caseId, access.token)
        if (epoch !== generation.current) return
        if (!ended(value)) {
          value = await candidateRequest(access.caseId, access.token, {
            action: 'voice', expected_revision: value.revision, statement: result.text,
            transcription_task_id: result.taskId,
          })
          if (epoch !== generation.current) return
        }
      }
    } catch (reason) {
      if (epoch === generation.current) { setError(reason instanceof Error ? reason.message : '连接未完成'); setPhase('通话已暂停'); setSubtitle('本轮未完成，请查看上方错误提示。已保存的回答会保留。') }
    } finally {
      if (epoch === generation.current) { running.current = false; setConnected(false); release() }
    }
  }
  async function newPractice() {
    if (running.current || setting) return
    invalidate(); setSetting(true); setError('')
    try {
      practiceNonce.current ??= crypto.randomUUID()
      const result = await practiceCandidate(access.caseId, access.token, practiceNonce.current)
      practiceNonce.current = null
      const next = { caseId: result.case_id, token: result.token }
      window.history.replaceState(null, '', `/candidate#${new URLSearchParams({ call: next.caseId, token: next.token })}`)
      goodbyePlayed.current = false; mailTriggered.current = false; mailRequest.current = null; setMailStatus(''); setAccess(next); setSession(result.session); setSeconds(0); setHistory([]); setAiSubtitle(''); setCandidateSubtitle('')
      setPhase('准备接通'); setSubtitle('新场次已准备好，点击接通即可开始。')
    } catch (reason) { setError(String(reason)) }
    finally { setSetting(false) }
  }
  async function emailMaterials() {
    if (sendingMail) return
    setSendingMail(true)
    try {
      mailRequest.current ??= crypto.randomUUID()
      let result = await sendBriefingEmail(access.caseId, access.token, email, mailRequest.current)
      const deadline = Date.now() + 25000
      while (['queued', 'running'].includes(result.status) && Date.now() < deadline) {
        setMailStatus('正在发送岗位资料，完成后会提醒您查看邮箱。')
        await new Promise(resolve => setTimeout(resolve, 800))
        result = await sendBriefingEmail(access.caseId, access.token, email, mailRequest.current)
      }
      setMailStatus(result.status === 'completed' ? '邮件服务器已接收，请检查收件箱或垃圾邮件。' : result.status === 'failed' ? '发送结果需核对，请联系邀请人，勿重复发送。' : '发送请求已入队，尚未确认送达。')
    } catch (reason) { setMailStatus(reason instanceof Error ? reason.message : '邮件请求未完成') }
    finally { setSendingMail(false) }
  }
  async function selectVoice(voiceId: string) {
    if (!session || running.current || setting) return
    setSetting(true); setError(''); release()
    try { setSession(await chooseCandidateVoice(access.caseId, access.token, session.revision, voiceId)) }
    catch (reason) { setError(String(reason)) }
    finally { setSetting(false) }
  }
  async function previewVoice() {
    if (!session || running.current || setting) return
    setSetting(true); setError(''); release()
    const epoch = generation.current
    try {
      const context = new AudioContext(); audio.current = context; await context.resume()
      const buffer = await candidateSpeech(access.caseId, access.token, session.revision, true)
      if (epoch !== generation.current) return
      const node = context.createBufferSource(); node.buffer = buffer; node.connect(context.destination); source.current = node
      await new Promise<void>(resolve => { node.onended = () => resolve(); node.start() })
      source.current = null
    } catch (reason) { if (epoch === generation.current) setError(String(reason)) }
    finally { if (epoch === generation.current) release(); setSetting(false) }
  }
  async function hangup() {
    generation.current++; running.current = false; release(); setConnected(false); setPhase('正在挂断')
    try {
      for (let attempt = 0; attempt < 2; attempt++) {
        const value = await candidateRequest(access.caseId, access.token)
        if (ended(value)) { setSession(value); await farewell(value); break }
        try {
          const stopped = await candidateRequest(access.caseId, access.token, {
            action: 'stop', expected_revision: value.revision, statement: '候选人点击挂断',
          })
          setSession(stopped); await farewell(stopped); break
        } catch (reason) { if (attempt === 1) throw reason }
      }
      setPhase('通话已结束'); setSubtitle('您已结束本次面试。')
    } catch (reason) { setError(String(reason)); setPhase('挂断状态待核对，请重试') }
  }
  const stopped = session ? ended(session) : false
  return <main className="candidate-room">
    <header><h1>AI 面试房间</h1><span>网页语音面试</span></header>
    {error && <Alert type="error" showIcon message={error} />}
    <div className="call-settings">
      <label>面试官音色 <Select aria-label="面试官音色" value={session?.voice_id} disabled={!session || connected || setting || stopped}
        style={{ minWidth: 230 }} options={session?.voices.map(voice => ({ value: voice.id, label: voice.label }))} onChange={voiceId => void selectVoice(voiceId)} /></label>
      <Button disabled={!session || connected || setting || stopped} onClick={() => void previewVoice()}>试听音色</Button>
      {session?.practice_available && <Button loading={setting} disabled={connected} onClick={() => void newPractice()}>开始新一轮体验</Button>}
    </div>
    {!connected && <div className="call-material">
      <label>岗位资料收件邮箱<Input type="email" value={email} onChange={event => { setEmail(event.target.value); mailRequest.current = null }} placeholder="您的常用邮箱" /></label>
      <Checkbox checked={autoMail} onChange={event => setAutoMail(event.target.checked)}>我有求职意愿时，同意自动把岗位资料发送到此邮箱</Checkbox>
    </div>}
    {mailStatus && <Alert type="info" message={mailStatus} />}
    <section className="candidate-call">
      <div className="call-heading"><strong>{session?.material.job_title ?? '候选人面试'}</strong><time>{String(Math.floor(seconds / 60)).padStart(2, '0')}:{String(seconds % 60).padStart(2, '0')}</time></div>
      <div className="call-participants">
        <article className={phase === 'AI正在说话' ? 'speaking' : ''}><div className="call-avatar"><RobotOutlined /></div><h2>AI 面试官</h2><p>{phase.startsWith('AI') ? phase : '语音面试官'}</p><div className="call-wave">▂ ▅ ▃ ▇ ▄ ▆ ▂ ▅</div></article>
        <article className={phase === '正在聆听' && !muted ? 'speaking' : ''}><div className="call-avatar"><UserOutlined /></div><h2>候选人</h2><p>{connected ? muted ? '麦克风已静音' : '麦克风已连接' : phase}</p></article>
      </div>
      <div className="call-subtitles"><small>实时对话 · {phase}</small>
        <div className="subtitle-tracks">
          <section aria-label="AI面试官字幕"><strong>AI 面试官</strong><p aria-live="polite">{aiSubtitle || '等待面试官发言'}</p></section>
          <section aria-label="候选人字幕"><strong>候选人</strong><p aria-live="polite">{candidateSubtitle || '等待您的回答'}</p></section>
        </div><small role="status">{subtitle}</small>
      </div>
      {session?.preflight.interested && <details className="call-material"><summary>岗位与薪资资料（完整内容）</summary>
        <p>岗位：{session.material.job_title ?? '待招聘方确认'}</p>
        <p>职责：{session.material.requirements.join('；') || '待招聘方确认'}</p>
        <p>薪资：{typeof session.material.salary === 'string' ? session.material.salary : JSON.stringify(session.material.salary) ?? '待招聘方确认'}</p>
        <p>公司：{typeof session.material.company_introduction === 'string' ? session.material.company_introduction : JSON.stringify(session.material.company_introduction) ?? '待招聘方确认'}</p>
        <label>收取岗位资料的邮箱<Input type="email" value={email} disabled={sendingMail} onChange={event => { setEmail(event.target.value); mailRequest.current = null; setMailStatus('') }} placeholder="支持 QQ、163、Gmail、Outlook、企业邮箱等" /></label>
        <Button loading={sendingMail} disabled={!email || stopped} onClick={() => void emailMaterials()}>同意并发送岗位资料到此邮箱</Button>
        <p role="status">{mailStatus}</p>
      </details>}
      <div className="call-controls">
        {!connected && <Button type="primary" size="large" disabled={!session || stopped || setting} onClick={() => void connect()}>{seconds && !stopped ? '恢复通话' : '接通并开始语音面试'}</Button>}
        <Button shape="circle" size="large" aria-label={muted ? '开启麦克风' : '静音麦克风'} disabled={!connected} icon={muted ? <AudioMutedOutlined /> : <AudioOutlined />} onClick={() => {
          mutedRef.current = !mutedRef.current; setMuted(mutedRef.current); microphone.current?.setMuted(mutedRef.current)
        }} />
        <Button danger type="primary" shape="circle" size="large" aria-label="挂断" disabled={!session || stopped} icon={<PhoneOutlined />} onClick={() => void hangup()} />
      </div>
      <p className="call-note">接通即允许麦克风转写。可直接说话打断AI，停顿约1.8秒自动交棒。单次回答最长{Math.floor((session?.interview_limits.max_turn_seconds ?? 600) / 60)}分钟，整场最长{Math.floor((session?.interview_limits.max_seconds ?? 3600) / 60)}分钟。说“结束面试”或点击挂断结束。建议戴耳机减少回声；重复测试请开启新一轮。</p>
    </section>
    {history.length > 0 && <details className="call-history"><summary>本次页面对话记录</summary>{history.map((line, index) => <p key={index}>{line}</p>)}</details>}
  </main>
}
