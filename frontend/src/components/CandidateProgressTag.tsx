import { Tag } from 'antd'
import { candidateProgressLabels, type CandidateProgress } from '../domain/candidateProgress'

export default function CandidateProgressTag({ progress }: { progress: CandidateProgress }) {
  return <Tag color={{ analysis: 'blue', phone: 'green', report_review: 'orange' }[progress]}>{candidateProgressLabels[progress]}</Tag>
}
