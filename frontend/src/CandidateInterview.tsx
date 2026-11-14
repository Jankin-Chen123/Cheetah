import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button } from 'antd'
import { AudioOutlined, AudioMutedOutlined, PhoneOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons'
import { candidateRequest, candidateSpeech, type CandidateSession } from './api/candidate'
import { openCandidateStream } from './api/streaming'
import './candidate-call.css'

const ended = (value: CandidateSession) => ['ended', 'cancelled'].includes(value.status) || value.stop_status !== 'none'
const wait = () => new Promise(resolve => setTimeout(resolve, 1000))

export default function CandidateInterview() {
  const [access] = useState(() => {
    const params = new URLSearchParams(window.location.hash.slice(1))
    return { caseId: params.get('call') ?? '', token: params.get('token') ?? '' }
  })
  const [session, setSession] = useState<CandidateSession | null>(null)
  const [phase, setPhase] = useState('准备接通')
  const [error, setError] = useState(() => !access.caseId || !access.token ? '请使用邀请人生成的完整候选人链接进入。' : '')
  const [connected, setConnected] = useState(false)
  const [muted, setMuted] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [subtitle, setSubtitle] = useState('接通后，AI会先语音询问您是否考虑新的工作机会。')
  const [history, setHistory] = useState<string[]>([])
  const generation = useRef(0)
  const live = useRef<ReturnType<typeof openCandidateStream> | null>(null)
  const audio = useRef<AudioContext | null>(null)
  const source = useRef<AudioBufferSourceNode | null>(null)
  const mutedRef = useRef(false)
  const running = useRef(false)
  const abortListen = useRef<(() => void) | null>(null)
  const release = useCallback(() => {
    live.current?.cancel(); live.current = null
    abortListen.current?.(); abortListen.current = null
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
      if (active) { setSession(value); if (ended(value)) setPhase('通话已结束') }
    }).catch((reason: Error) => { if (active) setError(reason.message) })
    return () => { active = false; invalidate() }
  }, [access, invalidate])
  useEffect(() => {
    if (!connected) return
    const timer = setInterval(() => setSeconds(value => value + 1), 1000)
    return () => clearInterval(timer)
  }, [connected])
  function listen(value: CandidateSession, epoch: number) {
    return new Promise<{ text: string; taskId: string }>((resolve, reject) => {
      abortListen.current = () => reject(new Error('通话已取消'))
      live.current = openCandidateStream(access.caseId, access.token, value.revision,
        text => { if (epoch === generation.current) setSubtitle(`您：${text}`) },
        (text, taskId) => { abortListen.current = null; live.current = null; resolve({ text, taskId }) },
        message => { abortListen.current = null; live.current = null; reject(new Error(message)) }, true)
      live.current.setMuted(mutedRef.current)
    })
  }
  async function speak(value: CandidateSession, epoch: number) {
    if (!value.spoken_prompt) throw new Error('面试问题尚未就绪，请联系邀请人生成 D07。')
    setPhase('AI正在准备语音'); setSubtitle(`AI：${value.spoken_prompt}`)
    const buffer = await candidateSpeech(access.caseId, access.token, value.revision)
    if (epoch !== generation.current || !audio.current) return
    setPhase('AI正在说话')
    const node = audio.current.createBufferSource(); node.buffer = buffer
    node.connect(audio.current.destination); source.current = node
    await new Promise<void>(resolve => { node.onended = () => resolve(); node.start() })
    if (source.current === node) source.current = null
  }
  async function connect() {
    if (running.current) return
    running.current = true
    const epoch = ++generation.current
    setError(''); setPhase('正在连接麦克风')
    try {
      const context = new AudioContext(); audio.current = context; await context.resume()
      const permission = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false })
      permission.getTracks().forEach(track => track.stop())
      if (epoch !== generation.current) return
      setConnected(true)
      let value = await candidateRequest(access.caseId, access.token)
      while (epoch === generation.current) {
        setSession(value)
        if (ended(value)) { setPhase('通话已结束'); setSubtitle('本次沟通已结束，感谢您的时间。'); break }
        let polls = 0
        while (value.decision_status === 'pending' && !ended(value)) {
          setPhase('AI正在思考'); setSubtitle('正在根据您的回答准备下一个问题…')
          if (++polls > 120) throw new Error('下一问题尚未生成，请联系邀请人检查任务。已保存的回答不会丢失。')
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
        let result: { text: string; taskId: string }
        if (value.transcription?.text) {
          result = { text: value.transcription.text, taskId: value.transcription.task_id }
        } else {
          await speak(value, epoch)
          if (epoch !== generation.current) return
          setPhase('正在聆听'); setSubtitle('请直接说话，停顿后会自动提交。')
          result = await listen(value, epoch)
        }
        if (epoch !== generation.current) return
        setSubtitle(`您：${result.text}`)
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
      if (epoch === generation.current) { setError(reason instanceof Error ? reason.message : '连接未完成'); setPhase('通话已暂停') }
    } finally {
      if (epoch === generation.current) { running.current = false; setConnected(false); release() }
    }
  }
  async function hangup() {
    generation.current++; running.current = false; release(); setConnected(false); setPhase('正在挂断')
    try {
      for (let attempt = 0; attempt < 2; attempt++) {
        const value = await candidateRequest(access.caseId, access.token)
        if (ended(value)) { setSession(value); break }
        try {
          const stopped = await candidateRequest(access.caseId, access.token, {
            action: 'stop', expected_revision: value.revision, statement: '候选人点击挂断',
          })
          setSession(stopped); break
        } catch (reason) { if (attempt === 1) throw reason }
      }
      setPhase('通话已结束'); setSubtitle('您已结束本次面试。')
    } catch (reason) { setError(String(reason)); setPhase('挂断状态待核对，请重试') }
  }
  const stopped = session ? ended(session) : false
  return <main className="candidate-room">
    <header><h1>AI 面试房间</h1><span>网页语音面试</span></header>
    {error && <Alert type="error" showIcon message={error} />}
    <section className="candidate-call">
      <div className="call-heading"><strong>{session?.material.job_title ?? '候选人面试'}</strong><time>{String(Math.floor(seconds / 60)).padStart(2, '0')}:{String(seconds % 60).padStart(2, '0')}</time></div>
      <div className="call-participants">
        <article className={phase === 'AI正在说话' ? 'speaking' : ''}><div className="call-avatar"><RobotOutlined /></div><h2>AI 面试官</h2><p>{phase.startsWith('AI') ? phase : '语音面试官'}</p><div className="call-wave">▂ ▅ ▃ ▇ ▄ ▆ ▂ ▅</div></article>
        <article className={phase === '正在聆听' && !muted ? 'speaking' : ''}><div className="call-avatar"><UserOutlined /></div><h2>候选人</h2><p>{connected ? muted ? '麦克风已静音' : '麦克风已连接' : phase}</p></article>
      </div>
      <div className="call-subtitles"><small>实时对话字幕 · {phase}</small><p aria-live="polite">{subtitle}</p></div>
      <div className="call-controls">
        {!connected && <Button type="primary" size="large" disabled={!session || stopped} onClick={() => void connect()}>{seconds ? '恢复通话' : '接通并开始语音面试'}</Button>}
        <Button shape="circle" size="large" aria-label={muted ? '开启麦克风' : '静音麦克风'} disabled={!connected} icon={muted ? <AudioMutedOutlined /> : <AudioOutlined />} onClick={() => {
          mutedRef.current = !mutedRef.current; setMuted(mutedRef.current); live.current?.setMuted(mutedRef.current)
        }} />
        <Button danger type="primary" shape="circle" size="large" aria-label="挂断" disabled={!session || stopped} icon={<PhoneOutlined />} onClick={() => void hangup()} />
      </div>
      <p className="call-note">接通即允许上传麦克风音频进行转写和面试。请直接用语音交流，停顿约1.5秒自动交给面试官；单轮最长2分钟。说“结束面试”或点击挂断即可结束。</p>
    </section>
    {history.length > 0 && <details className="call-history"><summary>本次页面对话记录</summary>{history.map((line, index) => <p key={index}>{line}</p>)}</details>}
  </main>
}
