export interface CandidateSession {
  spoken_prompt: string | null
  revision: number
  status: string
  stop_status: string
  material: { job_title: string | null; requirements: string[]; salary: unknown; company_introduction: unknown }
  material_sha256: string
  preflight: { interested: boolean | null; confirmed: boolean | null }
  question: string | null
  decision_status: string | null
  transcription?: { status: string; task_id: string; text: string | null; error_code?: string }
}

export async function candidateSpeech(caseId: string, token: string, revision: number): Promise<AudioBuffer> {
  const response = await fetch(`/api/v1/candidate/calls/${encodeURIComponent(caseId)}/speech`, {
    method: 'POST', credentials: 'omit', cache: 'no-store',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_revision: revision }),
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
