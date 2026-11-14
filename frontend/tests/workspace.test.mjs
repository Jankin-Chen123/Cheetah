import { test } from 'node:test'
import assert from 'node:assert/strict'
import { addImport, canExport, publishRules, reportMarkdown, requestStop, reviewReport, reviseReport } from '../src/domain/workspace.ts'

function fixture() {
  const report = { id: 'fixture-report', version: 1, state: 'pending', content: '模拟 D10，只有公开推荐内容。', exports: 0 }
  return {
    id: 'fixture-candidate', jobId: 'job', name: '虚构候选人', ruleVersion: 1, evaluation: 'recommended', gaps: ['个人贡献待核实'],
    reports: [report], timeline: [], call: { id: 'call-one', state: 'active', attempts: 1 },
    artifacts: [{ id: 'artifact-d10', type: 'D10', version: 1, status: 'valid', source: 'mock', upstreamSources: ['mock'], inputRefs: ['D09@v1'], content: report.content }],
  }
}
const job = { id: 'job', title: '虚构岗位', material: '原始虚构需求', rules: { screening: '测试初筛', interview: '测试面试', recommendation: '测试推荐' }, version: 1, status: 'published' }

test('未批准与已退回报告均阻止导出', () => {
  const candidate = fixture()
  assert.equal(canExport(candidate, candidate.reports[0]), false)
  assert.throws(() => reportMarkdown(candidate, candidate.reports[0], job), /批准/)
  const rejected = reviewReport(candidate, 1, 'reject', '证据需要补充')
  assert.equal(canExport(rejected, rejected.reports[0]), false)
})
test('批准绑定当前有效版本，并拒绝过期提交', () => {
  const candidate = fixture()
  assert.throws(() => reviewReport(candidate, 2, 'approve', '审核'), /版本/)
  const approved = reviewReport(candidate, 1, 'approve', '已核对模拟证据')
  assert.equal(canExport(approved, approved.reports[0]), true)
  assert.throws(() => reviewReport(approved, 1, 'approve', '重复提交'), /待审核/)
})
test('评估不足或未达标时，不能批准或导出 D10', () => {
  for (const evaluation of ['insufficient', 'rejected', undefined]) {
    const candidate = { ...fixture(), evaluation }
    assert.throws(() => reviewReport(candidate, 1, 'approve', '审核'), /推荐条件/)
    candidate.reports[0].state = 'approved'
    assert.equal(canExport(candidate, candidate.reports[0]), false)
  }
})
test('修订失效旧批准，新版本须重审，模拟来源与电话任务保留', () => {
  const approved = reviewReport(fixture(), 1, 'approve', '已核对')
  const stale = globalThis.structuredClone(approved.reports[0])
  const revised = reviseReport(approved, 1, '修订后的模拟报告', '更正职责范围')
  assert.equal(revised.reports[0].state, 'expired')
  assert.equal(revised.reports[1].state, 'pending')
  assert.equal(revised.reports[1].version, 2)
  assert.equal(revised.artifacts[0].status, 'expired')
  assert.equal(revised.artifacts[1].source, 'manual')
  assert.ok(revised.artifacts[1].upstreamSources.includes('mock'))
  assert.equal(canExport(revised, stale), false)
  assert.equal(canExport(revised, revised.reports[1]), false)
  assert.deepEqual(revised.call, approved.call)
  assert.throws(() => reviseReport(revised, 1, '旧版本内容', '旧版本提交'), /版本/)
})
test('当前报告失效时，即使保留批准对象也不能导出', () => {
  const approved = reviewReport(fixture(), 1, 'approve', '审核')
  const stale = globalThis.structuredClone(approved.reports[0])
  approved.reports[0].state = 'expired'
  assert.equal(canExport(approved, stale), false)
})
test('缺少有效产物或审核原因时阻止批准', () => {
  assert.throws(() => reviewReport(fixture(), 1, 'approve', '  '), /意见/)
  const candidate = fixture()
  candidate.artifacts[0].status = 'expired'
  assert.throws(() => reviewReport(candidate, 1, 'approve', '审核'), /有效/)
})
test('导出标明模拟、未知与版本，且不包含 D09 内部内容', () => {
  const candidate = reviewReport(fixture(), 1, 'approve', '核查完成')
  candidate.artifacts.push({ type: 'D09', content: '内部评分绝密标记' })
  const markdown = reportMarkdown(candidate, candidate.reports[0], job)
  assert.match(markdown, /模拟演示/)
  assert.match(markdown, /v1/)
  assert.match(markdown, /个人贡献待核实/)
  assert.match(markdown, /未发送给 HR/)
  assert.doesNotMatch(markdown, /内部评分绝密标记/)
})
test('进行中停止请求保持等待确认，不提前显示结束，也不新增尝试', () => {
  const candidate = fixture()
  const stopped = requestStop(candidate)
  assert.equal(stopped.call.state, 'stopping')
  assert.equal(stopped.call.id, candidate.call.id)
  assert.equal(stopped.call.attempts, 1)
  assert.equal(candidate.call.state, 'active')
  assert.throws(() => requestStop(stopped), /不允许/)
})
test('结果不明不得停止或重拨；排队可取消且不新增尝试', () => {
  const candidate = fixture()
  candidate.call.state = 'unknown'
  assert.throws(() => requestStop(candidate), /先核对/)
  candidate.call.state = 'waiting'
  candidate.call.attempts = 0
  const cancelled = requestStop(candidate)
  assert.equal(cancelled.call.state, 'cancelled')
  assert.equal(cancelled.call.attempts, 0)
})
test('规则发布要求独立标准与原始材料，产生新版本而不原地修改', () => {
  for (const key of ['screening', 'interview', 'recommendation']) assert.throws(() => publishRules(job, { ...job.rules, [key]: '' }), /分别填写/)
  assert.throws(() => publishRules({ ...job, material: '' }, job.rules), /原始需求/)
  const published = publishRules(job, { ...job.rules, screening: '新初筛规则' })
  assert.equal(published.version, 2)
  assert.equal(job.version, 1)
  assert.equal(job.rules.screening, '测试初筛')
  assert.equal(published.ruleHistory[0].rules.screening, '测试初筛')
  assert.equal(published.ruleHistory[1].rules.screening, '新初筛规则')
})
test('同岗位同内容改名导入被阻止，其他岗位可独立暂存', () => {
  const record = { id: 'import-1', jobId: 'job-1', name: 'original.txt', fingerprint: 'same-content-hash', state: 'waiting' }
  assert.throws(() => addImport([record], { ...record, id: 'import-2', name: 'renamed.txt' }), /内容相同/)
  assert.equal(addImport([record], { ...record, jobId: 'job-2' }).length, 2)
})
test('失败材料的替换不阻塞其他已暂存材料', () => {
  const failed = { id: 'failed', jobId: 'job-1', fingerprint: 'same', state: 'failed' }
  const valid = { ...failed, id: 'valid', state: 'waiting' }
  assert.equal(addImport([failed], valid).length, 2)
  assert.equal(failed.state, 'failed')
})
