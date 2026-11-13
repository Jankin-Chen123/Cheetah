import { useRef, useState } from 'react'
import { Alert, App, Button, Drawer, Empty, Input, Select, Space, Table, Tag } from 'antd'
import type { ImportRecord, Job } from '../domain/workspace'
import { addImport, uid } from '../domain/workspace'
import { Icon } from './ui'

export default function ResumeImport({ open, jobs, records, setRecords, onClose, initialJobId }: {
  open: boolean; jobs: Job[]; records: ImportRecord[]; setRecords: (update: (items: ImportRecord[]) => ImportRecord[]) => void;
  onClose: () => void; initialJobId?: string;
}) {
  const { message } = App.useApp()
  const [jobId, setJobId] = useState(initialJobId ?? jobs.find(j => j.status === 'published')?.id)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const replaceId = useRef<string | undefined>(undefined)
  const job = jobs.find(j => j.id === jobId)
  const allowed = job?.status === 'published'

  async function fingerprint(bytes: ArrayBuffer) {
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map(x => x.toString(16).padStart(2, '0')).join('')
  }
  async function addFiles(files: File[]) {
    if (!allowed || !jobId) return
    if (files.length > 10) { void message.error('每次最多选择 10 份材料，请分批暂存。'); return }
    setBusy(true)
    const additions: ImportRecord[] = []
    const replacement = replaceId.current
    try {
      for (const file of files) {
        const validType = /\.(txt|pdf)$/i.test(file.name)
        const validSize = file.size > 0 && file.size <= 5 * 1024 * 1024
        const valid = validType && validSize
        additions.push({
          id: uid('import'), jobId, name: file.name,
          fingerprint: valid ? await fingerprint(await file.arrayBuffer()) : uid('invalid'),
          state: valid ? 'waiting' : 'failed',
          reason: !validType ? '不支持该格式，请替换为 TXT 或文本型 PDF。' : !validSize ? '文件须非空且不超过 5 MB（前端演示限制）。' : '仅在本页校验并暂存文件摘要；解析与处理接口待接入，文件未上传。',
        })
      }
      setRecords(current => {
        let next = current
        for (const record of additions) {
          try {
            next = addImport(next, record)
            if (replacement && record.state !== 'failed') next = next.filter(r => r.id !== replacement)
          } catch (error) {
            // Keep validation feedback in the batch; no duplicate processing is created.
            next = [...next, { ...record, state: 'failed', reason: (error as Error).message }]
          }
        }
        return next
      })
    } catch {
      void message.error('文件读取失败，请重新选择；已暂存的其他记录保留。')
    } finally {
      setBusy(false)
      replaceId.current = undefined
      if (input.current) input.current.value = ''
    }
  }
  async function addText() {
    if (!text.trim() || !allowed || !jobId) return
    setBusy(true)
    try {
      const bytes = new TextEncoder().encode(text.trim())
      const record: ImportRecord = { id: uid('import'), jobId, name: '粘贴文本材料', fingerprint: await fingerprint(bytes.buffer), state: 'waiting', reason: '文本摘要已暂存；未解析、未筛选、未创建电话任务。' }
      // The updater also checks duplicates against concurrent additions.
      setRecords(current => {
        try { return addImport(current, record) }
        catch (error) { return [...current, { ...record, state: 'failed', reason: (error as Error).message }] }
      })
      setText('')
    } finally { setBusy(false) }
  }

  return <Drawer open={open} onClose={onClose} title="导入简历材料" size={740}>
    <div className="stack">
      <Alert showIcon type="warning" title="前端演示 · 请使用虚构或脱敏材料" description="文件不会发送到后端，也不会保存在浏览器存储中。当前只验证格式、大小与内容摘要，刷新页面清空；不会伪造解析或初筛结果。" />
      <label className="field-label" htmlFor="import-job">目标岗位</label><Select id="import-job" value={jobId} onChange={setJobId} options={jobs.map(j => ({ value: j.id, label: `${j.title} · ${j.status === 'published' ? `测试规则 v${j.version}` : '规则未发布'}` }))} />
      {!allowed && <Alert type="warning" title="请先在岗位详情确认并发布测试规则，再暂存材料。" />}
      <input ref={input} className="sr-only" type="file" multiple accept=".txt,.pdf" aria-label="选择简历文件" onChange={event => { void addFiles(Array.from(event.target.files ?? [])) }} />
      <div className="upload-area"><span className="upload-symbol"><Icon name="upload" size={28} /></span><h3>每一份材料，都有独立的处理记录</h3><p>TXT / 文本型 PDF · 每份最多 5 MB · 每次最多 10 份</p><Button type="primary" disabled={!allowed || busy} loading={busy} onClick={() => { replaceId.current = undefined; if (input.current) input.current.multiple = true; input.current?.click() }}>选择文件</Button></div>
      <label className="field-label" htmlFor="resume-text">或粘贴简历文本</label><Input.TextArea id="resume-text" value={text} maxLength={30000} onChange={e => setText(e.target.value)} rows={4} placeholder="在这里粘贴虚构或脱敏简历。材料中的文字不会作为系统操作指令执行。" /><div><Button disabled={!text.trim() || !allowed || busy} loading={busy} onClick={() => { void addText() }}>暂存文本</Button></div>
      <div className="section-heading"><h3>本次工作区记录</h3><span className="muted">等待 {records.filter(r => r.state === 'waiting').length} · 失败 {records.filter(r => r.state === 'failed').length}</span></div>
      <Table<ImportRecord> rowKey="id" size="small" dataSource={records.filter(r => r.jobId === jobId)} pagination={false} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未暂存材料" /> }} columns={[
        { title: '材料', dataIndex: 'name', render: (name, record) => <div className="import-name"><strong>{name}</strong><p>{record.reason}</p></div> },
        { title: '状态', width: 90, render: (_, r) => <Tag color={r.state === 'failed' ? 'red' : 'orange'}>{r.state === 'failed' ? '校验失败' : '待接入'}</Tag> },
        { title: '操作', width: 100, render: (_, r) => <Space>{r.state === 'failed' && <Button type="link" size="small" disabled={busy || !allowed} onClick={() => { replaceId.current = r.id; if (input.current) input.current.multiple = false; input.current?.click() }}>替换此份</Button>}</Space> },
      ]} />
    </div>
  </Drawer>
}
