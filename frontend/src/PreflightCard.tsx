import { useState } from 'react'
import { Alert, Button, Card, Input, Space } from 'antd'
import { api, type CallCase } from './api/outreach'

export default function PreflightCard({ current, refresh }: { current: CallCase; refresh: () => Promise<void> }) {
  const [statement, setStatement] = useState('')
  const [email, setEmail] = useState('')
  const [requestId, setRequestId] = useState(() => crypto.randomUUID())
  const [briefing, setBriefing] = useState<{ material: Record<string, unknown>; sha256: string }>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function act(body: Record<string, unknown>) {
    setBusy(true); setError('')
    try {
      await api(`/calls/${current.id}/preflight`, { expected_revision: current.revision, statement, ...body })
      await refresh()
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  const state = current.session.preflight as { interested?: boolean; confirmed?: boolean } | undefined
  const stopped = current.status === 'ended' || current.status === 'cancelled' || current.stop_status !== 'none'
  return <Card title="面试前：意愿与岗位信息确认">
    <p>先询问候选人：您目前是否有找工作或了解新机会的需求？</p>
    <p>有意愿后再介绍岗位要求、薪资范围和公司信息；未提供的信息保留未知，不作承诺。</p>
    <p>求职意愿：{state?.interested === undefined ? '待询问' : state.interested ? '有意愿' : '暂无意愿'}；开始确认：{state?.confirmed ? '已确认' : '未确认'}</p>
    <Input.TextArea value={statement} onChange={e => setStatement(e.target.value)} placeholder="记录候选人的实际原话：意愿、材料发送许可或了解材料后是否愿意开始。不要代替候选人同意。" />
    <Space wrap style={{ marginTop: 12 }}>
      <Button disabled={busy || stopped || !statement.trim()} onClick={() => void act({ action: 'interest', interested: true })}>记录有求职意愿</Button>
      <Button disabled={busy || stopped || !statement.trim()} onClick={() => void act({ action: 'interest', interested: false })}>记录暂无意愿</Button>
      <Button disabled={busy} onClick={() => {
        setError(''); void api<{ material: Record<string, unknown>; sha256: string }>(`/calls/${current.id}/briefing`).then(setBriefing).catch(e => setError(String(e)))
      }}>查看岗位、薪资及公司材料</Button>
    </Space>
    {briefing && <>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(briefing.material, null, 2)}</pre>
      <Alert type="info" message="邮件尚未接入真实服务。下面只生成模拟记录，不会向邮箱发信；仅接受虚构 .test 邮箱。" />
      <Input value={email} onChange={e => { setEmail(e.target.value); setRequestId(crypto.randomUUID()) }} placeholder="虚构邮箱 candidate@example.test" />
      <Space wrap style={{ marginTop: 12 }}>
        <Button disabled={busy || stopped || !state?.interested || !statement.trim() || !email} onClick={() => void act({ action: 'mock_email', email, request_id: requestId })}>模拟发送岗位与公司材料</Button>
        <Button disabled={busy || stopped || !state?.interested || !statement.trim()} onClick={() => void act({ action: 'confirm', material_sha256: briefing.sha256 })}>记录候选人已了解材料并同意开始面试</Button>
      </Space>
    </>}
    {error && <Alert type="error" message={error} />}
  </Card>
}
