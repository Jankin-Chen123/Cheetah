import type { Candidate } from './workspace'
import type { components } from '../api/generated'

export type CandidateProgress = 'analysis' | 'phone' | 'report_review'
export const candidateProgressLabels: Record<CandidateProgress, string> = {
  analysis: '简历分析', phone: '电话沟通', report_review: '推荐报告待审核',
}

// null removes a person from the job's active queue, without deleting their
// talent record, application, evidence, or versioned report history.
export function candidateProgress(candidate: Candidate): CandidateProgress | null {
  if (candidate.screening === 'rejected') return null
  if (candidate.screening !== 'passed') return 'analysis'
  const report = candidate.reports.at(-1)
  const artifact = candidate.artifacts.filter(item => item.type === 'D10').at(-1)
  const ready = candidate.call?.state === 'completed' && candidate.evaluation === 'recommended' &&
    report && artifact?.status === 'valid' && artifact.version === report.version &&
    !!report.content.trim() && artifact.content === report.content
  if (ready && ['approved', 'rejected'].includes(report.state) && report.reviewReason?.trim()) return null
  if (ready && report.state === 'pending') return 'report_review'
  return 'phone'
}

type Application = components['schemas']['ApplicationSummary']
type Artifact = components['schemas']['Artifact']

export function currentRecommendationArtifact(app: Application, artifact?: Artifact): boolean {
  const report = app.report_summary
  return !!report && report.application_id === app.id && report.job_id === app.job_id &&
    artifact?.type === 'D10' && artifact.status === 'valid' && artifact.application_id === app.id && artifact.job_id === app.job_id &&
    artifact.artifact_id === report.artifact_ref.artifact_id && artifact.version === report.artifact_ref.version &&
    artifact.version === report.version && typeof artifact.structured_content.candidate_summary === 'string' && !!artifact.structured_content.candidate_summary.trim()
}

export function applicationProgress(app: Application, artifact?: Artifact): CandidateProgress | null {
  if (app.screening_result === 'rejected') return null
  if (app.screening_result !== 'passed') return 'analysis'
  const ready = app.call_summary?.status === 'ended' && app.evaluation_result === 'recommended' && currentRecommendationArtifact(app, artifact)
  if (ready && ['approved', 'rejected'].includes(app.report_summary!.status)) return null
  if (ready && app.report_summary?.status === 'pending_review') return 'report_review'
  return 'phone'
}
