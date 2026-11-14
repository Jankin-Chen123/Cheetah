import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Input, Space, Typography } from 'antd'
import { candidateRequest, candidateSpeech, transcribeCandidate, type CandidateSession } from './api/candidate'
import { captureMicrophone, type MicrophoneCapture } from './api/microphone'
import { openCandidateStream } from './api/streaming'

export default function CandidateInterview() {
  const [access] = useState(() => {
    const params = new URLSearchParams(window.location.hash.slice(1))
    return { caseId: params.get('call') ?? '', token: params.get('token') ?? '' }
  })
  const [session, setSession] = useState<CandidateSession | null>(null)
  const [statement, setStatement] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const capture = useRef<MicrophoneCapture | null>(null)
  const [recording, setRecording] = useState(false)
  const [pcm, setPcm] = useState<Uint8Array | null>(null)
  const [transcriptionId, setTranscriptionId] = useState<string>()
  const liveStream = useRef<ReturnType<typeof openCandidateStream> | null>(null)
  const audioGeneration = useRef(0)
  const [streaming, setStreaming] = useState(false)
  const [partial, setPartial] = useState('')
  useEffect(() => () => { liveStream.current?.cancel() }, [])
  function startStream() {
    if (!session) return
    const generation = audioGeneration.current
    setError(''); setPartial(''); setStreaming(true)
    liveStream.current = openCandidateStream(access.caseId, access.token, session.revision,
      text => { if (generation === audioGeneration.current) setPartial(text) },
      (text, taskId) => {
        if (generation !== audioGeneration.current) return
        setStatement(text); setTranscriptionId(taskId); setStreaming(false); liveStream.current = null
        void candidateRequest(access.caseId, access.token).then(value => {
          if (generation === audioGeneration.current) setSession(value)
        }).catch((reason: Error) => setError(reason.message))
      },
      message => {
        if (generation !== audioGeneration.current) return
        setError(message); setStreaming(false); liveStream.current = null
      })
  }
  const playback = useRef<AudioContext | null>(null)
  useEffect(() => () => { void playback.current?.close() }, [])
  async function speak() {
    if (!session) return
    const generation = audioGeneration.current
    setBusy(true); setError('')
    try {
      await playback.current?.close()
      const context = new AudioContext(); playback.current = context
      await context.resume()
      const audio = await candidateSpeech(access.caseId, access.token, session.revision)
      if (generation !== audioGeneration.current) { await context.close(); return }
      const source = context.createBufferSource(); source.buffer = audio
      source.connect(context.destination); source.start()
      source.onended = () => { void context.close(); if (playback.current === context) playback.current = null }
    } catch (reason) { setError(String(reason)) }
    finally { setBusy(false) }
  }
  useEffect(() => () => { audioGeneration.current++; void capture.current?.cancel() }, [])
  async function record() {
    setError('')
    try {
      if (capture.current) {
        const bytes = await capture.current.finish()
        capture.current = null; setRecording(false); setPcm(bytes)
      } else {
        const generation = audioGeneration.current
        const microphone = await captureMicrophone()
        if (generation !== audioGeneration.current) { await microphone.cancel(); return }
        capture.current = microphone; setRecording(true); setPcm(null)
      }
    } catch (reason) { setRecording(false); setError(reason instanceof Error ? reason.message : '麦克风不可用') }
  }
  async function transcribe() {
    if (!pcm || !session) return
    const generation = audioGeneration.current
    setBusy(true); setError('')
    try {
      const result = await transcribeCandidate(access.caseId, access.token, session.revision, pcm)
      if (generation === audioGeneration.current) { setStatement(result.text); setTranscriptionId(result.transcription_task_id); setPcm(null) }
    } catch (reason) { if (generation === audioGeneration.current) setError(String(reason)) }
    finally { if (generation === audioGeneration.current) setBusy(false) }
  }
  useEffect(() => {
    let active = true
    candidateRequest(access.caseId, access.token).then(value => { if (active) setSession(value) })
      .catch((reason: Error) => { if (active) setError(reason.message) })
    return () => { active = false }
  }, [access])
  useEffect(() => {
    if (session?.decision_status !== 'pending') return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        if (document.visibilityState === 'visible') {
          const value = await candidateRequest(access.caseId, access.token)
          if (active) setSession(value)
        }
      } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : '状态查询失败') }
      if (active) timer = setTimeout(() => void poll(), 3000)
    }
    timer = setTimeout(() => void poll(), 3000)
    return () => { active = false; clearTimeout(timer) }
  }, [access, session?.decision_status])
  async function act(action: string, extra = {}) {
    if (!session) return
    if (action === 'stop') {
      liveStream.current?.cancel(); liveStream.current = null; setStreaming(false); setPartial('')
      void playback.current?.close(); playback.current = null
      audioGeneration.current++; await capture.current?.cancel(); capture.current = null
      setRecording(false); setPcm(null)
    }
    setBusy(true); setError('')
    try {
      setSession(await candidateRequest(access.caseId, access.token, {
        expected_revision: session.revision, action, statement,
        ...(action === 'answer' && transcriptionId ? { transcription_task_id: transcriptionId } : {}), ...extra,
      }))
      setStatement('')
      setTranscriptionId(undefined)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败') }
    finally { setBusy(false) }
  }
  const stopped = session?.status === 'ended' || session?.status === 'cancelled' || session?.stop_status !== 'none'
  return <main style={{ maxWidth: 760, margin: '32px auto', padding: 20 }}>
    <Typography.Title level={2}>候选人面试</Typography.Title>
    {error && <Alert type="error" message={error} />}
    {session && <Space orientation="vertical" style={{ width: '100%' }}>
      <Alert type="info" message="可播放当前问题，录制最多10秒回答并主动上传转写，核对文字后保存。连续实时通话仍在开发，当前分段音频流程尚待浏览器验收。" />
      <Card title="先了解机会">
        <Typography.Paragraph>请先说明您目前是否考虑新的工作机会。</Typography.Paragraph>
        {session.preflight.interested && <>
        <Typography.Paragraph>岗位：{session.material.job_title ?? '未知'}</Typography.Paragraph>
        <Typography.Paragraph>岗位要求：{session.material.requirements.join('；') || '未知'}</Typography.Paragraph>
        <Typography.Paragraph>薪资：{session.material.salary ? JSON.stringify(session.material.salary) : '未知，尚未确认'}</Typography.Paragraph>
        <Typography.Paragraph>公司简介：{session.material.company_introduction ? JSON.stringify(session.material.company_introduction) : '未知，尚未确认'}</Typography.Paragraph>
        </>}
      </Card>
      <Typography.Paragraph>{stopped ? '面试已结束。' : session.question ?? '确认意愿及材料后，等待面试问题。'}</Typography.Paragraph>
      {session.decision_status === 'pending' && !stopped && <Alert type="info" message="回答已保存，正在等待下一问题；您可以随时结束面试。" />}
      <Input.TextArea value={statement} onChange={event => setStatement(event.target.value)} placeholder="填写您的实际意愿、确认意见或回答" disabled={stopped} />
      {partial && <Typography.Paragraph>实时转写草稿（尚未保存）：{partial}</Typography.Paragraph>}
      {session.transcription && !stopped && <Alert type="info" message={session.transcription.status === 'completed' ? '已恢复本轮完成的转写草稿，可核对后继续保存。' : `本轮转写状态：${session.transcription.status}；结果不明时请联系邀请人核对，不要重复上传。`} />}
      <Space wrap>
        <Button disabled={busy || streaming || recording || stopped || streaming || !session.preflight.confirmed || !session.question || session.decision_status === 'pending'} onClick={startStream}>实时语音回答（上传麦克风音频）</Button>
        <Button disabled={!streaming} onClick={() => void liveStream.current?.finish()}>完成本轮语音</Button>
        {session.transcription?.text && <Button disabled={busy || streaming || stopped} onClick={() => {
          setStatement(session.transcription!.text!); setTranscriptionId(session.transcription!.task_id)
        }}>恢复已完成转写</Button>}
        <Button disabled={busy || streaming || stopped || !session.question || session.decision_status === 'pending'} onClick={() => void speak()}>语音播放当前问题</Button>
        <Button disabled={busy || streaming || stopped || !session.preflight.confirmed || !session.question || session.decision_status === 'pending'} onClick={() => void record()}>{recording ? '完成录音' : '录制回答'}</Button>
        <Button disabled={busy || streaming || stopped || !pcm} onClick={() => void transcribe()}>上传录音并转写</Button>
        <Button disabled={busy || streaming || stopped || !statement.trim()} onClick={() => void act('interest', { interested: true })}>正在考虑机会</Button>
        <Button disabled={busy || streaming || stopped || !statement.trim()} onClick={() => void act('interest', { interested: false })}>暂不考虑</Button>
        <Button disabled={busy || streaming || stopped || !statement.trim() || !session.preflight.interested} onClick={() => void act('confirm', { material_sha256: session.material_sha256 })}>已了解材料，愿意开始</Button>
        <Button disabled={busy || streaming || stopped || !statement.trim() || !session.preflight.confirmed || !session.question || session.decision_status === 'pending'} onClick={() => void act('answer')}>保存回答</Button>
        <Button danger disabled={stopped} onClick={() => void act('stop', { statement: statement || '候选人点击结束面试' })}>结束面试</Button>
        <Button disabled={busy || streaming} onClick={() => void candidateRequest(access.caseId, access.token).then(setSession).catch((reason: Error) => setError(reason.message))}>刷新状态</Button>
      </Space>
    </Space>}
  </main>
}
