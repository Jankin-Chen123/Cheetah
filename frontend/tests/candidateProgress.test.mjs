import { test } from 'node:test'
import assert from 'node:assert/strict'
import { candidateProgress, applicationProgress } from '../src/domain/candidateProgress.ts'
import { reviewReport, reviseReport } from '../src/domain/workspace.ts'

function candidate() {
  return {
    screening: 'passed', call: { state: 'completed' }, evaluation: 'recommended',
    reports: [{ id: 'report', version: 1, state: 'pending', content: '推荐内容', exports: 0 }],
    artifacts: [{ id: 'd10', type: 'D10', version: 1, status: 'valid', content: '推荐内容', source: 'mock', upstreamSources: ['mock'], inputRefs: [] }], timeline: [],
  }
}

test('岗位状态仅三种，未知和待复核仍为简历分析，明确初筛失败才移出', () => {
  for (const screening of ['pending', 'unknown', 'manual_review']) assert.equal(candidateProgress({ ...candidate(), screening }), 'analysis')
  assert.equal(candidateProgress({ ...candidate(), screening: 'rejected' }), null)
})

test('初筛通过后，等待、失败、停止、结果不明和已结束但未产出报告都属于电话沟通', () => {
  for (const state of ['waiting', 'active', 'stopping', 'unknown', 'cancelled', 'completed']) {
    assert.equal(candidateProgress({ ...candidate(), call: { state }, reports: [], artifacts: [] }), 'phone')
  }
  assert.equal(candidateProgress({ ...candidate(), call: undefined, reports: [], artifacts: [] }), 'phone')
})

test('必须已有当前有效且非空的D10内容，通话结束且内部评估允许推荐，才进入待审核', () => {
  assert.equal(candidateProgress(candidate()), 'report_review')
  for (const change of [
    { artifacts: [] }, { artifacts: [{ ...candidate().artifacts[0], status: 'expired' }] },
    { reports: [{ ...candidate().reports[0], content: '' }] },
    { artifacts: [{ ...candidate().artifacts[0], content: '另一份内容' }] },
    { artifacts: [{ ...candidate().artifacts[0], version: 2 }] },
    { call: { state: 'active' } }, { evaluation: 'insufficient' }, { evaluation: 'rejected' },
  ]) assert.equal(candidateProgress({ ...candidate(), ...change }), 'phone')
})

test('确认当前版本审核后移出岗位队列，档案不删除，新修订版本重新进入队列', () => {
  for (const action of ['approve', 'reject']) {
    const original = candidate()
    const reviewed = reviewReport(original, 1, action, '已审核本版本')
    assert.equal(candidateProgress(reviewed), null)
    assert.equal(original.reports[0].state, 'pending')
    assert.equal(reviewed.artifacts.length, 1)
    const next = reviseReport(reviewed, 1, '新报告内容', '补充证据')
    assert.equal(candidateProgress(next), 'report_review')
    assert.equal(next.reports[0].state, 'expired')
    const invalid = { ...reviewed, artifacts: [{ ...reviewed.artifacts[0], status: 'expired' }] }
    assert.equal(candidateProgress(invalid), 'phone')
  }
})

function remote() {
  const app = { id: 'application-a', job_id: 'job-a', screening_result: 'passed', evaluation_result: 'recommended', call_summary: { status: 'ended' }, report_summary: {
    report_id: 'report', application_id: 'application-a', job_id: 'job-a', version: 1, status: 'pending_review', artifact_ref: { artifact_id: 'd10', version: 1 },
  } }
  const artifact = { artifact_id: 'd10', type: 'D10', version: 1, status: 'valid', job_id: 'job-a', application_id: 'application-a', structured_content: { candidate_summary: '推荐内容' } }
  return { app, artifact }
}

test('服务端阶段标签和报告摘要不代表生成成功，须读取匹配的具体D10版本', () => {
  const { app, artifact } = remote()
  assert.equal(applicationProgress(app), 'phone')
  assert.equal(applicationProgress(app, artifact), 'report_review')
  for (const change of [{ type: 'D09' }, { artifact_id: 'other' }, { version: 2 }, { status: 'expired' }, { status: 'restricted' }, { application_id: 'other' }, { job_id: 'other' }, { structured_content: { candidate_summary: '' } }]) {
    assert.equal(applicationProgress(app, { ...artifact, ...change }), 'phone')
  }
  assert.equal(applicationProgress({ ...app, report_summary: { ...app.report_summary, application_id: 'other' } }, artifact), 'phone')
  assert.equal(applicationProgress({ ...app, report_summary: { ...app.report_summary, status: 'draft' } }, artifact), 'phone')
})

test('服务端审批结果仅移出当前有效版本，电话失败与结果不明不得冒充审核中', () => {
  const { app, artifact } = remote()
  for (const status of ['approved', 'rejected']) {
    const reviewed = { ...app, report_summary: { ...app.report_summary, status } }
    assert.equal(applicationProgress(reviewed, artifact), null)
    assert.equal(applicationProgress(reviewed, { ...artifact, status: 'expired' }), 'phone')
  }
  for (const status of ['queued', 'waiting_conditions', 'scheduled', 'in_progress', 'awaiting_reschedule', 'reconciling', 'cancelled']) assert.equal(applicationProgress({ ...app, call_summary: { status } }, artifact), 'phone')
  assert.equal(applicationProgress({ ...app, screening_result: 'unknown' }, artifact), 'analysis')
  assert.equal(applicationProgress({ ...app, screening_result: 'rejected' }, artifact), null)
})
