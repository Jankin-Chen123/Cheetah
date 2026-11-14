import { Alert, Descriptions, Empty, Table } from 'antd'
import type { components } from '../api/generated'

const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const text = (value: unknown) => typeof value === 'string' || typeof value === 'number' ? String(value) : '待确认'
const factText = (value: unknown) => { const fact = object(value); return fact.status === 'stated' ? text(fact.value) : typeof fact.note === 'string' && fact.note.trim() ? `待确认：${fact.note}` : '待确认' }

export default function IntakeResult({ artifact }: { artifact: components['schemas']['Artifact'] }) {
  const content = object(artifact.structured_content)
  if (['D07', 'D08', 'D09', 'D10'].includes(artifact.type) && artifact.content_markdown?.trim()) return <div className="document-content">{artifact.content_markdown}</div>
  if (artifact.type === 'D10') return <div className="stack">
    <p>{text(content.candidate_summary)}</p>
    {list(content.match_highlights).map((item, index) => <p key={`match-${index}`}>{text(object(item).text)}</p>)}
    {list(content.contribution_claims).map((item, index) => <p key={`contribution-${index}`}>{text(object(item).text)}</p>)}
    <p>求职意向：{text(content.job_intention)}</p>
    {list(content.unknowns).map((item, index) => <p key={`unknown-${index}`}>{text(item)}</p>)}
  </div>
  if (artifact.type === 'D03' && content.resume_form) {
    const sections = object(object(content.resume_form).sections)
    const form = object(content.resume_form)
    return <div className="stack">{form.parse_status !== 'completed' && <Alert type="warning" showIcon title="简历仅部分识别，需补充或核实材料" description={list(form.limitations).map(text).join('；')} />}{Object.entries(sections).map(([section, records]) => <section key={section}>
      <h4>{section}</h4>{list(records).map((record, index) => <Descriptions key={index} column={1} size="small" bordered items={Object.entries(object(object(record).fields)).map(([key, value]) => ({ key, label: key, children: factText(value) }))} />)}
    </section>)}</div>
  }
  if (artifact.type === 'D04' && content.report) return <div className="document-content">{artifact.content_markdown}</div>
  if (artifact.type === 'D04') return <div className="stack">
    {list(content.findings).length ? list(content.findings).map((item, i) => <p key={i}>{text(object(item).text)}</p>) : <Empty description="暂无研究发现" />}
    {list(content.gaps).map((item, i) => <p className="unknown-text" key={i}>{text(item)}</p>)}
  </div>
  if (artifact.type === 'D05') {
    const portrait = object(content.portrait)
    return Object.keys(portrait).length ? <Descriptions column={1} items={Object.entries(portrait).map(([key, value]) => ({ key, label: key, children: text(value) }))} /> : <div><p>{text(content.experience_context)}</p>{list(content.match_signals).map((item, i) => <p key={i}>{text(object(item).text)}</p>)}</div>
  }
  if (artifact.type === 'D06') {
    const assessment = object(content.assessment)
    const scores = list(assessment.scores)
    const summary = object(content.score_summary)
    return <div className="stack">
      {!!scores.length && <p>总分：{summary.total == null ? '尚未完整评估' : text(summary.total)}</p>}
      <Table<Record<string, unknown>> pagination={false} rowKey="id" size="small" dataSource={(scores.length ? scores : list(content.conditions)).map((item, i) => ({ ...object(item), id: String(i + 1) }))} columns={[
        { title: scores.length ? '维度' : '条件', dataIndex: 'id' },
        { title: scores.length ? '评分' : '核验结果', render: (_, item) => scores.length ? item.score == null ? '未评估' : text(item.score) : ({ satisfied: '满足', not_satisfied: '不满足', unknown: '待确认' } as Record<string, string>)[String(item.result)] ?? '待确认' },
        { title: '依据与说明', render: (_, item) => text(item.reason) },
      ]} />
      {list(assessment.reasons).map((item, i) => <p key={i}>{text(item)}</p>)}
    </div>
  }
  return <Empty description="暂无可展示的内容" />
}
