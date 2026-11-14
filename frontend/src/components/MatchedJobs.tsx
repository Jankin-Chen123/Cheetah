import type { MatchedJob } from '../domain/talentMatches'

export default function MatchedJobs({ jobs, emptyText = '暂无适配岗位' }: { jobs: MatchedJob[]; emptyText?: string }) {
  return jobs.length ? <ul className="matched-job-list" aria-label="适配岗位">{jobs.map(job => <li key={job.id}>{job.title}</li>)}</ul> : <span className="muted">{emptyText}</span>
}
