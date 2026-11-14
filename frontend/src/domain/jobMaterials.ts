import type { Job } from './workspace'
import type { RemoteArtifactInput } from './jobDocuments'

const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}

// Keep a separate snapshot of the model's extracted communication points. Later
// edits to D01 must not rewrite the record of what the model originally returned.
export function retainCommunicationMinutes(job: Job, artifact: RemoteArtifactInput): Job {
  if (artifact.type !== 'D01' || artifact.status !== 'valid' || !job.materialInput) return job
  if (job.materialInput.minutes?.some(item => item.artifactRef.artifact_id === artifact.artifact_id && item.artifactRef.version === artifact.version)) return job
  const fields = record(record(artifact.structured_content.job_form).fields)
  const lines = Object.entries(fields).flatMap(([label, value]) => {
    const fact = record(value)
    if (fact.status === 'stated' && (typeof fact.value === 'string' && fact.value.trim() || typeof fact.value === 'number')) return [`${label}：${fact.value}`]
    if (fact.status === 'conflict') return [`${label}：存在冲突，待确认`]
    return []
  })
  const unknowns = artifact.unknowns.filter(value => value.trim())
  if (!lines.length && !unknowns.length) return job
  const text = ['沟通要点', ...lines, ...(unknowns.length ? ['', '待核实事项', ...unknowns.map(value => `· ${value}`)] : [])].join('\n')
  const source = artifact.provenance.source_mode === 'live' ? 'real' : artifact.provenance.source_mode
  return {
    ...job,
    materialInput: {
      ...job.materialInput,
      minutes: [...(job.materialInput.minutes ?? []), {
        text, createdAt: artifact.generated_at, source,
        inheritedSources: artifact.provenance.inherited_source_modes.map(value => value === 'live' ? 'real' : value),
        artifactRef: { artifact_id: artifact.artifact_id, version: artifact.version },
        inputText: job.materialInput.transcript,
      }],
    },
  }
}

export function saveMaterialText(job: Job, text: string): Job {
  if (job.generation?.submitted || job.generation?.remoteJobId || job.documents?.length) throw new Error('材料已提交识别，不能覆盖原始记录。')
  if (!text.trim() || text.length > 30000 || text.includes('\0')) throw new Error('请填写不超过 30,000 字的文字记录。')
  return {
    ...job, material: text.trim(), updatedAt: new Date().toISOString(),
    materialInput: {
      ...job.materialInput, kind: job.materialInput?.kind ?? 'transcript',
      originalText: job.materialInput?.originalText ?? job.materialInput?.transcript ?? job.material,
      transcript: text.trim(),
    },
    generation: { ...job.generation, createKey: job.generation?.createKey ?? crypto.randomUUID(), analyzeKey: job.generation?.analyzeKey ?? crypto.randomUUID(), state: 'not_started', error: undefined },
  }
}
