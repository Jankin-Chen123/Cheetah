// Browser microphone capture. Audio remains local until an explicit transport submits it.
export interface MicrophoneCapture {
  finish: () => Promise<Uint8Array>
  cancel: () => Promise<void>
  setMuted: (muted: boolean) => void
}

export async function captureMicrophone(onFrame?: (pcm: Uint8Array) => void, onLimit?: () => void, automatic = false): Promise<MicrophoneCapture> {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('当前浏览器无法访问麦克风，请使用 HTTPS 或本机地址。')
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true }, video: false })
  let context: AudioContext
  try { context = new AudioContext({ sampleRate: 16000 }) }
  catch (reason) { stream.getTracks().forEach(track => track.stop()); throw reason }
  if (onFrame && context.sampleRate !== 16000) {
    stream.getTracks().forEach(track => track.stop()); await context.close()
    throw new Error('当前浏览器不支持16kHz实时采集，请使用分段录音。')
  }
  const chunks: Float32Array[] = []
  const source = context.createMediaStreamSource(stream)
  // Bounded fallback for browsers without a bundled AudioWorklet module.
  const processor = context.createScriptProcessor(4096, 1, 1)
  const maxSeconds = automatic ? 600 : 10
  let muted = false
  let voiced = false
  let silence = 0
  let voiceSamples = 0
  let ending = false
  let samples = 0
  let closed = false
  processor.onaudioprocess = event => {
    if (closed || muted || ending || samples >= context.sampleRate * maxSeconds) return
    const input = event.inputBuffer.getChannelData(0)
    const chunk = input.slice(0, Math.min(input.length, context.sampleRate * maxSeconds - samples))
    chunks.push(chunk); samples += chunk.length
    if (automatic) {
      const rms = Math.sqrt(chunk.reduce((sum, value) => sum + value * value, 0) / chunk.length)
      if (rms > 0.018) { voiceSamples += chunk.length; voiced = voiceSamples > context.sampleRate * 0.25; silence = 0 }
      else if (voiced) silence += chunk.length
    }
    if (onFrame) {
      const bytes = new Uint8Array(chunk.length * 2)
      const view = new DataView(bytes.buffer)
      chunk.forEach((sample, index) => {
        const value = Math.max(-1, Math.min(1, sample))
        view.setInt16(index * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true)
      })
      onFrame(bytes)
    }
    if (automatic && voiced && silence > context.sampleRate * 1.5) {
      ending = true
      onLimit?.()
    }
  }
  source.connect(processor); processor.connect(context.destination)
  async function close() {
    if (closed) return
    closed = true
    processor.disconnect(); source.disconnect()
    stream.getTracks().forEach(track => track.stop())
    await context.close()
  }
  const timeout = setTimeout(() => { void close().then(() => onLimit?.()) }, maxSeconds * 1000)
  return {
    setMuted: (value: boolean) => { muted = value; stream.getAudioTracks().forEach(track => { track.enabled = !value }) },
    cancel: async () => { clearTimeout(timeout); await close(); chunks.length = 0 },
    finish: async () => {
      clearTimeout(timeout); await close()
      const input = new Float32Array(samples)
      let offset = 0
      for (const chunk of chunks) { input.set(chunk, offset); offset += chunk.length }
      const count = Math.floor(samples * 16000 / context.sampleRate)
      const bytes = new Uint8Array(count * 2)
      const view = new DataView(bytes.buffer)
      for (let i = 0; i < count; i++) {
        const position = i * context.sampleRate / 16000
        const left = Math.floor(position)
        const fraction = position - left
        const value = Math.max(-1, Math.min(1, (input[left] ?? 0) * (1 - fraction) + (input[left + 1] ?? 0) * fraction))
        view.setInt16(i * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true)
      }
      chunks.length = 0
      return bytes
    },
  }
}
