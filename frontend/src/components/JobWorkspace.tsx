import { Button, Empty, Table, Tabs, Tag } from 'antd'
import type { Candidate, Job } from '../domain/workspace'
import { previewText } from '../domain/presentation'
import { areJobDocumentsConfirmed } from '../domain/jobDocuments'
import JobDocuments from './JobDocuments'
import type { IntakeSession } from '../api/jobIntake'
import { RoutedJobCandidates } from './TalentPool'
import { Icon, PageHeading, Person } from './ui'
import { candidateProgress } from '../domain/candidateProgress'
import CandidateProgressTag from './CandidateProgressTag'
import { useJobGeneration } from '../hooks/useJobGeneration'
import RulePublication from './RulePublication'

export default function JobWorkspace({ session, job, candidates, onUpdate, onCandidate, onImport, onBack, backLabel = '返回岗位列表', activeTab = 'documents', onTabChange, active = true }: {
  session?: IntakeSession | null; job: Job; candidates: Candidate[]; onUpdate: (job: Job) => void; onCandidate: (id: string, section?: 'summary' | 'call' | 'reports') => void; onImport: () => void; onBack: () => void; backLabel?: string; activeTab?: string; onTabChange?: (key: string) => void; active?: boolean;
}) {
  // Keep one controller per job mounted while navigating within the workspace.
  const generation = useJobGeneration(job, onUpdate)
  const visibleCandidates = candidates.flatMap(candidate => {
    const progress = candidateProgress(candidate)
    return progress ? [{ candidate, progress }] : []
  })
  if (!active) return null
  return <>
    <Button className="back-button" type="text" icon={<Icon name="back" size={16} />} onClick={onBack}>{backLabel}</Button>
    <PageHeading title={job.title} titleExtra={!areJobDocumentsConfirmed(job) && <Tag className="job-confirmation-reminder" color="orange" icon={<Icon name="clock" size={12} />}>岗位产物待确认</Tag>} description={`${job.source === 'mock' ? previewText(job.company) : job.company} · ${job.location || '地点待确认'}`} actions={<Button type="primary" icon={<Icon name="upload" size={16} />} onClick={onImport}>导入简历</Button>} />
    <Tabs className="workspace-tabs" activeKey={activeTab === 'candidates' ? 'candidates' : 'documents'} onChange={onTabChange} items={[
      { key: 'documents', label: '岗位产物', children: <><JobDocuments job={job} onUpdate={onUpdate} generation={generation} />{session && <RulePublication job={job} session={session} />}</> },
      { key: 'candidates', label: session ? '候选人' : `候选人 (${visibleCandidates.length})`, children: session ? (job.generation?.remoteJobId ? <RoutedJobCandidates jobId={job.generation.remoteJobId} session={session} /> : <Empty description="请先完成岗位分析，再设置岗位方向。" />) : <section className="panel"><Table rowKey={row => row.candidate.id} dataSource={visibleCandidates} pagination={{ pageSize: 8 }} scroll={{ x: 600 }} columns={[
        { title: '候选人', render: (_, { candidate: c }, i) => <button className="person-link" onClick={() => onCandidate(c.id)}><Person name={c.name} detail={c.source === 'mock' ? previewText(c.role) : c.role} index={i} /></button> },
        { title: '状态', render: (_, row) => <CandidateProgressTag progress={row.progress} /> },
        { title: '操作', render: (_, { candidate: c, progress }) => <Button type="link" onClick={() => onCandidate(c.id, progress === 'report_review' ? 'reports' : progress === 'phone' ? 'call' : 'summary')}>{progress === 'report_review' ? '查看与审核' : progress === 'phone' ? '查看沟通' : '查看详情'}</Button> },
      ]} /></section> },
    ]} />
  </>
}
