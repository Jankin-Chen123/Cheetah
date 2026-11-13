import { useEffect, useState } from 'react'
import { Alert, App as AntApp, Badge, Button, Empty, Form, Input, Modal, Select, Space, Table, Tag, Tooltip } from 'antd'
import { fetchHealth } from './api/client'
import type { Candidate, ImportRecord, Job } from './domain/workspace'
import { callLabels, reportLabels, screeningLabels, uid } from './domain/workspace'
import { demoCandidates, demoJobs } from './data/demo'
import CandidateWorkspace from './components/CandidateWorkspace'
import JobWorkspace from './components/JobWorkspace'
import ResumeImport from './components/ResumeImport'
import { Icon, PageHeading, Person, ScreeningTag, SourceTag } from './components/ui'

const navigation = [
  { id: 'overview', title: '工作台', icon: 'grid' }, { id: 'jobs', title: '招聘岗位', icon: 'briefcase' },
  { id: 'candidates', title: '候选人', icon: 'people' }, { id: 'calls', title: '电话任务', icon: 'phone' },
  { id: 'reports', title: '推荐审核', icon: 'file' },
]
const titles: Record<string, string> = { overview: '工作台', jobs: '招聘岗位', candidates: '候选人', calls: '电话任务', reports: '推荐审核', settings: '连接与说明', live: '业务工作区' }

