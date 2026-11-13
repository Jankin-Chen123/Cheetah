import { useState } from 'react'
import { Alert, App, Button, Descriptions, Empty, Form, Input, Modal, Select, Space, Tabs, Tag, Timeline } from 'antd'
import type { Artifact, ArtifactType, Candidate, Job, Report } from '../domain/workspace'
import { artifactNames, callLabels, canExport, displayTime, now, reportLabels, reportMarkdown, requestStop, reviewReport, reviseReport } from '../domain/workspace'
import ArtifactViewer from './ArtifactViewer'
import { Icon, PageHeading, ScreeningTag, SourceTag } from './ui'

export default function CandidateWorkspace({ candidate: c, job, onUpdate, onBack, initialTab = 'overview' }: {
  candidate: Candidate; job: Job; onUpdate: (candidate: Candidate) => void; onBack: () => void; initialTab?: string;
}) {
  const { message, modal } = App.useApp()
  const [artifact, setArtifact] = useState<Artifact>()
  const [reportVersion, setReportVersion] = useState<number>()
  const [review, setReview] = useState<{ version: number; action: 'approve' | 'reject' }>()
  const [revision, setRevision] = useState<number>()
  const [form] = Form.useForm<{ reason: string; content: string }>()
  const latest = c.reports.at(-1)
  const report = c.reports.find(r => r.version === reportVersion) ?? latest
  const reportArtifact = c.artifacts.find(a => a.type === 'D10' && a.version === report?.version)
  const viewingLatest = report?.version === latest?.version
  const types: ArtifactType[] = ['D03', 'D04', 'D05', 'D06', 'D07', 'D08', 'D09', 'D10']

  function operate(action: () => Candidate, success: string) {
    try { onUpdate(action()); void message.success(success) }
    catch (error) { void message.error((error as Error).message) }
  }
  function stop() {
    modal.confirm({ title: c.call?.state === 'active' ? '请求停止模拟通话？' : '取消模拟排队任务？', content: c.call?.state === 'active' ? '将显示“停止请求中”，只有收到模拟确认后才显示结束。这里不会调用真实电话接口。' : '仅取消本页的模拟排队状态，不会发起电话。', okText: '确认', cancelText: '返回', onOk: () => operate(() => requestStop(c), '已更新模拟任务状态。') })
  }
  function exportReport(r: Report) {
    try {
      const content = reportMarkdown(c, r, job)
      const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }))
      const link = document.createElement('a')
      link.href = url; link.download = `Cheetah_模拟推荐_${c.name}_v${r.version}.md`; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      onUpdate({ ...c, reports: c.reports.map(item => item.version === r.version ? { ...item, exports: item.exports + 1 } : item), timeline: [...c.timeline, { title: '发起演示报告下载', detail: `D10 v${r.version} · 仅本地下载请求，未向 HR 发送`, at: now() }] })
      void message.success('已发起模拟报告下载，未对外发送。')
    } catch (error) { void message.error((error as Error).message) }
  }
  const reportPanel = <div className="detail-grid"><section className="panel">
    <div className="section-heading"><h2>企业 HR 推荐报告 <Tag>D10</Tag></h2>{report && <Select aria-label="报告版本" value={report.version} onChange={setReportVersion} options={c.reports.map(r => ({ value: r.version, label: `v${r.version} · ${reportLabels[r.state]}` }))} />}</div>
    {report ? <><Space wrap><SourceTag source={reportArtifact?.source ?? 'mock'} />{reportArtifact?.upstreamSources.filter(s => s !== reportArtifact.source).map(s => <SourceTag key={s} source={s} inherited />)}<Tag color={report.state === 'approved' ? 'green' : report.state === 'expired' ? 'red' : 'orange'}>{reportLabels[report.state]}</Tag><Tag>v{report.version}</Tag></Space><div className="report-document"><span className="document-eyebrow">CHEETAH / CANDIDATE RECOMMENDATION</span><h2>{c.name} <span>推荐报告</span></h2><p className="muted">{job.title} · 测试规则 v{c.ruleVersion}</p><div className="document-content">{report.content}</div><h3>待核实事项</h3><ul className="unknown-list">{c.gaps.map(g => <li key={g}>{g}</li>)}</ul></div>
      {report.reviewReason && <Alert type="info" title="版本审核意见" description={report.reviewReason} />}
      <div className="report-actions"><Button disabled={!canExport(c, report)} type="primary" icon={<Icon name="file" size={16} />} onClick={() => exportReport(report)}>下载模拟 Markdown</Button><span className="muted small">本版本下载请求 {report.exports} 次 · 无对外交付记录</span></div>
    </> : <Empty description={c.screening === 'unknown' ? '信息不足，尚未形成内部评估与推荐报告。' : c.screening === 'rejected' ? '当前未达初筛条件，不生成 D10。' : '等待有效访谈与内部评估；未达推荐条件不生成 D10。'} image={Empty.PRESENTED_IMAGE_SIMPLE} />}
  </section><aside className="stack"><section className="panel"><span className="mini-label">人工审核</span><h3>批准的是这一份、这一个版本</h3><p className="muted">请先查看内部评估、证据与未知项。修订产生新版本，旧批准随即失效。</p>
    {!viewingLatest && <Alert className="form-alert" type="info" title="正在查看历史版本，请切换到当前版本后审核或修订。" />}
    <div className="stack"><Button type="primary" disabled={!viewingLatest || !latest || latest.state !== 'pending' || c.evaluation !== 'recommended'} onClick={() => { setReview({ version: latest!.version, action: 'approve' }); form.resetFields() }}>批准当前 v{latest?.version ?? '—'} · 模拟</Button><Button disabled={!viewingLatest || !latest || latest.state !== 'pending'} onClick={() => { setReview({ version: latest!.version, action: 'reject' }); form.resetFields() }}>退回并填写意见</Button><Button disabled={!viewingLatest || !latest || latest.state === 'expired'} onClick={() => { setRevision(latest!.version); form.setFieldsValue({ content: latest!.content, reason: '' }) }}>修订并生成新版本</Button></div>
  </section><Alert type="warning" showIcon title="真实报告生成与审核接口待接入" description="当前操作仅验证本地模拟版本控制。不会调用模型重生成，不会发送到 HR。" /><section className="panel"><h3>内部评估与推荐分开</h3><p className="muted">D09 仅内部可见；模拟导出仅包含 D10 内容、未知事项及来源标识。</p><Button block disabled={!c.artifacts.some(a => a.type === 'D09')} onClick={() => setArtifact(c.artifacts.find(a => a.type === 'D09'))}>查看 D09 内部评估</Button></section></aside></div>

  return <>
    <Button type="text" className="back-button" icon={<Icon name="back" size={16} />} onClick={onBack}>返回候选人列表</Button>
    <PageHeading eyebrow="CANDIDATE WORKSPACE / 候选人工作区" title={c.name} description={`${c.role} · ${c.experience}`} actions={<Space wrap><ScreeningTag value={c.screening} /><SourceTag source={c.source} /></Space>} />
    <div className="candidate-meta panel"><span><strong>应聘岗位</strong>{job.title}</span><span><strong>实际绑定规则</strong>v{c.ruleVersion} · 测试规则</span><span><strong>学历</strong>{c.education}</span><span><strong>材料来源</strong>虚构演示材料</span></div>
    <Tabs defaultActiveKey={initialTab} className="workspace-tabs" items={[
      { key: 'overview', label: '候选人概览', children: <div className="detail-grid"><div className="stack"><section className="panel"><div className="section-heading"><h2>当前结论与下一步</h2><ScreeningTag value={c.screening} /></div><p className="body-large">{c.summary}</p><h3>未知与待核实</h3>{c.gaps.length ? <ul className="unknown-list">{c.gaps.map(g => <li key={g}>{g}</li>)}</ul> : <p className="muted">此分支没有补充缺口。</p>}<Alert type="info" showIcon title={c.screening === 'unknown' ? '信息不足不代表不符合；补充证据后才能复核。' : c.screening === 'rejected' ? '保留初筛依据，不创建电话与推荐任务。' : '初筛达标自动关联电话任务；实际拨打仍受当前联系前提约束。'} /></section><section className="panel"><div className="section-heading"><h2>全流程产物</h2><span className="muted">D03 — D10</span></div><div className="artifact-grid">{types.map(type => {
        const item = c.artifacts.filter(a => a.type === type).at(-1)
        return <button className={`artifact-card ${item ? '' : 'unavailable'}`} key={type} disabled={!item} onClick={() => setArtifact(item)}><div><span className="artifact-code">{type}</span>{item && <Tag>v{item.version}</Tag>}</div><strong>{artifactNames[type]}</strong><span>{item ? `${item.source === 'manual' ? '人工修订 · 含模拟来源' : '模拟样例'} · ${item.status === 'valid' ? '可查看' : '已失效'}` : '未执行 · 等待上游条件'}</span></button>
      })}</div></section></div><aside className="panel"><div className="section-heading"><h2>流程时间线</h2><Icon name="clock" size={18} /></div><Timeline items={c.timeline.map((item, i) => ({ key: `${i}-${item.at}`, color: i === c.timeline.length - 1 ? 'green' : 'gray', content: <div className="timeline-item"><strong>{item.title}</strong><p>{item.detail}</p><time>{displayTime(item.at)} · 北京时间</time></div> }))} /></aside></div> },
      { key: 'call', label: '电话沟通', children: <div className="detail-grid"><section className="panel"><div className="section-heading"><h2>电话业务任务</h2><SourceTag source="mock" /></div>{c.call ? <><div className="call-state"><span className={`call-orb ${c.call.state === 'active' ? 'active' : ''}`}><Icon name="phone" size={30} /></span><h2 aria-live="polite">{callLabels[c.call.state]}</h2><p>{c.call.reason}</p></div><Descriptions column={1} items={[
        { key: 'id', label: '唯一业务任务', children: c.call.id }, { key: 'attempts', label: '模拟尝试记录', children: `${c.call.attempts} 条（无真实拨打）` }, { key: 'auth', label: '当前联系前提', children: '演示环境无真实联系授权' }, { key: 'permission', label: '真实拨打能力', children: '待接入 · 当前不可用' },
      ]} /><Space wrap>{['waiting', 'active'].includes(c.call.state) && <Button danger onClick={stop}>{c.call.state === 'active' ? '请求停止 · 模拟' : '取消排队 · 模拟'}</Button>}{c.call.state === 'stopping' && <Button onClick={() => operate(() => ({ ...c, call: { ...c.call!, state: 'completed', reason: '已手动模拟适配器结束确认，无真实通话。' }, timeline: [...c.timeline, { title: '模拟收到结束确认', detail: '停止请求已确认，仅本地状态', at: now() }] }), '已模拟确认结束。')}>模拟收到结束确认</Button>}{c.call.state === 'unknown' && <Tag color="orange">先核对外部状态 · 禁止重拨</Tag>}</Space></> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未达到进入电话条件，未建立电话任务。" />}</section><aside className="stack"><Alert type="warning" showIcon title="没有连接真实语音平台" description="停止与确认操作仅验证界面状态。真实候选人要求结束时，必须由服务端实时控制链路停止。" /><section className="panel"><h3>拨打前检查</h3><ul className="checklist"><li>有效联系前提与当前授权</li><li>允许时段与剩余预算</li><li>已有业务任务与正在进行的联系</li><li>外部结果不明时先查询核对</li></ul><p className="muted small">最终检查由后端执行，不能由前端按钮替代。</p></section></aside></div> },
      { key: 'reports', label: `评估与推荐${latest?.state === 'pending' ? ' · 待审核' : ''}`, children: reportPanel },
    ]} />
    <ArtifactViewer key={artifact ? `${artifact.id}-${artifact.version}` : 'closed'} artifact={artifact} evidence={c.evidence} onClose={() => setArtifact(undefined)} />
    <Modal title={review ? `${review.action === 'approve' ? '批准' : '退回'} D10 v${review.version} · 模拟` : `修订 D10 v${revision}`} open={!!review || !!revision} onCancel={() => { setReview(undefined); setRevision(undefined) }} footer={null} forceRender>
      <Form form={form} layout="vertical" onFinish={values => {
        try {
          if (review) onUpdate(reviewReport(c, review.version, review.action, values.reason))
          else if (revision) { onUpdate(reviseReport(c, revision, values.content, values.reason)); setReportVersion(undefined) }
          setReview(undefined); setRevision(undefined); void message.success('本地模拟版本已更新。')
        } catch (error) { void message.error((error as Error).message) }
      }}>
        {revision && <><Alert className="form-alert" type="warning" title="生成新的人工修订版本；旧批准失效，新版须重审。上游模拟来源保留。" /><Form.Item name="content" label="修订内容" rules={[{ required: true, whitespace: true, message: '请填写内容' }]}><Input.TextArea rows={10} maxLength={15000} /></Form.Item></>}
        <Form.Item name="reason" label={review ? '审核意见' : '修订原因'} rules={[{ required: true, whitespace: true, message: '请填写具体原因' }]}><Input.TextArea rows={3} maxLength={2000} placeholder="请说明证据核查结果、待补充信息或修订依据" /></Form.Item><div className="modal-actions"><Button onClick={() => { setReview(undefined); setRevision(undefined) }}>取消</Button><Button type="primary" htmlType="submit">{revision ? '保存新版本 · 待重审' : '确认本版本审核 · 模拟'}</Button></div>
      </Form>
    </Modal>
  </>
}
