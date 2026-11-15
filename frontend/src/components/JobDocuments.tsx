import { useContext, useState } from 'react'
import { RemoteAccessContext } from '../domain/access'
import { Alert, App, Button, Dropdown, Empty, Form, Input, Modal, Space, Tabs, Tag } from 'antd'
import type { Job } from '../domain/workspace'
import type { DocumentTable, JobDocument } from '../domain/jobDocuments'
import { ANCHORS, canExportJobDocument, currentDocument, confirmJobDocument, saveDocumentRevision, weightTotal } from '../domain/jobDocuments'
import { previewText } from '../domain/presentation'
import { exportJobPdf, exportJobWord } from '../domain/exportJobDocuments'
import type { useJobGeneration } from '../hooks/useJobGeneration'
import { SourceTag } from './ui'
import JobMaterialPanel from './JobMaterialPanel'

function DocumentView({ job, type, onUpdate }: { job: Job; type: JobDocument['type']; onUpdate: (job: Job) => void }) {
  const document = currentDocument(job, type)
  const [tables, setTables] = useState<DocumentTable[]>()
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState(false)
  const { message } = App.useApp()
  if (!document) return <section className="panel"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={type === 'D01' ? '岗位画像尚未生成' : '面试评估表尚未生成'} /></section>
  const unknowns = document.unknowns.filter(value => document.source !== 'mock' || !/(虚构示例|模拟样例)/.test(value))
  const shown = tables ?? document.tables
  function change(tableId: string, rowId: string, column: number, value: string) {
    setTables(items => items?.map(table => table.id !== tableId ? table : { ...table, rows: table.rows.map(row => row.id !== rowId ? row : { ...row, cells: row.cells.map((cell, i) => i === column ? value : cell) }) }))
  }
  async function exportOne(format: string) {
    setExporting(true); setError('')
    try { await (format === 'pdf' ? exportJobPdf : exportJobWord)(job, [document!]) }
    catch (caught) { setError((caught as Error).message) }
    finally { setExporting(false) }
  }
  return <section className="panel document-panel stack">
    <div className="document-toolbar"><Space wrap><h2>{document.title}</h2><SourceTag source={document.source} /><Tag color={document.status === 'confirmed' ? 'green' : undefined}>{document.status === 'confirmed' ? '已确认' : document.status === 'needs_review' ? '待复核' : '待确认草案'}</Tag></Space><Space wrap>

      {!tables && <Button onClick={() => { setTables(document.tables.map(table => ({ ...table, rows: table.rows.map(row => ({ ...row, cells: row.cells.map(cell => document.source === 'mock' ? previewText(cell) : cell) })) }))); setReason(''); setError('') }}>修改</Button>}
      {!tables && <Button type="primary" disabled={document.status === 'confirmed' || type === 'D02' && currentDocument(job, 'D01')?.status !== 'confirmed'} onClick={() => {
        try { onUpdate(confirmJobDocument(job, document.id)); setError(''); void message.success(`${document.title}已确认`) }
        catch (caught) { setError((caught as Error).message) }
      }}>{document.status === 'confirmed' ? '已确认' : type === 'D01' ? '确认岗位画像' : document.status === 'needs_review' ? '复核并确认面试表' : '确认面试评估表'}</Button>}
      <Dropdown trigger={['click']} menu={{ items: [{ key: 'pdf', label: 'PDF' }, { key: 'word', label: 'Word（可编辑）' }], onClick: ({ key }) => void exportOne(key) }} disabled={!!tables || !canExportJobDocument(job, document)}><Button loading={exporting}>导出 ▾</Button></Dropdown>
    </Space></div>
    {document.status === 'needs_review' && <Alert type="warning" showIcon title="岗位画像已修改，请复核面试标准后重新确认。" />}
    {type === 'D02' && document.status !== 'confirmed' && currentDocument(job, 'D01')?.status !== 'confirmed' && <span className="muted small">请先确认岗位画像，再确认面试评估表。</span>}
    {document.confirmedAt && <span className="muted small">确认时间：{new Date(document.confirmedAt).toLocaleString('zh-CN')}</span>}
    {shown.map(table => <div key={table.id} className="job-form-section">
      {table.title && <h3>{table.title}</h3>}
      <div className="job-form-scroll"><table className={`job-form-table ${table.id === 'dimensions' ? 'interview-form-table' : ''}`}><colgroup>{table.widths.map((width, index) => <col key={index} style={{ width: `${width * 100}%` }} />)}</colgroup><thead><tr>{table.headers.map((header, index) => <th scope="col" key={index}>{header}</th>)}{tables && table.id === 'dimensions' && <th>操作</th>}</tr></thead><tbody>{table.rows.map(row => row.group ? <tr className="form-group" key={row.id}><th colSpan={table.headers.length}>{row.cells[0]}</th></tr> : <tr key={row.id}>{row.cells.map((cell, column) => <td key={column}>{tables && !table.readonlyColumns?.includes(column) ? <Input.TextArea aria-label={`${row.cells[0] || '新维度'} · ${table.headers[column]}`} autoSize={{ minRows: 2, maxRows: 16 }} maxLength={12000} value={cell} onChange={e => change(table.id, row.id, column, e.target.value)} /> : <span>{document.source === 'mock' ? previewText(cell) : cell}</span>}</td>)}{tables && table.id === 'dimensions' && <td><Button danger size="small" onClick={() => setTables(items => items?.map(t => t.id === table.id ? { ...t, rows: t.rows.filter(r => r.id !== row.id) } : t))}>删除</Button></td>}</tr>)}</tbody></table></div>
      {table.id === 'dimensions' && <Space wrap><span className="muted small">{table.rows.length} 个维度 · 权重合计 {weightTotal(table.rows.map(row => row.cells[2]))} · 实际得分留空</span>{tables && <Button size="small" onClick={() => setTables(items => items?.map(t => t.id === 'dimensions' ? { ...t, rows: [...t.rows, { id: crypto.randomUUID(), cells: ['', '', '0%', ANCHORS.map(band => `${band}：待补充`).join('\n'), '', ''] }] } : t))}>添加维度</Button>}</Space>}
    </div>)}
    {!!unknowns.length && <Alert type="warning" showIcon title="待核实事项" description={<ul>{unknowns.map((unknown, i) => <li key={i}>{document.source === 'mock' ? previewText(unknown) : unknown}</li>)}</ul>} />}
    {tables && <div className="stack"><Input aria-label="修改原因" placeholder="修改原因（必填）" value={reason} onChange={e => setReason(e.target.value)} maxLength={500} /><Space><Button onClick={() => { setTables(undefined); setError('') }}>取消修改</Button><Button type="primary" onClick={() => {
      try { const next = saveDocumentRevision(job, document.id, tables, reason); onUpdate(next); setTables(undefined); setError(''); void message.success('修改已保存，请重新确认') }
      catch (caught) { setError((caught as Error).message) }
    }}>保存修改</Button></Space></div>}
    {error && <Alert type="error" showIcon title={error} />}
  </section>
}

