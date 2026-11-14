import type { ReactNode } from 'react'
import { Tag } from 'antd'
import type { Screening, SourceMode } from '../domain/workspace'
import { screeningLabels } from '../domain/workspace'

const paths: Record<string, ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  briefcase: <><rect x="3" y="7" width="18" height="14" rx="2" /><path d="M8 7V4h8v3M3 12a22 22 0 0 0 18 0M12 11v4" /></>,
  people: <><circle cx="9" cy="8" r="3" /><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6M17 15a5 5 0 0 1 4 5" /></>,
  phone: <path d="M7 3H4a1 1 0 0 0-1 1c0 9.4 7.6 17 17 17a1 1 0 0 0 1-1v-3l-5-2-2 2a14 14 0 0 1-7-7l2-2-2-5Z" />,
  file: <><path d="M14 3H5v18h14V8l-5-5ZM14 3v6h5M8 13h8M8 17h6" /></>,
  settings: <><circle cx="12" cy="12" r="4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2" /></>,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  upload: <><path d="M12 16V3M7 8l5-5 5 5M3 16v5h18v-5" /></>,
  chevron: <path d="m9 5 7 7-7 7" />,
  back: <path d="M19 12H5M11 6l-6 6 6 6" />,
  spark: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3ZM20 2v4M18 4h4" /></>,
  shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" /><path d="m8 12 3 3 5-6" /></>,
  logout: <><path d="M9 3H3v18h6M10 12h11M17 8l4 4-4 4" /></>,
}

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] ?? paths.file}</svg>
}
export function SourceTag({ source, inherited = false }: { source: SourceMode; inherited?: boolean }) {
  if (source === 'mock') return null
  return <Tag className="source-tag" color={source === 'manual' ? 'blue' : 'green'}>{inherited ? '含上游' : ''}{source === 'manual' ? '人工' : '真实'}来源</Tag>
}
export function ScreeningTag({ value }: { value: Screening }) {
  return <Tag className="status-tag" color={{ pending: 'default', passed: 'green', unknown: 'orange', rejected: 'default' }[value]}><span className={`status-dot ${value}`} />{screeningLabels[value]}</Tag>
}
export function PageHeading({ title, titleExtra, description, actions }: { title: string; titleExtra?: ReactNode; description?: string; actions?: ReactNode }) {
  return <div className="page-heading"><div><h1 className={titleExtra ? 'heading-with-status' : undefined}>{title}{titleExtra}</h1>{description && <p className="page-description">{description}</p>}</div><div className="heading-actions">{actions}</div></div>
}
export function Person({ name, detail, index = 0 }: { name: string; detail: string; index?: number }) {
  return <div className="person"><span className={`person-avatar tone-${index % 4}`}>{name.slice(-2)}</span><div><strong>{name}</strong><span>{detail}</span></div></div>
}
