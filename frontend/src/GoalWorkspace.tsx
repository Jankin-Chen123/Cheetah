import { useEffect, useState } from 'react'
import { Alert, Button, Card, Checkbox, Input, Select, Space, Typography } from 'antd'
import { api, download, type CallCase } from './api/outreach'
import KnowledgeReview from './KnowledgeReview'
import PreflightCard from './PreflightCard'
import InvitationCard from './InvitationCard'
import PostInterviewContent from './PostInterviewContent'
import EvaluationStandardCard from './EvaluationStandardCard'

export default function GoalWorkspace() {
  const [password, setPassword] = useState('')
  const [calls, setCalls] = useState<CallCase[]>([])
  const [current, setCurrent] = useState<CallCase>()
  const [answer, setAnswer] = useState('')
  const [correctionId, setCorrectionId] = useState<string>()
  const [correctionText, setCorrectionText] = useState('')
  const [preview, setPreview] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [methods, setMethods] = useState<unknown[]>([])
  const [taskId, setTaskId] = useState<string>()
  const [taskStatus, setTaskStatus] = useState('')
  const [reviewReason, setReviewReason] = useState('')
  const [fixtureBatch, setFixtureBatch] = useState('default')
  async function refresh(id?: string) {
    const list = await api<{ items: CallCase[] }>('/calls')
    setCalls(list.items)
    if (id) {
      const detail = await api<CallCase>(`/calls/${id}`)
      setCurrent(detail)
      const url = new URL(window.location.href)
      url.searchParams.set('call', id)
      window.history.replaceState(null, '', url)
      setPreview(Boolean(detail.session.knowledge_preview))
      const active = detail.active_tasks?.[0]
      if (active) { setTaskId(active.id); setTaskStatus(active.status) }
      else { setTaskId(undefined); setTaskStatus('') }
    }
  }
  async function run(action: () => Promise<unknown>) {
    setBusy(true); setError('')
    try { await action() } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  useEffect(() => {
    const id = new URL(window.location.href).searchParams.get('call') || undefined
    void api('/auth/me').then(() => refresh(id)).catch(e => {
      setError(String(e).includes('401') ? '请先使用本地审核密码登录。密码位于项目根目录 .env 的 CHEETA_LOCAL_PASSWORD；无需在聊天中发送。' : String(e))
    })
  }, [])
  useEffect(() => {
    if (!taskId) return
    let cancelled = false
    let pending = false
    const controller = new AbortController()
    const poll = () => {
      if (cancelled || pending || document.hidden) return
      pending = true
      void api<{ status: string; detail: { error_code?: string } }>(`/tasks/${taskId}`, undefined, controller.signal).then(task => {
        if (cancelled) return
        setTaskStatus(task.status)
        if (['completed', 'failed', 'cancelled'].includes(task.status)) {
          setTaskId(undefined)
          if (task.detail.error_code) setError(task.detail.error_code)
          void refresh(current?.id)
        }
      }).catch(e => { if (!cancelled) { setError(String(e)); setTaskId(undefined) } })
        .finally(() => { pending = false })
    }
    const timer = window.setInterval(poll, 3000)
    document.addEventListener('visibilitychange', poll)
    return () => {
      cancelled = true; controller.abort(); window.clearInterval(timer)
      document.removeEventListener('visibilitychange', poll)
    }
  }, [taskId, current?.id])
  async function command(name: string, extra = {}) {
    if (!current) return
    const modelSteps: Record<string, string> = { outline: 'D07', followup: 'followup', minutes: 'D08', evaluation: 'D09', recommendation: 'D10' }
    if (modelSteps[name]) {
      const task = await api<{ task_id: string; status: string }>(`/calls/${current.id}/steps`, {
        expected_revision: current.revision, step: modelSteps[name],
        knowledge_preview: name === 'outline' ? preview : Boolean(current.session.knowledge_preview),
      })
      setTaskId(task.task_id); setTaskStatus(task.status)
      return
    }
    await api(`/calls/${current.id}/${name}`, { expected_revision: current.revision, ...extra })
    await refresh(current.id)
  }
  return <main style={{ maxWidth: 1100, margin: '32px auto', padding: 20 }}>
    <Typography.Title level={2}>知识库与电话报告 · 本地验收</Typography.Title>
    <Alert type="warning" showIcon message="虚构样例／演示规则；真实电话未验收。模型失败不会替换成模拟成功。" />
    <Space wrap style={{ margin: '20px 0' }}>
      <Input.Password value={password} onChange={e => setPassword(e.target.value)} placeholder=".env 中的 CHEETA_LOCAL_PASSWORD" autoComplete="current-password" />
      <Button loading={busy} disabled={!password || busy} onClick={() => void run(async () => {
        try { await api('/auth/login', { username: 'local-reviewer', password }) }
        catch (e) {
          if (String(e).includes('401')) throw new Error('登录失败：本地审核密码不匹配。请使用项目根目录 .env 中 CHEETA_LOCAL_PASSWORD 的值（不含引号），无需发送到聊天。', { cause: e })
          throw e
        }
        setPassword('')
        await refresh(new URL(window.location.href).searchParams.get('call') || undefined)
      })}>登录</Button>
      <Button disabled={busy} onClick={() => void run(async () => {
        await api('/auth/logout', {})
        setCurrent(undefined); setCalls([]); setTaskId(undefined); setTaskStatus(''); setMethods([])
        setAnswer(''); setCorrectionId(undefined); setCorrectionText(''); setReviewReason('')
      })}>退出登录</Button>
      <Button onClick={() => void run(() => refresh(current?.id))}>刷新服务端记录</Button>
      <Input value={fixtureBatch} onChange={e => setFixtureBatch(e.target.value)} placeholder="虚构验收批次（字母、数字、下划线或短横线）" />
      <Button disabled={busy || !/^[a-zA-Z0-9_-]{1,64}$/.test(fixtureBatch)} onClick={() => void run(async () => {
        const created = await api<CallCase>('/dev/fixture', { batch: fixtureBatch })
        await refresh(created.id)
      })}>导入虚构初筛通过样例（重复复用）</Button>
      <Select style={{ width: 300 }} placeholder="选择持久化电话任务" value={current?.id}
        options={calls.map(c => ({ value: c.id, label: c.application_id }))}
        onChange={id => void run(() => refresh(id))} />
    </Space>
    {error && <Alert type="error" message={error} />}
    {taskStatus && <Alert type="info" message={`模型步骤：${taskStatus}`} />}
    <KnowledgeReview />
    {current && <Space orientation="vertical" style={{ width: '100%' }}>
      <EvaluationStandardCard key={`standard-${current.id}-${current.revision}`} current={current} refresh={() => refresh(current.id)} />
      <PreflightCard key={current.id} current={current} refresh={() => refresh(current.id)} />
      <InvitationCard key={`invitation-${current.id}`} current={current} refresh={() => refresh(current.id)} />
      <Card title={`任务 ${current.id} · revision ${current.revision}`}>
        <p>状态：{current.status}；停止：{current.stop_status}</p>
        {current.failed_tasks?.map(task => <Alert key={task.id} type="error" style={{ marginBottom: 8 }}
          message={`${task.step} 失败：${task.error_code}（输入 revision ${task.input_revision}）`}
          description="先修复配置或权限原因，再手动重试。中断且结果不明的任务须核对，不自动重新执行。"
          action={<Button disabled={busy || Boolean(taskId) || task.input_revision !== current.revision || task.retry_count >= 3 || task.error_code === 'WORKER_INTERRUPTED_REVIEW_REQUIRED'}
            onClick={() => void run(async () => {
              const retried = await api<{ task_id: string }>(`/tasks/${task.id}/retry`, { expected_revision: current.revision })
              setTaskId(retried.task_id); setTaskStatus('queued'); await refresh(current.id)
            })}>修复后重试此步骤</Button>} />)}
        <Checkbox checked={preview} onChange={e => setPreview(e.target.checked)}>显式使用未审核知识开发预览</Checkbox>
        <Button disabled={busy} onClick={() => void run(async () => {
          const result = await api<{ items: unknown[] }>(`/knowledge/search?tags=responsibility,results,detail&preview=${preview}`)
          setMethods(result.items)
        })}>检索方法与出处</Button>
        {methods.length > 0 && <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(methods, null, 2)}</pre>}
        <Space wrap>
          <Button disabled={busy} onClick={() => void run(() => command('mock-start'))}>模拟接通（不拨号）</Button>
          <Button disabled={busy || current.stop_status !== 'requested'} onClick={() => void run(() => command('mock-confirm-stop'))}>模拟确认停止</Button>
          {['outline', 'followup', 'minutes', 'evaluation', 'recommendation', 'cancel'].map(name =>
            <Button key={name} disabled={busy} onClick={() => void run(() => command(name,
              name === 'outline' ? { knowledge_preview: preview } : {}))}>
              {{ outline: '生成 D07', followup: '生成动态追问', minutes: '生成 D08', evaluation: '生成 D09', recommendation: '生成 D10', cancel: '请求停止' }[name]}
            </Button>)}
        </Space>
        <Typography.Title level={5}>当前问题</Typography.Title>
        <p>{typeof current.session.current_question === 'object' && current.session.current_question !== null &&
          'question' in current.session.current_question ? String(current.session.current_question.question) : '尚未生成问题'}</p>
        <Typography.Title level={5}>已保存的实际回答</Typography.Title>
        {(Array.isArray(current.session.answers) ? current.session.answers : []).map((item: { id: string; text: string }) =>
          <p key={item.id} style={{ whiteSpace: 'pre-wrap' }}>{item.text}</p>)}
        <details><summary>会话、追问引用与模拟尝试原始记录</summary>
          <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(current.session, null, 2)}</pre>
        </details>
        <Input.TextArea value={answer} onChange={e => setAnswer(e.target.value)} placeholder="输入虚构候选人的实际回答" />
        <Button disabled={busy || !answer.trim() || Boolean(current.session.preflight_required &&
          !(current.session.preflight as { confirmed?: boolean } | undefined)?.confirmed)} onClick={() => void run(async () => {
          await command('answers', { answer }); setAnswer('')
        })}>保存回答</Button>
        <Typography.Title level={5}>更正已保存回答（下游需重算与重审）</Typography.Title>
        <Select style={{ width: '100%' }} placeholder="选择要更正的回答" value={correctionId}
          options={(Array.isArray(current.session.answers) ? current.session.answers : []).map((item: { id: string; text: string }) => ({ value: item.id, label: item.text.slice(0, 80) }))}
          onChange={id => setCorrectionId(id)} />
        <Input.TextArea value={correctionText} onChange={e => setCorrectionText(e.target.value)} placeholder="输入更正内容；保存历史并使旧纪要、评估和推荐失效" />
        <Button disabled={busy || !correctionId || !correctionText.trim()} onClick={() => void run(async () => {
          await api(`/calls/${current.id}/answers/${correctionId}/corrections`, {
            expected_revision: current.revision, answer: correctionText,
          })
          setCorrectionId(undefined); setCorrectionText(''); await refresh(current.id)
        })}>保存更正为新版本</Button>
      </Card>
      {current.artifacts?.map(a => <Card key={a.id} title={`${a.type} v${a.version} · ${a.review_status} · ${a.valid ? '有效' : '失效'}`}>
        <PostInterviewContent artifact={a} />
        <details><summary>来源、知识预览与模板版本</summary>
          <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(a.provenance, null, 2)}</pre>
        </details>
        {typeof a.content.content_markdown === 'string' &&
          <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>{a.content.content_markdown}</pre>}
        <details><summary>结构化内容与证据引用</summary>
          <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(a.content, null, 2)}</pre>
        </details>
        {a.type === 'D10' && <Space orientation="vertical" style={{ width: '100%' }}>
          <Input.TextArea value={reviewReason} onChange={e => setReviewReason(e.target.value)}
            placeholder="核对本版本内容、证据与来源后填写审核意见" aria-label="推荐报告审核意见" />
          <Space wrap>
          {(['approve', 'reject'] as const).map(action => <Button key={action}
            disabled={!a.valid || busy || !reviewReason.trim()} onClick={() => void run(async () => {
              await api(`/reports/${a.id}/review`, { expected_version: a.version, expected_revision: a.revision,
                action, reason: reviewReason.trim() }); setReviewReason(''); await refresh(current.id)
            })}>{action === 'approve' ? '批准此版本' : '驳回此版本'}</Button>)}
          <Button disabled={!a.valid || a.review_status !== 'approved'} onClick={() => void run(() => download(a))}>下载 Markdown</Button>
          </Space>
        </Space>}
      </Card>)}
    </Space>}
  </main>
}
