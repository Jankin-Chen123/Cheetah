import type { components } from './generated'
import { intakeRequest, type IntakeSession } from './jobIntake'

export type Talent = components['schemas']['TalentView']
export type TalentDetail = components['schemas']['TalentDetail']
export type TalentReceipt = components['schemas']['TalentReceipt']
export type TalentApplication = components['schemas']['Application']
export type TalentApplicationSummary = components['schemas']['ApplicationSummary']
export type RemoteJob = components['schemas']['Job']
export type DirectionAssignment = components['schemas']['DirectionAssignment']
export type DirectionId = DirectionAssignment['direction_id']
export type Direction = { id: DirectionId; label: string }

const mutation = (session: IntakeSession, body: unknown, key?: string): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token, ...(key ? { 'Idempotency-Key': key } : {}) }, body: JSON.stringify(body),
})
export const getDirections = (signal?: AbortSignal) => intakeRequest<{ version: number; items: Direction[] }>('/talent-directions', {}, signal)
export const getTalents = (page: number, q: string, signal?: AbortSignal) => intakeRequest<components['schemas']['TalentPage']>(`/talents?page=${page}&q=${encodeURIComponent(q)}`, {}, signal)
export const getTalent = (id: string, signal?: AbortSignal) => intakeRequest<TalentDetail>(`/talents/${encodeURIComponent(id)}`, {}, signal)
export const getTalentApplication = (id: string, signal?: AbortSignal) => intakeRequest<TalentApplication>(`/applications/${encodeURIComponent(id)}`, {}, signal)
export const getTalentArtifact = (id: string, version: number, signal?: AbortSignal) => intakeRequest<components['schemas']['Artifact']>(`/artifacts/${encodeURIComponent(id)}?version=${version}`, {}, signal)
export const getRoutedApplications = (jobId: string, page: number, signal?: AbortSignal) => intakeRequest<components['schemas']['ApplicationPage']>(`/jobs/${encodeURIComponent(jobId)}/applications?page=${page}`, {}, signal)
export async function getAllRoutedApplications(jobId: string, signal?: AbortSignal) {
  const items = new Map<string, TalentApplicationSummary>()
  for (let page = 1; ; page++) {
    const result = await intakeRequest<components['schemas']['ApplicationPage']>(`/jobs/${encodeURIComponent(jobId)}/applications?page=${page}&page_size=100`, {}, signal)
    result.items.forEach(item => items.set(item.id, item))
    if (!result.items.length || page * result.page_size >= result.total) break
  }
  return [...items.values()]
}
export const getRoutingJob = (id: string, signal?: AbortSignal) => intakeRequest<RemoteJob>(`/jobs/${encodeURIComponent(id)}`, {}, signal)
export const saveJobDirections = (job: RemoteJob, directions: DirectionId[], session: IntakeSession) => intakeRequest<RemoteJob>(`/jobs/${encodeURIComponent(job.id)}`, { ...mutation(session, { expected_revision: job.revision, routing_directions: directions }), method: 'PATCH' })
export const saveTalentDirections = (talent: TalentDetail, directions: DirectionAssignment[], reason: string, session: IntakeSession) => intakeRequest<TalentDetail>(`/talents/${encodeURIComponent(talent.id)}/directions`, { ...mutation(session, { expected_revision: talent.revision, directions, reason }), method: 'PATCH' })
export const startTalentScreening = (id: string, revision: number, session: IntakeSession, key: string) => intakeRequest<components['schemas']['TaskAccepted']>(`/applications/${encodeURIComponent(id)}/start-screening`, mutation(session, { expected_revision: revision, reason: '猎头从已分流候选人列表启动深度初筛' }, key))
export const importTalentText = (text: string, session: IntakeSession, key: string) => intakeRequest<TalentReceipt>('/talent-imports', mutation(session, { execution_mode: 'live', items: [{ client_item_id: 'text', name: '粘贴简历.txt', text }] }, key))
export function importTalentFiles(files: File[], session: IntakeSession, key: string) {
  const form = new FormData()
  form.set('manifest', JSON.stringify({ execution_mode: 'live', items: files.map((file, index) => ({ client_item_id: String(index), filename: file.name })) }))
  files.forEach(file => form.append('files', file, file.name))
  return intakeRequest<TalentReceipt>('/talent-imports', { method: 'POST', headers: { 'X-CSRF-Token': session.csrf_token, 'Idempotency-Key': key }, body: form })
}
