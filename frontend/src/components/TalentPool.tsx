import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Descriptions, Drawer, Empty, Input, Select, Space, Table, Tag } from 'antd'
import { IntakeApiError, type IntakeSession } from '../api/jobIntake'
import {
  getDirections, getTalents, getTalent, getTalentApplication, getTalentArtifact,
  getAllRoutedApplications, getRoutingJob, saveJobDirections, saveTalentDirections,
  startTalentScreening,
  type Talent, type TalentDetail, type DirectionId,
} from '../api/talentPool'
import { Icon, PageHeading } from './ui'
import IntakeResult from './IntakeResult'
import MatchedJobs from './MatchedJobs'
import { talentMatchedJobs } from '../domain/talentMatches'
import CandidateJobFilter from './CandidateJobFilter'
import { applicationProgress, candidateProgressLabels } from '../domain/candidateProgress'
import CandidateProgressTag from './CandidateProgressTag'
import { artifactNames } from '../domain/workspace'

function useRemote<T>(load: (signal: AbortSignal) => Promise<T>, refresh = 0) {
  const [data, setData] = useState<T>()
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    let running = false
    async function update() {
      if (running || controller.signal.aborted) return
      running = true
      try {
        if (!document.hidden) {
          const value = await load(controller.signal)
          if (!controller.signal.aborted) { setData(value); setError('') }
        }
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取失败，请刷新重试。')
      } finally {
        running = false
        if (!controller.signal.aborted) timer = setTimeout(() => { void update() }, 5000)
      }
    }
    const visible = () => { if (!document.hidden) { clearTimeout(timer); void update() } }
    void update()
    document.addEventListener('visibilitychange', visible)
    return () => { controller.abort(); clearTimeout(timer); document.removeEventListener('visibilitychange', visible) }
  }, [load, refresh])
  return { data, error }
}

const statusText = (item: Talent) => ({ processing: '提取与分类中', classified: '已分类', unclassified: '待分类', failed: '提取未完成', reconciling: '等待核对提取结果' })[item.classification_state]
const screeningText = (app: { stage: string; screening_result: string }) => app.stage === 'matched' ? '待深度初筛' : ({ pending: '研究与初筛中', passed: '初筛通过', unknown: '信息不足', manual_review: '待人工复核', rejected: '初筛未通过' })[app.screening_result] ?? '处理中'

