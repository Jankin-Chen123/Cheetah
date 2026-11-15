import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, InputNumber, Select, Space, Tag } from 'antd'
import type { components } from '../api/generated'
import { intakeRequest, type IntakeSession } from '../api/jobIntake'
import type { Job } from '../domain/workspace'
import { areJobDocumentsConfirmed, currentDocument } from '../domain/jobDocuments'

type Draft = components['schemas']['RuleDraft']
type RemoteJob = components['schemas']['Job']
type Published = components['schemas']['RulePack']

export default function RulePublication({ job, session }: { job: Job; session: IntakeSession }) {
  const id = job.generation?.remoteJobId
  const [data, setData] = useState<{ draft: Draft; job: RemoteJob }>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [recommendation, setRecommendation] = useState('')
  const [threshold, setThreshold] = useState<number | null>(null)
  const [required, setRequired] = useState<string[]>([])
  const [research, setResearch] = useState('unavailable')
  const [testRule, setTestRule] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const pending = useRef<{ key: string; body: unknown } | null>(null)
  const load = useCallback(async (signal?: AbortSignal) => {
    if (!id) return
    const [draft, remote] = await Promise.all([
      intakeRequest<Draft>(`/jobs/${id}/rules/draft`, {}, signal),
      intakeRequest<RemoteJob>(`/jobs/${id}`, {}, signal),
    ])
    if (!signal?.aborted) setData({ draft, job: remote })
  }, [id])
  useEffect(() => {
    const controller = new AbortController()
    const refresh = () => { if (!document.hidden) void load(controller.signal).catch(failure => { if (!controller.signal.aborted) setError((failure as Error).message) }) }
    refresh()
    const timer = setInterval(refresh, 5000)
    return () => { controller.abort(); clearInterval(timer) }
  }, [load])
  if (!id || !data) return error ? <Alert type="error" title={error} /> : null
  const d01 = currentDocument(job, 'D01'), d02 = currentDocument(job, 'D02')
  const same = d01?.remoteRef?.artifact_id === data.job.d01_ref?.artifact_id && d01?.remoteRef?.version === data.job.d01_ref?.version && d02?.remoteRef?.artifact_id === data.job.d02_ref?.artifact_id && d02?.remoteRef?.version === data.job.d02_ref?.version
  const dimensions = data.draft.content.interview_dimensions ?? []
  const ready = areJobDocumentsConfirmed(job) && same && !!data.draft.content.screening_rubric && !!recommendation.trim() && threshold !== null && required.length > 0 && confirmed
  async function publish() {
    if (!data || !id || busy) return
    setBusy(true); setError('')
    const headers = { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token }
    try {
      const current = await intakeRequest<RemoteJob>(`/jobs/${id}`)
      if (current.published_rule_pack_ref) { await load(); return }
      if (!pending.current) {
        const saved = await intakeRequest<Draft>(`/jobs/${id}/rules/draft`, {
          method: 'PATCH', headers,
          body: JSON.stringify({ expected_draft_revision: data.draft.draft_revision, content: {
            ...data.draft.content, recommendation_text: recommendation.trim(),
            recommendation_policy: { decision_method: 'weighted_score', threshold, required_dimension_ids: required, manual_review_conditions: ['缺失证据或存在冲突时人工复核'] },
            research_config_ref: { config_id: research, version: 1 },
          } }),
        })
        pending.current = { key: crypto.randomUUID(), body: {
          expected_draft_revision: saved.draft_revision, d01_ref: d01!.remoteRef, d02_ref: d02!.remoteRef,
          is_test_rule: testRule, confirmation_note: '已在岗位页面逐份确认画像、面试表与独立初筛建议，并确认推荐标准和门槛。',
        } }
      }
      await intakeRequest<Published>(`/jobs/${id}/rules/publish`, {
        method: 'POST', headers: { ...headers, 'Idempotency-Key': pending.current.key }, body: JSON.stringify(pending.current.body),
      })
      pending.current = null
      await load()
    } catch (failure) { setError((failure as Error).message); await load().catch(() => {}) }
    finally { setBusy(false) }
  }
  const edit = () => { setConfirmed(false); pending.current = null }
  return <section className="panel stack" aria-label="发布岗位标准">
    <h2>发布岗位标准</h2>
    {data.job.published_rule_pack_ref ? <><Tag color="green">岗位标准已正式发布</Tag><p>人才将按职能方向关联此岗位，初筛绑定已发布的具体标准。</p></> : <>
      {!areJobDocumentsConfirmed(job) && <Alert type="info" title="请先分别确认岗位画像和岗位面试评估表，再发布标准。" />}
      {areJobDocumentsConfirmed(job) && !same && <Alert type="warning" title="网页修改尚未写回服务端，或服务端内容已变化。不能把不同版本直接发布，请先核对当前内容。" />}
      {!data.draft.content.screening_rubric && <Alert type="warning" title="初筛标准建议尚未就绪，请核对后台任务或补充岗位材料。" />}
      {data.draft.content.screening_rubric && <><h3>独立的简历初筛标准</h3>{data.draft.content.screening_rubric.dimensions.map(dimension => <p key={dimension.id}>{{ responsibilities: '核心职责适配', skills: '技能匹配', education_experience: '学历与经验', recent_relevance: '近期经历', industry_context: '业务场景', projects_preferences: '项目与优先条件', salary: '薪资' }[dimension.id]} · {dimension.enabled ? `${dimension.weight}%` : '不适用'} · {dimension.requirement} · {(dimension.source_quotes ?? []).join('；')}</p>)}</>}
      <label htmlFor="recommendation-standard">推荐标准</label><Input.TextArea id="recommendation-standard" disabled={busy} value={recommendation} maxLength={5000} rows={3} onChange={event => { setRecommendation(event.target.value); edit() }} />
      <label htmlFor="recommendation-threshold">面试推荐门槛（1—10 分）</label><InputNumber id="recommendation-threshold" disabled={busy} min={1} max={10} value={threshold} onChange={value => { setThreshold(value); edit() }} />
      <label>推荐前必须取得证据的能力维度</label><Checkbox.Group disabled={busy} value={required} options={dimensions.map(dimension => ({ value: dimension.id, label: dimension.label }))} onChange={values => { setRequired(values); edit() }} />
      <label htmlFor="research-policy">公开资料研究</label><Select id="research-policy" disabled={busy} value={research} onChange={value => { setResearch(value); edit() }} options={[{ value: 'unavailable', label: '暂不联网研究，保留研究缺口' }, { value: 'pi-research', label: '启用已配置的公开资料研究' }]} />
      {session.capabilities.mock_execution_allowed && <Checkbox checked={testRule} disabled={busy} onChange={event => { setTestRule(event.target.checked); edit() }}>仅用于隔离内测，后续始终保留测试来源</Checkbox>}
      <Checkbox checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)}>我已复核两阶段标准、权重、推荐依据与门槛，确认发布此版本</Checkbox>
      <Space><Button type="primary" disabled={!ready || busy} loading={busy} onClick={() => void publish()}>确认并发布岗位标准</Button><Button disabled={busy} onClick={() => void load().catch(failure => setError((failure as Error).message))}>重新读取状态</Button></Space>
    </>}
    {error && <Alert type="error" showIcon title={error} />}
  </section>
}
