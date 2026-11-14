import { Alert, Button, Descriptions, Drawer, Empty, Space, Tag } from 'antd'
import { useState } from 'react'
import type { Artifact, Evidence } from '../domain/workspace'
import { previewText } from '../domain/presentation'
import { artifactNames, displayTime } from '../domain/workspace'
import { Icon, SourceTag } from './ui'

export default function ArtifactViewer({ artifact, evidence, onClose }: { artifact?: Artifact; evidence: Evidence[]; onClose: () => void }) {
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence>()
  return <>
    <Drawer open={!!artifact} onClose={onClose} title={artifact ? artifactNames[artifact.type] : '产物查看'} size={640} destroyOnHidden>
      {artifact && <div className="artifact-viewer">
        <Space wrap><SourceTag source={artifact.source} />{artifact.upstreamSources.filter(s => s !== artifact.source).map(s => <SourceTag key={s} source={s} inherited />)}<Tag color={artifact.status === 'valid' ? 'green' : 'red'}>{artifact.status === 'valid' ? '当前有效' : '已失效'}</Tag></Space>
        <Descriptions size="small" column={1} items={[
          { key: 'at', label: '生成时间（北京时间）', children: displayTime(artifact.createdAt) },
        ]} />
        <h3>产物内容</h3><div className="document-content">{artifact.source === 'mock' ? previewText(artifact.content) : artifact.content}</div>
        <h3>未知与待核实</h3>{artifact.unknowns.length ? <ul className="unknown-list">{artifact.unknowns.map(x => <li key={x}>{x}</li>)}</ul> : <p className="muted">暂无新增待核实项</p>}
        <h3>证据引用</h3><div className="evidence-list">{artifact.evidenceIds.length ? artifact.evidenceIds.map(id => {
          const item = evidence.find(e => e.id === id)
          return <Button key={id} block icon={<Icon name="file" size={16} />} disabled={!item} onClick={() => setSelectedEvidence(item)}>{item?.title ?? '证据暂不可用'}</Button>
        }) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无研究证据" />}</div>
      </div>}
    </Drawer>
    <Drawer open={!!selectedEvidence && !!artifact} onClose={() => setSelectedEvidence(undefined)} title="来源与原文" size={420}>
      {selectedEvidence && <><Space wrap><SourceTag source={selectedEvidence.source} /><Tag>{selectedEvidence.kind}</Tag></Space><h3>{selectedEvidence.title}</h3><blockquote>{selectedEvidence.source === 'mock' ? previewText(selectedEvidence.quote) : selectedEvidence.quote}</blockquote><p className="muted">原文位置：{selectedEvidence.location}</p><Alert type="info" title="自述未独立核实；公司成果不等于个人贡献。" /></>}
    </Drawer>
  </>
}
