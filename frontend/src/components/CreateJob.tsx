import { useRef, useState } from 'react'
import { Alert, Button, Input, Modal, Space, Tag, Upload } from 'antd'
import type { Job } from '../domain/workspace'
import { createMaterialJob } from '../domain/jobDocuments'
import { Icon } from './ui'

export default function CreateJob({ open, ready, onClose, onCreate }: { open: boolean; ready: boolean; onClose: () => void; onCreate: (job: Job) => void }) {
  const [transcript, setTranscript] = useState('')
  const [audio, setAudio] = useState<File>()
  const [textFile, setTextFile] = useState<File>()
  const [originalText, setOriginalText] = useState<string>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [readingText, setReadingText] = useState(false)
  const uploadInput = useRef<HTMLInputElement>(null)
  async function readTranscript(file: File) {
    if (file.size > 2 * 1024 * 1024 || !/\.txt$/i.test(file.name)) { setError('转写文件须为不超过 2 MB 的 UTF-8 TXT。'); return }
    setReadingText(true)
    try {
      const content = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()).replace(/^\uFEFF/, '')
      if (content.length > 30000 || content.includes('\0')) { setError('转写文本须不超过 30,000 字，且不能含二进制内容。'); return }
      setTranscript(content); setTextFile(file); setOriginalText(content); setError('')
    } catch { setError('无法读取，请提供 UTF-8 TXT 或直接粘贴文字。') }
    finally { setReadingText(false) }
  }
  function create() {
    setBusy(true)
    try {
      const job = createMaterialJob({ kind: audio ? 'audio' : 'transcript', transcript, originalText, textFile: textFile ? { name: textFile.name, size: textFile.size, type: textFile.type, blob: textFile } : undefined, audio: audio ? { name: audio.name, size: audio.size, type: audio.type, blob: audio } : undefined })
      onCreate(job); setTranscript(''); setAudio(undefined); setTextFile(undefined); setOriginalText(undefined); setError(''); onClose()
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }
  return <Modal title="创建岗位" open={open} onCancel={onClose} footer={null} width={720} destroyOnHidden>
    <div className="stack">
      <Upload.Dragger maxCount={1} accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.webm,.flac" showUploadList={false} beforeUpload={file => {
          if (!/\.(mp3|wav|m4a|aac|ogg|webm|flac)$/i.test(file.name) || !file.size || file.size > 100 * 1024 * 1024) { setError('请选择非空录音，最大 100 MB。'); return false }
          setAudio(file); setError(''); return false
        }}><Icon name="upload" size={28} /><p>{audio ? audio.name : '拖入录音，或点击选择'}</p><span className="muted small">MP3 / WAV / M4A 等 · 最大 100 MB</span></Upload.Dragger>
      {audio && <Space wrap><Button size="small" type="text" onClick={() => { setAudio(undefined); setError('') }}>移除录音</Button><span className="muted small">自动转写待接入，可补充文字记录识别。</span></Space>}
      <details className="job-transcript-option">
      <summary>{audio ? '补充文字记录（可选）' : '没有录音？使用文字记录（可选）'}</summary>
      <div className="stack">
      <div className="section-heading intake-label"><label htmlFor="job-transcript">录音文字记录</label><Button size="small" type="text" onClick={() => uploadInput.current?.click()}>上传 TXT</Button></div>
      <input ref={uploadInput} type="file" className="sr-only" accept=".txt,text/plain" onChange={event => { const file = event.target.files?.[0]; if (file) void readTranscript(file); event.target.value = '' }} />
      {textFile && <Space wrap><span className="small">{textFile.name}</span><Button size="small" type="text" onClick={() => { setTextFile(undefined); setOriginalText(undefined); setTranscript('') }}>移除文字文件</Button></Space>}
      <Input.TextArea id="job-transcript" value={transcript} onChange={event => setTranscript(event.target.value)} rows={6} maxLength={30000} showCount placeholder="上传 TXT 或粘贴与 HR、用人方的沟通文字记录" />
      </div>
      </details>
      <Space wrap><Tag>岗位画像</Tag><Tag>岗位面试评估表</Tag><span className="muted small">生成后可修改、保存和导出 PDF / Word</span></Space>
      {error && <Alert type="error" showIcon title={error} />}
      <div className="modal-actions"><Button onClick={onClose}>取消</Button><Button type="primary" loading={busy || readingText} disabled={!ready || readingText || !transcript.trim() && !audio} onClick={create}>{transcript.trim() ? '创建并识别' : audio ? '保存录音' : '创建岗位'}<Icon name="arrow" size={16} /></Button></div>
    </div>
  </Modal>
}
