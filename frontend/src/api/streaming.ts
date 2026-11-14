import { captureMicrophone, type MicrophoneCapture } from './microphone'

export function openCandidateStream(caseId: string, token: string, revision: number,
  onDelta: (text: string) => void, onComplete: (text: string, taskId: string) => void,
  onError: (message: string) => void, automatic = false, externalMicrophone = false) {
  const url = new URL(`/api/v1/candidate/calls/${encodeURIComponent(caseId)}/stream`, window.location.href)
  url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const socket = new WebSocket(url)
  let microphone: MicrophoneCapture | null = null
  let cancelled = false
  let completed = false
  let finishing = false
  let muted = false
  let ready = false
  let queued: Uint8Array[] = []
  let queuedBytes = 0
  function pushFrame(frame: Uint8Array) {
    if (cancelled || finishing) return
    if (!ready) {
      queuedBytes += frame.length
      if (queuedBytes > 256000) { onError('语音连接建立超时，已暂停采集。'); cancel(); return }
      queued.push(frame)
    } else if (socket.bufferedAmount > 256000) {
      onError('语音网络积压，已暂停采集，请核对状态。'); cancel()
    } else socket.send(frame)
  }
  async function finish() {
    if (finishing || cancelled) return
    finishing = true
    await microphone?.finish(); microphone = null
    if (ready && socket.readyState === WebSocket.OPEN) socket.send('finish')
  }
  function cancel() {
    cancelled = true; queued = []; void microphone?.cancel(); microphone = null; socket.close()
  }
  socket.onopen = () => socket.send(JSON.stringify({ token, expected_revision: revision }))
  socket.onmessage = event => {
    const message = JSON.parse(String(event.data)) as { type: string; text?: string; transcription_task_id?: string }
    if (message.type === 'ready') {
      ready = true
      if (externalMicrophone) {
        for (const frame of queued) socket.send(frame)
        queued = []; queuedBytes = 0
        if (finishing) socket.send('finish')
        return
      }
      void captureMicrophone(frame => {
        if (!cancelled && !finishing && socket.readyState === WebSocket.OPEN) {
          if (socket.bufferedAmount > 65536) { onError('网络发送积压，已停止采集，请核对状态。'); cancel() }
          else socket.send(frame)
        }
      }, () => void finish(), automatic).then(capture => {
        if (cancelled || finishing) void capture.cancel(); else { microphone = capture; microphone.setMuted(muted) }
      }).catch((reason: Error) => { onError(reason.message); cancel() })
    } else if (message.type === 'transcript_delta') onDelta(message.text ?? '')
    else if (message.type === 'transcript_completed') {
      completed = true; onComplete(message.text ?? '', message.transcription_task_id ?? ''); cancel()
    } else if (message.type === 'error') { onError('实时转写未完成，请刷新核对任务状态。'); cancel() }
  }
  socket.onerror = () => { onError('实时连接失败，请核对状态。'); cancel() }
  socket.onclose = () => {
    void microphone?.cancel(); microphone = null
    if (!cancelled && !completed) onError('实时连接中断，请刷新恢复已完成转写。')
  }
  return { finish, cancel, pushFrame, setMuted: (value: boolean) => { muted = value; microphone?.setMuted(value) } }
}
