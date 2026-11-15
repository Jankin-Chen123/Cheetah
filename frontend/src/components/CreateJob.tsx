import { useRef, useState } from 'react'
import { Alert, Button, Input, Modal, Select, Space, Tag, Upload } from 'antd'
import type { Job } from '../domain/workspace'
import { createMaterialJob } from '../domain/jobDocuments'
import { Icon } from './ui'
import AudioFileRecognition from './AudioFileRecognition'
import type { AudioRef, AudioUrl } from '../api/audio'

export default function CreateJob({ open, ready, onClose, onCreate }: { open: boolean; ready: boolean; onClose: () => void; onCreate: (job: Job) => void }) {
  const [transcript, setTranscript] = useState('')
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState('')
  const [audio, setAudio] = useState<File>()
  const [audioRef, setAudioRef] = useState<AudioRef>()
  const [audioUrl, setAudioUrl] = useState('')
  const [urlFormat, setUrlFormat] = useState<AudioUrl['audio_format']>('mp3')
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
      const job = createMaterialJob({ kind: audio ? 'audio' : 'transcript', transcript, originalText, audioTranscriptionRef: audioRef, textFile: textFile ? { name: textFile.name, size: textFile.size, type: textFile.type, blob: textFile } : undefined, audio: audio ? { name: audio.name, size: audio.size, type: audio.type, blob: audio } : undefined })
      job.providedFields = { ...(title.trim() ? { title: title.trim() } : {}), ...(company.trim() ? { company: company.trim() } : {}) }
      if (title.trim()) job.title = title.trim()
      if (company.trim()) job.company = company.trim()
      setTitle(''); setCompany('')
      onCreate(job); setTranscript(''); setAudio(undefined); setAudioUrl(''); setAudioRef(undefined); setTextFile(undefined); setOriginalText(undefined); setError(''); onClose()
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }
  return <Modal title="创建岗位" open={open} onCancel={onClose} footer={null} width={720} destroyOnHidden>
    <div className="stack">
      <label htmlFor="job-title">岗位名称（可选，未填写则从材料识别）</label><Input id="job-title" value={title} onChange={event => setTitle(event.target.value)} maxLength={100} />
      <label htmlFor="job-company">企业名称（可选，未填写则保留未知或从材料识别）</label><Input id="job-company" value={company} onChange={event => setCompany(event.target.value)} maxLength={100} />
      <Upload.Dragger maxCount={1} accept=".mp3,.wav,.ogg" showUploadList={false} beforeUpload={file => {
          if (!/\.(mp3|wav|ogg)$/i.test(file.name) || !file.size || file.size > 20 * 1024 * 1024) { setError('请选择非空 WAV、MP3 或 OGG OPUS 录音，最大 20 MB、最长两小时。'); return false }
          setAudio(file); setAudioRef(undefined); setError(''); return false
        }}><Icon name="upload" size={28} /><p>{audio ? audio.name : '拖入录音，或点击选择'}</p><span className="muted small">MP3 / WAV / OGG OPUS · 最大 20 MB · 最长两小时</span></Upload.Dragger>
      {audio && <><Space wrap><Button size="small" type="text" onClick={() => { setAudio(undefined); setAudioRef(undefined); setError('') }}>移除录音</Button></Space><AudioFileRecognition key={`${audio.name}:${audio.lastModified}:${audio.size}`} file={audio} onComplete={(text, ref) => { setTranscript(text); setOriginalText(text); setAudioRef(ref); setTextFile(undefined) }} /></>}
      {!audio && <details><summary>使用音频网址（标准版）</summary><div className="stack">
        <p className="muted small">填写语音服务可直接读取的公网 HTTPS 音频地址。标准版异步处理，结果完成后自动回填。</p>
        <Input aria-label="音频公网网址" value={audioUrl} onChange={event => { setAudioUrl(event.target.value); setAudioRef(undefined) }} placeholder="https://…/recording.mp3" maxLength={2048} />
        <Select aria-label="远程音频格式" value={urlFormat} onChange={setUrlFormat} options={['mp3', 'wav', 'ogg', 'm4a', 'aac', 'amr', 'spx'].map(value => ({ value, label: value.toUpperCase() }))} />
        {audioUrl.trim() && <AudioFileRecognition key={`${audioUrl.trim()}:${urlFormat}`} audioUrl={{ audio_url: audioUrl.trim(), audio_format: urlFormat }} onComplete={(text, ref) => { setTranscript(text); setOriginalText(text); setAudioRef(ref); setTextFile(undefined) }} />}
      </div></details>}
      <details className="job-transcript-option" open={!!transcript}>
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
      <div className="modal-actions"><Button onClick={onClose}>取消</Button><Button type="primary" loading={busy || readingText} disabled={!ready || readingText || !transcript.trim()} onClick={create}>创建并识别<Icon name="arrow" size={16} /></Button></div>
    </div>
  </Modal>
}
