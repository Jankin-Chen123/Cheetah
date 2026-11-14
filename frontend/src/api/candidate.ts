export const processingPurposes = [
  ['formal_interview', '参加本次 AI 招聘面试'],
  ['transcription', '将本次语音转写为文字问答记录'],
  ['extraction', '从本次问答提取岗位相关职业信息'],
  ['evaluation', '按当前岗位标准生成机构内部面试评估'],
] as const

export interface CandidateSession {
  processing_permissions?: Record<string, string>
  client_sharing?: { client_label: string; status: string } | null
  voice_id: string
  voices: { id: string; label: string }[]
  practice_available: boolean
  interview_limits: { max_seconds: number; max_rounds: number; max_turn_seconds: number }
  elapsed_seconds: number
  spoken_prompt: string | null
  revision: number
  status: string
  stop_status: string
  material: { job_title: string | null; requirements: string[]; salary: unknown; company_introduction: unknown }
  material_sha256: string
  preflight: { interested: boolean | null; confirmed: boolean | null; briefing_presented?: boolean | null }
  question: string | null
  decision_task?: { status: string; error_code?: string | null; phase?: string | null } | null
  decision_status: string | null
  transcription?: { status: string; task_id: string; text: string | null; error_code?: string }
}

export async function candidateSpeech(caseId: string, token: string, revision: number, preview = false, signal?: AbortSignal, farewell = false): Promise<AudioBuffer> {
  const response = await fetch(`/api/v1/candidate/calls/${encodeURIComponent(caseId)}/speech`, {
    method: 'POST', credentials: 'omit', cache: 'no-store', signal,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_revision: revision, preview, farewell }),
  })
  if (!response.ok) throw new Error(`问题播报未完成（${response.status}）`)
  const result = await response.json() as { pcm_base64: string; sample_rate: number }
  const raw = atob(result.pcm_base64)
  const bytes = Uint8Array.from(raw, char => char.charCodeAt(0))
  const view = new DataView(bytes.buffer)
  const buffer = new AudioBuffer({ numberOfChannels: 1, length: bytes.length / 2, sampleRate: result.sample_rate })
  const channel = buffer.getChannelData(0)
  for (let i = 0; i < channel.length; i++) channel[i] = view.getInt16(i * 2, true) / 32768
  return buffer
}

async function candidateCommand<T>(caseId: string, token: string, action: string, body: object): Promise<T> {
  const response = await fetch(`/api/v1/candidate/calls/${encodeURIComponent(caseId)}/${action}`, {
    method: 'POST', credentials: 'omit', cache: 'no-store',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`操作未完成（${response.status}），请核对邀请有效期及当前状态。`)
  return response.json() as Promise<T>
}

export const setProcessingPermission = (caseId: string, token: string, revision: number, purpose: string, authorized: boolean) =>
  candidateCommand<CandidateSession>(caseId, token, 'processing-permissions', { expected_revision: revision, purpose, authorized })

export const setClientSharing = (caseId: string, token: string, revision: number, authorized: boolean) =>
  candidateCommand<CandidateSession>(caseId, token, 'client-sharing', { expected_revision: revision, authorized })

export const chooseCandidateVoice = (caseId: string, token: string, revision: number, voiceId: string) =>
  candidateCommand<CandidateSession>(caseId, token, 'voice', { expected_revision: revision, voice_id: voiceId })

export const practiceCandidate = (caseId: string, token: string, requestId: string) =>
  candidateCommand<{ case_id: string; token: string; session: CandidateSession }>(caseId, token, 'practice', { request_id: requestId })

export async function candidateRequest(caseId: string, token: string, body?: object): Promise<CandidateSession> {
  const response = await fetch(`/api/v1/candidate/calls/${encodeURIComponent(caseId)}`, {
    method: body ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
    cache: 'no-store',
    credentials: 'omit',
  })
  if (!response.ok) throw new Error(response.status === 401 ? '邀请已过期或失效，请联系邀请人。' : `操作未完成（${response.status}），请刷新状态后重试。`)
  return response.json() as Promise<CandidateSession>
}

export async function transcribeCandidate(caseId: string, token: string, revision: number, pcm: Uint8Array): Promise<{ text: string; transcription_task_id: string }> {
  let binary = ''
  for (let offset = 0; offset < pcm.length; offset += 8192) binary += String.fromCharCode(...pcm.subarray(offset, offset + 8192))
  const response = await fetch(`/api/v1/candidate/calls/${encodeURIComponent(caseId)}/transcription`, {
    method: 'POST', credentials: 'omit', cache: 'no-store',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_revision: revision, pcm_base64: btoa(binary) }),
  })
  if (!response.ok) throw new Error(`转写未完成（${response.status}），请刷新并核对状态，不要反复提交。`)
  return response.json() as Promise<{ text: string; transcription_task_id: string }>
}

export async function sendBriefingEmail(caseId: string, token: string, email: string, requestId: string) {
  const response = await fetch(`/api/v1/candidate/calls/${encodeURIComponent(caseId)}/briefing-email`, {
    method: 'POST', credentials: 'omit', cache: 'no-store',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, request_id: requestId, consent: true }),
  })
  if (response.status === 503) throw new Error('发件服务尚未配置，暂时无法发送邮件。')
  if (!response.ok) throw new Error('邮件请求未完成，请核对邮箱或联系邀请人。')
  return response.json() as Promise<{ task_id: string; status: string; error_code?: string }>
}

export async function streamCandidateSpeech(caseId: string, token: string, revision: number,
  signal: AbortSignal, onChunk: (buffer: AudioBuffer) => void) {
  const response = await fetch(`/api/v1/candidate/calls/${encodeURIComponent(caseId)}/speech-stream`, {
    method: 'POST', credentials: 'omit', cache: 'no-store', signal,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_revision: revision }),
  })
  if (!response.ok || !response.body) throw new Error('语音连接未完成')
  const reader = response.body.getReader(); const decoder = new TextDecoder()
  let pending = ''; let completed = false; let carry = new Uint8Array(0)
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      pending += decoder.decode(value, { stream: true })
      let split: number
      while ((split = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, split); pending = pending.slice(split + 1)
        if (!line) continue
        const message = JSON.parse(line) as { type: string; pcm?: string; sample_rate?: number }
        if (message.type === 'error') throw new Error('语音生成暂时未完成')
        if (message.type === 'completed') { completed = true; continue }
        const raw = atob(message.pcm ?? '')
        const bytes = new Uint8Array(carry.length + raw.length); bytes.set(carry)
        for (let i = 0; i < raw.length; i++) bytes[carry.length + i] = raw.charCodeAt(i)
        const length = bytes.length - bytes.length % 2
        carry = bytes.slice(length)
        if (!length) continue
        const view = new DataView(bytes.buffer)
        const buffer = new AudioBuffer({ numberOfChannels: 1, length: length / 2, sampleRate: message.sample_rate ?? 24000 })
        const channel = buffer.getChannelData(0)
        for (let i = 0; i < channel.length; i++) channel[i] = view.getInt16(i * 2, true) / 32768
        onChunk(buffer)
      }
    }
    if (!completed) throw new Error('语音连接中断')
  } finally { await reader.cancel(); reader.releaseLock() }
}