function ApplicationDetails({ id, session, section, jobId }: { id: string; session: IntakeSession; section?: 'call' | 'reports'; jobId?: string }) {
  const { message } = App.useApp()
  const [refresh, setRefresh] = useState(0)
  const [busy, setBusy] = useState(false)
  const pending = useRef<{ key: string; revision: number } | null>(null)
  const load = useCallback(async (signal: AbortSignal) => {
    const app = await getTalentApplication(id, signal)
    if (app.id !== id || jobId && app.job_id !== jobId) throw new Error('候选人与岗位记录不一致，请重新选择岗位。')
    const types = section === 'call' ? ['D07', 'D08'] : section === 'reports' ? ['D09', 'D10'] : ['D03', 'D04', 'D05', 'D06', 'D07', 'D08', 'D09', 'D10']
    const slots = app.artifact_slots.filter(item => item.state === 'available' && types.includes(item.type) && item.artifact_ref)
    const artifacts = await Promise.all(slots.map(item => getTalentArtifact(item.artifact_ref!.artifact_id, item.artifact_ref!.version, signal)))
    if (section && artifacts.some((artifact, index) => artifact.application_id !== id || artifact.job_id !== app.job_id || artifact.artifact_id !== slots[index].artifact_ref?.artifact_id || artifact.version !== slots[index].artifact_ref?.version || artifact.type !== slots[index].type)) throw new Error('返回内容不属于当前岗位或指定版本，请刷新重试。')
    return { app, artifacts }
  }, [id, jobId, section])
  const { data, error } = useRemote(load, refresh)
  async function start() {
    if (!data || busy) return
    setBusy(true)
    const intent = pending.current ?? { key: crypto.randomUUID(), revision: data.app.revision }
    pending.current = intent
    try {
      await startTalentScreening(id, intent.revision, session, intent.key)
      pending.current = null; setRefresh(value => value + 1)
      void message.success('已启动深度调研与初筛。')
    } catch (reason) {
      if (reason instanceof IntakeApiError && reason.status >= 400 && reason.status < 500) {
        pending.current = null; setRefresh(value => value + 1)
      }
      void message.error(reason instanceof Error ? reason.message : '启动失败，请重试。')
    }
    finally { setBusy(false) }
  }
  if (section) return <div className="stack">
    {error && <Alert showIcon type="error" title={error} />}
    {!data && !error && <p className="muted">正在读取所选岗位…</p>}
    {data && !error && <>
      <Descriptions column={1} items={[
        { key: 'state', label: '当前状态', children: screeningText(data.app) },
      ]} />
      {!data.artifacts.some(artifact => section === 'call' ? artifact.type === 'D08' : ['D09', 'D10'].includes(artifact.type)) && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={section === 'call' ? '此岗位暂无电话沟通记录' : '此岗位暂无评估与推荐'} />}
      {data.artifacts.map(artifact => <section className="panel" key={`${artifact.artifact_id}:${artifact.version}`}><h3>{artifactNames[artifact.type]}</h3><IntakeResult artifact={artifact} /></section>)}
      <Alert type="info" title={section === 'call' ? '实时电话状态与控制接口待接入' : '报告审核与下载接口待接入'} />
    </>}
  </div>
  return <div className="stack">
    {error && <Alert showIcon type="error" title={error} />}
    {data && <>
      <Descriptions column={1} items={[
        { key: 'name', label: '候选人', children: data.app.candidate.display_name || '姓名待确认' },
        { key: 'stage', label: '当前状态', children: (() => { const progress = applicationProgress(data.app, data.artifacts.find(artifact => artifact.type === 'D10')); return progress ? candidateProgressLabels[progress] : '本轮已处理' })() },
      ]} />
      {data.app.stage === 'matched' && <div><p>已按职能方向进入此岗位。尚未判断是否满足具体岗位要求。</p><Button type="primary" loading={busy} onClick={() => { void start() }}>开始深度初筛</Button></div>}
      {data.app.waiting_reason && <Alert type="info" title={data.app.waiting_reason.message} />}
      {applicationProgress(data.app, data.artifacts.find(artifact => artifact.type === 'D10')) === 'report_review' && <Alert type="info" title="报告审核接口待接入" />}
      {data.artifacts.map(artifact => <section className="panel" key={`${artifact.artifact_id}:${artifact.version}`}><h3>{artifactNames[artifact.type]}</h3><IntakeResult artifact={artifact} /></section>)}
    </>}
  </div>
}

function TalentDetails({ id, session }: { id: string; session: IntakeSession }) {
  const { message } = App.useApp()
  const [refresh, setRefresh] = useState(0)
  const [editing, setEditing] = useState(false)
  const [selected, setSelected] = useState<DirectionId[]>([])
  const [quote, setQuote] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [base, setBase] = useState<TalentDetail>()
  const [application, setApplication] = useState<string>()
  const load = useCallback(async (signal: AbortSignal) => ({ person: await getTalent(id, signal), taxonomy: await getDirections(signal) }), [id])
  const { data, error } = useRemote(load, refresh)
  async function save() {
    if (!base || busy) return
    setBusy(true)
    try {
      const directions = selected.map(direction_id => ({ direction_id, level: 'primary' as const, quote: quote.trim(), reason: reason.trim() }))
      await saveTalentDirections(base, directions, reason.trim(), session)
      setEditing(false); setRefresh(value => value + 1); void message.success('已保存分类新版本并更新相关岗位。')
    } catch (failure) { void message.error(failure instanceof Error ? failure.message : '保存失败。') }
    finally { setBusy(false) }
  }
  const person = data?.person
  const facts = person?.profile?.facts
  return <div className="stack">
    {error && <Alert showIcon type="error" title={error} />}
    {person && <>
      <h2>{person.name}</h2><p>{statusText(person)} · {person.filename}</p>
      {person.directions.map(item => <section key={item.direction_id}><Tag>{data?.taxonomy.items.find(direction => direction.id === item.direction_id)?.label}</Tag><p>{item.reason}</p><blockquote>{item.quote}</blockquote></section>)}
      {person.profile_version && <Button onClick={() => { setBase(person); setSelected(person.directions.map(item => item.direction_id)); setQuote(person.directions[0]?.quote ?? ''); setReason(''); setEditing(true) }}>调整职能分类</Button>}
      {editing && <section className="panel stack">
        <label htmlFor="talent-directions">职能方向，可多选</label><Select id="talent-directions" mode="multiple" value={selected} onChange={setSelected} options={data?.taxonomy.items.map(item => ({ value: item.id, label: item.label }))} />
        <label htmlFor="classification-quote">支持分类的简历原文</label><Input.TextArea id="classification-quote" value={quote} onChange={event => setQuote(event.target.value)} rows={3} maxLength={2000} />
        <label htmlFor="classification-reason">调整理由</label><Input id="classification-reason" value={reason} onChange={event => setReason(event.target.value)} maxLength={1000} />
        <Space><Button type="primary" loading={busy} disabled={!reason.trim() || (!!selected.length && !quote.trim())} onClick={() => { void save() }}>保存分类</Button><Button onClick={() => setEditing(false)}>取消</Button></Space>
      </section>}
      {facts && typeof facts === 'object' && <Descriptions title="简历信息" column={1} items={Object.entries(facts).map(([key, value]) => {
        const fact = value as { value?: unknown; status?: string }
        return { key, label: ({ name: '姓名', current_role: '当前职位', education: '学历', years_experience: '工作年限', skills: '技能', employer: '公司', location: '地点', salary: '薪资' } as Record<string, string>)[key] ?? key, children: fact.status === 'stated' ? String(fact.value ?? '待确认') : '待确认' }
      })} />}
      <h3>相关岗位</h3>{person.applications.length ? person.applications.map(link => <div key={link.application_id}><Button type="link" onClick={() => setApplication(link.application_id)}>{link.job_title}</Button><Tag>{screeningText(link)}</Tag></div>) : <Empty description={person.classification_state === 'classified' ? '已入库，等待相关岗位。' : '已入库，分类完成后再关联岗位。'} />}
    </>}
    {application && <Drawer open title="岗位候选人" size={740} onClose={() => setApplication(undefined)}><ApplicationDetails key={application} id={application} session={session} /></Drawer>}
  </div>
}

