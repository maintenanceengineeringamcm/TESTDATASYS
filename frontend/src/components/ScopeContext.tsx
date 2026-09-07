import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { HierarchyNode } from '../types'

/**
 * The hierarchy selection, shared by the navigator sidebar and every screen
 * that can be scoped by it.
 *
 * The selection lives in the URL (`?node=`) as well as in state so a filtered
 * view can be bookmarked and pasted to a colleague. The URL is the source of
 * truth on load; state carries the label so the scope banner can name the
 * selection without a second round-trip.
 */
export interface Scope {
  /** Asset number of the selected node — '' when the whole fleet is in view. */
  node: string
  /** Breadcrumb text, e.g. "Biyagama GS > Primary Equipment > 132 kV". */
  label: string
  /** Assets beneath the selection, for the banner count. */
  assetCount: number
  select: (node: HierarchyNode | null) => void
  clear: () => void
}

const ScopeCtx = createContext<Scope>({
  node: '',
  label: '',
  assetCount: 0,
  select: () => {},
  clear: () => {},
})

export const useScope = () => useContext(ScopeCtx)

export function ScopeProvider({ children }: { children: React.ReactNode }) {
  const [params, setParams] = useSearchParams()
  const urlNode = params.get('node') ?? ''

  // Label and count cannot be recovered from the URL alone. When a link is
  // opened cold the banner shows the code until the panel resolves the node.
  const [meta, setMeta] = useState<{ node: string; label: string; assetCount: number }>({
    node: urlNode,
    label: '',
    assetCount: 0,
  })

  const select = useCallback(
    (node: HierarchyNode | null) => {
      const next = new URLSearchParams(params)
      if (!node) {
        next.delete('node')
        setMeta({ node: '', label: '', assetCount: 0 })
      } else {
        next.set('node', node.assetNo)
        setMeta({ node: node.assetNo, label: node.path, assetCount: node.assetCount })
      }
      // Paging is scoped to the old selection, so it must not survive the change.
      next.delete('offset')
      setParams(next, { replace: false })
    },
    [params, setParams],
  )

  const clear = useCallback(() => select(null), [select])

  const value = useMemo<Scope>(
    () => ({
      node: urlNode,
      label: meta.node === urlNode ? meta.label : '',
      assetCount: meta.node === urlNode ? meta.assetCount : 0,
      select,
      clear,
    }),
    [urlNode, meta, select, clear],
  )

  return <ScopeCtx.Provider value={value}>{children}</ScopeCtx.Provider>
}