function Workspace() {
  const [route, setRoute] = useState(() => window.location.hash.slice(1) || 'overview')
  const [jobs, setJobs] = useState<Job[]>(() => structuredClone(demoJobs))
  const [candidates, setCandidates] = useState<Candidate[]>(() => structuredClone(demoCandidates))
  const [records, setRecords] = useState<ImportRecord[]>([])
  const [query, setQuery] = useState('')
  const [jobFilter, setJobFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [createOpen, setCreateOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [importJob, setImportJob] = useState<string>()
  const [connection, setConnection] = useState<'loading' | 'online' | 'offline'>('loading')
  const [refreshKey, setRefreshKey] = useState(0)
  const [form] = Form.useForm<{ title: string; company: string; location: string; salary: string; material: string }>()
  const { message, modal } = AntApp.useApp()

  useEffect(() => {
    const onHash = () => { setRoute(window.location.hash.slice(1) || 'overview'); setQuery(''); setStatusFilter('all'); setJobFilter('all'); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal).then(() => { if (!controller.signal.aborted) setConnection('online') }).catch(() => { if (!controller.signal.aborted) setConnection('offline') })
    return () => controller.abort()
  }, [refreshKey])

  const page = route.split('/')[0]
  const active = page === 'job' ? 'jobs' : page === 'candidate' ? 'candidates' : page
  const selectedJob = page === 'job' ? jobs.find(j => j.id === route.split('/')[1]) : undefined
  const selectedCandidate = page === 'candidate' ? candidates.find(c => c.id === route.split('/')[1]) : undefined
  const selectedCandidateJob = selectedCandidate ? jobs.find(j => j.id === selectedCandidate.jobId) : undefined
  const isLive = page === 'live'
  const pendingReports = candidates.filter(c => c.reports.at(-1)?.state === 'pending')
  const calls = candidates.filter(c => c.call)
  const waitingCalls = calls.filter(c => ['waiting', 'unknown', 'stopping'].includes(c.call!.state))
  const unknownCandidates = candidates.filter(c => c.screening === 'unknown')
  const draftJobs = jobs.filter(j => j.status === 'draft' || j.draft)
  const todos = pendingReports.length + unknownCandidates.length + draftJobs.length + calls.filter(c => c.call?.state === 'unknown').length
  function navigate(value: string) { window.location.assign(`#${value}`) }
  function openImport(jobId?: string) { setImportJob(jobId); setImportOpen(true) }
  function updateCandidate(candidate: Candidate) { setCandidates(items => items.map(item => item.id === candidate.id ? candidate : item)) }
  function jobFor(candidate: Candidate) { return jobs.find(j => j.id === candidate.jobId)! }
  const filteredCandidates = candidates.filter(c => (jobFilter === 'all' || c.jobId === jobFilter) && (statusFilter === 'all' || c.screening === statusFilter) && `${c.name}${c.role}${jobFor(c).title}`.toLowerCase().includes(query.toLowerCase()))

  const candidateTable = (items: Candidate[], compact = false) => <Table<Candidate> rowKey="id" dataSource={items} pagination={compact ? false : { pageSize: 8, showSizeChanger: false, showTotal: total => `共 ${total} 位演示候选人` }} scroll={{ x: compact ? 650 : 850 }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的候选人，试试调整筛选条件。" /> }} columns={[
    { title: '候选人', key: 'person', width: 270, render: (_, c, i) => <button className="person-link" onClick={() => navigate(`candidate/${c.id}`)}><Person name={c.name} detail={c.role} index={i} /></button> },
    { title: '应聘岗位', key: 'job', render: (_, c) => <span className="table-main">{jobFor(c).title}<span className="table-sub">测试规则 v{c.ruleVersion}</span></span> },
    { title: '初筛结论', key: 'status', width: 130, render: (_, c) => <ScreeningTag value={c.screening} /> },
    ...(!compact ? [{ title: '当前进展', key: 'stage', render: (_: unknown, c: Candidate) => <span>{c.reports.length ? `D10 · ${reportLabels[c.reports.at(-1)!.state]}` : c.call ? callLabels[c.call.state] : c.screening === 'unknown' ? '等待补充证据' : '保留初筛结果'}</span> }] : []),
    { title: '操作', key: 'action', width: 90, render: (_, c) => <Button type="link" onClick={() => navigate(`candidate/${c.id}`)}>查看 <Icon name="chevron" size={12} /></Button> },
  ]} />

  const dashboard = <>
    <PageHeading eyebrow="YOUR RECRUITING, IN FOCUS" title="每一次好推荐，始于好判断。" description="从招聘需求到候选人推荐，在一个工作区掌握每一步。" actions={<><Button icon={<Icon name="upload" size={16} />} onClick={() => openImport()}>导入简历</Button><Button type="primary" icon={<Icon name="plus" size={17} />} onClick={() => { form.resetFields(); setCreateOpen(true) }}>创建岗位</Button></>} />
    <div className="metric-grid">{[
      { label: '招聘岗位', value: jobs.length, detail: `${jobs.filter(j => j.status === 'published').length} 个已发布测试规则`, icon: 'briefcase', go: 'jobs', tone: 'sage' },
      { label: '候选人', value: candidates.length, detail: `${candidates.filter(c => c.screening === 'passed').length} 位模拟初筛达标`, icon: 'people', go: 'candidates', tone: 'blue' },
      { label: '等待处理的电话', value: waitingCalls.length, detail: '查看联系前提与核对事项', icon: 'phone', go: 'calls', tone: 'peach' },
      { label: '推荐待审核', value: pendingReports.length, detail: '由你确认每一个具体版本', icon: 'file', go: 'reports', tone: 'lilac' },
    ].map(item => <button key={item.label} className="metric-card" onClick={() => navigate(item.go)}><div><span>{item.label}</span><span className={`metric-icon ${item.tone}`}><Icon name={item.icon} /></span></div><strong>{String(item.value).padStart(2, '0')}</strong><p>{item.detail}<Icon name="arrow" size={15} /></p></button>)}</div>
    <section className="journey panel"><div className="section-heading"><div><h2>从需求到推荐</h2><p className="muted">可追溯的工作流，由你把握关键决定</p></div><Tag className="subtle-tag">流程规划 · 业务待接入</Tag></div><div className="journey-steps">{[
      ['01', '梳理招聘需求', '岗位画像与标准确认', 'briefcase', 'jobs'], ['02', '简历研究与初筛', '证据、匹配与信息缺口', 'search', 'candidates'], ['03', '电话沟通与评估', '核实经历与个人贡献', 'phone', 'calls'], ['04', '审核候选人推荐', '批准具体报告版本', 'shield', 'reports'],
    ].map(([number, title, detail, icon, go]) => <button key={number} onClick={() => navigate(go)}><span className="journey-icon"><Icon name={icon} size={21} /></span><div><span className="journey-number">{number}</span><h3>{title}</h3><p>{detail}</p></div><Icon name="chevron" size={16} /></button>)}</div></section>
    <div className="dashboard-grid"><section className="panel todo-panel"><div className="section-heading"><h2>需要你的判断 <span className="count-pill">{todos}</span></h2><span className="muted small">模拟待办</span></div><div className="todo-list">
      {pendingReports.map(c => <button key={c.id} onClick={() => navigate(`candidate/${c.id}/reports`)}><span className="todo-icon sage"><Icon name="file" size={19} /></span><div><strong>审核 {c.name} 的推荐报告</strong><span>{jobFor(c).title} · D10 v{c.reports.at(-1)!.version}</span></div><Tag color="green">待审核</Tag><Icon name="chevron" size={16} /></button>)}
      {unknownCandidates.map(c => <button key={c.id} onClick={() => navigate(`candidate/${c.id}`)}><span className="todo-icon peach"><Icon name="people" size={19} /></span><div><strong>补充 {c.name} 的经历信息</strong><span>{c.gaps[0]} · 缺失不作负面判断</span></div><Tag color="orange">信息不足</Tag><Icon name="chevron" size={16} /></button>)}
      {draftJobs.map(j => <button key={j.id} onClick={() => navigate(`job/${j.id}`)}><span className="todo-icon blue"><Icon name="briefcase" size={19} /></span><div><strong>确认 {j.title} 的岗位标准</strong><span>{j.company} · {j.draft ? '有未发布的新草案' : '规则尚未发布'}</span></div><Tag>待确认</Tag><Icon name="chevron" size={16} /></button>)}
      {calls.filter(c => c.call?.state === 'unknown').map(c => <button key={c.id} onClick={() => navigate(`candidate/${c.id}/call`)}><span className="todo-icon peach"><Icon name="phone" size={19} /></span><div><strong>核对 {c.name} 的外部电话状态</strong><span>结果不明，禁止直接重拨</span></div><Tag color="orange">待核对</Tag><Icon name="chevron" size={16} /></button>)}
      {!todos && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有待处理事项" />}
    </div></section><aside className="focus-card"><div className="focus-top"><Icon name="spark" size={25} /><span>CHEETAH NOTES</span></div><h2>把时间留给<br />值得深入沟通的人。</h2><p>让自动化整理线索与证据，<br />让专业判断始终掌握在你手中。</p><div className="focus-line" /><div className="focus-bottom"><Icon name="shield" size={18} /><span>有来源 · 有版本 · 有人工审核</span></div><span className="orbit orbit-one" /><span className="orbit orbit-two" /></aside></div>
    <section className="panel"><div className="section-heading"><div><h2>候选人进展</h2><p className="muted">以下均为虚构演示样例，点击查看来源与流程</p></div><Button type="text" onClick={() => navigate('candidates')}>全部候选人 <Icon name="arrow" size={15} /></Button></div>{candidateTable(candidates.slice(0, 4), true)}</section>
  </>

  const jobsPage = <><PageHeading eyebrow="JOBS / 招聘岗位" title="从清晰的岗位标准开始。" description="先确认需求与规则，再开始候选人流程。" actions={<Button type="primary" icon={<Icon name="plus" size={16} />} onClick={() => { form.resetFields(); setCreateOpen(true) }}>创建岗位</Button>} /><div className="filter-bar"><Input aria-label="搜索岗位" prefix={<Icon name="search" size={17} />} placeholder="搜索岗位、企业名称" allowClear value={query} onChange={e => setQuery(e.target.value)} /><Select aria-label="岗位状态" value={statusFilter} onChange={setStatusFilter} options={[{ value: 'all', label: '全部岗位状态' }, { value: 'published', label: '测试规则已发布' }, { value: 'draft', label: '规则草稿' }]} /></div><div className="jobs-grid">{jobs.filter(j => `${j.title}${j.company}`.toLowerCase().includes(query.toLowerCase()) && (statusFilter === 'all' || j.status === statusFilter)).map((j, i) => <article className="job-card panel" key={j.id}><div className="job-card-top"><span className={`company-mark tone-${i % 4}`}>{j.company.slice(0, 1)}</span><Tag color={j.status === 'published' ? 'green' : 'orange'}>{j.status === 'published' ? '测试规则已发布' : '规则待确认'}</Tag></div><button className="job-title-link" onClick={() => navigate(`job/${j.id}`)}><h2>{j.title}</h2></button><p className="muted">{j.company}</p><div className="job-facts"><span>{j.location || '地点待确认'}</span><span>{j.salary || '薪资待确认'}</span></div><div className="job-card-footer"><span><strong>{candidates.filter(c => c.jobId === j.id).length}</strong> 位演示候选人</span><Button type="text" onClick={() => navigate(`job/${j.id}`)}>管理岗位 <Icon name="arrow" size={15} /></Button></div></article>)}</div>{!jobs.some(j => `${j.title}${j.company}`.toLowerCase().includes(query.toLowerCase()) && (statusFilter === 'all' || j.status === statusFilter)) && <Empty description="没有匹配的岗位" />}</>

  const candidatesPage = <><PageHeading eyebrow="CANDIDATES / 候选人" title="看见经历，也看见证据。" description="区分已知、未知与待核实，保留每次判断的依据。" actions={<Button type="primary" icon={<Icon name="upload" size={16} />} onClick={() => openImport()}>导入简历</Button>} /><div className="panel"><div className="filter-bar"><Input prefix={<Icon name="search" size={17} />} aria-label="搜索候选人" placeholder="搜索姓名、经历或岗位" allowClear value={query} onChange={e => setQuery(e.target.value)} /><Select aria-label="筛选岗位" value={jobFilter} onChange={setJobFilter} options={[{ value: 'all', label: '全部岗位' }, ...jobs.map(j => ({ value: j.id, label: j.title }))]} /><Select aria-label="初筛状态" value={statusFilter} onChange={setStatusFilter} options={[{ value: 'all', label: '全部初筛结论' }, ...Object.entries(screeningLabels).map(([value, label]) => ({ value, label }))]} /></div>{candidateTable(filteredCandidates)}</div>{records.length > 0 && <Alert className="import-note" showIcon type="info" title={`本页已暂存 ${records.filter(r => r.state === 'waiting').length} 份材料摘要，等待解析接口接入。`} description="暂存材料尚未成为候选人结果。" action={<Button size="small" onClick={() => openImport()}>查看导入记录</Button>} />}</>

  const callsPage = <><PageHeading eyebrow="OUTREACH / 电话任务" title="有节奏地沟通，有边界地触达。" description="初筛达标自动关联业务任务；联系前提、停止和外部状态始终可见。" /><Alert className="page-alert" type="warning" showIcon title="全部为模拟电话任务，未连接真实线路" description="这里没有逐人拨号入口。真实拨打须由后端检查授权、时段、预算与防重；外部结果不明先核对。" /><section className="panel"><div className="filter-bar"><Input aria-label="搜索电话任务" prefix={<Icon name="search" size={17} />} placeholder="搜索候选人" allowClear value={query} onChange={e => setQuery(e.target.value)} /><Select aria-label="电话任务状态" value={statusFilter} onChange={setStatusFilter} options={[{ value: 'all', label: '全部电话状态' }, ...Object.entries(callLabels).map(([value, label]) => ({ value, label }))]} /></div><Table<Candidate> rowKey="id" scroll={{ x: 850 }} dataSource={calls.filter(c => c.name.includes(query) && (statusFilter === 'all' || c.call?.state === statusFilter))} pagination={{ pageSize: 8 }} columns={[
    { title: '候选人', render: (_, c, i) => <Person name={c.name} detail={jobFor(c).title} index={i} /> },
    { title: '任务状态', render: (_, c) => <Tag color={c.call?.state === 'active' ? 'green' : ['unknown', 'stopping', 'waiting'].includes(c.call!.state) ? 'orange' : 'default'}>{callLabels[c.call!.state]}</Tag> },
    { title: '等待原因 / 当前情况', width: 350, render: (_, c) => <span className="muted">{c.call!.reason}</span> },
    { title: '尝试', render: (_, c) => `${c.call!.attempts} 条模拟记录` },
    { title: '操作', render: (_, c) => <Button type="link" onClick={() => navigate(`candidate/${c.id}/call`)}>查看任务</Button> },
  ]} /></section></>

  const reportsPage = <><PageHeading eyebrow="RECOMMENDATIONS / 推荐审核" title="每一份推荐，都经你确认。" description="D09 用于内部判断，D10 批准具体版本后才可导出。" /><section className="panel"><Table<Candidate> rowKey="id" dataSource={candidates.filter(c => c.reports.length)} scroll={{ x: 650 }} locale={{ emptyText: <Empty description="尚无推荐报告。仅内部评估达标才生成 D10。" /> }} pagination={false} columns={[
    { title: '候选人', render: (_, c, i) => <Person name={c.name} detail={jobFor(c).title} index={i} /> }, { title: '当前报告', render: (_, c) => <Space><Tag>D10 v{c.reports.at(-1)!.version}</Tag><SourceTag source="mock" /></Space> }, { title: '审核状态', render: (_, c) => <Tag color={c.reports.at(-1)!.state === 'approved' ? 'green' : 'orange'}>{reportLabels[c.reports.at(-1)!.state]}</Tag> }, { title: '操作', render: (_, c) => <Button type="link" onClick={() => navigate(`candidate/${c.id}/reports`)}>查看与审核</Button> },
  ]} /></section><Alert className="import-note" showIcon type="info" title="修改报告产生新版本，旧批准不沿用" description="导出只是本地下载，不等同于已向 HR 交付。上游模拟来源随报告保留。" /></>

  const settingsPage = <><PageHeading eyebrow="WORKSPACE / 连接与说明" title="清楚知道，工作台正在做什么。" description="区分前端可用、基础服务在线与业务能力已接入。" /><div className="detail-grid"><section className="panel stack"><div className="section-heading"><h2>服务连接</h2><Badge status={connection === 'online' ? 'success' : connection === 'loading' ? 'processing' : 'default'} text={connection === 'online' ? '基础服务在线' : connection === 'loading' ? '检查中' : '尚未连接'} /></div><p>健康检查仅表示 API 存活。数据库、身份验证、模型、搜索和电话平台需要分别接入与验证。</p><Button loading={connection === 'loading'} onClick={() => { setConnection('loading'); setRefreshKey(k => k + 1) }}>重新检查基础连接</Button><div className="integration-list">{['登录与对象权限', '岗位与规则持久化', '简历解析与初筛', '联网研究与证据', '实时电话与停止', '报告生成、审批与导出'].map(title => <div key={title}><span>{title}</span><Tag>后端业务待接入</Tag></div>)}</div></section><aside className="panel"><h2>演示工作区</h2><p className="muted">预置姓名、企业、经历与报告均为虚构。新增岗位、草案、导入摘要、审核和下载记录只存在当前页面内存，刷新后重置。</p><p className="muted">此版本未实现真实鉴权，不能作为真实业务部署使用。</p><Button danger onClick={() => modal.confirm({ title: '重置当前演示工作区？', content: '将清除本页新建岗位、暂存摘要与模拟审核，恢复虚构样例。仅影响前端内存。', okText: '重置演示', cancelText: '保留', onOk: () => { setJobs(structuredClone(demoJobs)); setCandidates(structuredClone(demoCandidates)); setRecords([]); navigate('overview'); void message.success('已恢复演示样例。') } })}>重置演示数据</Button></aside></div></>

  const livePage = <div className="live-layout"><section className="live-intro"><span className="brand-word">Cheetah 猎报</span><p className="eyebrow">从需求到推荐</p><h1>招对人，<br />快人一步。</h1><p>清晰的岗位标准，可信的候选人证据，<br />以及由你把握的每一次推荐。</p></section><section className="panel login-panel"><span className="mini-label">业务工作区</span><h2>登录猎报</h2><Alert type="info" showIcon title="登录与身份服务待接入" description="当前后端尚未提供登录接口。请先使用虚构数据演示工作区查看页面。" /><Form layout="vertical"><Form.Item label="账号"><Input disabled placeholder="等待预置账号与登录接口" autoComplete="username" /></Form.Item><Form.Item label="密码"><Input.Password disabled placeholder="后端鉴权接入后开放" autoComplete="current-password" /></Form.Item><Button block type="primary" disabled>登录 · 待接入</Button></Form><Button block onClick={() => navigate('overview')}>进入演示工作区 <Icon name="arrow" size={16} /></Button></section></div>

  let content = dashboard
  if (page === 'jobs') content = jobsPage
  else if (page === 'candidates') content = candidatesPage
  else if (page === 'calls') content = callsPage
  else if (page === 'reports') content = reportsPage
  else if (page === 'settings') content = settingsPage
  else if (page === 'live') content = livePage
  else if (page === 'job' && selectedJob) content = <JobWorkspace key={selectedJob.id} job={selectedJob} candidates={candidates.filter(c => c.jobId === selectedJob.id)} onUpdate={job => setJobs(items => items.map(j => j.id === job.id ? job : j))} onCandidate={id => navigate(`candidate/${id}`)} onImport={() => openImport(selectedJob.id)} onBack={() => navigate('jobs')} />
  else if (page === 'candidate' && selectedCandidate && selectedCandidateJob) content = <CandidateWorkspace key={route} candidate={selectedCandidate} job={selectedCandidateJob} onUpdate={updateCandidate} onBack={() => navigate('candidates')} initialTab={route.split('/')[2] ?? 'overview'} />
  else if (!['overview', 'jobs', 'candidates', 'calls', 'reports', 'settings', 'live'].includes(page)) content = <div className="panel"><Empty description="这个页面或演示对象不存在；刷新后本页新增对象会重置。"><Button onClick={() => navigate('overview')}>返回工作台</Button></Empty></div>

  return <div className="app-shell">
    <a href="#main-content" className="skip-link" onClick={e => { e.preventDefault(); document.getElementById('main-content')?.focus() }}>跳转到主要内容</a>
    <aside className="sidebar"><a className="brand" href="#overview" aria-label="Cheetah 猎报工作台"><img className="brand-symbol" src="/cheetah.svg" alt="" /><span className="brand-word">Cheetah<small>猎报</small></span></a><div className="workspace-label"><span className="workspace-avatar">C</span><span>猎头工作空间<small>Recruiting workspace</small></span><Icon name="chevron" size={14} /></div><span className="nav-label">工作空间</span><nav aria-label="主要导航">{navigation.map(item => <a key={item.id} href={`#${item.id}`} className={`nav-item ${active === item.id ? 'selected' : ''}`} aria-current={active === item.id ? 'page' : undefined}><Icon name={item.icon} size={19} /><span>{item.title}</span>{item.id === 'reports' && pendingReports.length > 0 && <span className="nav-count">{pendingReports.length}</span>}</a>)}</nav><div className="sidebar-note"><span className="note-spark"><Icon name="spark" size={20} /></span><strong>你的判断，始终在场。</strong><p>关键标准由你确认，<br />每份推荐由你审核。</p><button onClick={() => navigate('settings')}>了解工作区 <Icon name="arrow" size={14} /></button></div><div className="sidebar-bottom"><a href="#settings" className={`nav-item ${active === 'settings' ? 'selected' : ''}`}><Icon name="settings" size={19} /><span>连接与说明</span></a><div className="profile"><span className="profile-avatar">演</span><div><strong>演示访客</strong><span>本地预览 · 无真实账号</span></div><Tooltip title="查看业务工作区接入状态"><Button type="text" aria-label="业务工作区登录" icon={<Icon name="logout" size={17} />} onClick={() => navigate('live')} /></Tooltip></div></div></aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb"><span>工作空间</span><Icon name="chevron" size={12} /><strong>{titles[active] ?? '详情'}</strong>{['job', 'candidate'].includes(page) && <><Icon name="chevron" size={12} /><span>{selectedJob?.title ?? selectedCandidate?.name ?? '详情'}</span></>}</div><div className="topbar-right"><Tooltip title="健康检查不代表业务、数据库或 AI 可用"><button className="service-state" onClick={() => navigate('settings')}><span className={`connection-dot ${connection}`} />{connection === 'online' ? '基础服务在线' : connection === 'loading' ? '检查基础连接' : '基础服务未连接'}</button></Tooltip><span className="topbar-divider" /><span className="demo-chip">演示模式</span></div></header>
      <div className="demo-banner"><span><Icon name="spark" size={15} />{isLive ? '业务接口尚未接入，登录暂不可用。' : '演示工作区 · 虚构数据，仅验证页面交互；新增与修改刷新后重置。'}</span><Button type="link" size="small" onClick={() => navigate(isLive ? 'overview' : 'live')}>{isLive ? '返回演示' : '业务工作区'}<Icon name="arrow" size={13} /></Button></div>
      <main id="main-content" tabIndex={-1}>{content}<footer className="page-footer"><span>Cheetah 猎报 · 招对人，快人一步。</span><span>前端演示版本 / 0.2</span></footer></main>
    </div>
    <Modal title="创建招聘岗位 · 前端演示" open={createOpen} onCancel={() => setCreateOpen(false)} footer={null} width={650} forceRender><Alert className="form-alert" type="info" showIcon title="请使用虚构或脱敏需求，内容只保存在本页内存。" /><Form form={form} layout="vertical" onFinish={values => { const job: Job = { ...values, id: uid('local-job'), status: 'draft', version: 0, rules: { screening: '', interview: '', recommendation: '' }, source: 'manual' }; setJobs(items => [...items, job]); setCreateOpen(false); navigate(`job/${job.id}`); void message.success('岗位草稿已在本页创建；模型分析接口待接入。') }}><div className="form-grid"><Form.Item name="title" label="岗位名称" rules={[{ required: true, whitespace: true, message: '请输入岗位名称' }]}><Input placeholder="例如：高级产品经理" maxLength={100} /></Form.Item><Form.Item name="company" label="招聘企业" rules={[{ required: true, whitespace: true, message: '请输入企业名称' }]}><Input placeholder="请使用虚构企业" maxLength={100} /></Form.Item><Form.Item name="location" label="工作地点"><Input placeholder="未提及可留空，标记未知" maxLength={100} /></Form.Item><Form.Item name="salary" label="薪资范围"><Input placeholder="未提及可留空，标记未知" maxLength={100} /></Form.Item></div><Form.Item name="material" label="原始 HR 需求 / JD" rules={[{ required: true, whitespace: true, message: '请粘贴原始需求' }]}><Input.TextArea rows={7} maxLength={30000} placeholder="粘贴需求原文。缺失或冲突会保留待确认，不补造事实。" /></Form.Item><div className="modal-actions"><Button onClick={() => setCreateOpen(false)}>取消</Button><Button type="primary" htmlType="submit">创建本页草稿 <Icon name="arrow" size={16} /></Button></div></Form></Modal>
    {importOpen && <ResumeImport open={importOpen} initialJobId={importJob} jobs={jobs} records={records} setRecords={setRecords} onClose={() => setImportOpen(false)} />}
  </div>
}

export default function App() { return <AntApp><Workspace /></AntApp> }
