export class TurnDetector {
  active = false
  muted = false
  private voicedFrames = 0
  private silence = 0
  private duration = 0
  private started = false
  private prebuffer: Uint8Array[] = []
  private callbacks: {
    start: (frames: Uint8Array[]) => void
    frame: (frame: Uint8Array) => void
    end: () => void
  }
  private sampleRate: number
  constructor(callbacks: TurnDetector['callbacks'], sampleRate = 16000) {
    this.callbacks = callbacks
    this.sampleRate = sampleRate
  }
  arm() {
    this.active = true; this.started = false; this.voicedFrames = 0
    this.silence = 0; this.duration = 0; this.prebuffer = []
  }
  disarm() { this.active = false; this.prebuffer = [] }
  feed(samples: Float32Array) {
    if (!this.active || this.muted) return
    const bytes = new Uint8Array(samples.length * 2)
    const view = new DataView(bytes.buffer)
    let sum = 0
    samples.forEach((sample, index) => {
      const value = Math.max(-1, Math.min(1, sample)); sum += value * value
      view.setInt16(index * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true)
    })
    const speaking = Math.sqrt(sum / samples.length) > 0.025
    if (!this.started) {
      this.prebuffer.push(bytes)
      if (this.prebuffer.length > 6) this.prebuffer.shift()
      this.voicedFrames = speaking ? this.voicedFrames + 1 : 0
      if (this.voicedFrames >= 3) {
        this.started = true; this.callbacks.start(this.prebuffer); this.prebuffer = []
      }
      return
    }
    this.callbacks.frame(bytes); this.duration += samples.length
    this.silence = speaking ? 0 : this.silence + samples.length
    if (this.silence >= this.sampleRate * 1.2 || this.duration >= this.sampleRate * 599) {
      this.disarm(); this.callbacks.end()
    }
  }
}

export async function createCallMicrophone(callbacks: ConstructorParameters<typeof TurnDetector>[0]) {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('请在本机 Chrome/Edge 或 HTTPS 页面使用麦克风。')
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false,
  })
  let context: AudioContext
  try { context = new AudioContext({ sampleRate: 16000 }); await context.resume() }
  catch (reason) { stream.getTracks().forEach(track => track.stop()); throw reason }
  if (context.sampleRate !== 16000) {
    stream.getTracks().forEach(track => track.stop()); await context.close()
    throw new Error('浏览器未提供16kHz采集，请使用最新版 Chrome 或 Edge。')
  }
  const detector = new TurnDetector(callbacks)
  const source = context.createMediaStreamSource(stream)
  const processor = context.createScriptProcessor(1024, 1, 1)
  processor.onaudioprocess = event => detector.feed(event.inputBuffer.getChannelData(0))
  source.connect(processor); processor.connect(context.destination)
  let closed = false
  return {
    arm: () => detector.arm(),
    disarm: () => detector.disarm(),
    setMuted: (value: boolean) => { detector.muted = value; stream.getAudioTracks().forEach(track => { track.enabled = !value }) },
    close: async () => {
      if (closed) return
      closed = true; detector.disarm(); processor.disconnect(); source.disconnect()
      stream.getTracks().forEach(track => track.stop()); await context.close()
    },
  }
}
