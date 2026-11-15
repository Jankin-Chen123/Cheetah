import type { Job, SourceMode } from './workspace'

export const JOB_GROUPS: Record<string, string[]> = {
  客户企业信息: ['客户企业名称', '客户企业简称', '客户所属行业', '对接 HR', '用人部门'],
  '一、基础信息': ['岗位名称', '所属部门', '直属上级岗位', '下属人数', '工作时间'],
  '二、薪酬与考核': ['试用期薪资', '转正薪资', '固定薪资与浮动薪资', '奖金与绩效', '薪资发放周期', '浮动薪资与绩效指标挂钩'],
  '三、任职要求': ['学历要求', '经验要求', '技能要求—硬技能', '技能要求—软技能', '行业经验', '项目经验', '行为特质'],
  '四、工作目标与核心成果': ['短期工作目标', '长期工作目标', '核心成果'],
  '五、团队与部门架构': ['团队结构', '跨部门协作需求'],
  '六、潜在挑战与成长机会': ['工作挑战', '成长机会'],
  '七、目标竞品公司': ['目标竞品公司'],
  '八、工作文化与环境': ['团队文化', '工作地点', '工作地点与流动性', '文化契合度'],
  '九、加分项与其他要求': ['加分项', '隐性门槛', '其他要求'],
}
export const JD_SECTIONS = ['岗位职责', '任职要求', '加分条件']
export const ANCHORS = ['1—2 分', '3—4 分', '5—6 分', '7—8 分', '9—10 分']

export interface DocumentRow { id: string; cells: string[]; group?: boolean }
export interface DocumentTable {
  id: string; title: string; headers: string[]; widths: number[];
  rows: DocumentRow[]; readonlyColumns?: number[]
}
export interface JobDocument {
  id: string; type: 'D01' | 'D02'; title: string; version: number;
  status: 'draft' | 'confirmed' | 'superseded' | 'needs_review'; source: SourceMode;
  inheritedSources: SourceMode[]; tables: DocumentTable[]; unknowns: string[];
  createdAt: string; changeReason: string; confirmedAt?: string; remoteRef?: { artifact_id: string; version: number }
}
export interface JobMaterial {
  kind: 'transcript' | 'audio'; transcript: string;
  audio?: MaterialFile;
  audioTranscriptionRef?: { id: string; revision: number };
  textFile?: MaterialFile;
  originalText?: string;
  minutes?: CommunicationMinutes[];
}
export interface MaterialFile { name: string; type: string; size: number; blob: Blob }
export interface CommunicationMinutes {
  text: string; createdAt: string; source: SourceMode; inheritedSources: SourceMode[];
  artifactRef: { artifact_id: string; version: number }; inputText: string;
}
export interface JobGeneration {
  state: 'not_started' | 'waiting_transcript' | 'queued' | 'running' | 'completed' | 'failed' | 'waiting_backend' | 'reconciling';
  error?: string; taskId?: string; remoteJobId?: string; createKey?: string; analyzeKey?: string; analyzeRevision?: number; submitted?: boolean
}
export interface RemoteArtifactInput {
  artifact_id: string; type: 'D01' | 'D02'; version: number;
  status: 'valid' | 'expired' | 'restricted';
  provenance: { source_mode: 'live' | 'mock' | 'manual'; inherited_source_modes: ('live' | 'mock' | 'manual')[] };
  structured_content: Record<string, unknown>; generated_at: string; unknowns: string[]
}

const id = () => crypto.randomUUID()
const time = () => new Date().toISOString()
const row = (cells: string[], group = false): DocumentRow => ({ id: id(), cells, group })
const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const text = (value: unknown, fallback = '未提及'): string => typeof value === 'string' && value.trim() ? value : typeof value === 'number' ? String(value) : fallback
const factText = (value: unknown): string => {
  const fact = object(value)
  return fact.status === 'stated' ? text(fact.value) : fact.status === 'conflict' || fact.note ? '待确认' : '未提及'
}
const source = (value: 'live' | 'mock' | 'manual'): SourceMode => value === 'live' ? 'real' : value

