import { useState } from 'react'
import { Alert, App, Button, Descriptions, Empty, Form, Input, Modal, Select, Space, Tag } from 'antd'
import type { Artifact, ArtifactType, Candidate, Evidence, Job, Report } from '../domain/workspace'
import { previewText } from '../domain/presentation'
import { artifactNames, callLabels, canExport, displayTime, now, reportLabels, reportMarkdown, requestStop, reviewReport, reviseReport } from '../domain/workspace'
import { Icon, PageHeading, ScreeningTag, SourceTag } from './ui'
import { candidateForJob, candidateJobOptions } from '../domain/candidateApplications'
import CandidateJobFilter from './CandidateJobFilter'


function ArtifactContent({ artifact, evidence, emptyTitle }: { artifact?: Artifact; evidence: Evidence[]; emptyTitle?: string }) {
  if (!artifact) return emptyTitle ? <section className="panel"><h2>{emptyTitle}</h2><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`暂无${emptyTitle}`} /></section> : null
  return <section className="panel focused-artifact"><div className="section-heading"><h2>{artifactNames[artifact.type]}</h2><Space><SourceTag source={artifact.source} />{artifact.upstreamSources.filter(source => source !== artifact.source).map(source => <SourceTag key={source} source={source} inherited />)}{artifact.status === 'expired' && <Tag color="red">已失效</Tag>}{artifact.type === 'D09' && <Tag>内部 · 不随推荐导出</Tag>}</Space></div>
    <div className="document-content">{artifact.source === 'mock' ? previewText(artifact.content) : artifact.content}</div>
    {!!artifact.unknowns.length && <div className="focused-unknowns"><h3>待核实</h3><ul className="unknown-list">{artifact.unknowns.map((value, index) => <li key={index}>{artifact.source === 'mock' ? previewText(value) : value}</li>)}</ul></div>}
    {!!artifact.evidenceIds.length && <details className="inline-evidence"><summary>来源依据</summary>{artifact.evidenceIds.map(id => { const item = evidence.find(value => value.id === id); return <div key={id}>{item ? <><strong>{item.source === 'mock' ? previewText(item.title) : item.title}</strong><blockquote>{item.source === 'mock' ? previewText(item.quote) : item.quote}</blockquote><span className="muted small">{item.source === 'mock' ? previewText(item.location) : item.location}</span></> : <span className="muted">来源暂不可用</span>}</div> })}</details>}
  </section>
}

export default function CandidateWorkspace({ candidate, jobs, jobId, onJobChange, onUpdate, onBack, section = 'summary', backLabel = '返回人才库' }: {
  candidate: Candidate; jobs: Job[]; jobId: string; onJobChange: (jobId: string) => void; onUpdate: (candidate: Candidate) => void; onBack: () => void; section?: string; backLabel?: string;
}) {
  const job = jobs.find(item => item.id === jobId)
  const selected = candidateForJob(candidate, jobId)
  const title = section === 'call' ? '电话沟通情况' : section === 'reports' ? '评估与推荐' : '基本信息'
  return <>
    <Button type="text" className="back-button" icon={<Icon name="back" size={16} />} onClick={onBack}>{backLabel}</Button>
    <PageHeading title={`${candidate.name} · ${title}`} description={job ? job.source === 'mock' ? previewText(job.title) : job.title : '岗位信息待更新'} actions={<SourceTag source={candidate.source} />} />
    {['call', 'reports'].includes(section) && <CandidateJobFilter value={jobId} onChange={onJobChange} options={candidateJobOptions(candidate, jobs).map(option => ({ ...option, label: candidate.source === 'mock' ? previewText(option.label) : option.label }))} />}
    {job && selected ? <CandidateDetails key={`${candidate.id}:${jobId}:${section}`} candidate={selected} job={job} onUpdate={onUpdate} section={section} /> : <section className="panel candidate-focused-content"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={!job ? '岗位信息暂不可用，请选择其他岗位。' : section === 'call' ? '此岗位暂无电话沟通记录' : section === 'reports' ? '此岗位暂无评估与推荐' : '此岗位暂无候选人流程记录'} /></section>}
  </>
}

