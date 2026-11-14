import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createMaterialJob, demoJobDocuments, jobCardLabels, jobCardState } from '../src/domain/jobDocuments.ts'

test('生成任务从创建到两份表单齐备之前保持生成中，演示区不冒充已启动', () => {
  const job = createMaterialJob({ kind: 'transcript', transcript: '虚构招聘材料' })
  for (const state of ['not_started', 'queued', 'running']) {
    job.generation.state = state
    assert.equal(jobCardState(job, true), 'generating')
    assert.equal(jobCardState(job, false), 'unavailable')
  }
  job.documents = demoJobDocuments(job).filter(document => document.type === 'D01')
  assert.equal(jobCardState(job, true), 'generating')
  job.documents = demoJobDocuments(job)
  job.generation.state = 'completed'
  assert.equal(jobCardState(job, true), 'draft')
  job.documents[0].status = 'confirmed'
  assert.equal(jobCardState(job, true), 'draft')
  job.documents[1].status = 'confirmed'
  assert.equal(jobCardState(job, true), 'published')
  job.documents[1].status = 'needs_review'
  assert.equal(jobCardState(job, true), 'review')
})

test('失败和待转写可区分，卡片状态文案均不包含产物', () => {
  const job = createMaterialJob({ kind: 'transcript', transcript: '虚构招聘材料' })
  job.generation.state = 'failed'
  assert.equal(jobCardState(job, true), 'failed')
  job.generation.state = 'waiting_transcript'
  assert.equal(jobCardState(job, true), 'waiting_transcript')
  assert.ok(Object.values(jobCardLabels).every(label => !label.includes('产物')))
})
