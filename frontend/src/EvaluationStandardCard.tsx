import { useState } from 'react'
import { Alert, Button, Card, Checkbox, Form, Input, InputNumber, Space, Typography } from 'antd'
import { api, type CallCase } from './api/outreach'

const bands = ['1-2', '3-4', '5-6', '7-8', '9-10']
interface DimensionDraft {
  id: string; label: string; indicators: string; weight_percent: number | null
  sources: string; anchors: Record<string, string>
}
export default function EvaluationStandardCard({ current, refresh }: { current: CallCase; refresh: () => Promise<void> }) {
  const [dimensions, setDimensions] = useState<DimensionDraft[]>([])
  const [version, setVersion] = useState<number | null>(null)
  const [threshold, setThreshold] = useState<number | null>(null)
  const [reportVersion, setReportVersion] = useState<number | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const weight = dimensions.reduce((sum, row) => sum + (row.weight_percent ?? 0), 0)
  const ready = confirmed && version !== null && threshold !== null && reportVersion !== null && dimensions.length > 0 && Math.abs(weight - 100) < 0.000001 && dimensions.every(row => row.label.trim() && row.indicators.trim() && row.sources.trim() && row.weight_percent && bands.every(band => row.anchors[band]?.trim()))
  function update(index: number, patch: Partial<DimensionDraft>) {
    setConfirmed(false)
    setDimensions(rows => rows.map((row, i) => i === index ? { ...row, ...patch } : row))
  }
  return <Card title="岗位面试标准确认与绑定">
    <Alert type="info" message="按岗位材料填写并确认；新版本会使旧评估、推荐及审批失效，需显式重算，不会重新拨号。" />
    <details><summary>查看当前绑定及历史</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify({ current: current.session.job_interview_standard ?? '尚未绑定 A02 标准', history: current.session.evaluation_binding_history ?? [] }, null, 2)}</pre></details>
    <Form layout="vertical">
      <Space wrap>
        <Form.Item label="标准版本（须递增）"><InputNumber aria-label="标准版本" min={1} precision={0} value={version} onChange={value => { setVersion(value); setConfirmed(false) }} /></Form.Item>
        <Form.Item label="推荐门槛（十分制）"><InputNumber aria-label="推荐门槛" min={1} max={10} value={threshold} onChange={value => { setThreshold(value); setConfirmed(false) }} /></Form.Item>
        <Form.Item label="推荐模板版本"><InputNumber aria-label="推荐模板版本" min={1} precision={0} value={reportVersion} onChange={value => { setReportVersion(value); setConfirmed(false) }} /></Form.Item>
      </Space>
      {dimensions.map((row, index) => <Card key={row.id} size="small" title={`维度 ${index + 1}`} style={{ marginBottom: 12 }} extra={<Button onClick={() => { setDimensions(rows => rows.filter((_, i) => i !== index)); setConfirmed(false) }}>移除此维度</Button>}>
        <Form.Item label="能力名称"><Input value={row.label} onChange={event => update(index, { label: event.target.value })} /></Form.Item>
        <Form.Item label="考核指标与解析"><Input.TextArea value={row.indicators} onChange={event => update(index, { indicators: event.target.value })} /></Form.Item>
        <Form.Item label="权重百分比"><InputNumber min={0.01} max={100} value={row.weight_percent} onChange={value => update(index, { weight_percent: value })} /></Form.Item>
        <Form.Item label="岗位材料来源引用（每行一个，需能定位原文）"><Input.TextArea value={row.sources} onChange={event => update(index, { sources: event.target.value })} /></Form.Item>
        {bands.map(band => <Form.Item key={band} label={`${band} 分行为锚点`}><Input.TextArea value={row.anchors[band] ?? ''} onChange={event => update(index, { anchors: { ...row.anchors, [band]: event.target.value } })} /></Form.Item>)}
      </Card>)}
      <Button onClick={() => { setDimensions(rows => [...rows, { id: crypto.randomUUID(), label: '', indicators: '', sources: '', weight_percent: null, anchors: {} }]); setConfirmed(false) }}>添加岗位能力维度</Button>
      <Typography.Paragraph>权重合计：{weight}%（必须等于 100%）。维度数量由岗位决定。</Typography.Paragraph>
      <Checkbox checked={confirmed} onChange={event => setConfirmed(event.target.checked)}>我已核对岗位来源、权重、行为锚点和推荐门槛，确认应用到此案例</Checkbox>
      {error && <Alert type="error" message={error} />}
      <Button type="primary" loading={busy} disabled={!ready || busy} onClick={() => void (async () => {
        setBusy(true); setError('')
        try {
          await api(`/calls/${current.id}/evaluation-standard`, {
            expected_revision: current.revision, threshold, report_template_version: reportVersion,
            standard: { contract_version: 'a02.v1', job_id: current.job_id, version, status: 'confirmed', confirmed_by: 'current-reviewer', dimensions: dimensions.map(({ sources, ...row }) => ({ ...row, source_refs: sources.split('\n').map(text => text.trim()).filter(Boolean) })) },
          })
          await refresh()
        } catch (failure) { setError(String(failure)) } finally { setBusy(false) }
      })()}>确认并绑定此版本</Button>
    </Form>
  </Card>
}
