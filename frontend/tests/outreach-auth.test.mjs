import test from 'node:test'
import assert from 'node:assert/strict'
import { api } from '../src/api/outreach.ts'

test('late unauthorized response cannot erase a newer login CSRF token', async () => {
  let finishOld
  let captured
  globalThis.fetch = async (url, options) => {
    if (url.endsWith('/old-request')) return new Promise(resolve => { finishOld = resolve })
    if (url.endsWith('/auth/login')) return globalThis.Response.json({ csrf_token: 'new-session-token' })
    captured = options.headers['X-CSRF-Token']
    return globalThis.Response.json({ ok: true })
  }
  const old = api('/old-request').catch(error => error)
  await api('/auth/login', { username: 'fixture', password: 'fixture' })
  finishOld(globalThis.Response.json({}, { status: 401 }))
  assert.match(String(await old), /401/)
  await api('/protected-command', {})
  assert.equal(captured, 'new-session-token')
})
