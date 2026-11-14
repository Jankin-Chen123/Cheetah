import { useLayoutEffect, useRef } from 'react'

export function usePageMotion(route: string) {
  const ref = useRef<HTMLElement>(null)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element?.animate || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const offset = element.classList.contains('dashboard-content') ? 0 : 6
    // Animate the existing surface, keeping background job controllers, form
    // state, and the navigation hook's scroll restoration mounted throughout.
    const animation = element.animate([
      { opacity: 0.65, transform: `translate3d(0, ${offset}px, 0)` },
      { opacity: 1, transform: 'translate3d(0, 0, 0)' },
    ], { duration: 220, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' })
    return () => animation.cancel()
  }, [route])
  return ref
}
