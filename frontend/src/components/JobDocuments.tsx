import { useContext, useEffect, useRef, useState } from 'react'
import { RemoteAccessContext } from '../domain/access'
import { Alert, App, Button, Dropdown, Empty, Form, Input, Modal, Select, Space, Tabs, Tag } from 'antd'
import type { Job } from '../domain/workspace'
import type { DocumentTable, JobDocument } from '../domain/jobDocuments'
import { ANCHORS, canExportJobDocument, currentDocument, saveDocumentRevision, weightTotal } from '../domain/jobDocuments'
import { exportJobPdf, exportJobWord } from '../domain/exportJobDocuments'
import { useJobGeneration } from '../hooks/useJobGeneration'
import { SourceTag } from './ui'

function AudioPreview({ blob }: { blob: Blob }) {
  const element = useRef<HTMLAudioElement>(null)
  useEffect(() => { const next = URL.createObjectURL(blob); if (element.current) element.current.src = next; return () => URL.revokeObjectURL(next) }, [blob])
  return <audio ref={element} aria-label="原始录音" controls />
}

function DocumentView({ job, type, onUpdate }: { job: Job; type: JobDocument['type']; onUpdate: (job: Job) => void }) {
  const versions = job.documents?.filter(d => d.type === type) ?? []
  const [selected, setSelected] = useState<string>()
  const document = versions.find(d => d.id === selected) ?? versions.at(-1)
  const [tables, setTables] = useState<DocumentTable[]>()
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState(false)
  const { message } = App.useApp()
  if (!document) return <section className="panel"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={type === 'D01' ? '岗位画像尚未生成' : '面试评估表尚未生成'} /></section>
  const current = currentDocument(job, type)?.id === document.id
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
    <div className="document-toolbar"><Space wrap><h2>{document.title}</h2><SourceTag source={document.source} />{document.inheritedSources.includes('mock') && document.source !== 'mock' && <Tag color="orange">含模拟来源</Tag>}<Tag>{document.status === 'needs_review' ? '待复核' : current ? '待确认草案' : '历史版本'}</Tag></Space><Space wrap>
      <Select aria-label={`${document.title}版本`} value={document.id} disabled={!!tables} onChange={setSelected} options={versions.map(d => ({ value: d.id, label: `v${d.version}${d.id === versions.at(-1)?.id ? ' · 当前' : ' · 历史'}` }))} />
      {!tables && <Button disabled={!current} onClick={() => { setTables(structuredClone(document.tables)); setReason(''); setError('') }}>修改</Button>}
      <Dropdown trigger={['click']} menu={{ items: [{ key: 'pdf', label: 'PDF' }, { key: 'word', label: 'Word（可编辑）' }], onClick: ({ key }) => void exportOne(key) }} disabled={!!tables || !canExportJobDocument(job, document)}><Button loading={exporting}>导出 ▾</Button></Dropdown>
    </Space></div>
    {document.status === 'needs_review' && <Alert type="warning" showIcon title="岗位画像已修改，请复核面试标准并保存新版本。" />}
    <span className="muted small">{document.changeReason} · {new Date(document.createdAt).toLocaleString('zh-CN')}</span>
    {shown.map(table => <div key={table.id} className="job-form-section">
      {table.title && <h3>{table.title}</h3>}
      <div className="job-form-scroll"><table className={`job-form-table ${table.id === 'dimensions' ? 'interview-form-table' : ''}`}><colgroup>{table.widths.map((width, index) => <col key={index} style={{ width: `${width * 100}%` }} />)}</colgroup><thead><tr>{table.headers.map((header, index) => <th scope="col" key={index}>{header}</th>)}{tables && table.id === 'dimensions' && <th>操作</th>}</tr></thead><tbody>{table.rows.map(row => row.group ? <tr className="form-group" key={row.id}><th colSpan={table.headers.length}>{row.cells[0]}</th></tr> : <tr key={row.id}>{row.cells.map((cell, column) => <td key={column}>{tables && !table.readonlyColumns?.includes(column) ? <Input.TextArea aria-label={`${row.cells[0] || '新维度'} · ${table.headers[column]}`} autoSize={{ minRows: 2, maxRows: 16 }} maxLength={12000} value={cell} onChange={e => change(table.id, row.id, column, e.target.value)} /> : <span>{cell}</span>}</td>)}{tables && table.id === 'dimensions' && <td><Button danger size="small" onClick={() => setTables(items => items?.map(t => t.id === table.id ? { ...t, rows: t.rows.filter(r => r.id !== row.id) } : t))}>删除</Button></td>}</tr>)}</tbody></table></div>
      {table.id === 'dimensions' && <Space wrap><span className="muted small">{table.rows.length} 个维度 · 权重合计 {weightTotal(table.rows.map(row => row.cells[2]))} · 实际得分留空</span>{tables && <Button size="small" onClick={() => setTables(items => items?.map(t => t.id === 'dimensions' ? { ...t, rows: [...t.rows, { id: crypto.randomUUID(), cells: ['', '', '0%', ANCHORS.map(band => `${band}：待补充`).join('\n'), '', ''] }] } : t))}>添加维度</Button>}</Space>}
    </div>)}
    {!!document.unknowns.length && <Alert type="warning" showIcon title="待核实事项" description={<ul>{document.unknowns.map((unknown, i) => <li key={i}>{unknown}</li>)}</ul>} />}
    {tables && <div className="stack"><Input aria-label="修改原因" placeholder="修改原因（必填）" value={reason} onChange={e => setReason(e.target.value)} maxLength={500} /><Space><Button onClick={() => { setTables(undefined); setError('') }}>取消修改</Button><Button type="primary" onClick={() => {
      try { const next = saveDocumentRevision(job, document.id, tables, reason); onUpdate(next); setSelected(undefined); setTables(undefined); setError(''); void message.success('已生成新版本，正在保存') }
      catch (caught) { setError((caught as Error).message) }
    }}>保存新版本</Button></Space></div>}
    {error && <Alert type="error" showIcon title={error} />}
  </section>
}