export function createMaterialJob(materialInput: JobMaterial): Job {
  const transcript = materialInput.transcript.trim()
  if (!transcript && !materialInput.audio) throw new Error('请粘贴转写记录或选择录音。')
  return {
    id: `local-job-${id()}`, title: '待识别岗位', company: '待识别企业', location: '', salary: '',
    material: transcript, materialInput: { ...materialInput, originalText: materialInput.originalText ?? materialInput.transcript, transcript },
    status: 'draft', version: 0, rules: { screening: '', interview: '', recommendation: '' },
    source: 'manual', documents: [], updatedAt: time(),
    generation: { state: transcript ? 'not_started' : 'waiting_transcript', createKey: id(), analyzeKey: id() },
  }
}

export function profileTables(fields: Record<string, string>, jd: Record<string, string>): DocumentTable[] {
  return [{
    id: 'profile', title: '', headers: ['字段', '岗位画像提取内容'], widths: [0.27, 0.73], readonlyColumns: [0],
    rows: [
      ...Object.entries(JOB_GROUPS).flatMap(([group, names]) => [row([group, ''], true), ...names.map(name => row([name, fields[name] ?? '未提及']))]),
      row(['招聘 JD 输出｜独立成稿', ''], true), ...JD_SECTIONS.map(name => row([`【${name}】`, jd[name] ?? '未提及'])),
    ],
  }]
}

export function interviewTables(context: Record<string, string>, dimensions: {
  label: string; explanation: string; weight: string; anchors: string
}[]): DocumentTable[] {
  return [
    { id: 'context', title: '一、客户与岗位信息', headers: ['字段', '内容'], widths: [0.27, 0.73], readonlyColumns: [0], rows: ['客户企业名称', '客户企业简称', '客户所属行业', '对接 HR', '用人部门', '岗位名称'].map(name => row([name, context[name] ?? '未提及'])) },
    { id: 'dimensions', title: '二、岗位核心能力面试评估', headers: ['考核维度', '考核指标及解析说明', '权重', '评分标准（1—10 分）', '实际得分', '折算得分'], widths: [0.14, 0.25, 0.07, 0.36, 0.09, 0.09], readonlyColumns: [4, 5], rows: dimensions.map(d => row([d.label, d.explanation, d.weight, d.anchors, '', ''])) },
    { id: 'summary', title: '三、评分汇总', headers: ['字段', '内容'], widths: [0.27, 0.73], readonlyColumns: [0, 1], rows: [row(['维度总数', String(dimensions.length)]), row(['权重合计', weightTotal(dimensions.map(d => d.weight))]), row(['评估状态', '待确认']), row(['综合总分', '']), row(['候选人姓名', '']), row(['已评分权重', ''])] },
  ]
}

export function weightTotal(weights: string[]): string {
  if (!weights.length || weights.some(w => !/^\d+(?:\.\d+)?%$/.test(w.trim()))) return '待确认'
  return `${Number(weights.reduce((sum, w) => sum + Number.parseFloat(w), 0).toFixed(4))}%`
}

export function documentFromArtifact(artifact: RemoteArtifactInput, context: Record<string, string> = {}): JobDocument {
  const content = artifact.structured_content
  let tables: DocumentTable[]
  if (artifact.type === 'D01') {
    const form = object(content.job_form)
    const fields = object(form.fields)
    if (!Object.keys(fields).length) throw new Error('岗位画像缺少标准表单字段，请检查后端 A01 产物。')
    const jd = object(form.jd)
    tables = profileTables(Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, factText(v)])), Object.fromEntries(JD_SECTIONS.map(name => [name, list(jd[name]).map(factText).filter(t => t !== '未提及').map((t, i) => `${i + 1}. ${t}`).join('\n') || '未提及'])))
  } else {
    const rules = object(content.rules)
    const dimensions = list(content.dimensions ?? rules.interview_dimensions).map(value => {
      const d = object(value); const anchors = object(d.anchors)
      return { label: text(d.label, '待确认维度'), explanation: text(d.rubric), weight: typeof d.weight === 'number' ? `${Number((d.weight * 100).toFixed(4))}%` : '待确认', anchors: Object.keys(anchors).length ? ['low', 'limited', 'partial', 'strong', 'excellent'].map((key, i) => `${ANCHORS[i]}：${text(anchors[key], '待补充')}`).join('\n') : text(d.rubric, '待补充') }
    })
    tables = interviewTables(context, dimensions)
  }
  return {
    id: id(), type: artifact.type, title: artifact.type === 'D01' ? '岗位画像' : '岗位面试评估表',
    version: 1, status: 'draft', source: source(artifact.provenance.source_mode),
    inheritedSources: artifact.provenance.inherited_source_modes.map(source), tables,
    unknowns: artifact.unknowns ?? [], createdAt: artifact.generated_at, changeReason: artifact.provenance.source_mode === 'mock' ? '模拟产物，非真实模型结果' : artifact.provenance.source_mode === 'manual' ? '人工产物草案' : '模型生成草案',
    remoteRef: { artifact_id: artifact.artifact_id, version: artifact.version },
  }
}

