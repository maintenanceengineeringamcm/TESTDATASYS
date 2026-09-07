import { Activity, ArrowUpDown, ListFilter, Play, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, qs, useApi } from '../api'
import ScopeBanner from '../components/ScopeBanner'
import { useScope } from '../components/ScopeContext'
import { GasTrendChart } from '../charts/Charts'
import { EmptyState, ErrorNote, Loader, SectionHeader } from '../components/ui'
import type { AssetTrend, ScopeEcho } from '../types'

const ALL_GASES = ['H2', 'CH4', 'CO', 'CO2', 'C2H4', 'C2H6', 'C2H2', 'O2', 'N2']

export default function DgaExplorer() {
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [gases, setGases] = useState(['H2', 'C2H2'])
  const [fleet, setFleet] = useState<AssetTrend[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const scope = useScope()

  const { data, loading } = useApi<{
    items: { assetNumber: string; records: number; earliest: string; latest: string }[]
    total?: number
    scope?: ScopeEcho | null
  }>(`/dga/assets${qs({ node: scope.node })}`, [scope.node])

  const items = useMemo(() => {
    const all = (data?.items ?? []).filter((a) => a.records > 0)
    if (!search.trim()) return all
    const q = search.trim().toLowerCase()
    return all.filter((a) => a.assetNumber.toLowerCase().includes(q))
  }, [data, search])

  // A selection made before the scope changed can point outside it. Keeping
  // it would silently score assets the screen is no longer showing.
  useEffect(() => {
    const inScope = new Set((data?.items ?? []).map((a) => a.assetNumber))
    setSelected((prev) => prev.filter((a) => inScope.has(a)))
  }, [data])

  async function scoreFleet() {
    setBusy(true)
    setErr(null)
    try {
      const res = await api.post<{ rows: AssetTrend[] }>('/dga/trend/fleet', {
        assets: selected.length ? selected : items.slice(0, 80).map((a) => a.assetNumber),
      })
      setFleet(res.rows)
    } catch (e: any) {
      setErr(e.message ?? 'Fleet scoring failed')
    } finally {
      setBusy(false)
    }
  }

  const single = selected.length === 1 ? selected[0] : null
  const series = useApi<{ points: Record<string, any>[]; gases: string[] }>(
    single ? `/dga/series/${encodeURIComponent(single)}${qs({ gases: gases.join(',') })}` : null,
  )

  return (
    <div>
      <SectionHeader
        accent="#0F6E8C"
        icon={Activity}
        title="DGA Explorer"
        subtitle="Browse dissolved-gas history, chart gas groups and rank the fleet by trend score"
      />

      <ScopeBanner label={data?.scope?.label} noun="assets with DGA"
                   count={data?.items.length} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Asset list */}
        <div className="card lg:col-span-1">
          <div className="border-b border-line px-4 py-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
              <input
                className="input pl-9 text-xs"
                placeholder="Filter assets…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-ink-muted">
              <span>{items.length} assets with DGA data</span>
              {selected.length > 0 && (
                <button onClick={() => setSelected([])} className="font-semibold text-brand-700 hover:underline">
                  Clear ({selected.length})
                </button>
              )}
            </div>
          </div>
          <div className="max-h-[520px] overflow-y-auto">
            {loading && <Loader />}
            {items.map((a) => {
              const on = selected.includes(a.assetNumber)
              return (
                <button
                  key={a.assetNumber}
                  onClick={() =>
                    setSelected((s) =>
                      on ? s.filter((x) => x !== a.assetNumber) : [...s, a.assetNumber],
                    )
                  }
                  className={`flex w-full items-center justify-between gap-2 border-b border-line/60 px-4 py-2.5 text-left transition-colors ${
                    on ? 'bg-brand-100' : 'hover:bg-brand-50'
                  }`}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-mono text-[11px] text-ink">
                      {a.assetNumber}
                    </span>
                    <span className="num block text-[10px] text-ink-faint">
                      {a.earliest} → {a.latest}
                    </span>
                  </span>
                  <span className="num shrink-0 text-[10px] text-ink-muted">{a.records}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Right panel */}
        <div className="space-y-4 lg:col-span-2">
          <div className="card card-pad">
            <label className="label">Gases to chart</label>
            <div className="flex flex-wrap gap-1.5">
              {ALL_GASES.map((g) => {
                const on = gases.includes(g)
                return (
                  <button
                    key={g}
                    onClick={() =>
                      setGases((cur) => (cur.includes(g) ? cur.filter((x) => x !== g) : [...cur, g]))
                    }
                    className={`chip text-xs ${
                      on ? 'bg-brand-600 text-white' : 'border border-line bg-white text-ink-soft hover:bg-brand-50'
                    }`}
                  >
                    {g}
                  </button>
                )
              })}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button onClick={scoreFleet} className="btn-primary" disabled={busy}>
                <Play className={`h-4 w-4 ${busy ? 'animate-pulse' : ''}`} />
                {busy
                  ? 'Scoring…'
                  : selected.length
                    ? `Score ${selected.length} selected`
                    : 'Score first 80 assets'}
              </button>
            </div>
          </div>

          {single && (
            <div className="card">
              <div className="card-head !py-3.5">
                <Activity className="h-4 w-4 text-brand-600" />
                <h2 className="truncate text-sm font-bold text-ink">
                  <span className="font-mono text-xs">{single}</span>
                </h2>
                <Link
                  to={`/trend-analysis?asset=${encodeURIComponent(single)}`}
                  className="ml-auto shrink-0 text-xs font-semibold text-brand-700 hover:underline"
                >
                  Full trend analysis →
                </Link>
              </div>
              <div className="card-pad">
                {series.loading && <Loader />}
                {series.data && <GasTrendChart points={series.data.points} gases={series.data.gases} />}
              </div>
            </div>
          )}

          {!single && !fleet && (
            <div className="card">
              <EmptyState
                icon={ListFilter}
                title="Select an asset to chart it"
                hint="Pick one asset for its gas chart, or score a group to rank them by trend."
              />
            </div>
          )}

          {err && <ErrorNote message={err} />}

          {fleet && (
            <div className="card">
              <div className="card-head !py-3.5">
                <ArrowUpDown className="h-4 w-4 text-brand-600" />
                <h2 className="text-sm font-bold text-ink">Fleet Trend Ranking</h2>
                <span className="ml-auto text-[11px] text-ink-muted">worst first</span>
              </div>
              <div className="scroll-x">
                <table className="w-full min-w-[820px] border-collapse">
                  <thead>
                    <tr>
                      <th className="th">Asset Number</th>
                      <th className="th">Trend</th>
                      <th className="th">Condition</th>
                      <th className="th">Samples</th>
                      <th className="th">Latest</th>
                      {['H2', 'CH4', 'CO', 'CO2', 'C2H4', 'C2H6', 'C2H2'].map((g) => (
                        <th key={g} className="th">
                          {g}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {fleet.map((r) => (
                      <tr key={r.asset} className="hover:bg-brand-50/50">
                        <td className="td">
                          <Link
                            to={`/trend-analysis?asset=${encodeURIComponent(r.asset)}`}
                            className="font-mono text-[11px] text-brand-700 hover:underline"
                          >
                            {r.asset}
                          </Link>
                        </td>
                        <td className="td num text-xs font-bold" style={{ color: r.conditionColor }}>
                          {r.trend !== null ? r.trend.toFixed(3) : '—'}
                        </td>
                        <td className="td">
                          <span
                            className="chip text-[11px]"
                            style={{ background: `${r.conditionColor}1A`, color: r.conditionColor }}
                          >
                            {r.condition}
                          </span>
                        </td>
                        <td className="td num text-xs">{r.samples}</td>
                        <td className="td num text-[11px] text-ink-muted">
                          {(r.latestSample || '—').slice(0, 10)}
                        </td>
                        {['H2', 'CH4', 'CO', 'CO2', 'C2H4', 'C2H6', 'C2H2'].map((g) => {
                          const gas = r.gases.find((x) => x.gas === g)
                          const v = gas?.subScore
                          return (
                            <td key={g} className="td num text-xs">
                              {v === null || v === undefined ? (
                                <span className="text-ink-faint">—</span>
                              ) : (
                                <span
                                  style={{
                                    color: v >= 1 ? '#0E9F6E' : v >= 0.5 ? '#B7791F' : '#D64545',
                                    fontWeight: 600,
                                  }}
                                >
                                  {v.toFixed(1)}
                                </span>
                              )}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
