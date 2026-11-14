import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Form, Input, Spin } from 'antd'
import Workspace from './App'
import { getIntakeSession, IntakeApiError, loginIntake, logoutAccount, registerAccount } from './api/jobIntake'
import type { IntakeSession } from './api/jobIntake'
import { RemoteAccessContext } from './domain/access'
import { Icon } from './components/ui'
import './site.css'

const currentPath = () => window.location.hash.slice(1) || 'home'
const go = (path: string) => { window.location.hash = path }
const safeNext = (path: string | null) => path && /^app\/(overview|jobs|candidates|calls|reports|settings|job\/[^?#]+|candidate\/[^?#]+)$/.test(path) ? path : 'app/overview'

function Brand() {
  return <a className="site-brand" href="#home" aria-label="Cheetah 猎报官网"><img src="/brand/cheetah-mark.png" alt="" /><span>Cheetah<span className="site-brand-cn">猎报</span></span></a>
}

function Landing({ session }: { session: IntakeSession | null }) {
  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  return <div className="site-page">
    <a className="skip-link" href="#site-main" onClick={event => { event.preventDefault(); document.getElementById('site-main')?.focus() }}>跳转到主要内容</a>
    <header className="site-header"><Brand /><nav aria-label="官网导航"><button onClick={() => scrollTo('workflow')}>工作方式</button><button onClick={() => scrollTo('product')}>产品能力</button><button onClick={() => scrollTo('questions')}>常见问题</button></nav><div className="site-header-actions">{session ? <a className="site-button primary small" href="#app/overview">进入工作空间 <Icon name="arrow" size={15} /></a> : <><a className="site-login-link" href="#login">登录</a><a className="site-button primary small" href="#register">开始使用 <Icon name="arrow" size={15} /></a></>}</div></header>
    <main id="site-main" tabIndex={-1}>
      <section className="site-hero">
        <div className="site-hero-copy"><span className="site-eyebrow"><span /> 为猎头而生的 Agent 工作空间</span><h1>招对人，<br /><em>快人一步。</em></h1><p>让繁杂的招聘流程有条不紊。<br />从梳理岗位需求开始，把时间留给值得深入的人才。</p><div className="site-hero-actions"><a className="site-button primary" href={session ? '#app/overview' : '#register'}>{session ? '进入我的工作空间' : '创建我的工作空间'}<Icon name="arrow" size={18} /></a><a className="site-button secondary" href="#demo/overview"><Icon name="grid" size={17} /> 预览工作台</a></div><div className="site-hero-signature"><span className="signature-line" /> 更清晰的判断，更从容的招聘。</div></div>
        <div className="site-preview" aria-label="招聘工作流示意，非真实任务"><div className="preview-orbit" /><div className="preview-window"><div className="preview-top"><div><span /><span /><span /></div><span>CHEETAH WORKSPACE</span><span>流程示意</span></div><div className="preview-body"><div className="preview-heading"><div><span className="site-eyebrow">从一份需求开始</span><h2>让每一步，都有依据。</h2></div><span className="preview-mark"><Icon name="spark" size={23} /></span></div><div className="preview-material"><span className="preview-icon"><Icon name="file" size={23} /></span><div><strong>HR 岗位沟通记录</strong><span>需求文字 → 结构化岗位产物</span></div><span className="preview-file-tag">文字</span></div><div className="preview-connector"><span /> 梳理与确认 <span /></div><div className="preview-docs"><div><strong>岗位画像</strong><p>职责 · 要求 · 待确认项</p><div className="preview-lines"><i /><i /><i /></div></div><div><strong>面试评估表</strong><p>维度 · 标准 · 核实重点</p><div className="preview-lines"><i /><i /><i /></div></div></div><div className="preview-confirm"><Icon name="people" size={17} /><span>关键标准，由你确认。</span><span className="preview-status">人工复核</span></div></div></div><div className="preview-floating"><span><Icon name="briefcase" size={19} /></span><div><strong>从材料到判断</strong><p>留存来源，保留未知</p></div><Icon name="arrow" size={17} /></div><span className="preview-note">招聘流程的每一步，都值得认真对待。</span></div>
      </section>
      <section className="site-principles" aria-label="产品理念"><span><Icon name="file" size={18} /> 判断有来源</span><span><Icon name="people" size={18} /> 关键节点由人确认</span><span><Icon name="grid" size={18} /> 产物可查看、可修订</span></section>
      <section id="workflow" className="site-section"><div className="site-section-heading"><div><span className="site-eyebrow">THE WORKFLOW</span><h2>把招聘流程，串成一条清晰的线。</h2></div><p>Agent 辅助整理信息，你把握关键决策。<br />这是猎报正在构建的工作方式。</p></div><div className="site-steps">{[
        ['01', '梳理需求', '从沟通文字提取岗位画像与面试评估表，记录缺失与待确认项。', '已接入文字分析流程'],
        ['02', '筛选人才', '围绕确认的岗位标准，整理简历信息、研究证据与初筛结论。', '待接入'],
        ['03', '深入沟通', '让候选人沟通与评估承接前序信息，保留值得核实的问题。', '待接入'],
        ['04', '形成推荐', '区分内部评估与对外推荐，在审核具体版本后再交付。', '待接入'],
      ].map(([number, title, description, status]) => <article key={number}><span className="site-step-number">{number}</span><h3>{title}</h3><p>{description}</p><span className="site-step-status">{status}</span></article>)}</div></section>
      <section id="product" className="site-product site-section"><div><span className="site-eyebrow">BUILT FOR YOUR JUDGMENT</span><h2>少一点信息搬运，<br />多一点判断空间。</h2><p>把原始材料、岗位产物和修订版本放在一起。<br />信息不足时，留下问题；有新信息时，再完善判断。</p><a className="site-text-link" href="#demo/jobs">看看岗位工作区 <Icon name="arrow" size={17} /></a></div><div className="site-feature-list">{[
        ['file', '从沟通文字开始', '粘贴或导入文字，进入岗位分析流程。录音可本机留存，自动转写仍待接入。'],
        ['grid', '让产物真正可用', '查看、修订岗位画像与面试评估表，保留本机历史版本，导出 PDF 或可编辑 Word。'],
        ['people', '把决定留在你手里', '岗位标准需要确认；未知不作负面事实；未审批的推荐版本不对外交付。'],
      ].map(([icon, title, description]) => <article key={title}><span><Icon name={icon} size={22} /></span><div><h3>{title}</h3><p>{description}</p></div></article>)}</div></section>
      <section id="questions" className="site-section site-faq"><div><span className="site-eyebrow">GOOD TO KNOW</span><h2>开始之前，你可能想知道</h2></div><div>{[
        ['现在可以使用哪些功能？', '可以创建账号、登录并从沟通文字创建岗位，查看和导出岗位产物。生成需要后端数据库、模型和任务服务就绪，真实模型端到端仍待验收。'],
        ['预览需要注册吗？', '无需注册即可预览工作台，保存自己的岗位需要创建账号。'],
        ['材料会保存在哪里？', '岗位材料和网页修订版本保存在当前浏览器，按账号分开；已提交分析的文字和生成产物也由后端保存。目前不支持跨设备恢复本机列表，人工修订尚未回写后端。退出不会清除本机材料，共用设备请在使用后清理自己的资料。'],
        ['猎报会自动拨打候选人电话吗？', '真实沟通能力仍待接入与验证；未来执行也需要满足授权、联系前提、时段和预算等条件。'],
      ].map(([question, answer]) => <details key={question}><summary>{question}<span>＋</span></summary><p>{answer}</p></details>)}</div></section>
      <section className="site-cta"><span className="site-eyebrow">YOUR NEXT GREAT HIRE STARTS HERE</span><h2>下一位合适的人才，<br />从更清晰的需求开始。</h2><a className="site-button light" href={session ? '#app/overview' : '#register'}>{session ? '进入工作空间' : '创建工作空间'}<Icon name="arrow" size={18} /></a></section>
    </main><footer className="site-footer"><Brand /><span>招对人，快人一步。</span><a href="#demo/overview">查看工作台 <Icon name="arrow" size={14} /></a><small>Cheetah 猎报 · 开发预览</small></footer>
  </div>
}

type AccountFields = { username: string; display_name: string; password: string; confirm: string }
function AuthPage({ register, onAuthenticated, notice }: { register: boolean; onAuthenticated: (session: IntakeSession) => void; notice?: string }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const pending = useRef<AbortController | null>(null)
  useEffect(() => () => pending.current?.abort(), [])
  async function submit(values: AccountFields) {
    const controller = new AbortController()
    pending.current = controller
    setBusy(true); setError('')
    try {
      const session = register ? await registerAccount({ username: values.username, display_name: values.display_name.trim(), password: values.password }, controller.signal) : await loginIntake(values.username, values.password, controller.signal)
      if (!controller.signal.aborted) onAuthenticated(session)
    } catch (caught) {
      if (controller.signal.aborted) return
      const failure = caught as IntakeApiError
      setError(`${failure.code === 'VALIDATION_ERROR' ? '请检查账号、称呼与密码格式。' : failure.message}${failure.requestId ? `（请求标识：${failure.requestId}）` : ''}`)
    } finally { if (!controller.signal.aborted) setBusy(false) }
  }
  return <div className="account-page"><aside className="account-story"><Brand /><div><span className="site-eyebrow">LESS BUSYWORK. MORE HUMAN.</span><h1>让好的人才，<br />与好的机会<br /><em>更早相遇。</em></h1><p>从需求梳理到人才判断，<br />让每一步工作都有迹可循。</p><div className="account-story-line"><Icon name="spark" size={20} /><span>你的判断，始终在中心。</span></div></div><span className="account-story-footer">Cheetah 猎报 · 招对人，快人一步。</span></aside><main className="account-main"><a className="account-back" href="#home">← 返回官网</a><div className="account-form"><span className="site-eyebrow">{register ? 'START WITH CHEETAH' : 'WELCOME BACK'}</span><h2>{register ? '创建你的工作空间' : '欢迎回到猎报'}</h2><p className="account-description">{register ? '创建账号，开始梳理你的第一个岗位。' : '登录账号，继续你的招聘工作。'}</p>{notice && <Alert type="info" showIcon title={notice} />}{error && <Alert type="error" showIcon title={error} role="alert" />}<Form<AccountFields> layout="vertical" requiredMark={false} onFinish={values => void submit(values)} disabled={busy}>
      {register && <Form.Item name="display_name" label="怎么称呼你" rules={[{ required: true, whitespace: true, message: '请输入你的称呼' }, { max: 100, message: '称呼最多 100 个字符' }]}><Input autoComplete="nickname" placeholder="你的姓名或昵称" maxLength={100} /></Form.Item>}
      <Form.Item name="username" label="账号" rules={[{ required: true, message: '请输入账号' }, ...(register ? [{ pattern: /^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}$/, message: '3–40 位字母、数字、下划线、点或短横线，以字母或数字开头' }] : [])]} extra={register ? '3–40 位，区分大小写；注册后使用此账号登录。' : undefined}><Input autoComplete="username" placeholder={register ? '为自己起一个账号' : '请输入账号'} maxLength={register ? 40 : 100} /></Form.Item>
      <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }, ...(register ? [{ min: 12, max: 128, message: '密码需要 12–128 个字符' }] : [])]}><Input.Password autoComplete={register ? 'new-password' : 'current-password'} placeholder={register ? '至少 12 个字符' : '请输入密码'} maxLength={register ? 128 : 1024} /></Form.Item>
      {register && <Form.Item name="confirm" label="确认密码" dependencies={['password']} rules={[{ required: true, message: '请再次输入密码' }, ({ getFieldValue }) => ({ validator(_, value) { return !value || value === getFieldValue('password') ? Promise.resolve() : Promise.reject(new Error('两次输入的密码不一致')) } })]}><Input.Password autoComplete="new-password" placeholder="再次输入密码" maxLength={128} /></Form.Item>}
      <Button type="primary" block size="large" htmlType="submit" loading={busy}>{register ? '创建账号并进入' : '登录工作空间'} <Icon name="arrow" size={17} /></Button>
    </Form><p className="account-switch">{register ? '已经有账号？' : '还没有账号？'} <a href={register ? '#login' : '#register'}>{register ? '直接登录' : '创建账号'}</a></p><div className="account-divider"><span>先了解一下</span></div><a className="site-button secondary" href="#demo/overview">无需注册，预览工作台 <Icon name="arrow" size={16} /></a><p className="account-footnote">{register ? '注册会创建独立工作空间。目前不支持团队邀请与密码找回，请妥善保管账号密码。' : '暂不支持自助找回密码；忘记密码请联系项目管理员。'}<br />材料在本机按账号保存，共用设备请注意清理。</p></div><span className="account-copyright">Cheetah 猎报 · 开发预览</span></main></div>
}