function CandidateDetails({ candidate: c, job, onUpdate, section }: {
  candidate: Candidate; job: Job; onUpdate: (candidate: Candidate) => void; section: string;
}) {
  const { message, modal } = App.useApp()
  const [reportVersion, setReportVersion] = useState<number>()
  const [review, setReview] = useState<{ version: number; action: 'approve' | 'reject' }>()
  const [revision, setRevision] = useState<number>()
  const [form] = Form.useForm<{ reason: string; content: string }>()
  const latest = c.reports.at(-1)
  const report = c.reports.find(r => r.version === reportVersion) ?? latest
  const reportArtifact = c.artifacts.find(a => a.type === 'D10' && a.version === report?.version)
  const viewingLatest = report?.version === latest?.version
  const currentArtifact = (type: ArtifactType) => c.artifacts.filter(item => item.type === type).at(-1)

  function operate(action: () => Candidate, success: string) {
    try { onUpdate(action()); void message.success(success) }
    catch (error) { void message.error((error as Error).message) }
  }
  function stop() {
    modal.confirm({ title: c.call?.state === 'active' ? '请求停止通话？' : '取消排队任务？', content: c.call?.state === 'active' ? '停止请求后仍需等待确认。' : '确认取消排队任务？', okText: '确认', cancelText: '返回', onOk: () => operate(() => requestStop(c), '任务状态已更新。') })
  }
  function exportReport(r: Report) {
    try {
      const content = reportMarkdown(c, r, job)
      const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }))
      const link = document.createElement('a')
      link.href = url; link.download = `Cheetah_模拟推荐_${c.name}_${job.title}_v${r.version}.md`; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      onUpdate({ ...c, reports: c.reports.map(item => item.version === r.version ? { ...item, exports: item.exports + 1 } : item), timeline: [...c.timeline, { title: '发起演示报告下载', detail: `D10 v${r.version} · 仅本地下载请求，未向 HR 发送`, at: now() }] })
      void message.success('已发起下载')
    } catch (error) { void message.error((error as Error).message) }
  }
  const reportPanel = !currentArtifact('D09') && !report ? <section className="panel candidate-focused-content"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={c.screening === 'unknown' ? '信息不足，暂无评估或推荐' : c.screening === 'rejected' ? '初筛未达标，无推荐报告' : '等待访谈与内部评估'} /></section> : <div className="stack candidate-focused-content"><ArtifactContent artifact={currentArtifact('D09')} evidence={c.evidence} emptyTitle="内部评估" /><section className="panel">
    <div className="section-heading"><h2>企业 HR 推荐报告</h2>{report && c.reports.length > 1 && <Select aria-label="选择报告" value={report.version} onChange={setReportVersion} options={c.reports.map((r, index) => {
      const createdAt = c.artifacts.find(a => a.type === 'D10' && a.version === r.version)?.createdAt
      return { value: r.version, label: `${r.version === latest?.version ? '当前报告' : '历史报告'} · ${createdAt ? displayTime(createdAt) : `第 ${index + 1} 次保存`} · ${reportLabels[r.state]}` }
    })} />}</div>
    {report ? <><Space wrap><SourceTag source={reportArtifact?.source ?? 'mock'} />{reportArtifact?.upstreamSources.filter(s => s !== reportArtifact.source).map(s => <SourceTag key={s} source={s} inherited />)}<Tag color={report.state === 'approved' ? 'green' : report.state === 'expired' ? 'red' : 'orange'}>{reportLabels[report.state]}</Tag></Space><div className="report-document"><h2>{c.name} <span>推荐报告</span></h2><p className="muted">{job.title}</p><div className="document-content">{reportArtifact?.source === 'mock' ? previewText(report.content) : report.content}</div><h3>待核实事项</h3><ul className="unknown-list">{c.gaps.map(g => <li key={g}>{g}</li>)}</ul></div>
      {report.reviewReason && <Alert type="info" title="版本审核意见" description={report.reviewReason} />}
      <div className="report-actions"><Button disabled={!canExport(c, report)} type="primary" icon={<Icon name="file" size={16} />} onClick={() => exportReport(report)}>下载 Markdown</Button><span className="muted small">本版本下载请求 {report.exports} 次 · 无对外交付记录</span></div>
    </> : <Empty description={c.screening === 'unknown' ? '信息不足，暂无评估或推荐' : c.screening === 'rejected' ? '初筛未达标，无推荐报告' : '等待访谈与内部评估'} image={Empty.PRESENTED_IMAGE_SIMPLE} />}
  </section>{latest && <section className="panel report-review-panel"><h3>审核当前版本</h3><p className="muted">修订后旧批准失效，新版须重审。</p>
    {!viewingLatest && <Alert className="form-alert" type="info" title="历史版本不可审核或修订" />}
    <div className="report-review-actions"><Button type="primary" disabled={!viewingLatest || !latest || latest.state !== 'pending' || c.evaluation !== 'recommended'} onClick={() => { setReview({ version: latest!.version, action: 'approve' }); form.resetFields() }}>批准当前报告</Button><Button disabled={!viewingLatest || !latest || latest.state !== 'pending'} onClick={() => { setReview({ version: latest!.version, action: 'reject' }); form.resetFields() }}>退回并填写意见</Button><Button disabled={!viewingLatest || !latest || latest.state === 'expired'} onClick={() => { setRevision(latest!.version); form.setFieldsValue({ content: latest!.content, reason: '' }) }}>修订并生成新版本</Button></div>
  </section>}</div>

  return <>
    {section === 'reports' ? reportPanel : section === 'call' ? !c.call && !currentArtifact('D08') ? <section className="panel candidate-focused-content"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未达电话条件，暂无沟通记录" /></section> : <div className="stack candidate-focused-content">
      <section className="panel"><div className="section-heading"><h2>沟通状态</h2></div>{c.call ? <>
        <Space wrap><Tag color={c.call.state === 'active' ? 'green' : 'orange'}>{callLabels[c.call.state]}</Tag></Space><p className="call-reason">{c.source === 'mock' ? previewText(c.call.reason) : c.call.reason}</p>
        <Space wrap>{['waiting', 'active'].includes(c.call.state) && <Button danger onClick={stop}>{c.call.state === 'active' ? '请求停止' : '取消排队'}</Button>}{c.call.state === 'stopping' && <Button onClick={() => operate(() => ({ ...c, call: { ...c.call!, state: 'completed', reason: '已手动模拟适配器结束确认，无真实通话。' }, timeline: [...c.timeline, { title: '确认已结束', detail: '停止请求已确认，仅本地状态', at: now() }] }), '已确认结束。')}>确认已结束</Button>}{c.call.state === 'unknown' && <Tag color="orange">先核对外部状态 · 禁止重拨</Tag>}</Space>
      </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未达电话条件，暂无沟通任务" />}</section>
      <ArtifactContent artifact={currentArtifact('D08')} evidence={c.evidence} emptyTitle="沟通记录" />
      {currentArtifact('D07') && <details className="panel focused-secondary"><summary>沟通提纲</summary><div className="document-content">{currentArtifact('D07')!.source === 'mock' ? previewText(currentArtifact('D07')!.content) : currentArtifact('D07')!.content}</div></details>}
    </div> : <div className="stack candidate-focused-content">
      <section className="panel"><div className="section-heading"><h2>基本信息</h2><ScreeningTag value={c.screening} /></div><Descriptions column={{ xs: 1, sm: 2 }} items={[
        { key: 'role', label: '当前经历', children: c.source === 'mock' ? previewText(c.role) : c.role }, { key: 'experience', label: '工作经验', children: c.experience }, { key: 'education', label: '学历', children: c.education }, { key: 'job', label: '应聘岗位', children: job.title },
      ]} /><p className="body-large">{c.source === 'mock' ? previewText(c.summary) : c.summary}</p>{!!c.gaps.length && <><h3>待核实</h3><ul className="unknown-list">{c.gaps.map(gap => <li key={gap}>{gap}</li>)}</ul></>}</section>
      <ArtifactContent artifact={currentArtifact('D03')} evidence={c.evidence} />
      {currentArtifact('D06') && <details className="panel focused-secondary"><summary>初筛依据</summary><div className="document-content">{currentArtifact('D06')!.source === 'mock' ? previewText(currentArtifact('D06')!.content) : currentArtifact('D06')!.content}</div></details>}
      {currentArtifact('D04') && <details className="panel focused-secondary"><summary>公司与项目研究</summary><div className="document-content">{currentArtifact('D04')!.source === 'mock' ? previewText(currentArtifact('D04')!.content) : currentArtifact('D04')!.content}</div></details>}
    </div>}
    <Modal title={review ? `${review.action === 'approve' ? '批准' : '退回'}推荐报告` : '修订推荐报告'} open={!!review || !!revision} onCancel={() => { setReview(undefined); setRevision(undefined) }} footer={null} forceRender>
      <Form form={form} layout="vertical" onFinish={values => {
        try {
          if (review) onUpdate(reviewReport(c, review.version, review.action, values.reason))
          else if (revision) { onUpdate(reviseReport(c, revision, values.content, values.reason)); setReportVersion(undefined) }
          setReview(undefined); setRevision(undefined); void message.success('版本已更新。')
        } catch (error) { void message.error((error as Error).message) }
      }}>
        {revision && <><Alert className="form-alert" type="warning" title="新版本须重新审核。" /><Form.Item name="content" label="修订内容" rules={[{ required: true, whitespace: true, message: '请填写内容' }]}><Input.TextArea rows={10} maxLength={15000} /></Form.Item></>}
        <Form.Item name="reason" label={review ? '审核意见' : '修订原因'} rules={[{ required: true, whitespace: true, message: '请填写具体原因' }]}><Input.TextArea rows={3} maxLength={2000} placeholder="填写审核意见或修订原因" /></Form.Item><div className="modal-actions"><Button onClick={() => { setReview(undefined); setRevision(undefined) }}>取消</Button><Button type="primary" htmlType="submit">{revision ? '保存新版本 · 待重审' : '确认本版本审核'}</Button></div>
      </Form>
    </Modal>
  </>
}
