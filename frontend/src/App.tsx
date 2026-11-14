import { useEffect, useState } from 'react'
import { Alert, App as AntApp, Badge, Button, Dropdown, Empty, Input, Pagination, Select, Space, Spin, Table, Tag, Tooltip } from 'antd'
import type { IntakeSession } from './api/jobIntake'
import { fetchHealth } from './api/client'
import { getTalents } from './api/talentPool'
import type { Candidate, ImportRecord } from './domain/workspace'
import { previewText } from './domain/presentation'
import { callLabels, reportLabels } from './domain/workspace'
import { candidateMatchedJobs } from './domain/talentMatches'
import { candidateApplicationViews, updateCandidateApplication } from './domain/candidateApplications'
import { candidateProgress } from './domain/candidateProgress'
import { demoCandidates, demoJobs } from './data/demo'
import { filledJobs } from './data/filledJobs'
import CandidateWorkspace from './components/CandidateWorkspace'
import JobWorkspace from './components/JobWorkspace'
import ResumeImport from './components/ResumeImport'
import TalentPool from './components/TalentPool'
import OutreachWorkspace from './components/OutreachWorkspace'
import MatchedJobs from './components/MatchedJobs'
import TalentImport from './components/TalentImport'
import CreateJob from './components/CreateJob'
import { demoJobDocuments, jobCardLabels, jobCardState } from './domain/jobDocuments'
import { usePersistentJobs } from './hooks/usePersistentJobs'
import { useWorkspaceNavigation } from './hooks/useWorkspaceNavigation'
import { usePageMotion } from './hooks/usePageMotion'
import { Icon, PageHeading, Person, SourceTag } from './components/ui'

const initialJobs = [...filledJobs, ...demoJobs.map(job => ({ ...job, documents: demoJobDocuments(job) }))]

const navigation = [
  { id: 'overview', title: '工作台', icon: 'grid' }, { id: 'jobs', title: '招聘岗位', icon: 'briefcase' },
  { id: 'candidates', title: '人才库', icon: 'people' }, { id: 'calls', title: '电话任务', icon: 'phone' },
  { id: 'reports', title: '推荐审核', icon: 'file' },
]
const titles: Record<string, string> = { overview: '工作台', jobs: '招聘岗位', candidates: '人才库', calls: '电话任务', reports: '推荐审核', settings: '连接与说明' }

const emptyJobs: typeof initialJobs = []

type WorkspaceProps = { session: IntakeSession | null; onLogout: () => void; logoutBusy: boolean }

