import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Checkbox, Empty, Input, Select, Space, Table, Tag, Typography } from 'antd'
import { api, download, regenerateRecommendation, type CallCase } from '../api/outreach'
import { Icon, PageHeading, Person } from './ui'
import InvitationCard from '../InvitationCard'
import PreflightCard from '../PreflightCard'
import EvaluationStandardCard from '../EvaluationStandardCard'
import PostInterviewContent from '../PostInterviewContent'
import ClientContextCard from '../ClientContextCard'
import CareerConfirmationCard from '../CareerConfirmationCard'

export default function OutreachWorkspace({ view = 'calls' }: { view?: 'calls' | 'reports' }) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [calls, setCalls] = useState<CallCase[]>([])
  const [current, setCurrent] = useState<CallCase>()
  const [loggedIn, setLoggedIn] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [reviewDrafts, setReviewDrafts] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState(false)
  const [answerId, setAnswerId] = useState<string>()
  const [replacement, setReplacement] = useState('')
  const currentEvaluation = current?.artifacts?.find(artifact => artifact.type === 'D09' && artifact.valid)
  const currentReport = current?.artifacts?.find(artifact => artifact.type === 'D10' && artifact.valid)
  const termination = current?.session.termination_reason
  const terminationLabel = typeof termination === 'string' ? ({
    interview_completed: '正常完成面试',
    candidate_requested_stop: '候选人主动结束',
    reviewer_requested_stop: '审核人请求停止',
    candidate_declined: '候选人未进入正式面试',
    duration_limit: '达到时长上限',
  } as Record<string, string>)[termination] ?? termination : undefined
  const waitingForReports = current?.status === 'ended' && Array.isArray(current.session.answers) && current.session.answers.length > 0 && !current.session.correction_requires_recompute &&
    !current.session.postprocessing_blocked &&
    !current.failed_tasks?.length && !current.artifacts?.some(artifact => artifact.type === 'D10' && artifact.valid) &&
    (!currentEvaluation || currentEvaluation.content.conclusion === 'recommended')
  const refresh = useCallback(async (id?: string, signal?: AbortSignal) => {
    const list = await api<{ items: CallCase[] }>('/calls', undefined, signal)
    const items = view === 'reports' ? await Promise.all(list.items.map(item => api<CallCase>(`/calls/${item.id}`, undefined, signal))) : list.items
    if (signal?.aborted) return
    setCalls(items)
    if (id && (view !== 'reports' || items.some(item => item.id === id && item.artifacts?.some(artifact => artifact.type === 'D10' && artifact.valid)))) {
      setCurrent(await api<CallCase>(`/calls/${id}`, undefined, signal))
      const url = new URL(window.location.href); url.searchParams.set('call', id)
      window.history.replaceState(null, '', url)
    }
  }, [view])
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('')
    try { await action() } catch (reason) { setError(String(reason)) }
    finally { setBusy(false) }
  }
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    void api('/auth/me', undefined, controller.signal).then(async () => {
      if (active) { setLoggedIn(true); await refresh(new URL(window.location.href).searchParams.get('call') || undefined, controller.signal) }
    }).catch(reason => { if (active) setError(String(reason)) })
    return () => { active = false; controller.abort() }
  }, [refresh])
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
  function label(call: CallCase, document: string, field: string, fallback: string) {
    const upstream = call.session.upstream_content as Record<string, Record<string, unknown>> | undefined
    const value = upstream?.[document]?.[field]
    return typeof value === 'string' && value.trim() ? value : fallback
  }
  const candidateName = (call: CallCase) => label(call, 'D03', 'display_name', call.candidate_id)
  const jobTitle = (call: CallCase) => label(call, 'D01', 'title', call.job_id)
  const states: Record<string, string> = { waiting_conditions: '等待联系条件', queued: '等待沟通', in_progress: '沟通中', ended: '已结束', cancelled: '已取消' }
  const latestReport = (call: CallCase) => call.artifacts?.find(artifact => artifact.type === 'D10' && artifact.valid)
  const visible = calls.filter(call => candidateName(call).includes(query) && (status === 'all' || call.status === status) && (view !== 'reports' || latestReport(call)))
  return <Space orientation="vertical" style={{ width: '100%' }}>
    <PageHeading title={view === 'reports' ? '推荐审核' : '电话任务'} actions={current && <Space><Button onClick={() => { setCurrent(undefined); const url = new URL(window.location.href); url.searchParams.delete('call'); window.history.replaceState(null, '', url); void run(() => refresh()) }}>返回列表</Button><Button loading={busy} onClick={() => void run(() => refresh(current.id))}>刷新记录</Button></Space>} />
    {error && <Alert type="error" title={error} />}
    {!loggedIn ? <Alert type="info" title="正在检查账号与面试任务" action={<Button href="/#login">前往登录</Button>} /> : <>
      {!current && <section className="panel">
        <div className="filter-bar"><Input aria-label={view === 'reports' ? '搜索推荐报告' : '搜索电话任务'} prefix={<Icon name="search" size={17} />} placeholder="搜索候选人" allowClear value={query} onChange={event => setQuery(event.target.value)} /><Select aria-label="电话任务状态" value={status} onChange={setStatus} options={[{ value: 'all', label: '全部电话状态' }, ...Object.entries(states).map(([value, label]) => ({ value, label }))]} /><Button loading={busy} onClick={() => void run(() => refresh())}>刷新</Button></div>
        <Table<CallCase> rowKey="id" scroll={{ x: 850 }} dataSource={visible} locale={{ emptyText: <Empty description={view === 'reports' ? '暂无推荐报告' : '暂无电话任务'} /> }} pagination={{ pageSize: 8 }} columns={[
          { title: '候选人', render: (_, call, index) => <Person name={candidateName(call)} detail={jobTitle(call)} index={index} /> },
          { title: view === 'reports' ? '审核状态' : '任务状态', render: (_, call) => <Tag>{view === 'reports' ? ({ approved: '已批准', rejected: '已驳回', pending_review: '待审核' }[latestReport(call)?.review_status ?? ''] ?? '待审核') : states[call.status] ?? call.status}</Tag> },
          { title: '当前情况', render: (_, call) => <span className="muted">{call.stop_status === 'requested' ? '正在停止，等待确认' : call.stop_status === 'confirmed' ? '已停止' : view === 'reports' ? `推荐报告 v${latestReport(call)?.version}` : '查看面试准备与沟通记录'}</span> },
          ...(view === 'calls' ? [{ title: '尝试', render: (_: unknown, call: CallCase) => `${Array.isArray(call.session.attempts) ? call.session.attempts.length : 0} 条记录` }] : []),
          { title: '操作', render: (_, call) => <Button type="link" onClick={() => void run(() => refresh(call.id))}>{view === 'reports' ? '查看与审核' : '查看任务'}</Button> },
        ]} />
      </section>}
      {current && <>
        <EvaluationStandardCard key={`standard-${current.id}-${current.revision}`} current={current} refresh={() => refresh(current.id)} />
        <Card title="面试与报告进度">
          {typeof current.session.postprocessing_blocked === 'string' && <Alert type="warning"
            title="面试后处理尚未开始"
            description={`会话交接未通过：${current.session.postprocessing_blocked}。请核对候选人处理许可、实际问题版本与回答记录；补齐后由后台重新检查。不会自动重拨。`} />}
          {current.session.outline_requires_regeneration === true && <Alert type="warning" title="面试标准已更新，旧提纲已失效。请重新生成 D07 后继续面试；仍可随时停止。" />}
          <Typography.Paragraph>会话状态：{current.status}；停止状态：{current.stop_status}{terminationLabel && `；结束原因：${terminationLabel}`}</Typography.Paragraph>
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
            {['D07', 'D08', 'D09'].map(step => <Button key={step} disabled={busy || Boolean(current.active_tasks?.length)} onClick={() => void run(async () => {
              await api(`/calls/${current.id}/steps`, { expected_revision: current.revision, step, knowledge_preview: step === 'D07' ? preview : Boolean(current.session.knowledge_preview) })
              await refresh(current.id)
            })}>生成 {step}</Button>)}
          </Space>
          {(!currentReport || currentReport.review_status === 'rejected') && currentEvaluation?.content.conclusion === 'recommended' && <Space wrap>
            <Button type="primary" disabled={busy || Boolean(current.active_tasks?.length)} onClick={() => void run(async () => {
              await regenerateRecommendation(current.id, current.revision)
              await refresh(current.id)
            })}>{current.artifacts?.some(a => a.type === 'D10') ? '生成新版推荐报告' : '生成推荐报告'}</Button>
            <span>新版本须单独审核；旧版本的批准不会沿用。</span>
          </Space>}
          {current.session.correction_requires_recompute === true && !currentEvaluation && <p>回答已更正。请先重新生成 D08，再更新 D09；只有当前评估达标才能生成新版推荐。</p>}
          {currentEvaluation && currentEvaluation.content.conclusion !== 'recommended' && <p>当前评估未达到推荐条件；请查看 D09 的结论与证据缺口。</p>}
          {current.active_tasks?.map(task => <Typography.Paragraph key={task.id}>{task.step}：{task.status}</Typography.Paragraph>)}
          {current.failed_tasks?.map(task => <Alert key={task.id} type="error" title={`${task.step}：${task.error_code ?? '失败待核对'}`}
            action={task.error_code !== 'WORKER_INTERRUPTED_REVIEW_REQUIRED' && task.input_revision === current.revision && task.retry_count < 3 && <Button disabled={busy || Boolean(current.active_tasks?.length)} onClick={() => void run(async () => {
              await api(`/interview-tasks/${task.id}/retry`, { expected_revision: current.revision }); await refresh(current.id)
            })}>重试失败步骤</Button>} />)}
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
        <ClientContextCard key={current.id} current={current} onSaved={() => refresh(current.id)} />
        <CareerConfirmationCard key={`career-${current.id}`} current={current} onSaved={() => refresh(current.id)} />
        {current.artifacts?.map(artifact => <Card key={artifact.id} title={`${artifact.type} v${artifact.version} · ${artifact.valid ? '有效' : '失效'} · ${artifact.review_status}`}>
          <PostInterviewContent artifact={artifact} />
          {artifact.type === 'D07' && <Button disabled={!artifact.valid} onClick={() => void run(() => download(artifact, 'docx'))}>下载面试准备稿 Word</Button>}
          {artifact.type === 'D08' && <Button disabled={!artifact.valid} onClick={() => void run(() => download(artifact, 'docx'))}>下载内部信息提取 Word</Button>}
          {artifact.type === 'D09' && <Button disabled={!artifact.valid} onClick={() => void run(() => download(artifact, 'docx'))}>下载内部评估 Word（非客户报告）</Button>}
          {typeof artifact.content.content_markdown === 'string' && <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{artifact.content.content_markdown}</Typography.Paragraph>}
          <details><summary>结构化内容与证据引用</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(artifact.content, null, 2)}</pre></details>
          <details><summary>来源和输入版本</summary><pre>{JSON.stringify({ provenance: artifact.provenance, input_refs: artifact.input_refs }, null, 2)}</pre></details>
          {artifact.type === 'D10' && <Button disabled={!artifact.valid || artifact.review_status !== 'approved'} onClick={() => void run(() => download(artifact))}>下载客户 Markdown</Button>}
          {artifact.type === 'D10' && <Button disabled={!artifact.valid || artifact.review_status !== 'approved'} onClick={() => void run(() => download(artifact, 'docx'))}>下载客户 Word</Button>}
          {artifact.type === 'D10' && artifact.valid && <Space orientation="vertical">
            <Input.TextArea aria-label={`D10 v${artifact.version} 审核意见`} value={reviewDrafts[artifact.id] ?? ''} maxLength={2000}
              onChange={event => setReviewDrafts(drafts => ({ ...drafts, [artifact.id]: event.target.value }))}
              placeholder="核读此版本后填写审核意见" />
            <Space>{(['approve', 'reject'] as const).map(action => <Button key={action} disabled={busy || !artifact.valid || !reviewDrafts[artifact.id]?.trim()} onClick={() => void run(async () => {
            await api(`/reports/${artifact.id}/review`, { expected_version: artifact.version, expected_revision: artifact.revision, action, reason: reviewDrafts[artifact.id].trim() })
            setReviewDrafts(drafts => ({ ...drafts, [artifact.id]: '' })); await refresh(current.id)
          })}>{action === 'approve' ? '批准此版本' : '驳回此版本'}</Button>)}</Space></Space>}
        </Card>)}
      </>}
    </>}
  </Space>
}