export function profileValues(document: JobDocument): Record<string, string> {
  return Object.fromEntries(document.tables[0]?.rows.filter(r => !r.group).map(r => [r.cells[0], r.cells[1]]) ?? [])
}
export function currentDocument(job: Job, type: JobDocument['type']): JobDocument | undefined {
  return job.documents?.filter(d => d.type === type).at(-1)
}

export function attachGeneratedDocument(job: Job, document: JobDocument): Job {
  if (job.documents?.some(d => d.remoteRef?.artifact_id === document.remoteRef?.artifact_id && d.remoteRef?.version === document.remoteRef?.version && d.type === document.type && document.remoteRef)) return job
  const previous = currentDocument(job, document.type)
  const changedProfile = document.type === 'D02' && document.remoteRef && currentDocument(job, 'D01')?.source === 'manual'
  const next = { ...document, status: changedProfile ? 'needs_review' as const : document.status, version: (previous?.version ?? 0) + 1 }
  const fields = document.type === 'D01' ? profileValues(document) : {}
  const meaningful = (value: string | undefined) => value && value.length <= 100 && !['未提及', '待确认'].includes(value) ? value : undefined
  return {
    ...job, title: meaningful(fields['岗位名称']) ?? job.title,
    company: meaningful(fields['客户企业名称']) ?? job.company,
    location: meaningful(fields['工作地点']) ?? job.location,
    salary: meaningful(fields['转正薪资']) ?? job.salary,
    source: document.source, updatedAt: time(),
    status: 'draft',
    documents: [...(job.documents ?? []).map(d => {
      if (d.type === document.type) return { ...d, status: 'superseded' as const }
      if (document.type === 'D01' && d.type === 'D02' && d.status !== 'superseded') return { ...d, status: 'needs_review' as const, confirmedAt: undefined }
      return d
    }), next],
  }
}

export function saveDocumentRevision(job: Job, documentId: string, tables: DocumentTable[], reason: string): Job {
  const original = job.documents?.find(d => d.id === documentId)
  if (!original || currentDocument(job, original.type)?.id !== documentId) throw new Error('版本已变化，请重新打开当前版本。')
  if (!reason.trim()) throw new Error('请填写修改原因。')
  const cleaned = structuredClone(tables)
  if (original.type === 'D02') {
    const dimensions = cleaned.find(t => t.id === 'dimensions')
    if (dimensions?.rows.some(r => r.cells[4] || r.cells[5])) throw new Error('面试前不能填写实际得分。')
    const total = weightTotal(dimensions?.rows.map(r => r.cells[2]) ?? [])
    if (!dimensions?.rows.length || total !== '100%') throw new Error('面试维度权重须合计 100%。')
    const summary = cleaned.find(t => t.id === 'summary')
    if (summary) { summary.rows[0].cells[1] = String(dimensions?.rows.length ?? 0); summary.rows[1].cells[1] = total }
  }
  return attachGeneratedDocument(job, { ...original, id: id(), remoteRef: undefined, confirmedAt: undefined, tables: cleaned, source: 'manual', inheritedSources: [...new Set([...original.inheritedSources, original.source])], createdAt: time(), changeReason: reason.trim(), status: 'draft' })
}

export function canExportJobDocument(job: Job, document: JobDocument): boolean {
  return currentDocument(job, document.type)?.id === document.id && ['draft', 'confirmed'].includes(document.status)
}

export function areJobDocumentsConfirmed(job: Job): boolean {
  return currentDocument(job, 'D01')?.status === 'confirmed' && currentDocument(job, 'D02')?.status === 'confirmed'
}

export const jobCardLabels = {
  waiting_backend: '等待后台处理', reconciling: '结果待核对',
  generating: '生成中', waiting_transcript: '待补充文字', unavailable: '待生成',
  failed: '生成失败', review: '待复核', draft: '待确认', published: '已确认',
} as const

