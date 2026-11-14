import { Select } from 'antd'

export default function CandidateJobFilter({ value, options, onChange }: {
  value?: string; options: { value: string; label: string }[]; onChange: (jobId: string) => void;
}) {
  return <section className="panel candidate-job-filter"><span>筛选岗位</span><Select aria-label="筛选岗位" value={value} onChange={onChange} options={options} placeholder="选择岗位" showSearch optionFilterProp="label" disabled={!options.length} /></section>
}
