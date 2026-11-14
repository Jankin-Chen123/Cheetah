import { useState } from 'react'
import { Alert, App, Button, Descriptions, Empty, Form, Input, Modal, Select, Table, Tabs, Tag } from 'antd'
import type { Candidate, Job, RuleDraft } from '../domain/workspace'
import { publishRules } from '../domain/workspace'
import JobDocuments from './JobDocuments'
import { Icon, PageHeading, Person, ScreeningTag, SourceTag } from './ui'

export default function JobWorkspace({ job, candidates, onUpdate, onCandidate, onImport, onBack, backLabel = '返回岗位列表', activeTab = 'documents', onTabChange }: {
  job: Job; candidates: Candidate[]; onUpdate: (job: Job) => void; onCandidate: (id: string) => void; onImport: () => void; onBack: () => void; backLabel?: string; activeTab?: string; onTabChange?: (key: string) => void;
}) {
  const { message, modal } = App.useApp()
  const [editing, setEditing] = useState(false)
  const [viewVersion, setViewVersion] = useState<number>()
  const history = job.ruleHistory ?? (job.version ? [{ version: job.version, rules: job.rules }] : [])
  const snapshot = history.find(item => item.version === viewVersion) ?? history.at(-1)
  const [form] = Form.useForm<RuleDraft>()
  function publish(values: RuleDraft) {
    modal.confirm({
      title: `发布测试规则 v${job.version + 1}？`,
      content: '仅发布本页测试规则，不修改历史版本或触发外呼。',
      okText: '发布测试版本', cancelText: '返回检查',
      onOk: () => {
        try { onUpdate(publishRules(job, values)); setViewVersion(undefined); setEditing(false); void message.success('测试规则已保存到本机') }
        catch (error) { void message.error((error as Error).message); throw error }
      },
    })
  }
  return <>
    <Button className="back-button" type="text" icon={<Icon name="back" size={16} />} onClick={onBack}>{backLabel}</Button>
    <PageHeading title={job.title} description={`${job.company} · ${job.location || '地点待确认'}`} actions={<><Button icon={<Icon name="file" size={16} />} onClick={() => { form.setFieldsValue(job.draft ?? job.rules); setEditing(true) }}>编辑规则草案</Button><Button type="primary" icon={<Icon name="upload" size={16} />} disabled={job.status !== 'published'} onClick={onImport}>导入简历</Button></>} />
    <div className="job-summary panel"><div><SourceTag source={job.source} /><Tag color={job.status === 'published' ? 'green' : 'orange'}>{job.status === 'published' ? `测试规则 v${job.version} · 已发布` : '规则草稿 · 未发布'}</Tag>{job.draft && <Tag color="orange">有未发布草案</Tag>}</div><span className="muted">岗位标识：{job.id}</span></div>
    <Tabs className="workspace-tabs" activeKey={activeTab} onChange={onTabChange} items={[
      { key: 'documents', label: '岗位产物', children: <JobDocuments job={job} onUpdate={onUpdate} /> },
      { key: 'overview', label: '岗位与规则', children: <div className="detail-grid"><div className="stack">
        <section className="panel"><div className="section-heading"><h2>岗位画像</h2><Tag>D01 · {job.source === 'mock' ? '模拟样例' : '人工录入'}</Tag></div><Descriptions column={{ xs: 1, sm: 2 }} items={[
          { key: 'company', label: '招聘企业', children: job.company }, { key: 'location', label: '工作地点', children: job.location || '未知 · 待确认' },
          { key: 'salary', label: '薪资范围', children: job.salary || '未知 · 待确认' }, { key: 'goal', label: '试用期目标', children: <span className="unknown-text">未知 · 原始需求未提及</span> },
        ]} /><h3>原始需求 / JD</h3><p className="document-content">{job.material}</p><p className="muted small">人工录入 · 未经模型分析</p></section>
        <section className="panel"><div className="section-heading"><h2>已发布标准</h2>{snapshot ? <Select aria-label="查看已发布规则版本" value={snapshot.version} onChange={setViewVersion} options={history.map(item => ({ value: item.version, label: `v${item.version} · ${item.version === job.version ? '当前测试版本' : '历史测试版本'}` }))} /> : <span className="muted">尚未发布</span>}</div>{job.status === 'published' && snapshot ? <div className="rule-sections">
          <article><span className="rule-number">01</span><div><h3>初筛标准</h3><p>{snapshot.rules.screening}</p></div></article>
          <article><span className="rule-number">02</span><div><h3>面试评估标准 <Tag>D02</Tag></h3><p>{snapshot.rules.interview}</p></div></article>
          <article><span className="rule-number">03</span><div><h3>推荐条件</h3><p>{snapshot.rules.recommendation}</p></div></article>
        </div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请补齐初筛、面试和推荐标准"><Button onClick={() => { form.setFieldsValue(job.draft ?? job.rules); setEditing(true) }}>填写规则</Button></Empty>}</section>
      </div><aside className="stack"><section className="panel"><h3>流程</h3><ol className="workflow-rail"><li className="done"><strong>梳理需求</strong></li><li className={job.status === 'published' ? 'done' : ''}><strong>确认岗位标准</strong><span>{job.status === 'published' ? `测试版本 v${job.version}` : '等待规则确认'}</span></li><li><strong>简历研究与初筛</strong><span>业务接口待接入</span></li><li><strong>电话沟通与评估</strong><span>达标后自动建电话任务</span></li><li><strong>人工审核推荐</strong><span>批准后导出</span></li></ol></section><Alert showIcon type="info" title="新规则不影响历史任务" /></aside></div> },
      { key: 'candidates', label: `候选人 (${candidates.length})`, children: <section className="panel"><Table<Candidate> rowKey="id" dataSource={candidates} pagination={{ pageSize: 8 }} scroll={{ x: 600 }} columns={[
        { title: '候选人', render: (_, c, i) => <button className="person-link" onClick={() => onCandidate(c.id)}><Person name={c.name} detail={c.role} index={i} /></button> },
        { title: '初筛结论', render: (_, c) => <ScreeningTag value={c.screening} /> },
        { title: '实际规则', render: (_, c) => `v${c.ruleVersion} · 测试` },
        { title: '操作', render: (_, c) => <Button type="link" onClick={() => onCandidate(c.id)}>查看详情</Button> },
      ]} /></section> },
    ]} />
    <Modal title="编辑岗位规则草案" open={editing} onCancel={() => setEditing(false)} footer={null} width={660} forceRender>
      <Alert className="form-alert" type="warning" showIcon title="测试规则 · 刷新清空，不触发外呼" />
      <Form form={form} layout="vertical" onFinish={publish}>
        <Form.Item name="screening" label="初筛标准" rules={[{ required: true, whitespace: true, message: '请填写初筛条件与未知处理方式' }]}><Input.TextArea rows={3} maxLength={5000} placeholder="初筛条件及未知处理" /></Form.Item>
        <Form.Item name="interview" label="面试评估标准（D02）" rules={[{ required: true, whitespace: true, message: '请填写独立的面试评估标准' }]}><Input.TextArea rows={3} maxLength={5000} placeholder="评估维度、评分及证据要求" /></Form.Item>
        <Form.Item name="recommendation" label="推荐条件" rules={[{ required: true, whitespace: true, message: '请填写推荐门槛与人工复核条件' }]}><Input.TextArea rows={3} maxLength={5000} placeholder="推荐门槛及复核条件" /></Form.Item>
        <div className="modal-actions"><Button onClick={() => { onUpdate({ ...job, draft: form.getFieldsValue() }); setEditing(false); void message.success('草案已保存，尚未发布') }}>保存草案</Button><Button type="primary" htmlType="submit">确认发布 v{job.version + 1} · 测试</Button></div>
      </Form>
    </Modal>
  </>
}
