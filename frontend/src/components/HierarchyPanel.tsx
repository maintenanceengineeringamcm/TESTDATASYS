import {
  Building2,
  ChevronDown,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  CircuitBoard,
  Cpu,
  Layers,
  Network,
  PanelLeftClose,
  RotateCcw,
  Search,
  Slash,
  X,
  Zap,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, qs, useApi } from '../api'
import type { HierarchyLevel, HierarchyNode } from '../types'
import { useScope } from './ScopeContext'

/** One icon per level so the depth is readable without counting indents. */
const KIND_ICON: Record<string, typeof Zap> = {
  site: Building2,
  discipline: Layers,
  voltage: Zap,
  bay: Network,
  equipment: CircuitBoard,
  oltc: RotateCcw,
  unit: Cpu,
  unassigned: Slash,
}

function KindIcon({ kind }: { kind: string }) {
  const Icon = KIND_ICON[kind] ?? Cpu
  return <Icon className="h-3.5 w-3.5 shrink-0 text-brand-500" />
}

/**
 * One row of the tree.
 *
 * Children are fetched on first expand rather than up front — the full tree is
 * 27k nodes, and a user opens one branch of it.
 */
function TreeRow({
  node,
  depth,
  expanded,
  onToggle,
  selected,
  onSelect,
  flagDerived,
}: {
  node: HierarchyNode
  depth: number
  expanded: Set<string>
  onToggle: (assetNo: string) => void
  selected: string
  onSelect: (n: HierarchyNode) => void
  /** Mark rows with no CMMS description, once the CMMS is supplying names. */
  flagDerived: boolean
}) {
  const isOpen = expanded.has(node.assetNo)
  const hasKids = node.childCount > 0
  const isSelected = selected === node.assetNo

  const { data, loading } = useApi<HierarchyLevel>(
    isOpen ? `/hierarchy${qs({ parent: node.assetNo })}` : null,
  )

  // Only worth flagging when the rest of the tree has real names; if nothing
  // does, italicising every row says nothing.
  const derivedName = flagDerived && !node.named

  return (
    <li>
      <div
        className={`group flex items-center gap-1 rounded-md pr-1 transition-colors ${
          isSelected ? 'bg-brand-100 ring-1 ring-brand-300' : 'hover:bg-brand-50'
        }`}
        style={{ paddingLeft: depth * 12 }}
      >
        <button
          onClick={() => hasKids && onToggle(node.assetNo)}
          className={`flex h-6 w-5 shrink-0 items-center justify-center rounded
                      text-ink-faint ${hasKids ? 'hover:text-brand-700' : 'invisible'}`}
          aria-label={isOpen ? `Collapse ${node.label}` : `Expand ${node.label}`}
          aria-expanded={hasKids ? isOpen : undefined}
        >
          {isOpen ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </button>

        <button
          onClick={() => onSelect(node)}
          title={
            derivedName
              ? `${node.label}\n${node.assetNo}\n(no CMMS description — name derived from the code)`
              : `${node.label}\n${node.assetNo}`
          }
          className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left"
        >
          <KindIcon kind={node.kind} />
          <span className="min-w-0 flex-1">
            {/* Name first, code second. Users are looking for "Biyagama", not
                for G008 — the code stays visible for cross-checking. */}
            <span
              className={`block truncate text-xs leading-tight ${
                isSelected ? 'font-semibold text-brand-800' : 'text-ink'
              } ${derivedName ? 'italic text-ink-muted' : ''}`}
            >
              {node.label}
            </span>
            <span className="block truncate font-mono text-[10px] leading-tight text-ink-faint">
              {node.code}
            </span>
          </span>
          <span className="num shrink-0 text-[10px] text-ink-muted">
            {node.assetCount.toLocaleString()}
          </span>
        </button>
      </div>

      {isOpen && (
        <ul>
          {loading && (
            <li className="py-1 text-[11px] text-ink-faint" style={{ paddingLeft: (depth + 1) * 12 + 20 }}>
              Loading…
            </li>
          )}
          {data?.items.map((child) => (
            <TreeRow
              key={child.assetNo}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              onToggle={onToggle}
              selected={selected}
              onSelect={onSelect}
              flagDerived={flagDerived}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

/**
 * The asset navigator — the second sidebar.
 *
 * Two ways in, because engineers arrive knowing different things: search by
 * name when the code is not remembered, browse the tree when it is a matter of
 * "everything at this substation". Either way the result is a scope filter that
 * the analysis screens honour.
 */
export default function HierarchyPanel({ onCollapse }: { onCollapse: () => void }) {
  const scope = useScope()
  const [term, setTerm] = useState('')
  const [debounced, setDebounced] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [busyExpand, setBusyExpand] = useState(false)

  // Search runs server-side over 27k nodes; typing must not fire per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term.trim()), 220)
    return () => clearTimeout(timer)
  }, [term])

  const roots = useApi<HierarchyLevel>('/hierarchy')
  const results = useApi<{ items: HierarchyNode[] }>(
    debounced.length >= 2 ? `/hierarchy/search${qs({ q: debounced, limit: 60 })}` : null,
    [debounced],
  )

  const searching = debounced.length >= 2

  // Expand-all walks the tree a level at a time rather than fetching all 27k
  // nodes: it opens what is already loaded, and each newly opened level loads
  // its own children, which the next click can open in turn. Opening every
  // level at once would be tens of thousands of rows in the DOM.
  async function expandVisible() {
    const level = roots.data?.items ?? []
    if (!level.length) return
    setBusyExpand(true)
    try {
      const open = new Set(expanded)
      // Two levels deep is the useful default: substation -> discipline.
      const queue = level.filter((n) => n.childCount > 0)
      queue.forEach((n) => open.add(n.assetNo))
      const nested = await Promise.all(
        queue.map((n) =>
          api
            .get<HierarchyLevel>(`/hierarchy${qs({ parent: n.assetNo })}`)
            .catch(() => null),
        ),
      )
      nested.forEach((lvl) =>
        lvl?.items.forEach((c) => c.childCount > 0 && open.add(c.assetNo)),
      )
      setExpanded(open)
    } finally {
      setBusyExpand(false)
    }
  }

  function collapseAll() {
    setExpanded(new Set())
  }

  function toggle(assetNo: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(assetNo)) next.delete(assetNo)
      else next.add(assetNo)
      return next
    })
  }

  // Selecting a search hit also opens its branch in the tree, so clearing the
  // search box leaves the user where they landed rather than back at the top.
  const openedFor = useRef('')
  async function selectAndReveal(node: HierarchyNode) {
    scope.select(node)
    if (openedFor.current === node.assetNo) return
    openedFor.current = node.assetNo
    try {
      const trail = await api.get<{ ancestors: HierarchyNode[] }>(
        `/hierarchy/node/${node.assetNo.split('/').map(encodeURIComponent).join('/')}`,
      )
      setExpanded((prev) => {
        const next = new Set(prev)
        // The node itself is not expanded — only the path down to it.
        trail.ancestors.slice(0, -1).forEach((a) => next.add(a.assetNo))
        return next
      })
    } catch {
      /* Reveal is a convenience; a failure must not block the selection. */
    }
  }

  const derived = roots.data?.source === 'derived'
  const status = roots.data?.status

  const summary = useMemo(() => {
    if (!roots.data) return ''
    return `${roots.data.roots} substations · ${roots.data.assets.toLocaleString()} in service`
  }, [roots.data])

  return (
    <div className="flex h-full w-72 shrink-0 flex-col border-r border-line bg-white">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-line bg-gradient-to-r from-brand-50 to-white px-3 py-2.5">
        <Network className="h-4 w-4 shrink-0 text-brand-600" />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-bold text-ink">Asset Navigator</p>
          <p className="num truncate text-[10px] text-ink-muted">{summary}</p>
        </div>
        <button
          onClick={onCollapse}
          className="rounded-md p-1 text-ink-faint hover:bg-brand-100 hover:text-brand-700"
          title="Hide navigator"
          aria-label="Hide navigator"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      {/* Search */}
      <div className="border-b border-line px-3 py-2.5">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
          <input
            className="input !py-1.5 !pl-8 !pr-7 !text-xs"
            placeholder="Search by name or code…"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            aria-label="Search the asset hierarchy"
          />
          {term && (
            <button
              onClick={() => setTerm('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-faint hover:text-ink"
              aria-label="Clear search"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <p className="mt-1.5 text-[10px] leading-tight text-ink-muted">
          {searching
            ? `${results.data?.items.length ?? 0} matches — every word must appear`
            : 'Try “biyagama 132 transformer” or a code such as G008'}
        </p>
      </div>

      {/* Active scope */}
      {scope.node && (
        <div className="border-b border-line bg-brand-50 px-3 py-2">
          <div className="flex items-start gap-1.5">
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-brand-700">
                Filtering
              </p>
              <p className="truncate text-[11px] font-medium text-ink" title={scope.label || scope.node}>
                {scope.label || scope.node}
              </p>
              <p className="num truncate font-mono text-[10px] text-ink-muted">{scope.node}</p>
            </div>
            <button
              onClick={scope.clear}
              className="shrink-0 rounded-md p-1 text-ink-faint hover:bg-white hover:text-brand-700"
              title="Clear filter"
              aria-label="Clear hierarchy filter"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Tree controls. Hidden while searching, where results are a flat list
          and there is nothing to expand. */}
      {!searching && (
        <div className="flex items-center gap-1 border-b border-line px-2 py-1.5">
          <button
            onClick={expandVisible}
            disabled={busyExpand}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium
                       text-ink-soft hover:bg-brand-50 hover:text-brand-700
                       disabled:opacity-50"
            title="Open the substation and discipline levels"
          >
            <ChevronsUpDown className="h-3.5 w-3.5" />
            {busyExpand ? 'Expanding…' : 'Expand'}
          </button>
          <button
            onClick={collapseAll}
            disabled={!expanded.size}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium
                       text-ink-soft hover:bg-brand-50 hover:text-brand-700
                       disabled:opacity-40"
            title="Close every open branch"
          >
            <ChevronsDownUp className="h-3.5 w-3.5" />
            Collapse
          </button>
          {expanded.size > 0 && (
            <span className="num ml-auto pr-1 text-[10px] text-ink-faint">
              {expanded.size} open
            </span>
          )}
        </div>
      )}

      {/* Tree / results */}
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {searching ? (
          <ul className="space-y-0.5">
            {results.loading && <li className="px-2 py-2 text-xs text-ink-muted">Searching…</li>}
            {!results.loading && !results.data?.items.length && (
              <li className="px-2 py-3 text-xs text-ink-muted">
                Nothing matches “{debounced}”.
              </li>
            )}
            {results.data?.items.map((node) => (
              <li key={node.assetNo}>
                <button
                  onClick={() => selectAndReveal(node)}
                  className={`flex w-full items-start gap-1.5 rounded-md px-2 py-1.5 text-left
                              transition-colors ${
                                scope.node === node.assetNo
                                  ? 'bg-brand-100 ring-1 ring-brand-300'
                                  : 'hover:bg-brand-50'
                              }`}
                >
                  <span className="mt-0.5">
                    <KindIcon kind={node.kind} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium text-ink">
                      {node.label}
                    </span>
                    {/* The breadcrumb is what disambiguates two bays with the
                        same name at different substations. */}
                    <span className="block truncate text-[10px] leading-tight text-ink-muted">
                      {node.path}
                    </span>
                    <span className="block truncate font-mono text-[10px] leading-tight text-ink-faint">
                      {node.assetNo}
                    </span>
                  </span>
                  <span className="num shrink-0 text-[10px] text-ink-muted">
                    {node.assetCount.toLocaleString()}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <ul>
            {roots.loading && <li className="px-2 py-2 text-xs text-ink-muted">Loading tree…</li>}
            {roots.error && (
              <li className="px-2 py-2 text-xs text-red-600">{roots.error}</li>
            )}
            {roots.data?.items.map((node) => (
              <TreeRow
                key={node.assetNo}
                node={node}
                depth={0}
                expanded={expanded}
                onToggle={toggle}
                selected={scope.node}
                onSelect={scope.select}
                flagDerived={!derived}
              />
            ))}
          </ul>
        )}
      </div>

      {/* Provenance. Which source produced these names is not a detail — it is
          the difference between an engineer's description and one this app
          inferred from the code. The same goes for the status filter: whether
          it actually ran changes what the tree is claiming to show. */}
      {roots.data && (
        <div className="space-y-1 border-t border-line px-3 py-2 text-[10px] leading-tight text-ink-muted">
          <p className={derived ? 'text-amber-700' : undefined}>
            {derived ? (
              <>
                Names derived from asset codes — no{' '}
                <span className="font-mono">ast_mst_asset_shortdesc</span> available. Set{' '}
                <span className="font-mono">HI_TOMMS_DB_SERVER</span>, or run{' '}
                <span className="font-mono">sync_hierarchy.py</span>.
              </>
            ) : (
              <>
                Names are <span className="font-mono">ast_mst_asset_shortdesc</span> from
                the CMMS{roots.data.source === 'staging' ? ' (staged copy)' : ''}
                {roots.data.named < roots.data.nodes && (
                  <>
                    {' '}— {roots.data.named.toLocaleString()} of{' '}
                    {roots.data.nodes.toLocaleString()} nodes; the rest keep a derived name
                  </>
                )}
                .
              </>
            )}
          </p>
          {status && (
            <p className={status.available ? 'text-ink-muted' : 'text-amber-700'}>
              {status.available ? (
                <>
                  Showing <span className="font-semibold">{status.keep.join(' / ')}</span> only
                  {status.excluded > 0 && (
                    <> — {status.excluded.toLocaleString()} not in service hidden</>
                  )}
                  .
                </>
              ) : (
                <>
                  <span className="font-semibold">{status.keep.join(' / ')}</span> filter is set
                  but no status data exists yet, so all{' '}
                  {status.unknown.toLocaleString()} assets are shown.
                </>
              )}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
