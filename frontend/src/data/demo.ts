import type { Artifact, ArtifactType, Candidate, Job } from '../domain/workspace'

// Entirely fictional fixtures. No fixture is submitted to the backend or a voice provider.
const at = '2026-11-13T02:20:00Z'
export const demoJobs: Job[] = [
  {
    id: 'demo-job-product', title: '高级产品经理', company: '星屿科技（虚构）', location: '上海 · 混合办公', salary: '30–45K · 15薪',
    material: '【虚构岗位】负责企业协作产品的增长与体验。需要独立负责 B 端产品，能够定义指标、组织用户研究并推动跨团队交付。薪资为测试字段；试用期目标、团队规模尚未确认。',
    status: 'published', version: 1, source: 'mock',
    rules: { screening: '有 B 端产品完整交付经历；年限与个人职责以材料证据为准。关键经历缺失时进入信息不足，不直接否决。', interview: '核实问题定义、个人贡献、指标口径与跨团队推动。未问到的维度标记未评估，不能记零分。', recommendation: '关键维度证据覆盖充分、无未解决的重大冲突，经内部评估达到推荐条件后形成 D10。此为测试规则，不用于真实招聘。' },
  },
  {
    id: 'demo-job-engineer', title: '前端开发工程师', company: '远川实验室（虚构）', location: '杭州', salary: '25–40K · 14薪',
    material: '【虚构岗位】负责 Web 应用开发，熟悉 React、TypeScript，能够独立完成复杂交互与性能优化。需确认面试维度与推荐门槛。',
    status: 'draft', version: 0, source: 'mock', rules: { screening: '', interview: '', recommendation: '' },
  },
  {
    id: 'demo-job-design', title: '产品设计师', company: '栖木数字（虚构）', location: '深圳', salary: '待确认',
    material: '【虚构岗位】负责企业产品体验设计，具备系统思维与可用性研究经历。', status: 'published', version: 1, source: 'mock',
    rules: { screening: '具备企业软件设计经历；缺作品证据时标记未知。', interview: '核实设计过程、研究方法与个人贡献。', recommendation: '关键经历得到核实且覆盖充分；所有规则均为测试用。' },
  },
]

const contents: Partial<Record<ArtifactType, string>> = {
  D03: '【虚构材料】曾负责企业协作产品，参与从需求调研到版本交付的完整过程。材料中的项目结果属于候选人自述，尚无公开来源核实。',
  D04: '【模拟研究状态】未执行真实联网研究。公司与项目名称均为虚构，不能据此验证个人贡献。研究接口与可信来源待接入。',
  D05: '【模拟样例】具备 B 端产品经历线索。个人职责边界、指标定义与团队成果归因需要电话核实。',
  D06: '【模拟初筛】按照测试规则，现有自述具备进入电话沟通的线索。结论为演示预置，未由真实模型生成。达标应自动建立电话任务，拨打仍需满足联系前提。',
  D07: '【模拟提纲】\n1. 请描述最近一个产品问题的定义过程。\n2. 你个人负责哪些决策？哪些由团队成员负责？\n3. 指标的基线、统计范围和变化时间是什么？\n4. 如果不方便继续，我们会立即结束。',
  D08: '【预置模拟访谈，非真实转写】\n问题：你个人负责什么？\n回答：负责访谈、需求排序和验收，工程实现由研发团队负责。\n追问：项目指标的口径是什么？\n回答：当前无法提供完整统计口径，需要后续补充。\n覆盖：个人职责已讨论；求职意向与到岗时间未覆盖。',
  D09: '【模拟内部评估】\n问题定义：有自述证据，需复核。\n个人贡献：模拟访谈中区分了本人职责与团队实现。\n指标证据：统计口径未完整提供，保留未知。\n求职意向：未评估，不记零分。\n测试样例结论：推荐进入人工审核。仅验证报告审批流程，不证明真实候选人质量。',
  D10: '【虚构候选人 · 模拟推荐草案】\n具有企业协作产品经历线索，曾参与需求调研、优先级梳理和交付验收。\n\n在预置模拟访谈中，候选人说明其负责访谈、需求排序和验收，工程实现由研发团队负责。该信息属于自述，未得到独立核实。\n\n建议进一步沟通其产品判断与跨团队协作经历。指标统计口径、到岗时间和求职意向仍待核实。不将团队成果直接归为个人业绩。',
}

