import { useEffect, useRef, useState } from 'react'
import { Alert, Button } from 'antd'

export default function CandidateCamera({ stopped }: { stopped: boolean }) {
  const [enabled, setEnabled] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const video = useRef<HTMLVideoElement>(null)
  const stream = useRef<MediaStream | null>(null)
  const generation = useRef(0)

  useEffect(() => {
    return () => {
      generation.current++
      stream.current?.getTracks().forEach(track => track.stop())
      stream.current = null
    }
  }, [])

  function close() {
    generation.current++
    stream.current?.getTracks().forEach(track => track.stop())
    stream.current = null
    if (video.current) video.current.srcObject = null
    setEnabled(false)
    setPending(false)
  }

  async function open() {
    const epoch = ++generation.current
    setPending(true)
    setError('')
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('当前环境无法访问摄像头，请使用 HTTPS 或 localhost 并检查浏览器支持。')
      const capture = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false })
      if (epoch !== generation.current) {
        capture.getTracks().forEach(track => track.stop())
        return
      }
      stream.current = capture
      capture.getVideoTracks().forEach(track => { track.onended = () => close() })
      if (video.current) video.current.srcObject = capture
      setEnabled(true)
    } catch (reason) {
      if (epoch !== generation.current) return
      const name = reason instanceof Error ? reason.name : ''
      setError(name === 'NotAllowedError' ? '摄像头权限未获允许，可在浏览器网站设置中修改；您仍可继续语音面试。' : name === 'NotFoundError' ? '未找到摄像头，您仍可继续语音面试。' : name === 'NotReadableError' ? '摄像头可能被其他程序占用，请关闭占用后重试。' : reason instanceof Error ? reason.message : '摄像头未能开启，请重试。')
    } finally {
      if (epoch === generation.current) setPending(false)
    }
  }

  return <div className="candidate-camera">
    <video ref={video} autoPlay muted playsInline hidden={!enabled} aria-label="候选人摄像头本地预览" style={{ width: '100%', maxHeight: 280, objectFit: 'contain', borderRadius: 12, transform: 'scaleX(-1)' }} />
    {error && <Alert type="info" showIcon message={error} />}
    <Button disabled={stopped} onClick={() => { if (enabled || pending) close(); else void open() }}>
      {pending ? '取消开启摄像头' : enabled ? '关闭摄像头' : '开启摄像头（可选）'}
    </Button>
    <p>摄像头默认关闭，仅在您点击后请求权限。画面仅供本地预览，不上传、不录制，也不用于 AI 评估；不开启不影响语音面试。</p>
  </div>
}
