export interface Artifact {
  id: string; type: string; version: number; revision: number; valid: boolean
  review_status: string; content: Record<string, unknown>
  provenance: Record<string, unknown>
  input_refs: { kind: string; id: string; version: number }[]
}
export interface CallCase {
  id: string; revision: number; status: string; stop_status: string
  candidate_id: string; job_id: string; fixture_only: boolean
  inherited_source_modes: string[]; upstream_refs: Record<string, { artifact_id: string; version: number }>
  application_id: string; session: Record<string, unknown>; artifacts?: Artifact[]
  active_tasks?: { id: string; status: string; step: string }[]
  failed_tasks?: { id: string; step: string; input_revision: number; status: string; error_code: string | null; retry_count: number }[]
}
export interface CareerConfirmationInput {
  expected_revision: number
  minutes_id: string
  minutes_version: number
  field_path: string
  value: string
  answer_id: string
  quote: string
  reason: string
  conflict_index: number | null
}
export interface CareerConfirmation extends Pick<CareerConfirmationInput, 'field_path' | 'value' | 'answer_id' | 'quote' | 'reason' | 'conflict_index'> {
  id: string
  answer_version: number
  minutes_ref: { id: string; version: number }
  resume_ref?: { artifact_id?: string; version: number }
  conflict_text?: string | null
}
export interface CareerRevocation { confirmation_id: string; reason: string }
export class OutreachError extends Error {
  readonly status: number
  readonly code: string
  constructor(status: number, code: string) {
    super(`请求失败 ${status} · ${code}；请检查当前状态与配置`)
    this.status = status
    this.code = code
  }
}
export const confirmCareerField = (id: string, input: CareerConfirmationInput) =>
  api<{ revision: number; confirmation: CareerConfirmation }>(`/calls/${id}/career-confirmations`, input)
export const revokeCareerField = (id: string, confirmationId: string, input: { expected_revision: number; reason: string }) =>
  api<{ revision: number }>(`/calls/${id}/career-confirmations/${confirmationId}/revoke`, input)
export const regenerateRecommendation = (id: string, revision: number) =>
  api(`/calls/${id}/recommendation`, { expected_revision: revision })
let csrf = ''
let authGeneration = 0
export function syncOutreachSession(token: string) {
  if (csrf !== token) { csrf = token; authGeneration += 1 }
}
export async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const requestGeneration = authGeneration
  const response = await fetch(`/api/v1${path}`, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    const failure: unknown = await response.json().catch(() => null)
    const rawCode = failure && typeof failure === 'object' ? Reflect.get(failure, 'code') ?? Reflect.get(failure, 'detail') : null
    const code = typeof rawCode === 'string' && /^[A-Z][A-Z0-9_]{0,99}$/.test(rawCode) ? rawCode : `HTTP_${response.status}`
    if (response.status === 401 && requestGeneration === authGeneration) {
      csrf = ''; authGeneration += 1
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('cheetah:session-expired'))
    }
    throw new OutreachError(response.status, code)
  }
  if (response.status === 204) {
    if (path === '/auth/logout') { csrf = ''; authGeneration += 1 }
    return undefined as T
  }
  const value = await response.json()
  if (value.csrf_token && (path === '/auth/login' || requestGeneration === authGeneration)) {
    csrf = value.csrf_token; authGeneration += 1
  }
  return value as T
}
export async function download(artifact: Artifact, format?: 'markdown' | 'docx') {
  const internal = ['D07', 'D08', 'D09'].includes(artifact.type)
  format ??= internal ? 'docx' : 'markdown'
  if (internal && format !== 'docx') throw new Error('内部产物仅支持 Word 下载')
  const category = artifact.type === 'D07' ? 'outlines' : artifact.type === 'D08' ? 'minutes' : artifact.type === 'D09' ? 'evaluations' : 'reports'
  const response = await fetch(`/api/v1/${category}/${artifact.id}/export?version=${artifact.version}&format=${format}`, {
    credentials: 'same-origin',
    headers: { 'X-Export-Request-ID': crypto.randomUUID() },
  })
  const expectedType = format === 'docx' ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' : 'text/markdown'
  if (!response.ok || !response.headers.get('Content-Type')?.includes(expectedType)) {
    throw new Error(internal ? '内部 Word 下载未完成，请检查登录状态及当前产物版本是否有效' : '下载未完成，请检查报告版本批准、有效性及候选人客户分享许可')
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  const label = internal ? { D07: '面试准备稿', D08: '内部信息提取', D09: '内部面试评估' }[artifact.type] : '推荐报告'
  anchor.href = url; anchor.download = `${label}-v${artifact.version}.${format === 'docx' ? 'docx' : 'md'}`; anchor.click()
  URL.revokeObjectURL(url)
}
