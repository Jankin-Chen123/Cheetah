import { useState } from 'react'
import { Alert, Button, Card, Checkbox, Input, Space, Pagination } from 'antd'
import { api } from './api/outreach'

interface MethodHit {
  entry_id: string; review_status: string; enabled: boolean
  source: { filename: string; version: number; paragraph: number; sha256: string }
  content: Record<string, unknown>
}
export default function KnowledgeReview() {
  const [items, setItems] = useState<MethodHit[]>([])
  const [selected, setSelected] = useState<MethodHit>()
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [structuredOnly, setStructuredOnly] = useState(true)
  async function load(nextPage: number) {
    const result = await api<{ items: MethodHit[]; total: number }>(`/knowledge/entries?page=${nextPage}&page_size=20&structured_only=${structuredOnly}`)
    setItems(result.items); setTotal(result.total); setPage(nextPage)
  }
  async function run(action: () => Promise<unknown>) {
    setError('')
    try { await action() } catch (e) { setError(String(e)) }
  }
  return <Card title="方法知识审核（本地开发）">
    <Alert type="warning" message="自动提取仅是待审核草稿。请核对原文、冲突和适用范围后批准。" />
    {error && <Alert type="error" message={error} />}
    <Checkbox checked={structuredOnly} onChange={e => { setStructuredOnly(e.target.checked); setItems([]); setSelected(undefined); setPage(1); setTotal(0) }}>仅显示结构化方法（切换后重新读取）</Checkbox>
    <Button onClick={() => void run(async () => {
      await load(1)
    })}>读取待核对方法</Button>
    <Pagination current={page} total={total} pageSize={20} showSizeChanger={false} onChange={p => void run(() => load(p))} />
    {items.map(item => <div key={item.entry_id} style={{ margin: 12 }}>
      <Button onClick={() => {
        setSelected(item)
        const fields = ['topic', 'dimensions', 'tags', 'trigger_conditions', 'question_examples', 'followup_strategy', 'stop_conditions', 'exceptions', 'conflicts']
        setDraft(JSON.stringify(Object.fromEntries(fields.map(key => [key, item.content[key]])), null, 2))
      }}>{String(item.content.topic)} · {item.source.filename} · v{item.source.version} · 段落 {item.source.paragraph} · {item.review_status} · {item.enabled ? '已启用' : '已停用'}</Button>
    </div>)}
    {selected && <>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(selected.source, null, 2)}{'\n'}{String(selected.content.source_context ?? selected.content.source_text)}</pre>
      <Input.TextArea rows={18} value={draft} onChange={e => setDraft(e.target.value)} aria-label="方法结构化内容" />
      <Space wrap>
        {[false, true].map(approve => <Button key={String(approve)} onClick={() => void run(async () => {
          await api(`/knowledge/${selected.entry_id}/curate`, { method: JSON.parse(draft), approve })
          setSelected(undefined)
          await load(page)
        })}>{approve ? '人工批准方法' : '保存待审核草稿'}</Button>)}
        <Button onClick={() => void run(async () => {
          await api(`/knowledge/${selected.entry_id}/enabled`, { enabled: !selected.enabled })
          setSelected(undefined)
          await load(page)
        })}>{selected.enabled ? '停用条目' : '启用条目'}</Button>
      </Space>
    </>}
  </Card>
}