export function jobCardState(job: Job, canGenerate: boolean): keyof typeof jobCardLabels {
  const state = job.generation?.state
  if (state === 'waiting_transcript') return 'waiting_transcript'
  if (state === 'failed') return 'failed'
  if (state === 'waiting_backend' || state === 'reconciling') return state
  if (state === 'not_started' || state === 'queued' || state === 'running') return canGenerate ? 'generating' : 'unavailable'
  if (areJobDocumentsConfirmed(job)) return 'published'
  if ((['D01', 'D02'] as const).some(type => currentDocument(job, type)?.status === 'needs_review')) return 'review'
  return 'draft'
}

export function confirmJobDocument(job: Job, documentId: string): Job {
  const document = job.documents?.find(item => item.id === documentId)
  if (!document || currentDocument(job, document.type)?.id !== documentId || document.status === 'superseded') throw new Error('内容已变化，请重新查看当前草案。')
  if (document.status === 'confirmed') return job
  const profile = currentDocument(job, 'D01')
  const values = profile ? profileValues(profile) : {}
  const meaningful = (value: string | undefined) => !!value?.trim() && !['未提及', '待确认', '待识别岗位', '待识别企业'].includes(value.trim())
  if (document.type === 'D01') {
    if (!meaningful(values['岗位名称']) || !meaningful(values['客户企业名称'])) throw new Error('请先补充岗位名称和客户企业名称。')
  } else {
    if (profile?.status !== 'confirmed') throw new Error('请先确认岗位画像。')
    const dimensions = document.tables.find(table => table.id === 'dimensions')?.rows ?? []
    if (!dimensions.length || weightTotal(dimensions.map(row => row.cells[2])) !== '100%' || dimensions.some(row => Number.parseFloat(row.cells[2]) <= 0)) throw new Error('面试维度权重须为正数且合计 100%。')
    const normalize = (value: string) => value.replace(/\s/g, '').replace(/[—–～~]/g, '-')
    if (dimensions.some(row => !meaningful(row.cells[0]) || !meaningful(row.cells[1]) || !ANCHORS.every(band => normalize(row.cells[3]).includes(normalize(band))))) throw new Error('请补齐每个维度的名称、考核说明和五档评分标准。')
    if (dimensions.some(row => row.cells[4] || row.cells[5])) throw new Error('面试前不能填写实际得分。')
    const context = document.tables.find(table => table.id === 'context')
    if (context?.rows.some(row => meaningful(values[row.cells[0]]) && row.cells[1] !== values[row.cells[0]])) throw new Error('面试表的客户或岗位信息与画像不一致，请先修改。')
  }
  const confirmedAt = time()
  return { ...job, updatedAt: confirmedAt, documents: job.documents?.map(item => item.id === documentId ? { ...item, status: 'confirmed', confirmedAt } : item) }
}

export function demoJobDocuments(job: Job): JobDocument[] {
  const values = { 客户企业名称: job.company, 岗位名称: job.title, 工作地点: job.location || '未提及', 转正薪资: job.salary || '未提及', 项目经验: '企业协作产品完整交付经历（虚构）' }
  const stamp = { version: 1, status: 'draft' as const, source: 'mock' as const, inheritedSources: ['mock' as const], createdAt: '2026-11-13T02:20:00Z', changeReason: '虚构示例，非模型生成' }
  return [
    { ...stamp, id: `${job.id}-document-D01`, type: 'D01', title: '岗位画像', tables: profileTables(values, { 岗位职责: '1. 负责企业协作产品的需求调研与交付（虚构）。', 任职要求: '1. 有 B 端产品交付经历（虚构）。', 加分条件: '未提及' }), unknowns: ['试用期目标未提及'] },
    { ...stamp, id: `${job.id}-document-D02`, type: 'D02', title: '岗位面试评估表', tables: interviewTables(values, [
      { label: '问题定义与研究', explanation: '结合具体案例说明问题、证据和决策过程（虚构）。', weight: '50%', anchors: ANCHORS.map((band, i) => `${band}：${['未说明问题依据', '仅描述需求表象', '能说明问题和部分证据', '用研究证据解释判断', '对比多种解释并验证关键假设'][i]}（虚构标准）`).join('\n') },
      { label: '个人职责与协作', explanation: '区分个人贡献和团队实现，说明协作边界（虚构）。', weight: '50%', anchors: ANCHORS.map((band, i) => `${band}：${['无法说明本人职责', '职责描述笼统', '能区分主要职责', '有具体决策与协作案例', '能清晰解释职责、取舍及复盘'][i]}（虚构标准）`).join('\n') },
    ]), unknowns: ['标准仅为虚构示例，待确认'] },
  ]
}
