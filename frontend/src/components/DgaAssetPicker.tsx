import { ChevronDown, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { qs, useApi } from '../api'
import { useAnchorRect } from './anchored'
import { useScope } from './ScopeContext'

/**
 * Picker over the assets that actually have dissolved-gas history.
 *
 * Distinct from `AssetSelect`, which searches the whole 13,000-asset register:
 * every screen that reads `CEB_DGA_DATA` should offer only the ~800 assets with
 * samples, so a user cannot pick a unit that will come back empty. The list is
 * portalled onto <body> so a surrounding `.card` cannot clip it.
 */
export default function DgaAssetPicker({
  value,
  onChange,
  label = 'Asset with DGA history',
}: {
  value: string
  onChange: (v: string) => void
  label?: string
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const { ref: anchorRef, rect } = useAnchorRect<HTMLDivElement>(open)
  // The picker lists only what the navigator has in scope, so the branch a
  // user selected in the sidebar is the branch they can pick from here.
  const scope = useScope()
  const { data } = useApi<{ items: { assetNumber: string; records: number; latest: string }[] }>(
    `/dga/assets${qs({ node: scope.node })}`,
    [scope.node],
  )

  const items = useMemo(() => {
    const all = (data?.items ?? []).filter((a) => a.records > 0)
    if (!query.trim()) return all.slice(0, 60)
    const q = query.trim().toLowerCase()
    return all.filter((a) => a.assetNumber.toLowerCase().includes(q)).slice(0, 60)
  }, [data, query])

  return (
    <div>
      <label className="label">{label}</label>
      <div className="relative" ref={anchorRef}>
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
        <input
          className="input pl-9 pr-9 font-mono text-xs"
          placeholder="Search asset number…"
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
              className="fixed z-[999] max-h-72 overflow-y-auto rounded-lg border border-line bg-white py-1 shadow-pop"
              style={{ left: rect.left, top: rect.top, width: rect.width }}
            >
              {items.map((a) => (
                <li key={a.assetNumber}>
                  <button
                    className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-brand-50"
                    onClick={() => {
                      onChange(a.assetNumber)
                      setQuery('')
                      setOpen(false)
                    }}
                  >
                    <span className="truncate font-mono text-[11px] text-ink">{a.assetNumber}</span>
                    <span className="num shrink-0 text-[10px] text-ink-faint">
                      {a.records} samples
                    </span>
                  </button>
                </li>
              ))}
              {!items.length && (
                <li className="px-3 py-3 text-xs text-ink-muted">No matching asset.</li>
              )}
            </ul>
          </>,
          document.body,
        )}
    </div>
  )
}
