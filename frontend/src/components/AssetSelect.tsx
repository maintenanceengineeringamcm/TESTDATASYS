import { ChevronDown, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { qs, useApi } from '../api'
import type { Asset } from '../types'
import { useAnchorRect } from './anchored'
import { useScope } from './ScopeContext'

/**
 * Searchable asset picker, scoped by reporting category and site.
 *
 * The fleet is ~13,000 assets, so the search runs on the server and the list is
 * capped; the filters above it are what make the result set navigable. The list
 * is portalled onto <body> so a surrounding `.card` cannot clip it.
 */
export default function AssetSelect({
  value,
  onChange,
  type,
  site,
  label = 'Asset',
  placeholder = 'Search asset number…',
}: {
  value: string
  onChange: (v: string) => void
  type?: string
  site?: string
  label?: string
  placeholder?: string
}) {
  // The picker inherits the navigator's scope, so every screen that uses it
  // narrows to the selected branch without each one wiring it up.
  const scope = useScope()
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)
  const { ref: anchorRef, rect } = useAnchorRect<HTMLDivElement>(open)

  // Typing must not fire a request per keystroke against a fleet-wide scan.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 220)
    return () => clearTimeout(t)
  }, [query])

  const { data, loading } = useApi<{ total: number; items: Asset[] }>(
    `/assets${qs({ type, site, q: debounced, node: scope.node, limit: 60 })}`,
    [type, site, debounced, scope.node],
  )

  const items = data?.items ?? []
  const more = (data?.total ?? 0) - items.length

  return (
    <div>
      <label className="label">{label}</label>
      <div className="relative" ref={anchorRef}>
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
        <input
          className="input pl-9 pr-9 font-mono text-xs"
          placeholder={placeholder}
          value={open ? query : value || query}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
        />
        <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
      </div>

      {open &&
        rect &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[998]" onClick={() => setOpen(false)} />
            <ul
              className="fixed z-[999] max-h-80 overflow-y-auto rounded-lg border border-line bg-white py-1 shadow-pop"
              style={{ left: rect.left, top: rect.top, width: rect.width }}
            >
              {items.map((a) => (
                <li key={a.assetNumber}>
                  <button
                    className="flex w-full items-start justify-between gap-2 px-3 py-2 text-left hover:bg-brand-50"
                    onClick={() => {
                      onChange(a.assetNumber)
                      setQuery('')
                      setOpen(false)
                    }}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-mono text-[11px] text-ink">
                        {a.assetNumber}
                      </span>
                      {a.site && (
                        <span className="block truncate text-[10px] text-ink-faint">
                          {a.site}
                        </span>
                      )}
                    </span>
                    <span className="chip shrink-0 bg-brand-100 text-[10px] text-brand-800">
                      {a.category}
                    </span>
                  </button>
                </li>
              ))}
              {!items.length && (
                <li className="px-3 py-3 text-xs text-ink-muted">
                  {loading ? 'Searching…' : 'No matching asset.'}
                </li>
              )}
              {more > 0 && (
                <li className="border-t border-line px-3 py-2 text-[11px] text-ink-faint">
                  {more.toLocaleString()} more — narrow the search or the filters.
                </li>
              )}
            </ul>
          </>,
          document.body,
        )}
    </div>
  )
}
