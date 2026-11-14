import { useState } from 'react'
import { Button, Card, Input, Space } from 'antd'
import { api, type CallCase } from './api/outreach'

export default function ClientContextCard({ current, onSaved }: { current: CallCase; onSaved: () => Promise<void> }) {
  const [clientId, setClientId] = useState('')
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const savedContext = current.session.client_context as { candidate_client_label?: string } | undefined
  const sharing = current.session.client_sharing as { status?: string } | undefined
  async function save() {
    setBusy(true); setMessage('')
    try {
      await api(`/calls/${current.id}/client-context`, { expected_revision: current.revision, client_company_id: clientId.trim(), candidate_client_label: label.trim() })
      await onSaved(); setMessage('客户范围已保存，请候选人在受限链接中单独确认分享许可。')
    } catch (reason) { setMessage(String(reason)) }
    finally { setBusy(false) }
  }
  return <Card title="推荐客户与分享范围">
    <p>当前客户：{savedContext?.candidate_client_label ?? '尚未设置'}；候选人分享许可：{sharing?.status === 'AUTHORIZED' ? '已同意' : sharing?.status === 'WITHDRAWN' ? '已撤回' : '待确认'}</p>
    <p>填写当前招聘项目的客户标识，以及获准向候选人披露的客户名称。更换客户会使旧推荐及批准失效；内部评估许可不能替代客户分享许可。</p>
    <Space wrap>
      <Input aria-label="客户企业标识" placeholder="客户企业标识" value={clientId} onChange={event => setClientId(event.target.value)} />
      <Input aria-label="允许披露的客户名称" placeholder="允许披露的客户名称" value={label} onChange={event => setLabel(event.target.value)} />
      <Button loading={busy} disabled={!clientId.trim() || !label.trim()} onClick={() => void save()}>保存客户范围</Button>
    </Space>
    {message && <p role="status">{message}</p>}
  </Card>
}