export default function SiteApp() {
  const [path, setPath] = useState(currentPath)
  const [session, setSession] = useState<IntakeSession | null>(null)
  const [checking, setChecking] = useState(true)
  const [sessionError, setSessionError] = useState('')
  const [logoutBusy, setLogoutBusy] = useState(false)
  const sessionSequence = useRef(0)
  const route = path.split('?')[0]
  const demo = route.startsWith('demo/')
  const publicPage = ['home', 'login', 'register'].includes(route)
  useEffect(() => {
    const sync = () => {
      const next = currentPath()
      setPath(next)
      // Workspace navigation restores each list's own scroll position.
      if (!/^(app|demo)\//.test(next)) window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', sync); window.addEventListener('popstate', sync)
    return () => { window.removeEventListener('hashchange', sync); window.removeEventListener('popstate', sync) }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    const refresh = async () => {
      const attempt = ++sessionSequence.current
      try {
        const restored = await getIntakeSession(controller.signal)
        if (!controller.signal.aborted && attempt === sessionSequence.current) { setSession(restored); setSessionError('') }
      } catch (caught) {
        if (!controller.signal.aborted && attempt === sessionSequence.current) { setSession(null); setSessionError(caught instanceof IntakeApiError && caught.status === 401 ? '' : '暂时无法检查登录状态，请检查服务连接后重新登录。') }
      } finally { if (!controller.signal.aborted && attempt === sessionSequence.current) setChecking(false) }
    }
    const expired = () => { sessionSequence.current++; setSession(null); setChecking(false); setSessionError('登录已过期，请重新登录。') }
    const focus = () => { if (document.visibilityState === 'visible') void refresh() }
    void refresh()
    const timer = setInterval(focus, 60000)
    window.addEventListener('focus', focus); document.addEventListener('visibilitychange', focus); window.addEventListener('cheetah:session-expired', expired)
    return () => { controller.abort(); clearInterval(timer); window.removeEventListener('focus', focus); document.removeEventListener('visibilitychange', focus); window.removeEventListener('cheetah:session-expired', expired) }
  }, [])
  useEffect(() => {
    if (!session) return
    const timer = setTimeout(() => { setSession(null); setSessionError('登录已过期，请重新登录。') }, Math.max(0, Date.parse(session.expires_at) - Date.now()))
    return () => clearTimeout(timer)
  }, [session])
  async function logout() {
    if (!session || demo) { go('login'); return }
    setLogoutBusy(true); setSessionError('')
    try { await logoutAccount(session); sessionSequence.current++; setSession(null); go('home') }
    catch (caught) { setSessionError(caught instanceof Error ? caught.message : '退出失败，请重试。') }
    finally { setLogoutBusy(false) }
  }
  const authenticate = (value: IntakeSession) => {
    sessionSequence.current++
    setSession(value); setSessionError(''); setChecking(false)
    const actual = currentPath().split('?')[0]
    go(safeNext(publicPage ? new URLSearchParams(path.split('?')[1]).get('next') : actual.startsWith('app/') ? actual : `app/${actual}`))
  }
  if (route === 'home') return <Landing session={session} />
  if (route === 'login' || route === 'register') return <AuthPage key={route} register={route === 'register'} onAuthenticated={authenticate} notice={sessionError || undefined} />
  if (!demo && checking) return <div className="site-loading"><Spin size="large" /><p>正在恢复工作空间…</p><a href="#home">返回官网</a></div>
  if (!demo && !session) return <AuthPage key="guard" register={false} onAuthenticated={authenticate} notice={sessionError || '请先登录，再进入你的工作空间。'} />
  return <RemoteAccessContext.Provider value={!demo && !!session}>{sessionError && session && <Alert type="error" showIcon title={sessionError} closable />}<Workspace key={demo ? 'demo' : session!.user.id} session={demo ? null : session} onLogout={() => void logout()} logoutBusy={logoutBusy} /></RemoteAccessContext.Provider>
}
