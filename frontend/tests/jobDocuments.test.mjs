import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Blob } from 'node:buffer'
import { ANCHORS, JOB_GROUPS, attachGeneratedDocument, canExportJobDocument, createMaterialJob, currentDocument, demoJobDocuments, documentFromArtifact, saveDocumentRevision } from '../src/domain/jobDocuments.ts'

function fixture() {
  const job = createMaterialJob({ kind: 'transcript', transcript: '虚构沟通记录' })
  job.documents = demoJobDocuments(job)
  return job
}

test('直接从材料建岗，不猜岗位和企业，录音没有文字则等待转写', () => {
  const job = createMaterialJob({ kind: 'transcript', transcript: '  虚构文本  ' })
  assert.equal(job.title, '待识别岗位')
  assert.equal(job.materialInput.transcript, '虚构文本')
  assert.equal(job.generation.state, 'not_started')
  assert.throws(() => createMaterialJob({ kind: 'transcript', transcript: ' ' }))
  const audio = createMaterialJob({ kind: 'audio', transcript: '', audio: { name: 'fixture.wav', blob: new Blob(['fixture']), size: 7, type: 'audio/wav' } })
  assert.equal(audio.generation.state, 'waiting_transcript')
})

test('标准表单保留38字段和JD三段；面试表为动态维度六列、五档锚点、实际分空白', () => {
  const job = fixture()
  const profile = currentDocument(job, 'D01')
  assert.equal(Object.values(JOB_GROUPS).flat().length, 38)
  assert.equal(profile.tables[0].rows.filter(row => !row.group).length, 41)
  const dimensions = currentDocument(job, 'D02').tables.find(t => t.id === 'dimensions')
  assert.equal(dimensions.headers.length, 6)
  assert.equal(dimensions.rows.length, 2)
  assert.ok(dimensions.rows.every(row => row.cells[4] === '' && row.cells[5] === '' && ANCHORS.every(a => row.cells[3].includes(a))))
})

test('画像更正保存新版本，旧版和受影响面试表禁止导出，模拟来源保留', () => {
  const job = fixture(); job.status = 'published'
  const old = currentDocument(job, 'D01')
  const tables = globalThis.structuredClone(old.tables)
  tables[0].rows.find(row => row.cells[0] === '岗位名称').cells[1] = '虚构新岗位'
  const next = saveDocumentRevision(job, old.id, tables, '修正岗位名称')
  assert.equal(next.title, '虚构新岗位')
  assert.equal(next.status, 'draft')
  assert.equal(currentDocument(next, 'D01').version, 2)
  assert.ok(currentDocument(next, 'D01').inheritedSources.includes('mock'))
  assert.equal(canExportJobDocument(next, old), false)
  assert.equal(currentDocument(next, 'D02').status, 'needs_review')
  assert.equal(canExportJobDocument(next, currentDocument(next, 'D02')), false)
  assert.throws(() => saveDocumentRevision(next, old.id, tables, '旧版并发修改'), /版本已变化/)
  const checked = saveDocumentRevision(next, currentDocument(next, 'D02').id, currentDocument(next, 'D02').tables, '已按画像逐项复核')
  assert.equal(canExportJobDocument(checked, currentDocument(checked, 'D02')), true)
})

test('面试维度编辑必须保留100%权重，不能预填实际分或删除全部维度', () => {
  const job = fixture(); const interview = currentDocument(job, 'D02')
  const tables = globalThis.structuredClone(interview.tables); const dimensions = tables.find(t => t.id === 'dimensions')
  dimensions.rows[0].cells[2] = '20%'
  assert.throws(() => saveDocumentRevision(job, interview.id, tables, '调整维度'), /100%/)
  dimensions.rows[0].cells[2] = '50%'; dimensions.rows[0].cells[4] = '8'
  assert.throws(() => saveDocumentRevision(job, interview.id, tables, '调整维度'), /实际得分/)
  dimensions.rows = []
  assert.throws(() => saveDocumentRevision(job, interview.id, tables, '移除'), /100%/)
  assert.throws(() => saveDocumentRevision(job, interview.id, interview.tables, ''), /原因/)
})

test('真实产物适配保留未知与冲突，live映射real，同一远程版本不重复落盘', () => {
  const artifact = { artifact_id: 'fixture-d01', type: 'D01', version: 1, generated_at: new Date().toISOString(), provenance: { source_mode: 'live', inherited_source_modes: ['manual'] }, unknowns: ['企业待核实'], structured_content: { job_form: { fields: { 岗位名称: { status: 'stated', value: '虚构工程师' }, 客户企业名称: { status: 'conflict' } }, jd: {} } } }
  const document = documentFromArtifact(artifact)
  assert.equal(document.source, 'real')
  assert.equal(document.tables[0].rows.find(row => row.cells[0] === '客户企业名称').cells[1], '待确认')
  const job = attachGeneratedDocument(fixture(), document)
  assert.equal(job.title, '虚构工程师')
  assert.equal(attachGeneratedDocument(job, document).documents.length, job.documents.length)
  const interview = documentFromArtifact({ ...artifact, type: 'D02', structured_content: { dimensions: [] } })
  assert.equal(interview.tables.find(t => t.id === 'dimensions').rows.length, 0)
})

test('面试表晚到时，已人工修订的画像仍使远程面试表待复核', () => {
  const job = fixture(); const profile = currentDocument(job, 'D01')
  const revised = saveDocumentRevision(job, profile.id, profile.tables, '补充核实说明')
  const remote = { ...currentDocument(job, 'D02'), id: 'remote-fixture', remoteRef: { artifact_id: 'remote-d02', version: 1 } }
  const next = attachGeneratedDocument(revised, remote)
  assert.equal(currentDocument(next, 'D02').status, 'needs_review')
  assert.equal(canExportJobDocument(next, currentDocument(next, 'D02')), false)
})
