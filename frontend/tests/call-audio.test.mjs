import assert from 'node:assert/strict'
import test from 'node:test'
import { TurnDetector } from '../src/api/callAudio.ts'

test('keeps onset audio and finishes after 1.2 seconds of silence', () => {
  let starts = 0
  let ends = 0
  let initialFrames = 0
  const detector = new TurnDetector({
    start: frames => { starts++; initialFrames = frames.length },
    frame: () => {},
    end: () => { ends++ },
  })
  detector.arm()
  const speech = new Float32Array(1024).fill(0.1)
  const silence = new Float32Array(1024)
  detector.feed(silence)
  for (let index = 0; index < 3; index++) detector.feed(speech)
  assert.equal(starts, 1)
  assert.equal(initialFrames, 4)
  for (let index = 0; index < 18; index++) detector.feed(silence)
  assert.equal(ends, 0)
  detector.feed(silence)
  assert.equal(ends, 1)
  assert.equal(detector.active, false)
})

test('muted and disarmed microphone never starts a turn', () => {
  const detector = new TurnDetector({ start: () => assert.fail(), frame: () => assert.fail(), end: () => assert.fail() })
  const speech = new Float32Array(1024).fill(0.1)
  detector.arm()
  detector.muted = true
  for (let index = 0; index < 10; index++) detector.feed(speech)
  detector.muted = false
  detector.disarm()
  detector.feed(speech)
})
