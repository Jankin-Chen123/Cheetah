import { useState } from 'react'
import { Alert, Button, Space } from 'antd'
import { setProcessingPermission, setClientSharing, processingPurposes, type CandidateSession } from './api/candidate'

export default function ProcessingPermissions({ caseId, token, session, onChange }: {
  caseId: string; token: string; session: CandidateSession; onChange: (value: CandidateSession) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const stopped = ['ended', 'cancelled'].includes(session.status) || session.stop_status !== 'none'
  async function update(purpose: string, authorized: boolean) {
    setBusy(true); setError('')
    try { onChange(await setProcessingPermission(caseId, token, session.revision, purpose, authorized)) }
    catch (reason) { setError(String(reason)) }
    finally { setBusy(false) }
  }
  async function share(authorized: boolean) {
    setBusy(true); setError('')
    try { onChange(await setClientSharing(caseId, token, session.revision, authorized)) }
    catch (reason) { setError(String(reason)) }
    finally { setBusy(false) }
  }
  return <section aria-label="本次面试资料使用许可" className="call-material">
    <h3>本次面试资料使用许可</h3>
    <p>请逐项选择。许可仅用于本岗位的面试与内部处理，不包含向客户分享或自动发送报告；可随时撤回。</p>
    {processingPurposes.map(([purpose, label]) => {
      const granted = session.processing_permissions?.[purpose] === 'AUTHORIZED'
      return <p key={purpose}><Space wrap><span>{label}：{granted ? '已同意' : '未同意'}</span>
        <Button size="small" disabled={busy || stopped || granted} onClick={() => void update(purpose, true)}>同意此项</Button>
        <Button size="small" disabled={busy || !granted} onClick={() => void update(purpose, false)}>撤回此项</Button>
      </Space></p>
    })}
    {session.client_sharing && <div>
      <h4>向客户分享职业资料</h4>
      <p>仅为本岗位招聘目的，向“{session.client_sharing.client_label}”分享本次职业资料和审核后的推荐报告。此项不影响内部面试，您可以单独选择或撤回。</p>
      <Space wrap><span>{session.client_sharing.status === 'AUTHORIZED' ? '已同意' : '未同意'}</span>
        <Button size="small" disabled={busy || session.client_sharing.status === 'AUTHORIZED'} onClick={() => void share(true)}>同意向该客户分享</Button>
        <Button size="small" disabled={busy || session.client_sharing.status !== 'AUTHORIZED'} onClick={() => void share(false)}>撤回客户分享许可</Button>
      </Space>
    </div>}
    {error && <Alert type="error" message={error} />}
  </section>
}