function TalentJobDetails({ id, section, session }: { id: string; section: 'call' | 'reports'; session: IntakeSession }) {
  const [jobId, setJobId] = useState<string>()
  const load = useCallback((signal: AbortSignal) => getTalent(id, signal), [id])
  const { data, error } = useRemote(load)
  const links = data?.applications ?? []
  const selected = links.find(link => link.job_id === jobId) ?? (!jobId ? links[0] : undefined)
  return <div className="stack">
    {error && <Alert type="error" showIcon title={error} />}
    {data && <>
      <h2>{data.name}</h2>
      <CandidateJobFilter value={selected?.job_id} onChange={setJobId} options={talentMatchedJobs(data).map(job => ({ value: job.id, label: job.title }))} />
      {selected ? <ApplicationDetails key={selected.application_id} id={selected.application_id} jobId={selected.job_id} section={section} session={session} /> : <Empty description={jobId ? '此岗位关联已变化，请重新选择岗位。' : '暂无关联岗位'} />}
    </>}
  </div>
}

export default function TalentPool({ session, onImport }: { session: IntakeSession; onImport: () => void }) {
  const [page, setPage] = useState(1)
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<{ id: string; section: 'summary' | 'call' | 'reports' }>()
  const load = useCallback((signal: AbortSignal) => getTalents(page, q, signal), [page, q])
  const { data, error } = useRemote(load)
  return <>
    <PageHeading title="人才库" actions={<Button type="primary" icon={<Icon name="upload" size={16} />} onClick={onImport}>导入简历</Button>} />
    {error && <Alert showIcon type="error" title={error} />}
    <section className="panel"><div className="filter-bar"><Input aria-label="搜索人才" placeholder="搜索人才姓名" allowClear value={q} onChange={event => { setQ(event.target.value); setPage(1) }} /></div>
      <Table<Talent> rowKey="id" loading={!data && !error} dataSource={data?.items ?? []} scroll={{ x: 600 }} pagination={{ current: page, pageSize: 20, total: data?.total ?? 0, onChange: setPage, showSizeChanger: false }} columns={[
        { title: '候选人', render: (_, person) => <Button type="link" onClick={() => setSelected({ id: person.id, section: 'summary' })}>{person.name || '姓名待确认'}</Button> },
        { title: '适配岗位', render: (_, person) => <MatchedJobs jobs={talentMatchedJobs(person)} emptyText={person.classification_state === 'classified' ? '暂无适配岗位' : person.classification_state === 'processing' ? '匹配中' : '等待匹配'} /> },
        { title: '查看信息', render: (_, person) => <div className="candidate-row-actions"><Button onClick={() => setSelected({ id: person.id, section: 'summary' })}>基本信息</Button><Button onClick={() => setSelected({ id: person.id, section: 'call' })}>电话沟通情况</Button><Button onClick={() => setSelected({ id: person.id, section: 'reports' })}>评估与推荐</Button></div> },
      ]} />
    </section>
    {selected && <Drawer open title={selected.section === 'call' ? '电话沟通情况' : selected.section === 'reports' ? '评估与推荐' : '人才档案'} size={800} onClose={() => setSelected(undefined)}>{selected.section === 'summary' ? <TalentDetails key={selected.id} id={selected.id} session={session} /> : <TalentJobDetails key={`${selected.id}:${selected.section}`} id={selected.id} section={selected.section} session={session} />}</Drawer>}
  </>
}

