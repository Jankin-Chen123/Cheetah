import { useEffect, useLayoutEffect, useRef, useState } from 'react'

type ListView = { query: string; jobFilter: string; statusFilter: string; tablePage: number }
type NavigationState = { route: string; from?: string }
const EMPTY: ListView = { query: '', jobFilter: 'all', statusFilter: 'all', tablePage: 1 }
const VIEWS_KEY = 'cheetah-list-views-v1'
const SCROLL_KEY = 'cheetah-list-scroll-v1'
const currentRoute = () => window.location.hash.slice(1).replace(/^(app|demo)\//, '') || 'overview'
function readViews(key: string): Record<string, ListView> {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) || '{}')
    return Object.fromEntries(Object.entries(saved).filter((entry): entry is [string, ListView] => {
      const view = entry[1] as ListView | null
      return !!view && typeof view.query === 'string' && typeof view.jobFilter === 'string' && typeof view.statusFilter === 'string' && Number.isInteger(view.tablePage) && view.tablePage > 0
    }))
  } catch { return {} }
}
function readPositions(key: string): Record<string, number> {
  try { return Object.fromEntries(Object.entries(JSON.parse(sessionStorage.getItem(key) || '{}')).filter((entry): entry is [string, number] => typeof entry[1] === 'number' && Number.isFinite(entry[1]) && entry[1] >= 0)) }
  catch { return {} }
}
function save(key: string, value: unknown) { try { sessionStorage.setItem(key, JSON.stringify(value)) } catch { /* Navigation still works when browser storage is unavailable. */ } }

export function useWorkspaceNavigation(prefix: 'app' | 'demo', scope: string) {
  const viewsKey = `${VIEWS_KEY}-${scope}`
  const scrollKey = `${SCROLL_KEY}-${scope}`
  const [route, setRoute] = useState(currentRoute)
  const [views, setViews] = useState(() => readViews(viewsKey))
  const positions = useRef(readPositions(scrollKey))
  const view = views[route] ?? EMPTY
  const state = window.history.state?.cheetahNavigation as NavigationState | undefined
  const from = state?.route === route ? state.from : undefined
  useEffect(() => { save(viewsKey, views) }, [views, viewsKey])
  useEffect(() => {
    const previous = window.history.scrollRestoration
    window.history.scrollRestoration = 'manual'
    const sync = () => setRoute(currentRoute())
    window.addEventListener('hashchange', sync); window.addEventListener('popstate', sync)
    return () => { window.removeEventListener('hashchange', sync); window.removeEventListener('popstate', sync); window.history.scrollRestoration = previous }
  }, [])
  useLayoutEffect(() => {
    const target = positions.current[route] ?? 0
    const frame = requestAnimationFrame(() => window.scrollTo(0, target))
    const remember = () => { positions.current[route] = window.scrollY }
    const persist = () => save(scrollKey, positions.current)
    window.addEventListener('scroll', remember, { passive: true }); window.addEventListener('pagehide', persist)
    return () => { cancelAnimationFrame(frame); window.removeEventListener('scroll', remember); window.removeEventListener('pagehide', persist); persist() }
  }, [route, scrollKey])

  function navigate(next: string, replace = false) {
    if (next === route) return
    positions.current[route] = window.scrollY
    save(scrollKey, positions.current)
    const entry = { cheetahNavigation: { route: next, from: replace ? from : route } }
    if (replace) window.history.replaceState(entry, '', `#${prefix}/${next}`)
    else window.history.pushState(entry, '', `#${prefix}/${next}`)
    setRoute(next)
  }
  function back(fallback: string) {
    if (from) window.history.back()
    else navigate(fallback, true)
  }
  function updateView(patch: Partial<ListView>) {
    setViews(items => ({ ...items, [route]: { ...(items[route] ?? EMPTY), ...patch } }))
  }
  const backLabel = from?.startsWith('job/') ? '返回岗位' : ({ overview: '返回工作台', calls: '返回电话任务', reports: '返回推荐审核', jobs: '返回岗位列表', candidates: '返回人才库' }[from ?? ''] ?? '返回人才库')
  return { route, navigate, back, backLabel, ...view,
    resetJobList: () => setViews(items => ({ ...items, jobs: { ...EMPTY } })),
    setQuery: (query: string) => updateView({ query, tablePage: 1 }),
    setJobFilter: (jobFilter: string) => updateView({ jobFilter, tablePage: 1 }),
    setStatusFilter: (statusFilter: string) => updateView({ statusFilter, tablePage: 1 }),
    setTablePage: (tablePage: number) => updateView({ tablePage }),
  }
}
