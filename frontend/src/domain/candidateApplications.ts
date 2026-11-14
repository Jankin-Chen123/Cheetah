import type { Candidate, CandidateApplication, Job } from './workspace'

export function candidateJobIds(candidate: Candidate): string[] {
  return [...new Set([candidate.jobId, ...(candidate.matchedJobIds ?? []), ...(candidate.applications ?? []).map(application => application.jobId)])]
}

export function candidateJobOptions(candidate: Candidate, jobs: Job[]) {
  return candidateJobIds(candidate).map(id => {
    const job = jobs.find(item => item.id === id)
    return { value: id, label: job ? `${job.title} · ${job.company}` : `岗位信息待更新（${id}）` }
  })
}

export function candidateForJob(candidate: Candidate, jobId: string): Candidate | undefined {
  if (candidate.jobId === jobId) return candidate
  const application = candidate.applications?.find(item => item.jobId === jobId)
  return application ? { ...candidate, ...applicationData(application) } : undefined
}

export function candidateApplicationViews(candidate: Candidate): Candidate[] {
  return candidateJobIds(candidate).flatMap(jobId => {
    const view = candidateForJob(candidate, jobId)
    return view ? [view] : []
  })
}

function applicationData(candidate: CandidateApplication): CandidateApplication {
  const { jobId, screening, ruleVersion, source, gaps, artifacts, evidence, call, evaluation, reports, timeline } = candidate
  return { jobId, screening, ruleVersion, source, gaps, artifacts, evidence, call, evaluation, reports, timeline }
}

export function updateCandidateApplication(candidate: Candidate, updated: Candidate): Candidate {
  if (candidate.id !== updated.id) throw new Error('候选人已变化，请重新打开。')
  if (updated.jobId === candidate.jobId) return { ...candidate, ...applicationData(updated) }
  if (!candidate.applications?.some(item => item.jobId === updated.jobId)) throw new Error('此岗位尚无流程记录，不能修改其他岗位的数据。')
  return { ...candidate, applications: candidate.applications.map(item => item.jobId === updated.jobId ? applicationData(updated) : item) }
}