export default function JobDocuments({ job, onUpdate }: { job: Job; onUpdate: (job: Job) => void }) {
  const canGenerate = useContext(RemoteAccessContext)
  const generation = useJobGeneration(job, onUpdate)
  const [transcript, setTranscript] = useState(job.materialInput?.transcript ?? '')
  const [form] = Form.useForm<{ username: string; password: string }>()
  const state = canGenerate || job.source === 'mock' ? job.generation?.state : undefined
  const d01 = currentDocument(job, 'D01'); const d02 = currentDocument(job, 'D02')
  const { message } = App.useApp()
  const [exporting, setExporting] = useState(false)
  async function exportBoth(format: string) {
    if (!d01 || !d02) return
    setExporting(true)
    try { await (format === 'pdf' ? exportJobPdf : exportJobWord)(job, [d01, d02]) }
    catch (caught) { void message.error((caught as Error).message) }
    finally { setExporting(false) }
  }
  return <div className="stack">
    {!canGenerate && <Alert type="info" showIcon title="演示工作区仅保存在本机" description={<>真实生成请先<a href="#login">登录</a>或<a href="#register">注册</a>，然后在账号工作空间创建岗位。演示材料不会自动转移。</>} />}
    <div className="document-toolbar"><span className="muted small">网页留存 · 人工修订保存在本机</span><Dropdown trigger={['click']} disabled={!d01 || !d02 || !canExportJobDocument(job, d01) || !canExportJobDocument(job, d02)} menu={{ items: [{ key: 'pdf', label: '两份 PDF' }, { key: 'word', label: '两份 Word' }], onClick: ({ key }) => void exportBoth(key) }}><Button loading={exporting}>导出两份产物 ▾</Button></Dropdown></div>
    {state && <Alert showIcon type={state === 'failed' || state === 'waiting_transcript' ? 'warning' : state === 'completed' ? 'success' : 'info'} title={state === 'failed' ? job.generation?.error : state === 'waiting_transcript' ? '自动转写待接入，请先补充文字记录。' : state === 'completed' ? job.source === 'mock' ? '两份模拟产物已载入，待确认。' : '两份产物已生成，待确认。' : d01 ? '岗位画像已生成，正在生成面试评估表…' : '正在识别文字记录…'} action={state === 'failed' && <Button size="small" loading={generation.busy} onClick={generation.start}>重新检查</Button>} />}
    <Tabs defaultActiveKey="D01" items={[
      { key: 'D01', label: '岗位画像', children: <DocumentView job={job} type="D01" onUpdate={onUpdate} /> },
      { key: 'D02', label: '岗位面试评估表', children: <DocumentView job={job} type="D02" onUpdate={onUpdate} /> },
      { key: 'material', label: '原始材料', children: <section className="panel stack"><h2>沟通记录</h2>{job.materialInput?.audio && <><span>{job.materialInput.audio.name}</span><AudioPreview blob={job.materialInput.audio.blob} /></>}{!job.generation?.submitted && !job.generation?.remoteJobId && !job.documents?.length ? <><Input.TextArea aria-label="补充文字记录" value={transcript} onChange={e => setTranscript(e.target.value)} rows={12} maxLength={30000} /><Button type="primary" disabled={!transcript.trim() || generation.busy} onClick={() => { onUpdate({ ...job, material: transcript.trim(), materialInput: { ...job.materialInput!, transcript: transcript.trim() }, generation: { ...job.generation!, state: 'not_started', error: undefined } }); setTimeout(generation.start, 0) }}>保存文字并识别</Button></> : <p className="document-content">{job.materialInput?.transcript || job.material || '无文字记录'}</p>}</section> },
    ]} />
    <Modal title="登录后生成岗位产物" open={generation.loginOpen} onCancel={generation.closeLogin} afterClose={() => form.resetFields()} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={values => void generation.login(values.username, values.password)}><Form.Item name="username" label="账号" rules={[{ required: true }]}><Input autoComplete="username" /></Form.Item><Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item>{generation.loginError && <Alert type="error" title={generation.loginError} />}<div className="modal-actions"><Button type="primary" loading={generation.loginBusy} htmlType="submit">登录并继续</Button></div></Form>
    </Modal>
  </div>
}