export default function JobDocuments({ job, onUpdate, generation }: { job: Job; onUpdate: (job: Job) => void; generation: ReturnType<typeof useJobGeneration> }) {
  const canGenerate = useContext(RemoteAccessContext)
  const [form] = Form.useForm<{ username: string; password: string }>()
  const state = canGenerate || job.source === 'mock' ? job.generation?.state : undefined
  const d01 = currentDocument(job, 'D01')
  const needsCheck = !!state && ['failed', 'waiting_backend', 'reconciling'].includes(state)
  return <div className="stack">
    {state && state !== 'completed' && <Alert showIcon type={needsCheck || state === 'waiting_transcript' ? 'warning' : 'info'} title={needsCheck ? job.generation?.error : state === 'waiting_transcript' ? '自动转写待接入，请先补充文字记录。' : d01 ? '岗位画像已生成，正在生成面试评估表…' : '正在识别文字记录…'} action={needsCheck && <Button size="small" loading={generation.busy} onClick={generation.start}>重新检查</Button>} />}
    {generation.retryable && <div><Button loading={generation.busy} onClick={() => void generation.retry()}>重试失败步骤</Button></div>}
    {generation.regeneratable && <div><Button loading={generation.busy} onClick={() => void generation.retry(true)}>重新生成失败步骤</Button><p className="muted">重新调用一次模型，保留失败记录；不会重复创建岗位或重新执行结果未知的请求。</p></div>}
    <Tabs defaultActiveKey="D01" items={[
      { key: 'D01', label: '岗位画像', children: <DocumentView job={job} type="D01" onUpdate={onUpdate} /> },
      { key: 'D02', label: '岗位面试评估表', children: <DocumentView job={job} type="D02" onUpdate={onUpdate} /> },
      { key: 'material', label: '原始材料', children: <JobMaterialPanel key={job.id} job={job} busy={generation.busy} onUpdate={onUpdate} onRecognize={generation.start} /> },
    ]} />
    <Modal title="登录后生成岗位产物" open={generation.loginOpen} onCancel={generation.closeLogin} afterClose={() => form.resetFields()} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={values => void generation.login(values.username, values.password)}><Form.Item name="username" label="账号" rules={[{ required: true }]}><Input autoComplete="username" /></Form.Item><Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item>{generation.loginError && <Alert type="error" title={generation.loginError} />}<div className="modal-actions"><Button type="primary" loading={generation.loginBusy} htmlType="submit">登录并继续</Button></div></Form>
    </Modal>
  </div>
}
