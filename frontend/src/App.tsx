import { useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, Flex, Space, Tag, Typography } from 'antd'
import { fetchHealth } from './api/client'

const { Title, Paragraph, Text } = Typography

const stages = [
  {
    number: '01',
    title: '梳理招聘需求',
    description: '整理 HR 需求，确认岗位画像与筛选标准。',
    output: '岗位画像 · 面试评估表',
  },
  {
    number: '02',
    title: '分析与初筛简历',
    description: '结合经历与背景证据，找出适合进一步沟通的候选人。',
    output: '候选人画像 · 初筛报告',
  },
  {
    number: '03',
    title: '电话沟通与推荐',
    description: '核实关键经历，形成内部评估和待审核的推荐报告。',
    output: '访谈纪要 · 评估与推荐报告',
  },
]

export default function App() {
  const [connection, setConnection] = useState<'loading' | 'online' | 'offline'>('loading')
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal)
      .then(() => {
        if (!controller.signal.aborted) setConnection('online')
      })
      .catch(() => {
        if (!controller.signal.aborted) setConnection('offline')
      })
    return () => controller.abort()
  }, [refreshKey])

  const connectionText = {
    loading: '正在连接基础服务',
    online: '基础服务连接正常',
    offline: '基础服务尚未连接',
  }[connection]

  return (
    <div className="workspace">
      <header className="site-header">
        <Space size={12}>
          <span className="brand-mark" aria-hidden="true">C</span>
          <span className="brand-name">Cheeta</span>
          <span className="brand-divider" />
          <Text type="secondary">猎头工作台</Text>
        </Space>
        <Tag>初始化版本</Tag>
      </header>

      <main>
        <section className="intro" aria-labelledby="intro-title">
          <Text className="eyebrow">从需求到推荐，让每一步有据可循</Text>
          <Title id="intro-title" level={1}>把时间留给值得深入沟通的人。</Title>
          <Paragraph className="intro-description">
            在一个工作台中梳理招聘需求、筛选简历、核实经历，再由你审核每一份推荐。
          </Paragraph>
          <Button type="primary" size="large" disabled>创建岗位 · 即将开放</Button>
        </section>

        <Alert
          type="info"
          showIcon
          title="项目骨架已建立，业务流程尚待开发"
          description="下方展示规划中的工作阶段。目前没有处理真实简历，也未接入 AI 电话。"
        />

        <section className="workflow-section" aria-labelledby="workflow-title">
          <Flex justify="space-between" align="center" wrap gap={12}>
            <Title id="workflow-title" level={3}>你的工作流程</Title>
            <Text type="secondary">规划中的三个阶段</Text>
          </Flex>
          <div className="stage-grid">
            {stages.map((stage) => (
              <Card key={stage.number} className="stage-card">
                <Flex justify="space-between" align="center">
                  <span className="stage-number">{stage.number}</span>
                  <Tag>待开发</Tag>
                </Flex>
                <Title level={4}>{stage.title}</Title>
                <Paragraph type="secondary">{stage.description}</Paragraph>
                <div className="stage-output"><Text type="secondary">{stage.output}</Text></div>
              </Card>
            ))}
          </div>
        </section>

        <Card className="connection-card">
          <Flex justify="space-between" align="center" wrap gap={16}>
            <Space orientation="vertical" size={6} aria-live="polite">
              <Badge
                status={connection === 'online' ? 'success' : connection === 'loading' ? 'processing' : 'default'}
                text={connectionText}
              />
              <Text type="secondary">仅表示基础服务是否可访问，业务功能尚未开放。</Text>
            </Space>
            <Button
              loading={connection === 'loading'}
              onClick={() => { setConnection('loading'); setRefreshKey((value) => value + 1) }}
            >
              重新检查连接
            </Button>
          </Flex>
        </Card>
      </main>

      <footer>Cheeta · 每一份推荐，都应有清楚的依据。</footer>
    </div>
  )
}
