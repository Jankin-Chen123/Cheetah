import { useEffect, useState } from 'react'
import { Alert, Button, Card, Checkbox, Input, Select, Space, Typography } from 'antd'
import { api, download, type CallCase } from '../api/outreach'
import InvitationCard from '../InvitationCard'
import PreflightCard from '../PreflightCard'
import EvaluationStandardCard from '../EvaluationStandardCard'
import PostInterviewContent from '../PostInterviewContent'
import ClientContextCard from '../ClientContextCard'

export default function OutreachWorkspace() {
  const [password, setPassword] = useState('')
  const [calls, setCalls] = useState<CallCase[]>([])
  const [current, setCurrent] = useState<CallCase>()
  const [loggedIn, setLoggedIn] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState(false)
  const [answerId, setAnswerId] = useState<string>()
  const [replacement, setReplacement] = useState('')
  const currentEvaluation = current?.artifacts?.find(artifact => artifact.type === 'D09' && artifact.valid)
  const waitingForReports = current?.status === 'ended' && Array.isArray(current.session.answers) && current.session.answers.length > 0 && !current.session.correction_requires_recompute &&
    !current.failed_tasks?.length && !current.artifacts?.some(artifact => artifact.type === 'D10' && artifact.valid) &&
    (!currentEvaluation || currentEvaluation.content.conclusion === 'recommended')
  async function refresh(id?: string) {
    const list = await api<{ items: CallCase[] }>('/calls'); setCalls(list.items)
    if (id) {
      setCurrent(await api<CallCase>(`/calls/${id}`))
      const url = new URL(window.location.href); url.searchParams.set('call', id)
      window.history.replaceState(null, '', url)
    }
  }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('')
    try { await action() } catch (reason) { setError(String(reason)) }
    finally { setBusy(false) }
  }
  useEffect(() => {
    let active = true
    void api('/auth/me').then(async () => {
      if (active) { setLoggedIn(true); await refresh(new URL(window.location.href).searchParams.get('call') || undefined) }
    }).catch(() => {})
    return () => { active = false }
  }, [])
  useEffect(() => {
    if (!current || (!current.active_tasks?.length && !waitingForReports)) return
    let cancelled = false
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const id = current.id
    async function poll() {
      try {
        if (document.visibilityState === 'visible' && !cancelled) {
          const detail = await api<CallCase>(`/calls/${id}`, undefined, controller.signal)
          if (!cancelled) setCurrent(detail)
        }
      }
      catch (reason) { if (!cancelled) setError(String(reason)) }
      if (!cancelled) timer = setTimeout(() => void poll(), 3000)
    }
    timer = setTimeout(() => void poll(), 3000)
    return () => { cancelled = true; controller.abort(); clearTimeout(timer) }
  }, [current, waitingForReports])
  const answers = (current?.session.answers ?? []) as { id: string; text: string; question: { question: string } }[]
  return <Space orientation="vertical" style={{ width: '100%' }}>
    <Typography.Title level={2}>面试与推荐工作区</Typography.Title>
    <Alert type="info" message="本地持久化业务入口；现有案例继承虚构上游与演示评估规则。真实上游尚未接通。" />
    {error && <Alert type="error" message={error} />}
    {!loggedIn ? <Card title="本地账户登录">
      <Input.Password value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" placeholder="本地审核密码" />
      <Button disabled={busy || !password} onClick={() => void run(async () => {
        await api('/auth/login', { username: 'local-reviewer', password }); setPassword('')
        setLoggedIn(true); await refresh(new URL(window.location.href).searchParams.get('call') || undefined)
      })}>登录</Button>
    </Card> : <>
      <Space wrap>
        <Select style={{ minWidth: 300 }} placeholder="选择服务端面试任务" value={current?.id}
          options={calls.map(call => ({ value: call.id, label: `${call.candidate_id} · ${call.status}` }))}
          onChange={id => { setAnswerId(undefined); setReplacement(''); setReason(''); void run(() => refresh(id)) }} />
        <Button disabled={busy} onClick={() => void run(() => refresh(current?.id))}>刷新记录</Button>
        <Button onClick={() => void run(async () => { await api('/auth/logout', {}); setLoggedIn(false); setCurrent(undefined); setCalls([]) })}>退出</Button>
      </Space>
      {current && <>
        <EvaluationStandardCard key={`standard-${current.id}-${current.revision}`} current={current} refresh={() => refresh(current.id)} />
        <Card title="面试与报告进度">
          {current.session.outline_requires_regeneration === true && <Alert type="warning" message="面试标准已更新，旧提纲已失效。请重新生成 D07 后继续面试；仍可随时停止。" />}
          <Typography.Paragraph>电话状态：{current.status}；停止状态：{current.stop_status}</Typography.Paragraph>
          <Space wrap>
            <Button disabled={busy || current.stop_status !== 'none' || ['ended', 'cancelled'].includes(current.status)} onClick={() => void run(async () => {
              await api(`/calls/${current.id}/cancel`, { expected_revision: current.revision }); await refresh(current.id)
            })}>请求停止</Button>
            {current.fixture_only && <Button disabled={busy || current.stop_status !== 'requested'} onClick={() => void run(async () => {
              await api(`/calls/${current.id}/mock-confirm-stop`, { expected_revision: current.revision }); await refresh(current.id)
            })}>模拟确认停止（不拨号）</Button>}
          </Space>
          <Checkbox checked={preview} onChange={event => setPreview(event.target.checked)}>显式开发知识预览（未审核方法，不能作为正式标准）</Checkbox>
          <Space wrap>
            {['D07', 'D08', 'D09', 'D10'].map(step => <Button key={step} disabled={busy || Boolean(current.active_tasks?.length)} onClick={() => void run(async () => {
              await api(`/calls/${current.id}/steps`, { expected_revision: current.revision, step, knowledge_preview: step === 'D07' ? preview : Boolean(current.session.knowledge_preview) })
              await refresh(current.id)
            })}>生成 {step}</Button>)}
          </Space>
          {current.active_tasks?.map(task => <Typography.Paragraph key={task.id}>{task.step}：{task.status}</Typography.Paragraph>)}
          {current.failed_tasks?.map(task => <Alert key={task.id} type="error" message={`${task.step}：${task.error_code ?? '失败待核对'}`} />)}
        </Card>
        <PreflightCard key={current.id} current={current} refresh={() => refresh(current.id)} />
        <InvitationCard key={`invite-${current.id}`} current={current} refresh={() => refresh(current.id)} />
        <Card title="实际问答与更正">
          {answers.map(answer => <Typography.Paragraph key={answer.id}>问：{answer.question.question}<br />答：{answer.text}</Typography.Paragraph>)}
          <Select style={{ width: '100%' }} placeholder="选择需要更正的回答" value={answerId} onChange={setAnswerId} options={answers.map(answer => ({ value: answer.id, label: answer.text }))} />
          <Input.TextArea value={replacement} onChange={event => setReplacement(event.target.value)} placeholder="实际更正内容；保存会使下游旧报告及批准失效" />
          <Button disabled={busy || !answerId || !replacement.trim()} onClick={() => void run(async () => {
            await api(`/calls/${current.id}/answers/${answerId}/corrections`, { expected_revision: current.revision, answer: replacement })
            setAnswerId(undefined); setReplacement(''); await refresh(current.id)
          })}>保存新回答版本</Button>
        </Card>
        <Input.TextArea value={reason} onChange={event => setReason(event.target.value)} placeholder="核读具体推荐版本后填写真实审核意见" />
        <ClientContextCard key={current.id} current={current} onSaved={() => refresh(current.id)} />
        {current.artifacts?.map(artifact => <Card key={artifact.id} title={`${artifact.type} v${artifact.version} · ${artifact.valid ? '有效' : '失效'} · ${artifact.review_status}`}>
          <PostInterviewContent artifact={artifact} />
          {typeof artifact.content.content_markdown === 'string' && <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{artifact.content.content_markdown}</Typography.Paragraph>}
          <details><summary>结构化内容与证据引用</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(artifact.content, null, 2)}</pre></details>
          <details><summary>来源和输入版本</summary><pre>{JSON.stringify({ provenance: artifact.provenance, input_refs: artifact.input_refs }, null, 2)}</pre></details>
          {artifact.type === 'D10' && <Button disabled={!artifact.valid || artifact.review_status !== 'approved'} onClick={() => void run(() => download(artifact))}>下载已批准版本</Button>}
          {artifact.type === 'D10' && <Button disabled={!artifact.valid || artifact.review_status !== 'approved'} onClick={() => void run(() => download(artifact, 'docx'))}>下载 Word</Button>}
          {artifact.type === 'D10' && <Space>{(['approve', 'reject'] as const).map(action => <Button key={action} disabled={busy || !artifact.valid || !reason.trim()} onClick={() => void run(async () => {
            await api(`/reports/${artifact.id}/review`, { expected_version: artifact.version, expected_revision: artifact.revision, action, reason: reason.trim() })
            setReason(''); await refresh(current.id)
          })}>{action === 'approve' ? '批准此版本' : '驳回此版本'}</Button>)}</Space>}
        </Card>)}
      </>}
    </>}
  </Space>
}
