import { useState } from 'react'
import { Alert, Button, Card, Input, Space, Typography } from 'antd'
import { api, type CallCase } from './api/outreach'

export default function InvitationCard({ current, refresh }: { current: CallCase; refresh: () => Promise<void> }) {
  const [link, setLink] = useState('')
  const [expiry, setExpiry] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function act(action: 'issue' | 'revoke') {
    setBusy(true); setError(''); setLink('')
    try {
      const result = await api<{ token?: string; expires_at?: number }>(`/calls/${current.id}/invitation`, {
        expected_revision: current.revision, action, lifetime_seconds: 3600,
      })
      if (result.token && result.expires_at) {
        const url = new URL('/candidate', window.location.origin)
        url.hash = new URLSearchParams({ call: current.id, token: result.token }).toString()
        setLink(url.toString()); setExpiry(new Date(result.expires_at * 1000).toLocaleString())
      } else setExpiry('')
      await refresh()
    } catch (reason) { setError(String(reason)) }
    finally { setBusy(false) }
  }
  const stopped = ['ended', 'cancelled'].includes(current.status) || current.stop_status !== 'none'
  return <Card title="候选人受限邀请">
    <Typography.Paragraph>链接仅允许访问本次面试，有效期一小时。重新生成会使旧链接失效；不会自动发送。</Typography.Paragraph>
    <Alert type="info" message="本机地址仅供本机验收；候选人远程访问仍需获准的 HTTPS 服务。候选人页面已接分段录音转写和问题播报，连续实时通话与浏览器验收待完成。" />
    {error && <Alert type="error" message={error} />}
    <Space style={{ marginTop: 12 }}>
      <Button disabled={busy || stopped} onClick={() => void act('issue')}>生成新邀请</Button>
      <Button disabled={busy} onClick={() => void act('revoke')}>撤销邀请</Button>
    </Space>
    {link && <>
      <Typography.Paragraph>有效至 {expiry}。请妥善保管，持有者可进入该面试。</Typography.Paragraph>
      <Input.TextArea readOnly value={link} autoSize />
    </>}
  </Card>
}
