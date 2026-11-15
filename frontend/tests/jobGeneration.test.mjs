import { test } from 'node:test'
import assert from 'node:assert/strict'
import { generationIssue } from '../src/domain/jobGeneration.ts'
import { createMaterialJob, jobCardState } from '../src/domain/jobDocuments.ts'

test('外部结果未知立即解除无限生成，并保留核对状态而不重发', () => {
  const issue = generationIssue([{ status: 'reconciling' }], 0)
  assert.equal(issue.state, 'reconciling')
  assert.match(issue.message, /不会重复提交/)
  const job = createMaterialJob({ kind: 'transcript', transcript: '虚构材料' })
  job.generation.state = issue.state
  assert.equal(jobCardState(job, true), 'reconciling')
})

test('无执行器的排队任务显示等待后台，实际运行与排队分别处理', () => {
  assert.equal(generationIssue([{ status: 'queued' }], 89_999), undefined)
  assert.equal(generationIssue([{ status: 'queued' }], 90_000).state, 'waiting_backend')
  assert.equal(generationIssue([{ status: 'waiting_conditions' }, { status: 'queued' }], 90_000).state, 'waiting_backend')
  assert.equal(generationIssue([{ status: 'queued' }, { status: 'running' }], 90_000), undefined)
  assert.equal(generationIssue([{ status: 'running' }], 600_000).state, 'waiting_backend')
})

test('已知失败给出实际原因，不能被排队状态覆盖', () => {
  const issue = generationIssue([{ status: 'queued' }, { status: 'failed', error: { code: 'MODEL_OUTPUT_TRUNCATED', message: '模型输出截断' } }], 90_000)
  assert.equal(issue.state, 'failed')
  assert.match(issue.message, /模型输出截断/)
})
