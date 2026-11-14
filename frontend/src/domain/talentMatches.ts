import type { Candidate, Job } from './workspace'
import type { Talent } from '../api/talentPool'

export interface MatchedJob { id: string; title: string }

export function talentMatchedJobs(talent: Pick<Talent, 'applications'>): MatchedJob[] {
  // The server owns initial routing. A later screening result does not change
  // which jobs appear here, and jobs with the same title remain distinct.
  return [...new Map(talent.applications.map(link => [link.job_id, { id: link.job_id, title: link.job_title }])).values()]
}

export function candidateMatchedJobs(candidate: Pick<Candidate, 'matchedJobIds'>, jobs: Pick<Job, 'id' | 'title'>[]): MatchedJob[] {
  return [...new Set(candidate.matchedJobIds ?? [])].map(id => ({ id, title: jobs.find(job => job.id === id)?.title ?? '岗位信息待更新' }))
}
