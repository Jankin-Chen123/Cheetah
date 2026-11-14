import { test } from 'node:test'
import assert from 'node:assert/strict'
import { candidateMatchedJobs, talentMatchedJobs } from '../src/domain/talentMatches.ts'

test('适配岗位保留初步关联的多个岗位，不按后续初筛结果删选，同名不同ID仍为两个岗位', () => {
  const jobs = talentMatchedJobs({ applications: [
    { job_id: 'job-a', job_title: '后端工程师', stage: 'matched', screening_result: 'pending' },
    { job_id: 'job-b', job_title: '后端工程师', stage: 'screened', screening_result: 'rejected' },
    { job_id: 'job-c', job_title: '全栈工程师', stage: 'researching', screening_result: 'unknown' },
    { job_id: 'job-a', job_title: '后端工程师', stage: 'matched', screening_result: 'pending' },
  ] })
  assert.deepEqual(jobs.map(job => job.id), ['job-a', 'job-b', 'job-c'])
  assert.equal(jobs[0].title, jobs[1].title)
})

test('预览使用单独的初步匹配列表，不能拿下游岗位关联冒充匹配结果', () => {
  const jobs = [{ id: 'bound-job', title: '当前流程岗位' }, { id: 'match-a', title: '初配甲' }, { id: 'match-b', title: '初配乙' }]
  assert.deepEqual(candidateMatchedJobs({ jobId: 'bound-job', matchedJobIds: ['match-a', 'match-b'] }, jobs), [
    { id: 'match-a', title: '初配甲' }, { id: 'match-b', title: '初配乙' },
  ])
  assert.deepEqual(candidateMatchedJobs({ jobId: 'bound-job' }, jobs), [])
})

test('没有匹配结果可显示空列表，岗位名称尚不可读时保留关联ID', () => {
  assert.deepEqual(talentMatchedJobs({ applications: [] }), [])
  assert.deepEqual(candidateMatchedJobs({ matchedJobIds: ['missing', 'missing'] }, []), [{ id: 'missing', title: '岗位信息待更新' }])
})