function artifacts(id: string, types: ArtifactType[]): Artifact[] {
  return types.map((type, index) => ({
    id: `${id}-${type}`, type, version: 1, status: 'valid', ruleVersion: 1,
    source: 'mock', upstreamSources: ['mock'], inputRefs: index ? [`${id}-${types[index - 1]}@v1`] : ['fictional-resume@v1'],
    content: contents[type] ?? '', unknowns: ['个人贡献尚未独立核实', '到岗时间未提及'],
    evidenceIds: type === 'D04' ? [] : [`${id}-e1`], createdAt: at,
  }))
}

export const demoCandidates: Candidate[] = [
  {
    id: 'demo-lin', jobId: 'demo-job-product', name: '林予安', role: '产品经理 · 星河协作（虚构）', experience: '6 年经验', education: '本科 · 信息管理',
    screening: 'passed', ruleVersion: 1, source: 'mock', summary: '有企业协作产品经历，个人职责与团队贡献已在模拟访谈中初步区分。', gaps: ['指标统计口径待核实', '到岗时间与求职意向未评估'],
    artifacts: artifacts('demo-lin', ['D03', 'D04', 'D05', 'D06', 'D07', 'D08', 'D09', 'D10']),
    evidence: [{ id: 'demo-lin-e1', version: 1, title: '模拟访谈：个人职责', quote: '我负责访谈、需求排序和验收，工程实现由研发团队负责。', location: '预置模拟访谈 · 问答 1', kind: '模拟访谈', source: 'mock' }],
    call: { id: 'demo-call-lin', state: 'completed', reason: '预置模拟记录，无真实拨号、录音或费用。', attempts: 1 }, evaluation: 'recommended',
    reports: [{ id: 'demo-report-lin', version: 1, state: 'pending', content: contents.D10!, exports: 0 }],
    timeline: [
      { title: '导入虚构材料', detail: '演示预置 · 非真实简历', at: '2026-11-13T01:00:00Z' },
      { title: '模拟初筛达标', detail: '绑定测试规则 v1 · 自动关联唯一模拟电话任务', at: '2026-11-13T01:10:00Z' },
      { title: '载入预置模拟访谈', detail: '未发生真实电话 · D08 / D09', at },
      { title: '推荐草案待审核', detail: 'D10 v1 · 批准具体版本后才能下载演示报告', at },
    ],
  },
  {
    id: 'demo-zhou', jobId: 'demo-job-product', name: '周见微', role: '高级产品经理 · 微原数字（虚构）', experience: '5 年经验', education: '硕士 · 管理科学',
    screening: 'passed', ruleVersion: 1, source: 'mock', summary: '具备测试规则要求的项目经历线索，等待有效联系前提。', gaps: ['联系授权尚未提供', '项目指标需要核实'],
    artifacts: artifacts('demo-zhou', ['D03', 'D04', 'D05', 'D06', 'D07']), evidence: [{ id: 'demo-zhou-e1', version: 1, title: '虚构材料：项目经历', quote: '参与企业服务产品的需求调研与发布。', location: '虚构简历 · 项目经历段', kind: '自述', source: 'mock' }],
    call: { id: 'demo-call-zhou', state: 'waiting', reason: '缺少有效联系授权；即使初筛达标也不能拨打。', attempts: 0 }, reports: [],
    timeline: [{ title: '模拟初筛达标', detail: '自动关联电话任务，等待联系前提', at }],
  },
  {
    id: 'demo-shen', jobId: 'demo-job-product', name: '沈知夏', role: '产品经理 · 岸石科技（虚构）', experience: '4 年经验', education: '本科 · 软件工程',
    screening: 'unknown', ruleVersion: 1, source: 'mock', summary: '材料没有说明个人负责的产品范围，需补充信息，不能认定为不满足。', gaps: ['个人职责边界未知', '完整交付经历未提及'],
    artifacts: artifacts('demo-shen', ['D03', 'D04', 'D05', 'D06']).map(a => a.type === 'D06' ? { ...a, content: '【模拟初筛】信息不足。个人职责与交付经历缺失，需要人工补充证据；缺失不等于不符合。' } : a),
    evidence: [{ id: 'demo-shen-e1', version: 1, title: '缺失信息', quote: '原始虚构材料未提及个人职责范围。', location: '虚构简历 · 职责段缺失', kind: '未知', source: 'mock' }], reports: [], timeline: [{ title: '等待材料补充', detail: '未建立电话任务 · 未生成推荐报告', at }],
  },
  {
    id: 'demo-xu', jobId: 'demo-job-design', name: '许以宁', role: '视觉设计师 · 白榆创意（虚构）', experience: '3 年经验', education: '本科 · 视觉传达',
    screening: 'rejected', ruleVersion: 1, source: 'mock', summary: '虚构材料明确说明仅负责品牌视觉，无企业软件设计经历。此为预置分支样例。', gaps: [],
    artifacts: artifacts('demo-xu', ['D03', 'D06']).map(a => a.type === 'D06' ? { ...a, content: '【模拟初筛】暂不推荐。虚构材料明确写明仅从事品牌视觉；这是预置分支，不是实际模型判定。' } : a), evidence: [{ id: 'demo-xu-e1', version: 1, title: '虚构材料：工作范围', quote: '工作范围仅包括品牌视觉与平面设计。', location: '虚构简历 · 工作范围', kind: '自述', source: 'mock' }], reports: [], timeline: [{ title: '模拟初筛暂不推荐', detail: '保留初筛依据，不建电话任务与 D10', at }],
  },
  {
    id: 'demo-tang', jobId: 'demo-job-product', name: '唐亦舟', role: '产品负责人 · 青序软件（虚构）', experience: '7 年经验', education: '本科 · 计算机科学',
    screening: 'passed', ruleVersion: 1, source: 'mock', summary: '用于验证通话停止请求的界面状态，无真实语音链路。', gaps: ['实际维度覆盖尚未确认'],
    artifacts: artifacts('demo-tang', ['D03', 'D06', 'D07']), evidence: [{ id: 'demo-tang-e1', version: 1, title: '虚构项目材料', quote: '负责企业产品规划。', location: '虚构简历 · 项目段', kind: '自述', source: 'mock' }], reports: [],
    call: { id: 'demo-call-tang', state: 'active', reason: '前端模拟状态；可请求停止，等待手动模拟结束确认。', attempts: 1 }, timeline: [{ title: '载入模拟通话中状态', detail: '仅验证停止请求交互，无真实通话', at }],
  },
  {
    id: 'demo-gu', jobId: 'demo-job-product', name: '顾清和', role: '产品经理 · 原点系统（虚构）', experience: '5 年经验', education: '本科 · 工业工程',
    screening: 'passed', ruleVersion: 1, source: 'mock', summary: '用于验证外部结果不明的阻断状态，不能直接重拨。', gaps: ['外部请求结果待核对'], artifacts: artifacts('demo-gu', ['D03', 'D06', 'D07']), evidence: [], reports: [],
    call: { id: 'demo-call-gu', state: 'unknown', reason: '模拟请求超时；必须由服务端核对服务商状态，当前禁止重拨。', attempts: 1 }, timeline: [{ title: '模拟外部结果不明', detail: '等待核对，不创建第二次拨打', at }],
  },
]
