import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, Space } from 'antd'
import type { Job } from '../domain/workspace'
import type { MaterialFile } from '../domain/jobDocuments'
import { saveMaterialText } from '../domain/jobMaterials'
import { previewText } from '../domain/presentation'

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = name
  document.body.append(link); link.click(); link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 30000)
}

function AudioPreview({ blob }: { blob: Blob }) {
  const element = useRef<HTMLAudioElement>(null)
  useEffect(() => {
    const url = URL.createObjectURL(blob)
    if (element.current) element.current.src = url
    return () => URL.revokeObjectURL(url)
  }, [blob])
  return <audio ref={element} aria-label="原始录音" controls preload="metadata" style={{ maxWidth: '100%' }} />
}

function FileDownload({ file, label }: { file: MaterialFile; label: string }) {
  return <div className="material-file"><span>{file.name}</span><span className="muted small">{file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`}</span><Button size="small" onClick={() => download(file.blob, file.name)}>{label}</Button></div>
}

export default function JobMaterialPanel({ job, busy, onUpdate, onRecognize }: {
  job: Job; busy: boolean; onUpdate: (job: Job) => void; onRecognize: () => void;
}) {
  const material = job.materialInput
  const original = material?.originalText ?? material?.transcript ?? (job.source === 'mock' ? previewText(job.material) : job.material)
  const current = material?.transcript ?? original
  const minutes = material?.minutes?.at(-1)
  const editable = !job.generation?.submitted && !job.generation?.remoteJobId && !job.documents?.length
  const [text, setText] = useState(current)
  const [error, setError] = useState('')
  return <div className="stack">
    {material?.audio && <section className="panel stack" aria-label="原始录音材料">
      <h2>原始录音</h2><FileDownload file={material.audio} label="下载录音" /><AudioPreview blob={material.audio.blob} />
      <span className="muted small">自动转写待接入</span>
    </section>}
    {(original || material?.textFile) && <section className="panel stack" aria-label="原始文字材料">
      <div className="document-toolbar"><h2>原始文字</h2>{!material?.textFile && <Button size="small" onClick={() => download(new Blob([original], { type: 'text/plain;charset=utf-8' }), '原始文字.txt')}>下载文字</Button>}</div>
      {material?.textFile && <FileDownload file={material.textFile} label="下载文字原件" />}
      <p className="document-content">{original || '文件内容为空'}</p>
    </section>}
    {current && current !== original && <section className="panel stack"><h2>识别用文字</h2><p className="document-content">{current}</p></section>}
    {editable && <section className="panel stack">
      <h2>{original ? '补充或修正文字' : '补充文字记录'}</h2>
      <Input.TextArea aria-label="补充文字记录" value={text} onChange={event => setText(event.target.value)} rows={6} maxLength={30000} placeholder="粘贴文字记录，原始文件会保留" />
      <Space><Button type="primary" disabled={!text.trim() || busy} onClick={() => {
        try { onUpdate(saveMaterialText(job, text)); setError(''); setTimeout(onRecognize, 0) }
        catch (caught) { setError((caught as Error).message) }
      }}>保存文字并识别</Button></Space>
      {error && <Alert type="error" showIcon title={error} />}
    </section>}
    <section className="panel stack" aria-label="沟通纪要">
      <div className="document-toolbar"><h2>沟通纪要</h2>{minutes && <Button size="small" onClick={() => {
        const source = minutes.source === 'real' ? '真实模型提取' : minutes.source === 'mock' ? '模拟产物' : '人工产物'
        download(new Blob([`沟通纪要\n来源：${source}\n生成时间：${minutes.createdAt}\n依据：${minutes.artifactRef.artifact_id} v${minutes.artifactRef.version}\n继承来源：${minutes.inheritedSources.join(', ')}\n\n${minutes.text}`], { type: 'text/plain;charset=utf-8' }), '沟通纪要.txt')
      }}>下载纪要</Button>}</div>
      {minutes ? <><span className="muted small">{new Date(minutes.createdAt).toLocaleString('zh-CN')}</span><p className="document-content">{minutes.source === 'mock' ? previewText(minutes.text) : minutes.text}</p></> : <span className="muted">{job.generation?.state === 'failed' ? '识别未完成，尚无沟通纪要' : material?.audio && !current ? '录音待转写，尚无沟通纪要' : ['queued', 'running'].includes(job.generation?.state ?? '') ? '正在提取沟通要点…' : '文字识别后保存沟通纪要'}</span>}
    </section>
  </div>
}
