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

test('career write errors preserve the server conflict code for draft recovery', async () => {
  const { confirmCareerField, OutreachError } = await import('../src/api/outreach.ts')
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/v1/calls/case-1/career-confirmations')
    const body = JSON.parse(options.body)
    assert.equal(body.expected_revision, 4)
    assert.equal(body.minutes_version, 2)
    return globalThis.Response.json({ detail: 'VERSION_CONFLICT' }, { status: 409 })
  }
  await assert.rejects(confirmCareerField('case-1', {
    expected_revision: 4, minutes_id: 'minutes-2', minutes_version: 2,
    field_path: 'profile.current_city', value: '杭州', quote: '我在杭州',
    answer_id: 'answer-1', reason: '候选人原话', conflict_index: null,
  }), error => error instanceof OutreachError && error.status === 409 && error.code === 'VERSION_CONFLICT')
})
