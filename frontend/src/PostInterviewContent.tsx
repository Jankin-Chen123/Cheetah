import { Alert, Table, Typography } from 'antd'
import type { Artifact } from './api/outreach'

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> =>
    typeof item === 'object' && item !== null && !Array.isArray(item)) : []
}
function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}
const dimensionLabels: Record<string, string> = { responsibility: '个人职责', results: '业绩结果', intention: '求职意愿', other: '其他' }

export default function PostInterviewContent({ artifact }: { artifact: Artifact }) {
  const { content, type } = artifact
  if (type !== 'D08' && type !== 'D09') return null
  const gaps = strings(content.gaps)
  const conflicts = strings(content.conflicts)
  return <section aria-label={type === 'D08' ? '面试信息提取' : '内部面试评估'}>
    {type === 'D08' && <>
      <p>提取覆盖：{content.coverage === 'full' ? '已提取职责和结果事实' : '部分覆盖'}。以下为候选人自述，原话存在不代表已独立核实。</p>
      {records(content.facts).length === 0 && <Alert type="info" message="尚未提取到有效事实" />}
      {records(content.facts).map((fact, index) => <div key={index} style={{ marginBottom: 16 }}>
        <Typography.Text strong>{dimensionLabels[String(fact.kind)] ?? String(fact.kind)}：{String(fact.statement ?? '')}</Typography.Text>
        <blockquote style={{ whiteSpace: 'pre-wrap' }}>{String(fact.quote ?? '')}</blockquote>
        <Typography.Text type="secondary">回答引用：{String(fact.answer_id ?? '')}</Typography.Text>
      </div>)}
    </>}
    {type === 'D09' && <>
      <Alert type="info" message={`内部结论：${({ recommended: '达到当前规则推荐门槛', rejected: '未达到当前规则推荐门槛', insufficient: '信息不足' } as Record<string, string>)[String(content.conclusion)] ?? '待评估'}`} />
      <p>总分：{typeof content.score === 'number' ? `${content.score.toFixed(2)} / ${content.score_scale === '1-10' ? '10' : '5'}` : '未形成完整总分'}；量表：{content.score_scale === '1-10' ? 'A02 十分制' : '原五分制'}{content.demo_rules === true ? '（演示规则）' : ''}。缺证据维度保持未评估，不按零分处理。</p>
      <Table size="small" pagination={false} rowKey="dimension_id" scroll={{ x: 650 }} dataSource={records(content.dimensions)} columns={[
        { title: '维度', render: (_, row) => String(row.label ?? dimensionLabels[String(row.dimension_id)] ?? row.dimension_id) },
        { title: '指标及解析', dataIndex: 'indicators', render: value => String(value ?? '见绑定模板') },
        { title: '权重', dataIndex: 'weight_percent', render: value => typeof value === 'number' ? `${value}%` : '见绑定模板' },
        { title: '评分标准', dataIndex: 'scoring_anchors', render: value => <details><summary>行为锚点</summary>{records([value]).flatMap(anchors => Object.entries(anchors).map(([band, text]) => <p key={band}>{band}：{String(text)}</p>))}</details> },
        { title: '得分', dataIndex: 'score', render: value => typeof value === 'number' ? value : '未评估' },
        { title: '折算分', dataIndex: 'weighted_score', render: value => typeof value === 'number' ? value.toFixed(2) : '未评估' },
        { title: '依据', dataIndex: 'reason', render: value => String(value ?? '') },
        { title: '回答引用', dataIndex: 'evidence_ids', render: value => strings(value).join('、') || '无' },
      ]} />
      <p>百分制总分：{typeof content.total_score === 'number' ? `${content.total_score.toFixed(2)} / 100` : '未形成'}；已评估权重覆盖：{typeof content.scored_weight_percent === 'number' ? `${content.scored_weight_percent}%` : '未记录'}。未覆盖权重不重新分配。</p>
    </>}
    {gaps.length > 0 && <Alert style={{ marginTop: 12 }} type="warning" message="缺失与待核实" description={<ul>{gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>} />}
    {conflicts.length > 0 && <Alert style={{ marginTop: 12 }} type="warning" message="材料冲突" description={<ul>{conflicts.map((conflict, index) => <li key={index}>{conflict}</li>)}</ul>} />}
  </section>
}
