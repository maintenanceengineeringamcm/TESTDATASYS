import { Building2, Cable, CircuitBoard, Gauge, Search, Settings2, Zap } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { qs, useApi } from '../api'
import ScopeBanner from '../components/ScopeBanner'
import { useScope } from '../components/ScopeContext'
import { TYPE_LABELS, categoryColor } from '../components/AssetTypeFilter'
import { ErrorNote, Loader, SectionHeader, StatCard } from '../components/ui'
import type { Asset, AssetCounts, ScopeEcho } from '../types'

const TYPES = [
  { value: '', label: 'All types' },
  ...['TR', 'AET', 'OLTC', 'CTVT', 'CB', 'ESDS', 'SA', 'OTHER'].map((v) => ({
    value: v,
    label: TYPE_LABELS[v] ?? v,
  })),
]

export default function AssetRegister() {
  const [type, setType] = useState('')
  const [site, setSite] = useState('')
  const [search, setSearch] = useState('')

  const scope = useScope()

  const counts = useApi<AssetCounts>('/assets/counts')
  const sites = useApi<{ items: { site: string; total: number }[] }>('/assets/sites')
  const { data, loading, error, reload } = useApi<{
    total: number
    items: Asset[]
    scope?: ScopeEcho | null
  }>(
    `/assets${qs({ type, site, q: search, node: scope.node, limit: 500 })}`,
    [type, site, search, scope.node],
  )

  return (
    <div>
      <SectionHeader
        accent="#41708C"
        icon={Zap}
        title="Asset Register"
        subtitle="Inventory derived from the asset numbering in the live test tables"
      />

      <ScopeBanner label={data?.scope?.label} count={data?.total} />

      {counts.data && (
        <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
          <StatCard icon={Zap} label="Total" value={counts.data.total.toLocaleString()}
                    accent="#123252" />
          <StatCard icon={CircuitBoard} label="Power Transformers"
                    value={counts.data.transformers.toLocaleString()}
                    accent={categoryColor('TR')} />
          <StatCard icon={Cable} label="Earthing Transformers"
                    value={(counts.data.earthingTransformers ?? 0).toLocaleString()}
                    accent={categoryColor('AET')} />
          <StatCard icon={Settings2} label="OLTC"
                    value={counts.data.oltc.toLocaleString()}
                    accent={categoryColor('OLTC')} />
          <StatCard icon={Gauge} label="CT / VT"
                    value={counts.data.ctvt.toLocaleString()}
                    sub={`${counts.data.ct.toLocaleString()} CT · ${counts.data.vt.toLocaleString()} VT`}
                    accent={categoryColor('CTVT')} />
          <StatCard icon={Building2} label="Substations"
                    value={counts.data.sites.toLocaleString()}
                    accent={categoryColor('OTHER')} />
        </div>
      )}

      <div className="card card-pad mb-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="label">Search</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
              <input
                className="input pl-9"
                placeholder="Asset number…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="label">Type</label>
            <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Substation</label>
            <select className="input" value={site} onChange={(e) => setSite(e.target.value)}>
              <option value="">All substations</option>
              {(sites.data?.items ?? []).map((s) => (
                <option key={s.site} value={s.site}>
                  {s.site} ({s.total})
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {error && <ErrorNote message={error} onRetry={reload} />}
      {loading && <Loader />}

      {data && !loading && (
        <div className="card">
          <div className="card-head text-sm font-semibold text-ink">
            {data.items.length.toLocaleString()} shown of {data.total.toLocaleString()} matching
          </div>
          <div className="scroll-x">
            <table className="w-full min-w-[820px] border-collapse">
              <thead>
                <tr>
                  <th className="th">Asset Number</th>
                  <th className="th">Equipment</th>
                  <th className="th">Type</th>
                  <th className="th">Site</th>
                  <th className="th">Bay</th>
                  <th className="th">Phase</th>
                  <th className="th">Data sources</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((a) => (
                  <tr key={a.assetNumber} className="hover:bg-brand-50/50">
                    <td className="td">
                      <Link
                        to={`/health-index/${encodeURIComponent(a.assetNumber)}`}
                        className="font-mono text-xs text-brand-700 hover:underline"
                      >
                        {a.assetNumber}
                      </Link>
                    </td>
                    <td className="td text-xs text-ink-soft">{a.label}</td>
                    <td className="td text-xs">
                      <span
                        className="chip text-[11px]"
                        style={{
                          background: `${categoryColor(a.category)}1A`,
                          color: categoryColor(a.category),
                        }}
                      >
                        {TYPE_LABELS[a.category] ?? a.category}
                      </span>
                    </td>
                    <td className="td text-xs text-ink-soft">{a.site}</td>
                    <td className="td num text-xs text-ink-soft">{a.bay}</td>
                    <td className="td text-xs text-ink-soft">{a.phase || '—'}</td>
                    <td className="td">
                      <div className="flex flex-wrap gap-1">
                        {a.sources.map((s) => (
                          <span key={s} className="font-mono text-[10px] text-ink-faint">
                            {s}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
