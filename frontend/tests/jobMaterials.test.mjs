import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Blob } from 'node:buffer'
import { TextEncoder } from 'node:util'
import { createMaterialJob, attachGeneratedDocument, documentFromArtifact, saveDocumentRevision, currentDocument } from '../src/domain/jobDocuments.ts'
import { retainCommunicationMinutes, saveMaterialText } from '../src/domain/jobMaterials.ts'

const artifact = () => ({
  artifact_id: 'fixture-material-d01', type: 'D01', version: 1, status: 'valid',
  generated_at: '2026-11-14T10:00:00Z', provenance: { source_mode: 'live', inherited_source_modes: ['manual'] },
  structured_content: { job_form: { fields: {
    岗位名称: { status: 'stated', value: '测试工程师' },
    薪资: { status: 'conflict', value: '不应采用的冲突数值' },
    学历: { status: 'unknown', value: '不能当作事实' },
  } } }, unknowns: ['薪酬待确认'],
})

test('原文字与上传原件逐字节保留，识别用文字可修正，刷新序列化不丢录音和TXT', async () => {
  const raw = '  测试原文\r\n第二行  '
  const bytes = new TextEncoder().encode(`\uFEFF${raw}`)
  const textFile = { name: '原文.txt', type: 'text/plain', size: bytes.length, blob: new Blob([bytes]) }
  const audio = { name: '录音.wav', type: 'audio/wav', size: 4, blob: new Blob([new Uint8Array([0, 1, 2, 255])]) }
  const job = createMaterialJob({ kind: 'audio', transcript: raw, textFile, audio })
  const next = saveMaterialText(job, '修正的识别文字')
  const restored = globalThis.structuredClone(next)
  assert.equal(restored.materialInput.originalText, raw)
  assert.equal(restored.materialInput.transcript, '修正的识别文字')
  assert.equal(restored.materialInput.textFile.name, '原文.txt')
  assert.deepEqual(new Uint8Array(await restored.materialInput.textFile.blob.arrayBuffer()), bytes)
  assert.deepEqual(new Uint8Array(await restored.materialInput.audio.blob.arrayBuffer()), new Uint8Array([0, 1, 2, 255]))
  assert.equal(job.materialInput.transcript, raw.trim())
})

test('旧材料补充兼容，已提交或已有产物不能覆盖原记录', () => {
  const legacy = createMaterialJob({ kind: 'transcript', transcript: '旧材料' })
  delete legacy.materialInput.originalText
  assert.equal(saveMaterialText(legacy, '补充').materialInput.originalText, '旧材料')
  assert.throws(() => saveMaterialText({ ...legacy, generation: { ...legacy.generation, submitted: true } }, '改写'), /不能覆盖/)
  assert.throws(() => saveMaterialText(legacy, ' '), /文字记录/)
})

test('沟通纪要绑定模型产物版本与输入文字，保留未知和来源，并防止重复留存', () => {
  const original = createMaterialJob({ kind: 'audio', transcript: '人工提供的录音文字记录' })
  const next = retainCommunicationMinutes(original, artifact())
  const minutes = next.materialInput.minutes[0]
  assert.match(minutes.text, /岗位名称：测试工程师/)
  assert.match(minutes.text, /薪资：存在冲突，待确认/)
  assert.match(minutes.text, /薪酬待确认/)
  assert.doesNotMatch(minutes.text, /不应采用|不能当作事实/)
  assert.equal(minutes.source, 'real')
  assert.deepEqual(minutes.inheritedSources, ['manual'])
  assert.equal(minutes.inputText, original.materialInput.transcript)
  assert.equal(retainCommunicationMinutes(next, artifact()), next)
  const later = retainCommunicationMinutes(next, { ...artifact(), version: 2 })
  assert.equal(later.materialInput.minutes.length, 2)
  assert.equal(globalThis.structuredClone(later).materialInput.minutes[0].artifactRef.version, 1)
})

test('人工修改岗位画像不改写已留存纪要，失败的音频材料不产生虚假纪要', () => {
  const source = createMaterialJob({ kind: 'transcript', transcript: '测试文字' })
  const next = attachGeneratedDocument(retainCommunicationMinutes(source, artifact()), documentFromArtifact(artifact()))
  const profile = currentDocument(next, 'D01')
  const tables = globalThis.structuredClone(profile.tables)
  tables[0].rows.find(row => row.cells[0] === '岗位名称').cells[1] = '修改后的岗位'
  const edited = saveDocumentRevision(next, profile.id, tables, '测试修正')
  assert.match(edited.materialInput.minutes[0].text, /测试工程师/)
  assert.doesNotMatch(edited.materialInput.minutes[0].text, /修改后的岗位/)
  const waiting = createMaterialJob({ kind: 'audio', transcript: '', audio: { name: '录音.wav', type: 'audio/wav', size: 1, blob: new Blob(['a']) } })
  assert.equal(waiting.materialInput.minutes, undefined)
  assert.equal(retainCommunicationMinutes(waiting, { ...artifact(), status: 'expired' }), waiting)
  assert.equal(retainCommunicationMinutes(waiting, { ...artifact(), type: 'D02' }), waiting)
})

test('模拟模型结果保留模拟来源，不能升级为真实纪要', () => {
  const job = createMaterialJob({ kind: 'transcript', transcript: '测试' })
  const next = retainCommunicationMinutes(job, { ...artifact(), provenance: { source_mode: 'mock', inherited_source_modes: ['mock', 'manual'] } })
  assert.equal(next.materialInput.minutes[0].source, 'mock')
  assert.deepEqual(next.materialInput.minutes[0].inheritedSources, ['mock', 'manual'])
})
