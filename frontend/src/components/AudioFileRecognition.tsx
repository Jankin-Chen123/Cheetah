import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Space } from 'antd'
import { readAudio, retryAudio, submitAudio, submitAudioUrl, type AudioRecognition, type AudioRef, type AudioUrl } from '../api/audio'

export default function AudioFileRecognition({ file, audioUrl, onComplete }: { file?: File; audioUrl?: AudioUrl; onComplete: (text: string, ref: AudioRef) => void }) {
  const [result, setResult] = useState<AudioRecognition>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submission = useRef(crypto.randomUUID())
  const retryIntent = useRef<{ key: string; revision: number } | null>(null)
  const completed = useRef<string | null>(null)
  const callback = useRef(onComplete)
  const mounted = useRef(true)
  useEffect(() => { callback.current = onComplete }, [onComplete])
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const accept = (value: AudioRecognition) => {
    if (!mounted.current) return
    setResult(value)
    if (value.status === 'completed' && value.transcript && completed.current !== `${value.id}:${value.revision}`) {
      completed.current = `${value.id}:${value.revision}`
      callback.current(value.transcript, { id: value.id, revision: value.revision })
    }
  }
  useEffect(() => {
    if (!result || !['queued', 'running', 'waiting_provider'].includes(result.status)) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try { const next = await readAudio(result.id, controller.signal); if (!controller.signal.aborted) { accept(next); setError('') } }
      catch (failure) { if (!controller.signal.aborted) setError((failure as Error).message) }
      finally { if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 2000) }
    }
    timer = setTimeout(() => void poll(), 1000)
    return () => { controller.abort(); clearTimeout(timer) }
  }, [result?.id, result?.status]) // eslint-disable-line react-hooks/exhaustive-deps
  async function act(retry = false) {
    if (busy) return
    setBusy(true); setError('')
    try {
      if (retry && result) {
        const intent = retryIntent.current ?? { key: crypto.randomUUID(), revision: result.revision }
        retryIntent.current = intent
        accept(await retryAudio({ ...result, revision: intent.revision }, intent.key)); retryIntent.current = null
      } else if (audioUrl) accept(await submitAudioUrl(audioUrl, submission.current))
      else if (file) accept(await submitAudio(file, submission.current))
    } catch (failure) { if (mounted.current) setError((failure as Error).message) }
    finally { if (mounted.current) setBusy(false) }
  }
  const active = result && ['queued', 'running', 'waiting_provider'].includes(result.status)
  return <div className="stack">
    <Space wrap>
      {!result && <Button loading={busy} onClick={() => void act()}>识别录音为文字</Button>}
      {active && <span role="status">{result.status === 'queued' ? '录音已保存，等待后台识别…' : result.status === 'waiting_provider' ? '语音服务正在处理，结果会自动更新，暂时关闭窗口也不会重复提交。' : '正在识别录音，完成后可核对和修改文字…'}</span>}
      {result?.retryable && <Button loading={busy} onClick={() => void act(true)}>重新识别失败录音</Button>}
      {result && <Button disabled={busy} onClick={() => void readAudio(result.id).then(accept).catch(failure => setError(failure.message))}>重新检查识别结果</Button>}
    </Space>
    {result?.status === 'completed' && <Alert type="success" title="录音已转成文字，请核对专有名词、数字及说话人，再创建岗位。" />}
    {result?.error_message && <Alert type={result.status === 'reconciling' ? 'warning' : 'error'} title={result.error_message} />}
    {error && <Alert type="error" title={error} />}
  </div>
}
