import {
  AlertTriangle,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Filter,
  Gauge,
  Search,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { qs, useApi } from '../api'
import AssetTypeFilter, {
  TYPE_LABELS,
  categoryColor,
  type AvailableType,
} from '../components/AssetTypeFilter'
import ScopeBanner from '../components/ScopeBanner'
import { useScope } from '../components/ScopeContext'
import SnapshotBar, { type SnapshotStatus } from '../components/SnapshotBar'
import { ErrorNote, HIBadge, Loader, SectionHeader } from '../components/ui'
import type { HIBand, HIRow, ScopeEcho } from '../types'

type SortKey = 'asset' | 'healthIndex' | 'coverage' | 'assetType'

export default function HealthIndex() {
  const [params] = useSearchParams()
  // The navigator's selection scopes the table to one branch of the hierarchy.
  const scope = useScope()
  // Opens on transformers unless the caller asked for something else.
  const [type, setType] = useState(params.get('type') ?? 'TR')
  const [search, setSearch] = useState('')
  const [band, setBand] = useState('')
  const [limit, setLimit] = useState(200)
  const [page, setPage] = useState(0)
  const [sort, setSort] = useState<SortKey>('healthIndex')
  const [dir, setDir] = useState<'asc' | 'desc'>('asc')

  // Filters change what the server returns, so reset to the first page.
  useEffect(() => setPage(0), [type, limit, scope.node])

  const { data, loading, error, reload } = useApi<{
    total: number
    rows: HIRow[]
    bands: HIBand[]
    availableTypes?: AvailableType[]
    /** Echoed hierarchy scope, so the banner can name it on a cold link. */
    scope?: ScopeEcho | null
    source?: 'snapshot' | 'live'
    snapshot?: SnapshotStatus
  }>(`/health-index${qs({ type, node: scope.node, limit, offset: page * limit })}`, [
    type,
    scope.node,
  ])

  const rows = useMemo(() => {
    let out = data?.rows ?? []
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      out = out.filter((r) => r.asset.toLowerCase().includes(q) || r.site.toLowerCase().includes(q))
    }
    if (band) out = out.filter((r) => r.bandKey === band)
    return [...out].sort((a, b) => {
      const mul = dir === 'asc' ? 1 : -1
      if (sort === 'healthIndex') {
        // Unscored assets always sort last, regardless of direction.
        if (a.healthIndex === null) return 1
        if (b.healthIndex === null) return -1
        return (a.healthIndex - b.healthIndex) * mul
      }
      if (sort === 'coverage') return (a.coverage - b.coverage) * mul
      return String(a[sort]).localeCompare(String(b[sort])) * mul
    })
  }, [data, search, band, sort, dir])

  function toggleSort(key: SortKey) {
    if (sort === key) setDir(dir === 'asc' ? 'desc' : 'asc')
    else {
      setSort(key)
      setDir(key === 'asset' || key === 'assetType' ? 'asc' : 'asc')
    }
  }

  const Th = ({ label, sortKey }: { label: string; sortKey?: SortKey }) => (
    <th className="th">
      {sortKey ? (
        <button
          onClick={() => toggleSort(sortKey)}
          className="inline-flex items-center gap-1 hover:text-brand-700"
        >
          {label}
          <ArrowUpDown className={`h-3 w-3 ${sort === sortKey ? 'text-brand-600' : 'opacity-40'}`} />
        </button>
      ) : (
        label
      )}
    </th>
  )

  return (
    <div>
      <SectionHeader
        accent="#2A78D6"
        icon={Gauge}
        title="Health Index"
        subtitle={`Weighted condition score per asset, colour-coded by band. Higher is healthier. Showing ${
          type === 'all' ? 'all asset types' : (TYPE_LABELS[type] ?? type)
        }.`}
      />

      {data && (
        <SnapshotBar status={data.snapshot} source={data.source} onRefreshed={reload} />
      )}

      <ScopeBanner label={data?.scope?.label} count={data?.total} />

      {/* Filters */}
      <div className="card card-pad mb-4">
        <div className="mb-4 border-b border-line pb-4">
          <AssetTypeFilter
            value={type}
            types={data?.availableTypes ?? []}
            onChange={setType}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="label">Search</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
              <input
                className="input pl-9"
                placeholder="Asset number or site…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="label">Condition band</label>
            <select className="input" value={band} onChange={(e) => setBand(e.target.value)}>
              <option value="">All bands</option>
              {(data?.bands ?? []).map((b) => (
                <option key={b.key} value={b.key}>
                  {b.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Rows per page</label>
            <select
              className="input"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              {[50, 100, 200, 500].map((n) => (
                <option key={n} value={n}>
                  {n} rows
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="mt-3 flex items-start gap-1.5 text-[11px] text-ink-muted">
          <Filter className="mt-px h-3.5 w-3.5 shrink-0" />
          Search and band filters apply to the current page. Type and paging are applied
          by the server across the whole fleet, worst-scoring first.
        </p>
      </div>

      {error && <ErrorNote message={error} onRetry={reload} />}
      {loading && <Loader label="Computing health indices…" />}

      {data && !loading && (
        <div className="card">
          <div
            className="card-head card-head-accent justify-between"
            style={{ '--accent': categoryColor(type) } as React.CSSProperties}
          >
            <span className="text-sm font-semibold text-ink">
              {rows.length} shown
              <span className="ml-1 font-normal text-ink-muted">
                of {data.total.toLocaleString()} matching
              </span>
            </span>
            <div className="flex flex-wrap gap-2">
              {(data.bands ?? []).map((b) => {
                const n = rows.filter((r) => r.bandKey === b.key).length
                return (
                  <button
                    key={b.key}
                    onClick={() => setBand(band === b.key ? '' : b.key)}
                    className={`chip text-[11px] transition-opacity ${
                      band && band !== b.key ? 'opacity-40' : ''
                    }`}
                    style={{ background: b.bg, color: b.color }}
                  >
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: b.color }} />
                    {b.label} <span className="num">{n}</span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="scroll-x">
            <table className="w-full min-w-[880px] border-collapse">
              <thead>
                <tr>
                  <Th label="Asset Number" sortKey="asset" />
                  <Th label="Type" sortKey="assetType" />
                  <Th label="Site" />
                  <Th label="Health Index" sortKey="healthIndex" />
                  <Th label="Condition" />
                  <Th label="Components" />
                  <Th label="Coverage" sortKey="coverage" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.asset} className="hover:bg-brand-50/50">
                    <td className="td">
                      <Link
                        to={`/health-index/${encodeURIComponent(r.asset)}`}
                        className="font-mono text-xs text-brand-700 hover:underline"
                      >
                        {r.asset}
                      </Link>
                    </td>
                    <td className="td text-xs text-ink-soft" title={r.assetTypeLabel}>
                      {r.assetType}
                    </td>
                    <td className="td text-xs text-ink-soft">{r.site}</td>
                    <td className="td">
                      <div className="flex items-center gap-1.5">
                        <HIBadge value={r.healthIndex} color={r.bandColor} bg={r.bandBg} />
                        {r.configTrusted === false && (
                          <span
                            title={`Score bands for ${r.assetType} are missing or mis-scaled — this index is not a valid condition assessment.`}
                          >
                            <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="td text-xs font-medium" style={{ color: r.bandColor ?? undefined }}>
                      {r.configTrusted === false ? (
                        <span className="text-amber-700">not configured</span>
                      ) : (
                        (r.bandLabel ?? '—')
                      )}
                    </td>
                    <td className="td num text-xs text-ink-soft">
                      {r.componentsUsed}/{r.componentsTotal}
                    </td>
                    <td className="td">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-brand-100">
                          <div
                            className="h-full rounded-full bg-brand-500"
                            style={{ width: `${r.coverage}%` }}
                          />
                        </div>
                        <span className="num text-[11px] text-ink-muted">{r.coverage}%</span>
                      </div>
                    </td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr>
                    <td colSpan={7} className="td py-10 text-center text-sm text-ink-muted">
                      {scope.node && !data.total
                        ? `No ${TYPE_LABELS[type] ?? type} beneath this part of the hierarchy.`
                        : 'No assets match the current filters.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {data.total > limit && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
              <span className="num text-xs text-ink-muted">
                Page {page + 1} of {Math.ceil(data.total / limit).toLocaleString()} ·
                rows {(page * limit + 1).toLocaleString()}–
                {Math.min((page + 1) * limit, data.total).toLocaleString()}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0 || loading}
                  className="btn-ghost !py-1.5 !text-xs"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                  Previous
                </button>
                <button
                  onClick={() => setPage((p) => p + 1)}
                  disabled={(page + 1) * limit >= data.total || loading}
                  className="btn-ghost !py-1.5 !text-xs"
                >
                  Next
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
