import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Input, Space, Typography } from 'antd'
import { candidateRequest, processingPurposes, type CandidateSession } from './api/candidate'
import ProcessingPermissions from './ProcessingPermissions'

export default function CandidateTextInterview() {
  const [access] = useState(() => {
    const params = new URLSearchParams(location.hash.slice(1))
    return { caseId: params.get('call') ?? '', token: params.get('token') ?? '' }
  })
  const [session, setSession] = useState<CandidateSession>()
  const latest = useRef<CandidateSession | undefined>(undefined)
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const mutating = useRef(false)
  const [error, setError] = useState('')
  const update = (value: CandidateSession) => {
    if (!latest.current || value.revision >= latest.current.revision) {
      latest.current = value; setSession(value)
    }
  }
  useEffect(() => {
    if (!access.caseId || !access.token) return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    async function refresh() {
      try {
        if (!mutating.current && !document.hidden) {
          const value = await candidateRequest(access.caseId, access.token)
          if (active) update(value)
        }
      } catch (failure) { if (active) setError((failure as Error).message) }
      finally { if (active) timer = setTimeout(() => void refresh(), 2000) }
    }
    void refresh()
    return () => { active = false; clearTimeout(timer) }
  }, [access])
  async function command(action: string, statement: string, extra = {}) {
    if (!latest.current || mutating.current) return
    mutating.current = true; setBusy(true); setError('')
    const before = latest.current
    try {
      const value = await candidateRequest(access.caseId, access.token, {
        expected_revision: before.revision, action, statement, ...extra,
      })
      update(value)
      if (action === 'answer') {
        setAnswer('')
      }
    } catch (failure) { setError((failure as Error).message) }
    finally { mutating.current = false; setBusy(false) }
  }
  const stopped = !!session && (['ended', 'cancelled'].includes(session.status) || session.stop_status !== 'none')
  const permitted = !!session && processingPurposes.every(([purpose]) => session.processing_permissions?.[purpose] === 'AUTHORIZED')
  if (!access.caseId || !access.token) return <Alert type="error" title="请通过本次面试的有效邀请链接进入。" />
  return <main className="panel stack" style={{ maxWidth: 900, margin: '24px auto', padding: 24 }}>
    <Typography.Title level={2}>AI 文字面试</Typography.Title>
    {error && <Alert type="error" showIcon title={error} />}
    {!session && <p>正在读取本次面试…</p>}
    {session && <>
      <h3>{session.material.job_title ?? '岗位信息待确认'}</h3>
      <p>本次通过文字沟通，回答按您选择的许可用于岗位信息整理和内部评估。</p>
      {stopped && <Alert type="info" title="本次对话已结束，已保存的回答将按许可范围处理。" />}
      {!stopped && !session.preflight.interested && <Button disabled={busy} onClick={() => void command('interest', '我对本岗位有求职意愿，希望查看岗位资料。', { interested: true })}>我有求职意愿，查看岗位资料</Button>}
      {session.preflight.interested && <Card title="岗位资料">
        <p>职责：{session.material.requirements.join('；') || '待招聘方确认'}</p>
        <p>薪资：{typeof session.material.salary === 'string' ? session.material.salary : '待招聘方确认'}</p>
        <p>企业：{typeof session.material.company_introduction === 'string' ? session.material.company_introduction : '待招聘方确认'}</p>
      </Card>}
      <ProcessingPermissions textMode caseId={access.caseId} token={access.token} session={session} onChange={update} />
      {!stopped && session.preflight.interested && !session.preflight.confirmed && <Button type="primary" disabled={busy || !permitted} onClick={() => void command('confirm', '我已阅读岗位资料，并同意按已选择的许可开始本次文字面试。', { material_sha256: session.material_sha256 })}>确认岗位资料并开始文字面试</Button>}
      {(session.turn_history ?? []).map((item, index) => <Card key={index} size="small"><p><strong>AI 面试官：</strong>{item.question}</p><p><strong>我的回答：</strong>{item.answer}</p></Card>)}
      {session.preflight.confirmed && !stopped && <Card title="AI 面试官">
        <p role="status" aria-live="polite">{session.decision_status === 'pending' ? '正在分析本轮回答…' : session.question ?? session.spoken_prompt ?? '正在准备下一问…'}</p>
        {session.decision_task?.error_code && <Alert type="error" title="本轮处理未完成，请联系邀请人核对任务。" />}
        <Input.TextArea aria-label="文字回答" value={answer} onChange={event => setAnswer(event.target.value)} rows={6} maxLength={10000} disabled={busy || session.decision_status === 'pending'} />
        <Button type="primary" loading={busy} disabled={!answer.trim() || !permitted || !session.question || session.decision_status === 'pending'} onClick={() => void command('answer', answer.trim())}>发送回答</Button>
      </Card>}
      {!stopped && <Space><Button danger disabled={busy} onClick={() => void command('stop', '候选人要求结束本次对话。')}>结束本次对话</Button></Space>}
    </>}
  </main>
}