export function RoutedJobCandidates({ jobId, session }: { jobId: string; session: IntakeSession }) {
  const { message } = App.useApp()
  const [page, setPage] = useState(1)
  const [refresh, setRefresh] = useState(0)
  const [selected, setSelected] = useState<string>()
  const [draft, setDraft] = useState<DirectionId[] | null>(null)
  const [baseRevision, setBaseRevision] = useState<number>()
  const [busy, setBusy] = useState(false)
  const load = useCallback(async (signal: AbortSignal) => {
    const [job, applications, taxonomy] = await Promise.all([getRoutingJob(jobId, signal), getAllRoutedApplications(jobId, signal), getDirections(signal)])
    let reportReadFailed = false
    const rows = await Promise.all(applications.map(async app => {
      let artifact: Awaited<ReturnType<typeof getTalentArtifact>> | undefined
      if (app.screening_result === 'passed' && app.call_summary?.status === 'ended' && app.evaluation_result === 'recommended' && app.report_summary) {
        try { artifact = await getTalentArtifact(app.report_summary.artifact_ref.artifact_id, app.report_summary.artifact_ref.version, signal) }
        catch { if (!signal.aborted) reportReadFailed = true }
      }
      const progress = applicationProgress(app, artifact)
      return progress ? { app, progress } : null
    }))
    return { job, rows: rows.filter(row => row !== null), taxonomy, reportReadFailed }
  }, [jobId])
  const { data, error } = useRemote(load, refresh)
  const currentPage = Math.min(page, Math.max(1, Math.ceil((data?.rows.length ?? 0) / 20)))
  async function save() {
    if (!data || draft === null || busy || baseRevision === undefined) return
    setBusy(true)
    try {
      await saveJobDirections({ ...data.job, revision: baseRevision }, draft, session)
      setDraft(null); setRefresh(value => value + 1); void message.success('岗位方向已保存。')
    } catch (failure) { void message.error(failure instanceof Error ? failure.message : '保存失败。') }
    finally { setBusy(false) }
  }
  return <section className="panel stack">
    {error && <Alert showIcon type="error" title={error} />}
    {data?.reportReadFailed && <Alert showIcon type="error" title="部分推荐报告暂不可读取，请稍后重试。" />}
    {data && <><label htmlFor="job-routing-directions">此岗位接收的人才方向</label><Select id="job-routing-directions" mode="multiple" value={draft ?? data.job.routing_directions as DirectionId[]} onChange={value => { if (draft === null) setBaseRevision(data.job.revision); setDraft(value) }} options={data.taxonomy.items.map(item => ({ value: item.id, label: item.label }))} /><div><Button disabled={draft === null} loading={busy} onClick={() => { void save() }}>保存岗位方向</Button></div>
      {data.job.rule_status !== 'published' && <Alert type="info" title="确认并发布岗位标准后，相关人才会进入此列表。" />}
      <Table rowKey={row => row.app.id} dataSource={data.rows} pagination={{ current: currentPage, pageSize: 20, total: data.rows.length, onChange: setPage, showSizeChanger: false }} scroll={{ x: 600 }} columns={[
        { title: '候选人', render: (_, { app }) => app.candidate.display_name || '姓名待确认' },
        { title: '分流方向', render: (_, { app }) => Array.isArray(app.routing?.direction_ids) ? app.routing?.direction_ids.map((id: string) => data.taxonomy.items.find(direction => direction.id === id)?.label).join('、') : '岗位直接导入' },
        { title: '状态', render: (_, row) => <CandidateProgressTag progress={row.progress} /> },
        { title: '操作', render: (_, { app }) => <Button type="link" onClick={() => setSelected(app.id)}>{app.stage === 'matched' ? '查看与开始初筛' : '查看进度'}</Button> },
      ]} />
    </>}
    {selected && <Drawer open title="岗位候选人" size={800} onClose={() => setSelected(undefined)}><ApplicationDetails key={selected} id={selected} session={session} /></Drawer>}
  </section>
}
