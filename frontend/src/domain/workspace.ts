import type { JobDocument, JobGeneration, JobMaterial } from './jobDocuments'

export type SourceMode = 'mock' | 'manual' | 'real'
export type Screening = 'pending' | 'passed' | 'unknown' | 'rejected'
export type CallState = 'waiting' | 'active' | 'stopping' | 'unknown' | 'completed' | 'cancelled'
export type ReportState = 'pending' | 'approved' | 'rejected' | 'expired'
export type ArtifactType = 'D01' | 'D02' | 'D03' | 'D04' | 'D05' | 'D06' | 'D07' | 'D08' | 'D09' | 'D10'

export interface RuleDraft {
  screening: string
  interview: string
  recommendation: string
}
export interface Job {
  id: string
  title: string
  company: string
  location: string
  salary: string
  material: string
  status: 'draft' | 'published'
  version: number
  draft?: RuleDraft
  rules: RuleDraft
  ruleHistory?: { version: number; rules: RuleDraft }[]
  source: SourceMode
  materialInput?: JobMaterial
  providedFields?: { title?: string; company?: string }
  generation?: JobGeneration
  documents?: JobDocument[]
  updatedAt?: string
}
export interface Evidence {
  id: string
  version: number
  title: string
  quote: string
  location: string
  kind: '自述' | '未知' | '模拟访谈'
  source: SourceMode
}
export interface Artifact {
  id: string
  type: ArtifactType
  version: number
  status: 'valid' | 'expired'
  ruleVersion: number
  source: SourceMode
  upstreamSources: SourceMode[]
  inputRefs: string[]
  content: string
  unknowns: string[]
  evidenceIds: string[]
  createdAt: string
}
export interface Report {
  id: string
  version: number
  state: ReportState
  content: string
  reviewReason?: string
  exports: number
}
export interface Candidate {
  id: string
  jobId: string
  matchedJobIds?: string[]
  applications?: CandidateApplication[]
  name: string
  role: string
  experience: string
  education: string
  screening: Screening
  ruleVersion: number
  source: SourceMode
  summary: string
  gaps: string[]
  artifacts: Artifact[]
  evidence: Evidence[]
  call?: { id: string; state: CallState; reason: string; attempts: number }
  evaluation?: 'recommended' | 'insufficient' | 'rejected'
  reports: Report[]
  timeline: { title: string; detail: string; at: string }[]
}
// A person's other applications own their workflow data, including approvals.
export type CandidateApplication = Pick<Candidate, 'jobId' | 'screening' | 'ruleVersion' | 'source' | 'gaps' | 'artifacts' | 'evidence' | 'call' | 'evaluation' | 'reports' | 'timeline'>
export interface ImportRecord {
  id: string
  jobId: string
  name: string
  fingerprint: string
  state: 'waiting' | 'failed'
  reason: string
}

export const artifactNames: Record<ArtifactType, string> = {
  D01: '岗位画像', D02: '面试评估表', D03: '结构化简历', D04: '公司与项目研究',
  D05: '候选人初步画像', D06: '初筛匹配报告', D07: '结构化面试提纲',
  D08: '电话访谈纪要', D09: '内部面试评估', D10: '企业 HR 推荐报告',
}
export const screeningLabels: Record<Screening, string> = {
  pending: '待评估', passed: '进入电话', unknown: '信息不足', rejected: '暂不推荐',
}
export const callLabels: Record<CallState, string> = {
  waiting: '等待条件', active: '沟通进行中', stopping: '停止请求中', unknown: '外部结果待核对',
  completed: '已结束', cancelled: '已取消',
}
export const reportLabels: Record<ReportState, string> = {
  pending: '待审核', approved: '已批准', rejected: '已退回', expired: '已失效',
}
export const now = () => new Date().toISOString()
export const uid = (prefix: string) => `${prefix}-${crypto.randomUUID()}`
export const displayTime = (value: string) => new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  hour12: false,
}).format(new Date(value))

export function publishRules(job: Job, rules: RuleDraft): Job {
  if ([rules.screening, rules.interview, rules.recommendation].some(value => !value?.trim())) throw new Error('请分别填写初筛、面试与推荐标准。')
  if (!job.material.trim()) throw new Error('请先补充岗位原始需求。')
  const history = job.ruleHistory ?? (job.version ? [{ version: job.version, rules: { ...job.rules } }] : [])
  const version = job.version + 1
  return { ...job, rules: { ...rules }, draft: undefined, version, status: 'published', ruleHistory: [...history, { version, rules: { ...rules } }] }
}

export function canExport(candidate: Candidate, report: Report): boolean {
  const current = candidate.reports.at(-1)
  return candidate.evaluation === 'recommended' && report.state === 'approved' &&
    current?.version === report.version && current.state === 'approved' && current.content === report.content &&
    candidate.artifacts.some(a => a.type === 'D10' && a.version === report.version && a.status === 'valid')
}

