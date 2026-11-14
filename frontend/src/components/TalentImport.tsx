import { useRef, useState } from 'react'
import { Alert, Button, Drawer, Input, Table, Tag } from 'antd'
import type { IntakeSession } from '../api/jobIntake'
import { importTalentFiles, importTalentText, type TalentReceipt } from '../api/talentPool'

export default function TalentImport({ session, onClose, onImported }: {
  session: IntakeSession; onClose: () => void; onImported: () => void;
}) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [receipt, setReceipt] = useState<TalentReceipt>()
  const keys = useRef(new Map<string, string>())
  const input = useRef<HTMLInputElement>(null)

  async function submit(files?: File[]) {
    if (busy) return
    setBusy(true); setError('')
    try {
      if (files && (!files.length || files.length > 10)) throw new Error('每批请选择 1—10 份简历。')
      const value = files ? await Promise.all(files.map(async file => {
        if (!/\.(txt|pdf|doc|docx)$/i.test(file.name) || file.size <= 0 || file.size > 5 * 1024 * 1024) throw new Error('支持 TXT、文本 PDF 和 DOC/DOCX，每份须非空且不超过 5 MB。')
        const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
        return { name: file.name, digest: Array.from(new Uint8Array(digest)).join(',') }
      })) : text.trim()
      const signature = JSON.stringify(value)
      const key = keys.current.get(signature) ?? crypto.randomUUID()
      keys.current.set(signature, key)
      const result = files ? await importTalentFiles(files, session, key) : await importTalentText(text.trim(), session, key)
      setReceipt(result); onImported()
      if (!files) setText('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '上传失败，请重试。') }
    finally { setBusy(false); if (input.current) input.current.value = '' }
  }

  return <Drawer open onClose={onClose} title="导入人才库" size={740}>
    <div className="stack">
      <p>无需选择岗位。简历先进入人才库，提取经历并识别职能方向，再关联相关岗位。暂时没有合适岗位的人才也会保留。</p>
      {error && <Alert showIcon type="error" title={error} />}
      <input ref={input} type="file" className="sr-only" accept=".txt,.pdf,.doc,.docx" multiple aria-label="选择人才简历文件" disabled={busy} onChange={event => { const files = Array.from(event.target.files ?? []); if (files.length) void submit(files) }} />
      <div className="upload-area"><p>TXT / 文本型 PDF / DOC / DOCX · 每份最多 5 MB · 每批最多 10 份</p><Button type="primary" loading={busy} disabled={busy} onClick={() => input.current?.click()}>选择并上传简历</Button></div>
      <label htmlFor="talent-resume-text">或粘贴一份简历</label>
      <Input.TextArea id="talent-resume-text" value={text} onChange={event => setText(event.target.value)} rows={6} maxLength={30000} disabled={busy} />
      <div><Button loading={busy} disabled={!text.trim() || busy} onClick={() => { void submit() }}>上传到人才库</Button></div>
      {receipt && <><h3>接收结果</h3><Table rowKey="client_item_id" dataSource={receipt.items} pagination={false} columns={[
        { title: '材料', dataIndex: 'name' },
        { title: '状态', render: (_, item) => <Tag color={item.disposition === 'invalid' ? 'red' : 'green'}>{item.disposition === 'accepted' ? '已接收，等待提取' : item.disposition === 'duplicate' ? '已在人才库中' : '文件未接收'}</Tag> },
        { title: '说明', render: (_, item) => item.error_code ? ({ PDF_TEXT_UNAVAILABLE: 'PDF 无可读正文、已加密或页数超限，请提供文本版 PDF 或 TXT。', DOCUMENT_TEXT_UNAVAILABLE: 'Word 无法可靠读取，请另存为 DOCX 或 TXT。', UNSUPPORTED_FILE_TYPE: '文件格式不受支持，请提供 TXT、文本 PDF 或 DOC/DOCX。', PAYLOAD_TOO_LARGE: '文件为空、超过 5 MB 或提取文字超限，请拆分后上传。', VALIDATION_ERROR: '文本编码或文件内容不正确，请使用 UTF-8 TXT。' } as Record<string, string>)[item.error_code] ?? '文件无法读取，请检查格式或更换文件。' : '提取与分类进度可在人才库查看。' },
      ]} /><Button onClick={onClose}>查看人才库</Button></>}
    </div>
  </Drawer>
}
