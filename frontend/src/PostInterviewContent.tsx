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
  if (type === 'D10') {
    const summary = records([content.summary])[0]
    const profile = records([content.client_profile])[0]
    return <section aria-label="客户推荐报告">
      <Alert type="info" message="具体版本推荐草案；批准与导出仍以当前有效版本及客户分享许可为准。" />
      {summary && <><Typography.Title level={5}>核心推荐摘要</Typography.Title><p>{String(summary.text ?? '')}</p></>}
      <Table size="small" pagination={false} rowKey={(_, index) => String(index)} scroll={{ x: 600 }}
        dataSource={records(content.match_highlights)} columns={[
          { title: '岗位关注点', dataIndex: 'dimension_id', render: value => String(value ?? '岗位相关经历') },
          { title: '候选人事实与证据', dataIndex: 'text' },
          { title: '岗位关联与边界', dataIndex: 'job_relevance', render: value => value || '以本行具体经历为限，其他能力待核实' },
        ]} />
      {profile && strings(profile.unresolved_conflicts).length > 0 && <Alert type="warning" message="存在未解决冲突，不能批准或导出" description={<ul>{strings(profile.unresolved_conflicts).map((text, index) => <li key={index}>{text}</li>)}</ul>} />}
    </section>
  }
  if (type !== 'D07' && type !== 'D08' && type !== 'D09') return null
  const gaps = strings(content.gaps)
  const conflicts = strings(content.conflicts)
  const limitations = strings(content.extraction_limitations)
  return <section aria-label={type === 'D07' ? '面试提纲' : type === 'D08' ? '面试信息提取' : '内部面试评估'}>
    {type === 'D07' && <>
      <Alert type="info" message="面试准备稿；不代表候选人已同意，也不代表问题已经问过。" />
      <p>准备状态：{String(content.readiness ?? '历史提纲未记录就绪状态')}</p>
      {strings(content.readiness_reasons).map((reason, index) => <p key={index}>{reason}</p>)}
      {records(content.dimension_coverage).length > 0 && <Table size="small" pagination={false} rowKey="dimension_id" scroll={{ x: 600 }} dataSource={records(content.dimension_coverage)} columns={[
        { title: '岗位能力', dataIndex: 'dimension_name' },
        { title: '权重', dataIndex: 'weight_percent' },
        { title: '指标', dataIndex: 'indicator' },
        { title: '计划题号', render: (_, row) => strings(row.question_ids).join('、') },
        { title: '分钟', dataIndex: 'planned_minutes' },
        { title: '覆盖状态', render: (_, row) => row.coverage_status === 'PLANNED' ? '已安排' : '缺失' },
      ]} />}
      {typeof content.planned_total_minutes === 'number' && <p>建议总时长：{content.planned_total_minutes} 分钟</p>}
      {records(content.questions).map((question, index) => <div key={index} style={{ marginTop: 16 }}>
        <Typography.Text strong>{String(question.id ?? '')}：{String(question.question ?? '')}</Typography.Text>
        <p>考察维度：{String(question.dimension_id ?? '未记录')}；计划时长：{Number(question.planned_minutes) > 0 ? `${String(question.planned_minutes)} 分钟` : '未记录'}</p>
        <p>目标证据：{String(question.evidence_target ?? '未记录')}</p>
        {records(question.conditional_followups).map((followup, followupIndex) => <p key={followupIndex}>当{String(followup.trigger ?? '')}时：{String(followup.question ?? '')}</p>)}
        {typeof question.stop_rule === 'string' && question.stop_rule && <p>停止追问条件：{question.stop_rule}</p>}
      </div>)}
      {strings(content.unknowns).length > 0 && <Alert type="warning" message="提纲待核实事项" description={<ul>{strings(content.unknowns).map((note, index) => <li key={index}>{note}</li>)}</ul>} />}
    </>}
    {type === 'D08' && <>
      {records(content.question_execution_coverage).length > 0 && <Table size="small" pagination={false}
        rowKey="question_id" scroll={{ x: 600 }} dataSource={records(content.question_execution_coverage)} columns={[
          { title: '计划题号', dataIndex: 'question_id' },
          { title: '维度', dataIndex: 'dimension_id' },
          { title: '实际记录', render: (_, row) => row.execution_status === 'ANSWER_RECORDED' ? '已保存回答' : '未记录回答，原因未知' },
          { title: '主问题回答', render: (_, row) => strings(row.answer_ids).join('、') || '无' },
          { title: '追问回答', render: (_, row) => strings(row.followup_answer_ids).join('、') || '无' },
          { title: '原话轮次', render: (_, row) => strings(row.turn_ids).join('、') || '未记录' },
        ]} />}
      <Alert type={content.extraction_status === 'READY_FOR_A08' ? 'info' : 'warning'}
        message={content.extraction_status === 'READY_FOR_A08' ? '完整会话已交接评估；证据充分性仍须逐维核对。' : '部分会话或历史材料：仅供受限复核，不能据此宣称完整面试已完成。'} />
      <p>提取覆盖：{content.coverage === 'full' ? '已提取职责和结果事实' : '部分覆盖'}。以下为候选人自述，原话存在不代表已独立核实。</p>
      {records(content.facts).length === 0 && <Alert type="info" message="尚未提取到有效事实" />}
      {(records(content.evidence_items).length ? records(content.evidence_items) : records(content.facts)).map((fact, index) => <div key={index} style={{ marginBottom: 16 }}>
        <Typography.Text strong>{dimensionLabels[String(fact.kind)] ?? String(fact.kind)}：{String(fact.statement ?? '')}</Typography.Text>
        <blockquote style={{ whiteSpace: 'pre-wrap' }}>{String(fact.quote ?? '')}</blockquote>
        <Typography.Text type="secondary">回答引用：{String(fact.answer_id ?? '')}</Typography.Text>
        {typeof fact.evidence_id === 'string' && fact.evidence_id && <p>事实编号：{fact.evidence_id}；原话轮次：{strings(fact.turn_ids).join('、') || '未提供会话轮次'}；来源：{fact.source_type === 'CANDIDATE_ORAL' ? '候选人口述记录' : '已存回答记录'}</p>}
        <p>证据类型：{({ PAST_BEHAVIOR: '过去实际行为', SITUATIONAL: '假设情景', FACT_ONLY: '职业事实', GENERAL_CLAIM: '一般声称' } as Record<string, string>)[String(fact.evidence_kind)] ?? '未标注'}；方向：{({ SUPPORTING: '支持性原话', LIMITING: '本人明确的边界或局限', NEUTRAL: '中性事实' } as Record<string, string>)[String(fact.evidence_direction)] ?? '未标注'}。类别不代表分数。</p>
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
      ]} />
      {records(content.dimensions).map((dimension, index) => <div key={index} style={{ marginTop: 12 }}>
        <Typography.Text strong>{String(dimension.label ?? dimension.dimension_id)} · 评分依据</Typography.Text>
        <p>{String(dimension.reason ?? '未记录')}</p>
        <p>回答引用：{strings(dimension.evidence_ids).join('、') || '无'}</p>
        {dimension.anchor_basis_status === 'RECORDED' && <>
          <p>命中档位：{String(dimension.matched_anchor_band)}；岗位锚点：{String(dimension.matched_anchor_text ?? '')}</p>
          <p>定分依据：{String(dimension.anchor_rationale ?? '')}</p>
          <p>事实引用：{strings(dimension.fact_evidence_ids).join('、') || '无'}</p>
        </>}
        {dimension.anchor_basis_status === 'LEGACY_NOT_RECORDED' && <p>历史评分未记录结构化锚点依据，需要复核。</p>}
      </div>)}
      <p>百分制总分：{typeof content.total_score === 'number' ? `${content.total_score.toFixed(2)} / 100` : '未形成'}；已评估权重覆盖：{typeof content.scored_weight_percent === 'number' ? `${content.scored_weight_percent}%` : '未记录'}。未覆盖权重不重新分配。</p>
    </>}
    {gaps.length > 0 && <Alert style={{ marginTop: 12 }} type="warning" message="缺失与待核实" description={<ul>{gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>} />}
    {conflicts.length > 0 && <Alert style={{ marginTop: 12 }} type="warning" message="材料冲突" description={<ul>{conflicts.map((conflict, index) => <li key={index}>{conflict}</li>)}</ul>} />}
    {records(content.indicator_evidence).length > 0 && <>
      <p>指标取证预检：充分性不代表能力分数，仍需按岗位标准复核。</p>
      <Table size="small" pagination={false} rowKey={row => `${String(row.dimension_id)}:${String(row.indicator_ref)}`} scroll={{ x: 1150 }} dataSource={records(content.indicator_evidence)} columns={[
        { title: '维度', width: 120, dataIndex: 'dimension_id', render: value => String(value) },
        { title: '指标来源', width: 200, dataIndex: 'indicator_ref', render: value => String(value) },
        { title: '取证情况', width: 100, dataIndex: 'evidence_sufficiency', render: value => ({ SUFFICIENT: '充分', PARTIAL: '部分充分', INSUFFICIENT: '不足' } as Record<string, string>)[String(value)] ?? '未标注' },
        { title: '事实理由', width: 300, dataIndex: 'sufficiency_reason', render: value => String(value ?? '') },
        { title: '回答引用', width: 150, dataIndex: 'answer_ids', render: value => strings(value).join('、') || '无' },
        { title: '缺口', width: 280, dataIndex: 'gaps', render: value => strings(value).join('；') },
      ]} />
    </>}
    {records(content.dimension_coverage).map((dimension, index) => <div key={index} style={{ marginTop: 16 }}>
      <Typography.Text strong>{String(dimension.dimension_name ?? dimension.d02_dimension_id)} · 维度取证汇总</Typography.Text>
      <p>问题覆盖：{({ COVERED: '有相关证据', PARTIAL: '部分记录', NO_EVIDENCE: '已问但缺证据', NOT_ASKED: '未问' } as Record<string, string>)[String(dimension.coverage_status)] ?? '未记录'}；证据预检：{({ SUFFICIENT: '充分', PARTIAL: '部分充分', INSUFFICIENT: '不足' } as Record<string, string>)[String(dimension.dimension_evidence_sufficiency)] ?? '未记录'}。预检不是分数。</p>
      <p>{String(dimension.dimension_sufficiency_reason ?? '')}</p>
      {records(dimension.indicator_evidence).map((indicator, rowIndex) => <div key={rowIndex}>
        <p>指标原文：{String(indicator.indicator_text ?? '')}</p>
        <p>实际题号：{strings(indicator.question_ids).join('、') || '无'}；支持事实：{strings(indicator.supporting_evidence_ids).join('、') || '无'}；局限事实：{strings(indicator.limiting_evidence_ids).join('、') || '无'}；情景事实：{strings(indicator.situational_evidence_ids).join('、') || '无'}；中性事实：{strings(indicator.neutral_evidence_ids).join('、') || '无'}</p>
        {indicator.fact_links_complete === false && <p>旧资料缺少逐事实指标引用，需要复核。</p>}
      </div>)}
    </div>)}
    {limitations.length > 0 && <Alert style={{ marginTop: 12 }} type="warning" message="提取与交接限制" description={<ul>{limitations.map((note, index) => <li key={index}>{note}</li>)}</ul>} />}
  </section>
}