export function reviewReport(candidate: Candidate, expectedVersion: number, action: 'approve' | 'reject', reason: string): Candidate {
  const report = candidate.reports.at(-1)
  if (!report || report.version !== expectedVersion) throw new Error('报告版本已变化，请重新查看当前版本。')
  if (candidate.evaluation !== 'recommended') throw new Error('内部评估未达推荐条件，不能批准推荐报告。')
  if (report.state !== 'pending' || !candidate.artifacts.some(a => a.type === 'D10' && a.version === expectedVersion && a.status === 'valid')) {
    throw new Error('只有当前有效的待审核版本可以审核。')
  }
  if (!reason.trim()) throw new Error('请填写审核意见。')
  return {
    ...candidate,
    reports: candidate.reports.map(r => r.version === expectedVersion ? {
      ...r, state: action === 'approve' ? 'approved' : 'rejected', reviewReason: reason.trim(),
    } : r),
    timeline: [...candidate.timeline, { title: action === 'approve' ? '模拟批准推荐报告' : '模拟退回推荐报告', detail: `v${expectedVersion} · ${reason.trim()}`, at: now() }],
  }
}

export function reviseReport(candidate: Candidate, expectedVersion: number, content: string, reason: string): Candidate {
  const previous = candidate.reports.at(-1)
  if (!previous || previous.version !== expectedVersion || previous.state === 'expired') throw new Error('报告版本已变化。')
  if (candidate.evaluation !== 'recommended') throw new Error('当前评估不满足推荐条件。')
  if (!content.trim() || !reason.trim()) throw new Error('修订内容和原因不能为空。')
  const version = previous.version + 1
  const artifact = candidate.artifacts.find(a => a.type === 'D10' && a.version === previous.version)
  if (!artifact) throw new Error('缺少推荐报告产物。')
  return {
    ...candidate,
    reports: [...candidate.reports.map(r => ({ ...r, state: 'expired' as const })), {
      id: previous.id, version, state: 'pending', content: content.trim(), exports: 0,
    }],
    artifacts: [...candidate.artifacts.map(a => a.type === 'D10' ? { ...a, status: 'expired' as const } : a), {
      ...artifact, version, status: 'valid', content: content.trim(), source: 'manual',
      upstreamSources: [...new Set([...artifact.upstreamSources, artifact.source])],
      inputRefs: [...artifact.inputRefs, `${artifact.id}@v${previous.version}`], createdAt: now(),
    }],
    timeline: [...candidate.timeline, { title: '推荐报告保存新版本', detail: `v${version} 待重审，旧批准失效 · ${reason.trim()}`, at: now() }],
  }
}

export function requestStop(candidate: Candidate): Candidate {
  if (!candidate.call || !['active', 'waiting'].includes(candidate.call.state)) throw new Error('当前电话状态不允许此操作；结果不明时须先核对。')
  const active = candidate.call.state === 'active'
  return {
    ...candidate, call: {
      ...candidate.call, state: active ? 'stopping' : 'cancelled',
      reason: active ? '已模拟发送停止请求，等待适配器确认；尚未确认结束。' : '本地模拟队列已取消，未拨号。',
    }, timeline: [...candidate.timeline, { title: active ? '模拟请求停止' : '取消模拟排队', detail: '未调用真实电话接口', at: now() }],
  }
}

export function reportMarkdown(candidate: Candidate, report: Report, job: Job): string {
  if (!canExport(candidate, report)) throw new Error('只能导出当前有效且已批准的版本。')
  if (candidate.jobId !== job.id) throw new Error('推荐报告与所选岗位不一致。')
  return `# 【模拟演示 · 不用于真实交付】候选人推荐报告\n\n候选人：${candidate.name}\n岗位：${job.title}\n版本：v${report.version}\n来源：虚构材料 / 模拟访谈 / 人工修订（如有），无真实模型或研究结果\n规则包：v${candidate.ruleVersion}（测试规则）\n\n${report.content}\n\n## 待核实事项\n${candidate.gaps.map(g => `- ${g}`).join('\n') || '- 无新增事项（仅限模拟样例）'}\n\n审核意见：${report.reviewReason}\n\n仅下载至本地，未发送给 HR。\n`
}

export function addImport(records: ImportRecord[], record: ImportRecord): ImportRecord[] {
  if (records.some(r => r.jobId === record.jobId && r.fingerprint === record.fingerprint && r.state !== 'failed')) {
    throw new Error(`${record.name} 与该岗位已暂存的材料内容相同，已阻止重复导入。`)
  }
  return [...records, record]
}
