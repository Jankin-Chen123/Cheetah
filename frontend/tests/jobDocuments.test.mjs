import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Blob } from 'node:buffer'
import { ANCHORS, JOB_GROUPS, areJobDocumentsConfirmed, attachGeneratedDocument, canExportJobDocument, confirmJobDocument, createMaterialJob, currentDocument, demoJobDocuments, documentFromArtifact, saveDocumentRevision } from '../src/domain/jobDocuments.ts'

function fixture(known = false) {
  const job = createMaterialJob({ kind: 'transcript', transcript: '虚构沟通记录' })
  if (known) { job.title = '后端工程师'; job.company = '示例企业' }
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

test('确认依次绑定当前画像和面试表，重复确认幂等，且不等同规则发布', () => {
  const job = fixture(true)
  assert.equal(areJobDocumentsConfirmed(job), false)
  assert.throws(() => confirmJobDocument(job, currentDocument(job, 'D02').id), /先确认岗位画像/)
  const profile = confirmJobDocument(job, currentDocument(job, 'D01').id)
  assert.equal(currentDocument(profile, 'D01').status, 'confirmed')
  assert.ok(currentDocument(profile, 'D01').confirmedAt)
  assert.equal(areJobDocumentsConfirmed(profile), false)
  assert.equal(confirmJobDocument(profile, currentDocument(profile, 'D01').id), profile)
  const both = confirmJobDocument(profile, currentDocument(profile, 'D02').id)
  assert.equal(areJobDocumentsConfirmed(both), true)
  assert.equal(both.status, 'draft')
  assert.equal(both.version, 0)
  assert.equal(canExportJobDocument(both, currentDocument(both, 'D02')), true)
  assert.equal(currentDocument(both, 'D01').source, 'mock')
})

test('画像修改撤销两份确认，过期内容不能确认，历史确认记录仍保留', () => {
  let job = fixture(true)
  job = confirmJobDocument(job, currentDocument(job, 'D01').id)
  job = confirmJobDocument(job, currentDocument(job, 'D02').id)
  const old = currentDocument(job, 'D01')
  const next = saveDocumentRevision(job, old.id, old.tables, '补充画像说明')
  assert.equal(areJobDocumentsConfirmed(next), false)
  assert.equal(currentDocument(next, 'D01').confirmedAt, undefined)
  assert.equal(currentDocument(next, 'D02').confirmedAt, undefined)
  assert.equal(currentDocument(next, 'D02').status, 'needs_review')
  assert.ok(next.documents.find(d => d.id === old.id).confirmedAt)
  assert.throws(() => confirmJobDocument(next, old.id), /内容已变化/)
  const checked = confirmJobDocument(next, currentDocument(next, 'D01').id)
  assert.equal(areJobDocumentsConfirmed(confirmJobDocument(checked, currentDocument(checked, 'D02').id)), true)
})

test('面试表修改只撤销自身确认，权重、评分空白及画像一致性均受校验', () => {
  let job = fixture(true)
  job = confirmJobDocument(job, currentDocument(job, 'D01').id)
  job = confirmJobDocument(job, currentDocument(job, 'D02').id)
  const original = currentDocument(job, 'D02')
  const next = saveDocumentRevision(job, original.id, original.tables, '优化面试说明')
  assert.equal(currentDocument(next, 'D01').status, 'confirmed')
  assert.equal(currentDocument(next, 'D02').status, 'draft')
  assert.equal(areJobDocumentsConfirmed(next), false)
  const invalid = globalThis.structuredClone(next)
  const interview = currentDocument(invalid, 'D02')
  const dimension = interview.tables.find(t => t.id === 'dimensions').rows[0]
  dimension.cells[2] = '20%'
  assert.throws(() => confirmJobDocument(invalid, interview.id), /100%/)
  dimension.cells[2] = '50%'; dimension.cells[4] = '8'
  assert.throws(() => confirmJobDocument(invalid, interview.id), /实际得分/)
  dimension.cells[4] = ''; dimension.cells[3] = '待补充'
  assert.throws(() => confirmJobDocument(invalid, interview.id), /五档/)
  dimension.cells[3] = original.tables.find(t => t.id === 'dimensions').rows[0].cells[3]
  interview.tables.find(t => t.id === 'context').rows[0].cells[1] = '另一企业'
  assert.throws(() => confirmJobDocument(invalid, interview.id), /不一致/)
})

test('未知与待识别名称不能被确认成完整岗位画像', () => {
  const job = fixture()
  assert.throws(() => confirmJobDocument(job, currentDocument(job, 'D01').id), /岗位名称和客户企业名称/)
})
