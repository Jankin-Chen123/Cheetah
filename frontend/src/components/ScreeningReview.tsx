import { useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, Select } from 'antd'
import type { components } from '../api/generated'
import { intakeRequest, IntakeApiError, type IntakeSession } from '../api/jobIntake'

export default function ScreeningReview({ applicationId, artifact, session, onSaved }: {
  applicationId: string; artifact: components['schemas']['Artifact']; session: IntakeSession; onSaved: () => void;
}) {
  const [result, setResult] = useState<'passed' | 'unknown' | 'rejected' | 'manual_review'>('manual_review')
  const [reason, setReason] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const intent = useRef<{ key: string; body: components['schemas']['ScreeningReviewInput'] } | null>(null)
  async function save() {
    if (busy) return
    setBusy(true); setError('')
    const pending = intent.current ?? { key: crypto.randomUUID(), body: {
      expected_d06_ref: { artifact_id: artifact.artifact_id, version: artifact.version },
      result, reason: reason.trim(), evidence_refs: artifact.evidence_refs.slice(0, 30),
    } }
    intent.current = pending
    try {
      await intakeRequest(`/applications/${encodeURIComponent(applicationId)}/screening-review`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token, 'Idempotency-Key': pending.key }, body: JSON.stringify(pending.body),
      })
      intent.current = null; setReason(''); setAcknowledged(false); onSaved()
    } catch (failure) {
      if (failure instanceof IntakeApiError && failure.status >= 400 && failure.status < 500) intent.current = null
      setError((failure as Error).message)
    } finally { setBusy(false) }
  }
  return <section className="panel stack">
    <h3>人工复核初筛 v{artifact.version}</h3>
    <Alert type="info" title="先核读下方初筛报告与证据，再提交复核。通过仅进入面试准备，缺口继续保留。" />
    {error && <Alert type="error" title={error} />}
    <Select aria-label="初筛复核结论" value={result} disabled={busy} onChange={setResult} options={[
      { value: 'manual_review', label: '仍待复核' }, { value: 'unknown', label: '信息不足' },
      { value: 'passed', label: '通过，进入面试核实' }, { value: 'rejected', label: '不通过' },
    ]} />
    <Input.TextArea aria-label="初筛复核理由" value={reason} disabled={busy} onChange={event => setReason(event.target.value)} rows={3} maxLength={2000} placeholder="说明依据及仍需面试核实的事项" />
    <Checkbox checked={acknowledged} disabled={busy} onChange={event => setAcknowledged(event.target.checked)}>已核读当前版本及引用证据，保留未知与未核实事项</Checkbox>
    <Button loading={busy} disabled={!reason.trim() || !acknowledged || !artifact.evidence_refs.length} onClick={() => void save()}>保存人工复核新版本</Button>
  </section>
}