function Workspace({ session, onLogout, logoutBusy }: WorkspaceProps) {
  const isDemo = !session
  const [talentCount, setTalentCount] = useState<number | null>(null)
  useEffect(() => {
    if (!session) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    async function refreshCount() {
      try {
        if (!document.hidden) {
          const people = await getTalents(1, '', controller.signal)
          if (!controller.signal.aborted) setTalentCount(people.total)
        }
      } catch { if (!controller.signal.aborted) setTalentCount(null) }
      finally { if (!controller.signal.aborted) timer = setTimeout(() => { void refreshCount() }, 10000) }
    }
    void refreshCount()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [session])
  const prefix = isDemo ? 'demo' : 'app'
  const scope = session?.user.id ?? 'demo'
  const { route, navigate, back, backLabel, query, setQuery, jobFilter, setJobFilter, statusFilter, setStatusFilter, tablePage, setTablePage, resetJobList } = useWorkspaceNavigation(prefix, scope)
  const pageMotionRef = usePageMotion(route)
  const { jobs, setJobs, storage, ready } = usePersistentJobs(isDemo ? initialJobs : emptyJobs, scope)
  const [candidates, setCandidates] = useState<Candidate[]>(() => structuredClone(isDemo ? demoCandidates : []))
  const [records, setRecords] = useState<ImportRecord[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [importJob, setImportJob] = useState<string>()
  const [connection, setConnection] = useState<'loading' | 'online' | 'offline'>('loading')
  const [refreshKey, setRefreshKey] = useState(0)
  const { message, modal } = AntApp.useApp()

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal).then(() => { if (!controller.signal.aborted) setConnection('online') }).catch(() => { if (!controller.signal.aborted) setConnection('offline') })
    return () => controller.abort()
  }, [refreshKey])

  const page = route.split('/')[0]
  const active = page === 'job' ? 'jobs' : page === 'candidate' ? 'candidates' : page
  const selectedJob = page === 'job' ? jobs.find(j => j.id === route.split('/')[1]) : undefined
  const selectedCandidate = page === 'candidate' ? candidates.find(c => c.id === route.split('/')[1]) : undefined
  const selectedCandidateJobId = route.split('/')[3] ?? selectedCandidate?.jobId
  const applications = candidates.flatMap(candidateApplicationViews)
  const pendingReports = applications.filter(c => c.reports.at(-1)?.state === 'pending')
  const calls = applications.filter(c => c.call)
  const waitingCalls = calls.filter(c => ['waiting', 'unknown', 'stopping'].includes(c.call!.state))
  const unknownCandidates = candidates.filter(c => c.screening === 'unknown')
  const draftJobs = jobs.filter(j => ['draft', 'review'].includes(jobCardState(j, !isDemo)))
  const todos = pendingReports.length + unknownCandidates.length + draftJobs.length + calls.filter(c => c.call?.state === 'unknown').length
  function openImport(jobId?: string) { setImportJob(jobId); setImportOpen(true) }
  function updateCandidate(candidate: Candidate) { setCandidates(items => items.map(item => item.id === candidate.id ? updateCandidateApplication(item, candidate) : item)) }
  function jobFor(candidate: Candidate) { return jobs.find(j => j.id === candidate.jobId)! }
  const filteredCandidates = candidates.filter(c => {
    const matched = candidateMatchedJobs(c, jobs)
    return (jobFilter === 'all' || matched.some(job => job.id === jobFilter)) && `${c.name} ${c.role} ${matched.map(job => job.title).join(' ')}`.toLowerCase().includes(query.toLowerCase())
  })

  const candidateActions = (c: Candidate) => <div className="candidate-row-actions">
      <Button aria-label={`查看${c.name}的基本信息`} onClick={() => navigate(`candidate/${c.id}/summary`)}>基本信息</Button>
      <Button aria-label={`查看${c.name}的电话沟通情况`} onClick={() => navigate(`candidate/${c.id}/call/${c.jobId}`)}>电话沟通情况</Button>
      <Button aria-label={`查看${c.name}的评估与推荐`} onClick={() => navigate(`candidate/${c.id}/reports/${c.jobId}`)}>评估与推荐</Button>
    </div>

  const candidateTable = (items: Candidate[], compact = false) => {
    const currentPage = Math.min(tablePage, Math.max(1, Math.ceil(items.length / 8)))
    return <div className="candidate-list"><div className="candidate-table-desktop"><Table<Candidate> rowKey="id" dataSource={items} pagination={compact ? false : { current: currentPage, onChange: setTablePage, pageSize: 8, showSizeChanger: false, showTotal: total => `共 ${total} 位人才` }} scroll={{ x: 800 }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配候选人" /> }} columns={[
    { title: '候选人', key: 'person', width: 215, render: (_, c, i) => <button className="person-link" onClick={() => navigate(`candidate/${c.id}/summary`)}><Person name={c.name} detail={c.source === 'mock' ? previewText(c.role) : c.role} index={i} /></button> },
    { title: '适配岗位', key: 'jobs', render: (_, c) => <MatchedJobs jobs={candidateMatchedJobs(c, jobs)} /> },
    { title: '查看信息', key: 'action', width: 320, render: (_, c) => candidateActions(c) },
  ]} /></div><div className="candidate-cards">{(compact ? items : items.slice((currentPage - 1) * 8, currentPage * 8)).map((c, index) => <article className="candidate-mobile-card" key={c.id}>
    <div className="candidate-card-heading"><button className="person-link" onClick={() => navigate(`candidate/${c.id}/summary`)}><Person name={c.name} detail={c.source === 'mock' ? previewText(c.role) : c.role} index={index} /></button></div>
    <div className="candidate-matched-jobs"><span className="muted small">适配岗位</span><MatchedJobs jobs={candidateMatchedJobs(c, jobs)} /></div>{candidateActions(c)}
  </article>)}{!items.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配候选人" />}{!compact && !!items.length && <Pagination current={currentPage} onChange={setTablePage} pageSize={8} total={items.length} showSizeChanger={false} />}</div></div>
  }

  const dashboard = <>
    <PageHeading title="工作台" actions={<><Button icon={<Icon name="upload" size={16} />} onClick={() => openImport()}>导入简历</Button><Button type="primary" icon={<Icon name="plus" size={17} />} onClick={() => { setCreateOpen(true) }}>创建岗位</Button></>} />
    <div className="metric-grid">{[
      { label: '招聘岗位', value: jobs.length, icon: 'briefcase', go: 'jobs', tone: 'sage' },
      { label: '人才库', value: session ? talentCount ?? '—' : candidates.length, icon: 'people', go: 'candidates', tone: 'blue' },
      { label: '待处理电话', value: waitingCalls.length, icon: 'phone', go: 'calls', tone: 'peach' },
      { label: '推荐待审核', value: pendingReports.length, icon: 'file', go: 'reports', tone: 'lilac' },
    ].map(item => <button key={item.label} className="metric-card" onClick={() => navigate(item.go)}><div><span>{item.label}</span><span className={`metric-icon ${item.tone}`}><Icon name={item.icon} /></span></div><strong>{String(item.value).padStart(2, '0')}</strong></button>)}</div>

    <div className="dashboard-grid"><section className="panel todo-panel" aria-labelledby="dashboard-todo-title"><div className="section-heading"><h2 id="dashboard-todo-title">待办 <span className="count-pill">{todos}</span></h2></div><div className="todo-list" role="region" aria-label="待办列表" tabIndex={0}>
      {pendingReports.map(c => <button key={`${c.id}:${c.jobId}`} onClick={() => navigate(`candidate/${c.id}/reports/${c.jobId}`)}><span className="todo-icon sage"><Icon name="file" size={19} /></span><div><strong>审核 {c.name} 的推荐报告</strong><span>{jobFor(c).title}</span></div><Tag color="green">待审核</Tag><Icon name="chevron" size={16} /></button>)}
      {unknownCandidates.map(c => <button key={c.id} onClick={() => navigate(`candidate/${c.id}/summary`)}><span className="todo-icon peach"><Icon name="people" size={19} /></span><div><strong>补充 {c.name} 的经历信息</strong><span>{c.gaps[0]}</span></div><Tag color="orange">信息不足</Tag><Icon name="chevron" size={16} /></button>)}
      {draftJobs.map(j => <button key={j.id} onClick={() => navigate(`job/${j.id}`)}><span className="todo-icon blue"><Icon name="briefcase" size={19} /></span><div><strong>确认 {j.title} 的岗位产物</strong><span>{j.source === 'mock' ? previewText(j.company) : j.company} · {'岗位画像与面试表待确认'}</span></div><Tag>待确认</Tag><Icon name="chevron" size={16} /></button>)}
      {calls.filter(c => c.call?.state === 'unknown').map(c => <button key={`${c.id}:${c.jobId}`} onClick={() => navigate(`candidate/${c.id}/call/${c.jobId}`)}><span className="todo-icon peach"><Icon name="phone" size={19} /></span><div><strong>核对 {c.name} 的外部电话状态</strong><span>结果不明，禁止直接重拨</span></div><Tag color="orange">待核对</Tag><Icon name="chevron" size={16} /></button>)}
      {!todos && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无待办" />}
    </div></section></div>
  </>

  const visibleJobs = jobs.filter(j => `${j.title}${j.company}`.toLowerCase().includes(query.toLowerCase()) && (statusFilter === 'all' || jobCardState(j, !isDemo) === statusFilter))
  const jobsPage = <>
    <PageHeading title="招聘岗位" actions={<Button type="primary" icon={<Icon name="plus" size={16} />} onClick={() => setCreateOpen(true)}>创建岗位</Button>} />
    <div className="filter-bar"><Input aria-label="搜索岗位" prefix={<Icon name="search" size={17} />} placeholder="搜索岗位、企业名称" allowClear value={query} onChange={e => setQuery(e.target.value)} /><Select aria-label="岗位状态" value={statusFilter} onChange={setStatusFilter} options={[{ value: 'all', label: '全部岗位状态' }, ...Object.entries(jobCardLabels).map(([value, label]) => ({ value, label }))]} /></div>
    <div className="jobs-grid">{visibleJobs.map((j, i) => {
      const state = jobCardState(j, !isDemo)
      const generating = state === 'generating'
      return <article className={`job-card panel${generating ? ' job-card-generating' : ''}`} key={j.id} aria-disabled={generating || undefined} aria-busy={generating || undefined}>
        {!generating && <a className="job-card-link" href={`#${prefix}/job/${j.id}`} aria-label={`查看${j.title}的岗位详情`} onClick={event => { if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { event.preventDefault(); navigate(`job/${j.id}`) } }} />}
        <div className="job-card-top"><span className={`company-mark tone-${i % 4}`}>{generating && j.company === '待识别企业' ? <Icon name="briefcase" size={22} /> : j.company.slice(0, 1)}</span>{state !== 'published' && <Tag color={generating || state === 'unavailable' ? 'default' : state === 'failed' ? 'red' : 'orange'}>{jobCardLabels[state]}</Tag>}</div>
        <h2 className="job-card-title">{generating && j.title === '待识别岗位' ? '岗位生成中' : j.title}</h2>
        <p className="muted">{generating && j.company === '待识别企业' ? '正在识别企业信息' : j.source === 'mock' ? previewText(j.company) : j.company}</p>
        {generating ? <div className="job-generation-note" role="status"><Spin size="small" /><span>正在生成岗位画像与面试评估表…</span></div> : <div className="job-facts"><span>{j.location || '地点待确认'}</span><span>{j.salary || '薪资待确认'}</span></div>}
        <div className="job-card-footer">{generating ? <span>生成完成后可查看并确认</span> : <span><strong>{applications.filter(c => c.jobId === j.id && candidateProgress(c) !== null).length}</strong> 位候选人</span>}</div>
      </article>
    })}</div>
    {!visibleJobs.length && <Empty description="没有匹配的岗位" />}
  </>

  const candidatesPage = session ? <TalentPool session={session} onImport={() => openImport()} /> : <><PageHeading title="人才库" actions={<Button type="primary" icon={<Icon name="upload" size={16} />} onClick={() => openImport()}>导入简历</Button>} /><div className="panel"><div className="filter-bar"><Input prefix={<Icon name="search" size={17} />} aria-label="搜索候选人" placeholder="搜索姓名、经历或岗位" allowClear value={query} onChange={e => setQuery(e.target.value)} /><Select aria-label="筛选适配岗位" value={jobFilter} onChange={setJobFilter} options={[{ value: 'all', label: '全部适配岗位' }, ...jobs.map(j => ({ value: j.id, label: j.title }))]} /></div>{candidateTable(filteredCandidates)}</div>{records.length > 0 && <Alert className="import-note" showIcon type="info" title={`本页已暂存 ${records.filter(r => r.state === 'waiting').length} 份材料，解析待接入。`} action={<Button size="small" onClick={() => openImport()}>查看导入记录</Button>} />}</>

  const callsPage = <><PageHeading title="电话任务" /><section className="panel"><div className="filter-bar"><Input aria-label="搜索电话任务" prefix={<Icon name="search" size={17} />} placeholder="搜索候选人" allowClear value={query} onChange={e => setQuery(e.target.value)} /><Select aria-label="电话任务状态" value={statusFilter} onChange={setStatusFilter} options={[{ value: 'all', label: '全部电话状态' }, ...Object.entries(callLabels).map(([value, label]) => ({ value, label }))]} /></div><Table<Candidate> rowKey={c => `${c.id}:${c.jobId}`} scroll={{ x: 850 }} dataSource={calls.filter(c => c.name.includes(query) && (statusFilter === 'all' || c.call?.state === statusFilter))} pagination={{ current: tablePage, onChange: setTablePage, pageSize: 8 }} columns={[
    { title: '候选人', render: (_, c, i) => <Person name={c.name} detail={jobFor(c).title} index={i} /> },
    { title: '任务状态', render: (_, c) => <Tag color={c.call?.state === 'active' ? 'green' : ['unknown', 'stopping', 'waiting'].includes(c.call!.state) ? 'orange' : 'default'}>{callLabels[c.call!.state]}</Tag> },
    { title: '当前情况', width: 350, render: (_, c) => <span className="muted">{c.source === 'mock' ? previewText(c.call!.reason) : c.call!.reason}</span> },
    { title: '尝试', render: (_, c) => `${c.call!.attempts} 条记录` },
    { title: '操作', render: (_, c) => <Button type="link" onClick={() => navigate(`candidate/${c.id}/call/${c.jobId}`)}>查看任务</Button> },
  ]} /></section></>

  const reportsPage = <><PageHeading title="推荐审核" /><section className="panel"><Table<Candidate> rowKey={c => `${c.id}:${c.jobId}`} dataSource={applications.filter(c => c.reports.length)} scroll={{ x: 650 }} locale={{ emptyText: <Empty description="暂无推荐报告" /> }} pagination={false} columns={[
    { title: '候选人', render: (_, c, i) => <Person name={c.name} detail={jobFor(c).title} index={i} /> }, { title: '当前报告', render: () => <Space><Tag>推荐报告</Tag><SourceTag source="mock" /></Space> }, { title: '审核状态', render: (_, c) => <Tag color={c.reports.at(-1)!.state === 'approved' ? 'green' : 'orange'}>{reportLabels[c.reports.at(-1)!.state]}</Tag> }, { title: '操作', render: (_, c) => <Button type="link" onClick={() => navigate(`candidate/${c.id}/reports/${c.jobId}`)}>查看与审核</Button> },
  ]} /></section><Alert className="import-note" showIcon type="info" title="修订后须重审" description="仅下载当前已批准版本，不自动交付。" /></>

  const settingsPage = <><PageHeading title="连接与说明" /><div className="detail-grid"><section className="panel stack"><div className="section-heading"><h2>服务连接</h2><Badge status={connection === 'online' ? 'success' : connection === 'loading' ? 'processing' : 'default'} text={connection === 'online' ? '基础服务在线' : connection === 'loading' ? '检查中' : '尚未连接'} /></div><p>基础连接不代表业务就绪。</p><Button loading={connection === 'loading'} onClick={() => { setConnection('loading'); setRefreshKey(k => k + 1) }}>重新检查基础连接</Button><div className="integration-list">{['服务端修订与正式规则发布', '简历解析与初筛', '联网研究与证据', '实时电话与停止', '报告生成、审批与导出'].map(title => <div key={title}><span>{title}</span><Tag>前端待接入</Tag></div>)}</div></section><aside className="panel"><h2>{isDemo ? '本机工作区' : '账号工作区'}</h2><Button danger onClick={() => modal.confirm({ title: '重置当前本机工作区？', content: '将删除当前工作区本机保存的岗位、录音和产物版本；不会删除后端记录。', okText: '重置', cancelText: '保留', onOk: () => { setJobs(structuredClone(isDemo ? initialJobs : emptyJobs)); setCandidates(structuredClone(isDemo ? demoCandidates : [])); setRecords([]); navigate('overview'); void message.success('已重置本机数据。') } })}>重置本机数据</Button></aside></div></>


  let content = dashboard
  if (page === 'jobs') content = jobsPage
  else if (page === 'candidates') content = candidatesPage
  else if (page === 'calls') content = isDemo ? callsPage : <OutreachWorkspace key="calls" />
  else if (page === 'reports') content = isDemo ? reportsPage : <OutreachWorkspace key="reports" view="reports" />
  else if (page === 'settings') content = settingsPage
  else if (page === 'job' && selectedJob) content = <></>
  else if (page === 'candidate' && selectedCandidate && selectedCandidateJobId) content = <CandidateWorkspace key={selectedCandidate.id} candidate={selectedCandidate} jobs={jobs} jobId={selectedCandidateJobId} onJobChange={jobId => navigate(`candidate/${selectedCandidate.id}/${route.split('/')[2] ?? 'summary'}/${jobId}`, true)} onUpdate={updateCandidate} onBack={() => back('candidates')} backLabel={backLabel} section={route.split('/')[2] ?? 'summary'} />
  else if (!['overview', 'jobs', 'candidates', 'calls', 'reports', 'settings'].includes(page)) content = <div className="panel"><Empty description="页面不存在或已随刷新重置。"><Button onClick={() => navigate('overview')}>返回工作台</Button></Empty></div>

  return <div className="app-shell">
    <a href="#main-content" className="skip-link" onClick={e => { e.preventDefault(); document.getElementById('main-content')?.focus() }}>跳转到主要内容</a>
    <aside className="sidebar"><a className="brand" href={`#${prefix}/overview`} aria-label="Cheetah 猎报工作台"><img className="brand-symbol" src="/brand/cheetah-mark.png" alt="" /><span className="brand-word">Cheetah<small>猎报</small></span></a><nav aria-label="主要导航">{navigation.map(item => <a key={item.id} href={`#${prefix}/${item.id}`} className={`nav-item ${active === item.id ? 'selected' : ''}`} aria-current={active === item.id ? 'page' : undefined}><Icon name={item.icon} size={19} /><span>{item.title}</span>{item.id === 'reports' && pendingReports.length > 0 && <span className="nav-count">{pendingReports.length}</span>}</a>)}</nav><div className="sidebar-bottom"><a href={`#${prefix}/settings`} className={`nav-item ${active === 'settings' ? 'selected' : ''}`}><Icon name="settings" size={19} /><span>连接与说明</span></a><div className="profile"><span className="profile-avatar">{session?.user.display_name.slice(0, 1) ?? '访'}</span><div><strong>{session?.user.display_name ?? '访客'}</strong><span>{isDemo ? '本机工作区' : '个人工作空间'}</span></div><Tooltip title={isDemo ? '登录' : '退出登录'}><Button type="text" aria-label={isDemo ? '登录账号' : '退出登录'} loading={logoutBusy} icon={<Icon name="logout" size={17} />} onClick={onLogout} /></Tooltip></div></div></aside>
    <div className={`main-shell${page === 'overview' ? ' dashboard-shell' : ''}`}><header className="topbar"><div className="breadcrumb"><span>工作空间</span><Icon name="chevron" size={12} /><strong>{titles[active] ?? '详情'}</strong>{['job', 'candidate'].includes(page) && <><Icon name="chevron" size={12} /><span>{selectedJob?.title ?? selectedCandidate?.name ?? '详情'}</span></>}</div><div className="topbar-right"><Tooltip title="基础连接不代表业务就绪"><button className="service-state" onClick={() => navigate('settings')}><span className={`connection-dot ${connection}`} />{connection === 'online' ? '基础服务在线' : connection === 'loading' ? '检查基础连接' : '基础服务未连接'}</button></Tooltip><span className="topbar-divider" /><a className="demo-chip" href="#home">返回官网</a><Dropdown trigger={['click']} menu={{ items: [{ key: 'identity', label: session?.user.display_name ?? '访客', disabled: true }, { key: 'home', label: '返回官网' }, { key: 'settings', label: '连接与说明' }, { key: 'logout', label: isDemo ? '登录账号' : '退出登录', disabled: logoutBusy }], onClick: ({ key }) => { if (key === 'home') window.location.hash = 'home'; else if (key === 'settings') navigate('settings'); else if (key === 'logout') onLogout() } }}><Button className="workspace-mobile-account" type="text" aria-label="账号菜单" loading={logoutBusy} icon={<Icon name="people" size={17} />} /></Dropdown></div></header>
      {storage === 'error' && <Alert className="page-alert" showIcon type="error" title="本机保存失败，请导出备份后检查浏览器存储" />}
      <main ref={pageMotionRef} id="main-content" className={page === 'overview' ? 'dashboard-content' : undefined} tabIndex={-1}>{content}{ready && jobs.map(job => <JobWorkspace session={session} key={job.id} job={job} active={selectedJob?.id === job.id} candidates={applications.filter(c => c.jobId === job.id)} onUpdate={updated => setJobs(items => items.map(j => j.id === updated.id ? updated : j))} onCandidate={(id, section = 'summary') => navigate(`candidate/${id}/${section}/${job.id}`)} onImport={() => openImport(job.id)} onBack={() => back('jobs')} backLabel={backLabel === '返回人才库' ? '返回岗位列表' : backLabel} activeTab={route.split('/')[2] ?? 'documents'} onTabChange={tab => navigate(`job/${job.id}/${tab}`, true)} />)}</main>
    </div>
    <CreateJob open={createOpen} ready={ready} onClose={() => setCreateOpen(false)} onCreate={job => { setJobs(items => [job, ...items]); resetJobList(); navigate('jobs') }} />
    {importOpen && session && <TalentImport session={session} onClose={() => setImportOpen(false)} onImported={() => navigate('candidates')} />}
    {importOpen && !session && <ResumeImport open={importOpen} initialJobId={importJob} jobs={jobs} records={records} setRecords={setRecords} onClose={() => setImportOpen(false)} />}
  </div>
}

export default function App(props: WorkspaceProps) { return <AntApp><Workspace {...props} /></AntApp> }
