import { test } from 'node:test'
import assert from 'node:assert/strict'
import { candidateApplicationViews, candidateForJob, candidateJobIds, candidateJobOptions, updateCandidateApplication } from '../src/domain/candidateApplications.ts'
import { reviewReport, requestStop, reportMarkdown } from '../src/domain/workspace.ts'

function fixture() {
  const application = jobId => ({
    jobId, screening: 'passed', ruleVersion: 1, source: 'mock', gaps: [`${jobId}待核实`], evidence: [], timeline: [],
    call: { id: `${jobId}-call`, state: 'active', reason: `${jobId}通话`, attempts: 1 }, evaluation: 'recommended',
    reports: [{ id: `${jobId}-report`, version: 1, state: 'pending', content: `${jobId}推荐`, exports: 0 }],
    artifacts: [{ id: `${jobId}-d10`, type: 'D10', version: 1, status: 'valid', content: `${jobId}推荐` }],
  })
  return { id: 'person-a', name: '虚构人才', ...application('job-a'), matchedJobIds: ['job-a', 'job-b', 'job-empty'], applications: [application('job-b')] }
}

test('同一人才的多岗位记录按岗位ID选择，同名岗位不合并，未生成内容不回退到其他岗位', () => {
  const person = fixture()
  const jobs = ['job-a', 'job-b', 'job-empty'].map(id => ({ id, title: '同名岗位', company: '同名企业' }))
  assert.deepEqual(candidateJobIds(person), ['job-a', 'job-b', 'job-empty'])
  assert.deepEqual(candidateJobOptions(person, jobs).map(option => option.value), ['job-a', 'job-b', 'job-empty'])
  assert.equal(candidateForJob(person, 'job-b').reports[0].content, 'job-b推荐')
  assert.equal(candidateForJob(person, 'job-empty'), undefined)
  assert.equal(candidateForJob(person, 'unrelated'), undefined)
  assert.deepEqual(candidateApplicationViews(person).map(view => view.jobId), ['job-a', 'job-b'])
})

test('第二岗位无电话或评估时，不继承默认岗位的可选状态', () => {
  const person = fixture()
  delete person.applications[0].call
  delete person.applications[0].evaluation
  const view = candidateForJob(person, 'job-b')
  assert.equal(view.call, undefined)
  assert.equal(view.evaluation, undefined)
})

test('同版本报告审批只更新所选岗位，保留另一岗位和人才身份', () => {
  const person = fixture()
  const updated = reviewReport(candidateForJob(person, 'job-b'), 1, 'approve', '仅批准乙岗位')
  const next = updateCandidateApplication(person, updated)
  assert.equal(next.jobId, 'job-a')
  assert.equal(next.reports[0].state, 'pending')
  assert.equal(next.applications[0].reports[0].state, 'approved')
  assert.deepEqual(next.matchedJobIds, person.matchedJobIds)
  assert.equal(person.applications[0].reports[0].state, 'pending')
  const primary = updateCandidateApplication(next, reviewReport(next, 1, 'reject', '仅退回甲岗位'))
  assert.equal(primary.reports[0].state, 'rejected')
  assert.equal(primary.applications[0].reports[0].state, 'approved')
})

test('停止与下载计数只更新所选岗位，停止仍须等待确认', () => {
  const person = fixture()
  const stopped = updateCandidateApplication(person, requestStop(candidateForJob(person, 'job-b')))
  assert.equal(stopped.call.state, 'active')
  assert.equal(stopped.applications[0].call.state, 'stopping')
  const selected = candidateForJob(stopped, 'job-b')
  const exported = updateCandidateApplication(stopped, { ...selected, reports: selected.reports.map(report => ({ ...report, exports: report.exports + 1 })) })
  assert.equal(exported.reports[0].exports, 0)
  assert.equal(exported.applications[0].reports[0].exports, 1)
})

test('不允许给无记录的匹配岗位或其他候选人误写流程结果', () => {
  const person = fixture()
  assert.throws(() => updateCandidateApplication(person, { ...person, jobId: 'job-empty' }), /尚无流程记录/)
  assert.throws(() => updateCandidateApplication(person, { ...person, id: 'person-b' }), /候选人已变化/)
})

test('推荐导出校验所选岗位，不能把甲岗位批准内容导出成乙岗位报告', () => {
  const approved = reviewReport(fixture(), 1, 'approve', '确认甲岗位')
  assert.throws(() => reportMarkdown(approved, approved.reports[0], { id: 'job-b', title: '乙岗位' }), /所选岗位不一致/)
  const markdown = reportMarkdown(approved, approved.reports[0], { id: 'job-a', title: '甲岗位' })
  assert.match(markdown, /甲岗位/)
  assert.match(markdown, /job-a推荐/)
  assert.doesNotMatch(markdown, /job-b推荐/)
})
