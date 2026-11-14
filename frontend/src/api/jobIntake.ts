import type { components } from './generated'
import type { RemoteArtifactInput } from '../domain/jobDocuments'

const baseUrl = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
export type IntakeSession = components['schemas']['Session']
export interface IntakeRemoteJob {
  id: string; revision: number; active_task_ids: string[];
  d01_ref?: { artifact_id: string; version: number } | null;
  d02_ref?: { artifact_id: string; version: number } | null
}
export interface IntakeTask {
  id: string; kind: string; status: string; retryable: boolean;
  error?: { message: string; code: string } | null;
  result_refs: { artifact_id: string; version: number }[];
  continuation_task_id?: string | null;
  poll_after_ms?: number | null
}
export class IntakeApiError extends Error {
  code: string
  status: number
  requestId?: string
  constructor(message: string, code: string, status: number, requestId?: string) {
    super(message); this.name = 'IntakeApiError'; this.code = code; this.status = status; this.requestId = requestId
  }
}

async function request<T>(path: string, options: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${baseUrl}${path}`, { ...options, credentials: 'same-origin', signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000) })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new IntakeApiError('服务暂不可用，请检查后端连接。', 'NETWORK_UNAVAILABLE', 0)
  }
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 && !['/auth/login', '/auth/me'].includes(path)) window.dispatchEvent(new Event('cheetah:session-expired'))
    const payload = body && typeof body === 'object' ? body as Record<string, unknown> : {}
    throw new IntakeApiError(typeof payload.message === 'string' ? payload.message : response.status >= 500 ? '后端服务暂不可用，材料已保存在本机。' : '请求失败，请稍后重试。', typeof payload.code === 'string' ? payload.code : `HTTP_${response.status}`, response.status, typeof payload.request_id === 'string' ? payload.request_id : undefined)
  }
  if (response.status === 204) return undefined as T
  if (!body || typeof body !== 'object') throw new IntakeApiError('服务返回格式不正确。', 'INVALID_RESPONSE', response.status)
  return body as T
}
const json = (body: unknown, session: IntakeSession, key?: string): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token, ...(key ? { 'Idempotency-Key': key } : {}) }, body: JSON.stringify(body) })

export const getIntakeSession = (signal?: AbortSignal) => request<IntakeSession>('/auth/me', {}, signal)
export const loginIntake = (username: string, password: string, signal?: AbortSignal) => request<IntakeSession>('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) }, signal)
export const registerAccount = (body: components['schemas']['RegisterInput'], signal?: AbortSignal) => request<IntakeSession>('/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }, signal)
export const logoutAccount = (session: IntakeSession) => request<void>('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': session.csrf_token } })
export const createIntakeRemoteJob = (transcript: string, session: IntakeSession, key: string, signal?: AbortSignal) => request<IntakeRemoteJob>('/jobs', json({ material_text: transcript }, session, key), signal)
export const analyzeIntakeJob = (job: IntakeRemoteJob, session: IntakeSession, key: string, signal?: AbortSignal) => request<{ task_id: string }>(`/jobs/${encodeURIComponent(job.id)}/analyze`, json({ expected_revision: job.revision, execution_mode: 'live' }, session, key), signal)
export const getIntakeJob = (id: string, signal?: AbortSignal) => request<IntakeRemoteJob>(`/jobs/${encodeURIComponent(id)}`, {}, signal)
export const getIntakeTask = (id: string, signal?: AbortSignal) => request<IntakeTask>(`/tasks/${encodeURIComponent(id)}`, {}, signal)
export async function getIntakeArtifact(artifactRef: { artifact_id: string; version: number }, signal?: AbortSignal): Promise<RemoteArtifactInput> {
  const result = await request<RemoteArtifactInput>(`/artifacts/${encodeURIComponent(artifactRef.artifact_id)}?version=${artifactRef.version}`, {}, signal)
  if (!['D01', 'D02'].includes(result.type) || result.status !== 'valid' || result.artifact_id !== artifactRef.artifact_id || result.version !== artifactRef.version || !result.structured_content || !result.provenance || !Array.isArray(result.provenance.inherited_source_modes) || !['live', 'mock', 'manual'].includes(result.provenance.source_mode)) {
    throw new IntakeApiError('岗位产物与请求版本不一致。', 'INVALID_ARTIFACT', 200)
  }
  return result
}
