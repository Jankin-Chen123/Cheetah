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
let csrf = ''
let authGeneration = 0
export async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const requestGeneration = authGeneration
  const response = await fetch(`/api/v1${path}`, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    const failure: unknown = await response.json().catch(() => null)
    const code = failure && typeof failure === 'object' && 'code' in failure &&
      typeof failure.code === 'string' && /^[A-Z][A-Z0-9_]{0,99}$/.test(failure.code)
      ? failure.code : `HTTP_${response.status}`
    if (response.status === 401 && requestGeneration === authGeneration) {
      csrf = ''; authGeneration += 1
    }
    throw new Error(`请求失败 ${response.status} · ${code}；请检查当前状态与配置`)
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
export async function download(artifact: Artifact, format: 'markdown' | 'docx' = 'markdown') {
  const internal = ['D07', 'D08', 'D09'].includes(artifact.type)
  const category = artifact.type === 'D07' ? 'outlines' : artifact.type === 'D08' ? 'minutes' : artifact.type === 'D09' ? 'evaluations' : 'reports'
  const response = await fetch(`/api/v1/${category}/${artifact.id}/export?version=${artifact.version}&format=${format}`, {
    credentials: 'same-origin',
    headers: { 'X-Export-Request-ID': crypto.randomUUID() },
  })
  const expectedType = format === 'docx' ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' : 'text/markdown'
  if (!response.ok || !response.headers.get('Content-Type')?.includes(expectedType)) {
    throw new Error('下载未完成，请检查报告版本批准、有效性及候选人客户分享许可')
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  const label = internal ? { D07: '面试准备稿', D08: '内部信息提取', D09: '内部面试评估' }[artifact.type] : '推荐报告'
  anchor.href = url; anchor.download = `${label}-v${artifact.version}.${format === 'docx' ? 'docx' : 'md'}`; anchor.click()
  URL.revokeObjectURL(url)
}
