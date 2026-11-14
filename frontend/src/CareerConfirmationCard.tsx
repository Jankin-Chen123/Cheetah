import { useState } from 'react'
import { Alert, Button, Card, Input, Select, Space } from 'antd'
import { confirmCareerField, revokeCareerField, OutreachError, type CallCase, type CareerConfirmation, type CareerRevocation } from './api/outreach'

const profileFields = [
  ['current_city', '当前城市'], ['current_employer', '当前公司'],
  ['current_role', '当前岗位'], ['current_employment_status', '在职状态'],
  ['professional_direction', '专业方向'],
]
const employmentFields = [
  ['period', '任职时间'], ['company', '公司'], ['position', '职位'],
  ['department', '部门'], ['reports_to', '汇报对象'], ['team_scope', '团队范围'],
  ['reason_for_leaving', '离职原因'],
  ['company_business', '企业业务或行业'],
]
export default function CareerConfirmationCard({ current, onSaved }: { current: CallCase; onSaved: () => Promise<void> }) {
  const [field, setField] = useState('profile.current_city')
  const [answerId, setAnswerId] = useState('')
  const [quote, setQuote] = useState('')
  const [value, setValue] = useState('')
  const [reason, setReason] = useState('')
  const [conflict, setConflict] = useState<{ index: number; source: string }>()
  const [revokeId, setRevokeId] = useState<string>()
  const [revokeReason, setRevokeReason] = useState('')
  const [needsRefresh, setNeedsRefresh] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const minutes = current.artifacts?.find(a => a.type === 'D08' && a.valid)
  const confirmations = (current.session.career_confirmations ?? []) as CareerConfirmation[]
  const revoked = (current.session.career_confirmation_revocations ?? []) as CareerRevocation[]
  const conflicts = (minutes?.content.conflicts ?? []) as string[]
  const answers = (current.session.answers ?? []) as { id: string; text: string; version?: number }[]
  const upstream = (current.session.career_confirmed_upstream ?? current.session.upstream_content) as { D03?: { employment?: unknown[]; education?: unknown[]; projects?: unknown[]; qualifications?: unknown[]; additional_projects_or_results?: unknown[]; career_preferences?: unknown[]; professional_skills?: unknown[] } } | undefined
  const original = current.session.upstream_content as { D03?: unknown } | undefined
  const activeIds = (current.session.active_career_confirmation_ids ?? []) as string[]
  const fields = [
    ...Array.from({ length: (upstream?.D03?.projects?.length ?? 0) + 1 }, (_, index) => index).flatMap(index => [
      ['name', '项目名称'], ['background', '背景与场景'], ['role', '个人角色'], ['actions', '实际行动'], ['results', '成果与原始口径'],
    ].map(([key, label]) => ({ value: `projects.${index}.${key}`, label: `项目 ${index + 1} · ${label}` }))),
    ...profileFields.map(([key, label]) => ({ value: `profile.${key}`, label })),
    ...[['target_role', '意向岗位'], ['target_location', '意向地点'], ['salary_expectation', '薪酬要求与口径'], ['availability', '可到岗时间'], ['other_conditions', '其他必要条件']].map(([key, label]) => ({ value: `job_preferences.${key}`, label })),

    ...Array.from({ length: (upstream?.D03?.employment?.length ?? 0) + 1 }, (_, index) => index).flatMap(index => employmentFields.map(([key, label]) => ({ value: `employment.${index}.${key}`, label: `任职 ${index + 1} · ${label}` }))),
    ...(upstream?.D03?.employment ?? []).flatMap((record, index) => {
      const row = record as { responsibilities?: unknown[]; achievements?: unknown[] }
      return (['responsibilities', 'achievements'] as const).flatMap(key => Array.from({ length: (row[key]?.length ?? 0) + 1 }, (_, item) => ({ value: `employment.${index}.${key}.${item}`, label: `任职 ${index + 1} · ${key === 'responsibilities' ? '职责' : '业绩'} ${item + 1}` })))
    }),
    ...Array.from({ length: (upstream?.D03?.education?.length ?? 0) + 1 }, (_, index) => index).flatMap(index => [
      ['period', '时间'], ['institution', '学校或机构'], ['major_or_course', '专业或课程'], ['credential', '学历或证书'], ['notes', '说明'],
    ].map(([key, label]) => ({ value: `education.${index}.${key}`, label: `教育 ${index + 1} · ${label}` }))),
    ...(['qualifications', 'additional_projects_or_results', 'career_preferences', 'professional_skills'] as const).flatMap(key => {
      const labels = { professional_skills: '专业技能', qualifications: '专业资格', additional_projects_or_results: '项目与成果', career_preferences: '求职条件' }
      const rows = upstream?.D03?.[key] ?? []
      return Array.from({ length: rows.length + 1 }, (_, index) => ({ value: `${key}.${index}`, label: `${labels[key]} · ${index < rows.length ? index + 1 : '新增'}` }))
    }),
  ]
  const source = minutes ? `${minutes.id}:${minutes.version}` : ''
  const selectedAnswer = answers.find(a => a.id === answerId)
  const staleConflict = Boolean(conflict && conflict.source !== source)
  const validQuote = Boolean(quote.trim() && selectedAnswer?.text.includes(quote) && value.trim() && quote.includes(value))
  const fieldIsAvailable = fields.some(option => option.value === field)

  function fieldValue(root: unknown) {
    const result = field.split('.').reduce<unknown>((node, part) =>
      node && typeof node === 'object' ? Reflect.get(node, part) : undefined, root)
    if (result == null || result === '') return '未记录'
    return typeof result === 'string' ? result : JSON.stringify(result)
  }

  async function refreshCase(success: string) {
    try {
      await onSaved()
      setNeedsRefresh(false)
      setMessage(success)
    } catch {
      setNeedsRefresh(true)
      setMessage(`${success} 当前记录未能刷新，请重新读取后再操作。`)
    }
  }

  async function mutate(action: () => Promise<unknown>, success: string, afterSave: () => void) {
    setBusy(true); setMessage('')
    try {
      await action()
      afterSave()
      await refreshCase(success)
    } catch (error) {
      if (error instanceof OutreachError && ['VERSION_CONFLICT', 'CURRENT_MINUTES_REQUIRED', 'CAREER_SOURCE_QUOTE_INVALID', 'CAREER_FIELD_INVALID', 'CAREER_CONFLICT_REFERENCE_INVALID'].includes(error.code)) {
        await refreshCase(`无法保存（${error.code}）。已保留输入，请重新核对当前字段、原话与 D08 版本。`)
      } else setMessage(String(error))
    } finally { setBusy(false) }
  }

  async function save() {
    if (!minutes || !fieldIsAvailable || !validQuote || staleConflict) return
    await mutate(() => confirmCareerField(current.id, {
      expected_revision: current.revision, minutes_id: minutes.id, minutes_version: minutes.version,
      field_path: field, value, answer_id: answerId, quote, reason: reason.trim(), conflict_index: conflict?.index ?? null,
    }), '确认已保存。旧推荐及批准已失效；请在面试与报告进度中生成新版推荐，再单独审核。', () => {
      setQuote(''); setValue(''); setReason(''); setConflict(undefined)
    })
  }

  async function revoke(id: string) {
    await mutate(() => revokeCareerField(current.id, id, { expected_revision: current.revision, reason: revokeReason.trim() }),
      '确认已撤销。旧推荐及批准已失效；请在面试与报告进度中生成新版推荐。', () => {
        setRevokeId(undefined); setRevokeReason('')
      })
  }
  return <Card title="职业字段确认">
    <p>核对履历与当前面试原话后逐项确认。确认值须逐字来自所选回答，不代表已独立核实；原始履历与历史报告保留。未解决冲突仍阻止报告批准。</p>
    {!minutes && <p>请先完成当前有效 D08。</p>}
    <details><summary>原始履历对照</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(original?.D03 ?? {}, null, 2)}</pre></details>
    <details><summary>当前确认后的职业资料</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(upstream?.D03 ?? {}, null, 2)}</pre></details>
    <details><summary>字段确认历史</summary>
      {confirmations.map((item, index) => <div key={item.id ?? index}>
        <p>{item.field_path}：{item.value} · D08 v{item.minutes_ref.version} · {revoked.some(r => r.confirmation_id === item.id) ? '已撤销' : activeIds.includes(item.id) ? '当前采用' : confirmations.some((later, position) => position > index && later.field_path === item.field_path) ? '已被后续确认替代' : item.minutes_ref.id !== minutes?.id || item.minutes_ref.version !== minutes?.version ? '来源已过期' : '当前未采用'}</p>
        <p>回答 {item.answer_id} v{item.answer_version} · 原始履历 v{item.resume_ref?.version ?? '未知'}</p>
        <p>原话：{item.quote}；理由：{item.reason}</p>
        {item.conflict_text && <p>关联冲突：{item.conflict_text}</p>}
        {revoked.find(r => r.confirmation_id === item.id)?.reason && <p>撤销理由：{revoked.find(r => r.confirmation_id === item.id)?.reason}</p>}
        {!revoked.some(r => r.confirmation_id === item.id) && (revokeId === item.id ? <Space orientation="vertical">
          <Input.TextArea aria-label="撤销理由" value={revokeReason} maxLength={2000} onChange={e => setRevokeReason(e.target.value)} />
          <Space><Button danger disabled={busy || needsRefresh || !revokeReason.trim()} onClick={() => void revoke(item.id)}>确认撤销</Button>
            <Button disabled={busy} onClick={() => { setRevokeId(undefined); setRevokeReason('') }}>取消</Button></Space>
        </Space> : <Button disabled={busy || revokeId !== undefined} onClick={() => setRevokeId(item.id)}>撤销此确认</Button>)}
      </div>)}
    </details>
    <Space orientation="vertical" style={{ width: '100%' }}>
      <Select aria-label="职业字段" value={field} onChange={next => { setField(next); setConflict(undefined) }} options={fields} style={{ minWidth: 240 }} />
      <p>原始值：{fieldValue(original?.D03)}<br />当前采用：{fieldValue(upstream?.D03)}</p>
      {staleConflict && <Alert type="warning" message="D08 已换版，请重新选择关联冲突。" action={<Button onClick={() => setConflict(undefined)}>清除关联</Button>} />}
      <Select allowClear aria-label="本次处理的冲突" placeholder="仅选择本字段原话确实解决的冲突；无关冲突仍保留" value={staleConflict ? undefined : conflict?.index} onChange={index => setConflict(index === undefined ? undefined : { index, source })} options={conflicts.map((text, index) => ({ value: index, label: text }))} style={{ width: '100%' }} />
      <Select aria-label="来源回答" value={answerId || undefined} placeholder="选择实际来源回答" onChange={id => { setAnswerId(id); setConflict(undefined) }} options={answers.map(a => ({ value: a.id, label: a.text.slice(0, 70) }))} style={{ width: '100%' }} />
      <p style={{ whiteSpace: 'pre-wrap' }}>{answers.find(a => a.id === answerId)?.text}</p>
      <Input.TextArea aria-label="字段来源原话" placeholder="逐字摘录来源原话" value={quote} onChange={e => setQuote(e.target.value)} maxLength={4000} />
      <Input aria-label="确认字段值" placeholder="确认值（必须包含在原话中）" value={value} onChange={e => setValue(e.target.value)} maxLength={500} />
      <Input.TextArea aria-label="字段确认理由" placeholder="确认理由与适用边界" value={reason} onChange={e => setReason(e.target.value)} maxLength={2000} />
      <Button loading={busy} disabled={busy || needsRefresh || !minutes || !fieldIsAvailable || !validQuote || staleConflict || !reason.trim()} onClick={() => void save()}>保存字段确认并使旧推荐失效</Button>
      {quote.trim() && !selectedAnswer?.text.includes(quote) && <p>摘录必须逐字出现在所选回答中。</p>}
      {needsRefresh && <Button disabled={busy} onClick={() => void refreshCase('已重新读取，请核对当前资料。')}>重新读取案例</Button>}
      {message && <p role="status">{message}</p>}
    </Space>
  </Card>
}
