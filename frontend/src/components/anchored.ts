import { useLayoutEffect, useRef, useState } from 'react'

export interface AnchorRect {
  left: number
  top: number
  width: number
}

/**
 * Viewport coordinates of an element, kept current while `open`.
 *
 * Dropdowns inside a `.card` cannot be positioned with `absolute`: the card
 * clips with `overflow-hidden`, so the list is cut off however high its
 * z-index. The fix is to portal the list onto `document.body` and place it with
 * `fixed`, which needs the anchor's position in viewport coordinates —
 * re-measured on resize and on scroll (capture phase, so inner scroll
 * containers count too).
 */
export function useAnchorRect<T extends HTMLElement>(open: boolean) {
  const ref = useRef<T>(null)
  const [rect, setRect] = useState<AnchorRect | null>(null)

  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const el = ref.current
      if (!el) return
      const r = el.getBoundingClientRect()
      setRect({ left: r.left, top: r.bottom + 4, width: r.width })
    }
    place()
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [open])

  return { ref, rect }
}
