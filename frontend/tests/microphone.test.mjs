import test from 'node:test'
import assert from 'node:assert/strict'
import { captureMicrophone } from '../src/api/microphone.ts'

test('automatic voice turns finish after speech and silence; mute and cancel release capture', async () => {
  let processor
  let stopped = false
  let closed = false
  const track = { enabled: true, stop() { stopped = true } }
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {
    mediaDevices: { async getUserMedia() { return { getTracks: () => [track], getAudioTracks: () => [track] } } },
  } })
  globalThis.AudioContext = class {
    sampleRate = 16000
    createMediaStreamSource() { return { connect() {}, disconnect() {} } }
    createScriptProcessor() { processor = { connect() {}, disconnect() {} }; return processor }
    async close() { closed = true }
  }
  let finished = 0
  let frames = 0
  const capture = await captureMicrophone(() => frames++, () => finished++, true)
  const feed = level => processor.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array(4096).fill(level) } })
  capture.setMuted(true)
  feed(0.1)
  assert.equal(track.enabled, false)
  assert.equal(frames, 0)
  capture.setMuted(false)
  feed(0.1); feed(0.1)
  for (let i = 0; i < 6; i++) feed(0)
  assert.equal(finished, 1)
  feed(0)
  assert.equal(finished, 1)
  const pcm = await capture.finish()
  assert.equal(pcm.length, 8 * 4096 * 2)
  assert.ok(stopped && closed)
  await capture.cancel()
})
