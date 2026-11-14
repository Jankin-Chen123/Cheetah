import { useRef, useState } from 'react'
import { Alert, App, Button, Drawer, Empty, Input, Select, Space, Table, Tag } from 'antd'
import type { ImportRecord, Job } from '../domain/workspace'
import { areJobDocumentsConfirmed } from '../domain/jobDocuments'
import { addImport, uid } from '../domain/workspace'
import { Icon } from './ui'

export default function ResumeImport({ open, jobs, records, setRecords, onClose, initialJobId }: {
  open: boolean; jobs: Job[]; records: ImportRecord[]; setRecords: (update: (items: ImportRecord[]) => ImportRecord[]) => void;
  onClose: () => void; initialJobId?: string;
}) {
  const { message } = App.useApp()
  const [jobId, setJobId] = useState(initialJobId ?? jobs.find(j => areJobDocumentsConfirmed(j) || j.status === 'published')?.id)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const replaceId = useRef<string | undefined>(undefined)
  const job = jobs.find(j => j.id === jobId)
  const allowed = !!job && (areJobDocumentsConfirmed(job) || job.status === 'published')

  async function fingerprint(bytes: ArrayBuffer) {
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map(x => x.toString(16).padStart(2, '0')).join('')
  }
  async function addFiles(files: File[]) {
    if (!allowed || !jobId) return
    if (files.length > 10) { void message.error('每次最多 10 份，请分批暂存'); return }
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
          reason: !validType ? '仅支持 TXT 或文本型 PDF' : !validSize ? '文件须非空且不超过 5 MB' : '已校验，未上传；解析待接入',
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
      void message.error('读取失败，请重选此文件')
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
      const record: ImportRecord = { id: uid('import'), jobId, name: '粘贴文本材料', fingerprint: await fingerprint(bytes.buffer), state: 'waiting', reason: '文本已暂存，解析待接入' }
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
      <label className="field-label" htmlFor="import-job">目标岗位</label><Select id="import-job" value={jobId} onChange={setJobId} options={jobs.map(j => ({ value: j.id, label: `${j.title} · ${areJobDocumentsConfirmed(j) ? '产物已确认' : j.status === 'published' ? '可导入' : '产物待确认'}` }))} />
      {!allowed && <Alert type="warning" title="请先确认岗位画像和面试评估表" />}
      <input ref={input} className="sr-only" type="file" multiple accept=".txt,.pdf" aria-label="选择简历文件" onChange={event => { void addFiles(Array.from(event.target.files ?? [])) }} />
      <div className="upload-area"><span className="upload-symbol"><Icon name="upload" size={28} /></span><p>TXT / 文本型 PDF · 每份最多 5 MB · 每次最多 10 份</p><Button type="primary" disabled={!allowed || busy} loading={busy} onClick={() => { replaceId.current = undefined; if (input.current) input.current.multiple = true; input.current?.click() }}>选择文件</Button></div>
      <label className="field-label" htmlFor="resume-text">或粘贴简历文本</label><Input.TextArea id="resume-text" value={text} maxLength={30000} onChange={e => setText(e.target.value)} rows={4} placeholder="粘贴简历文本" /><div><Button disabled={!text.trim() || !allowed || busy} loading={busy} onClick={() => { void addText() }}>暂存文本</Button></div>
      <div className="section-heading"><h3>导入记录</h3><span className="muted">等待 {records.filter(r => r.state === 'waiting').length} · 失败 {records.filter(r => r.state === 'failed').length}</span></div>
      <Table<ImportRecord> rowKey="id" size="small" dataSource={records.filter(r => r.jobId === jobId)} pagination={false} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未暂存材料" /> }} columns={[
        { title: '材料', dataIndex: 'name', render: (name, record) => <div className="import-name"><strong>{name}</strong><p>{record.reason}</p></div> },
        { title: '状态', width: 90, render: (_, r) => <Tag color={r.state === 'failed' ? 'red' : 'orange'}>{r.state === 'failed' ? '校验失败' : '待接入'}</Tag> },
        { title: '操作', width: 100, render: (_, r) => <Space>{r.state === 'failed' && <Button type="link" size="small" disabled={busy || !allowed} onClick={() => { replaceId.current = r.id; if (input.current) input.current.multiple = false; input.current?.click() }}>替换此份</Button>}</Space> },
      ]} />
    </div>
  </Drawer>
}
