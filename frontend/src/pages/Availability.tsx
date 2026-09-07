import { Check, ListChecks, Minus, Search } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { qs, useApi } from '../api'
import ScopeBanner from '../components/ScopeBanner'
import { useScope } from '../components/ScopeContext'
import { ErrorNote, Loader, SectionHeader } from '../components/ui'
import type { AvailabilityTest, ScopeEcho } from '../types'

interface Row {
  asset: string
  assetType?: string
  tests: AvailabilityTest[]
}

export default function Availability() {
  const [params] = useSearchParams()
  const [asset, setAsset] = useState(params.get('asset') ?? '')
  const [type, setType] = useState('')
  const [limit, setLimit] = useState(25)
  const scope = useScope()

  // A named asset is an explicit request for that one asset, so the hierarchy
  // scope only narrows the browse list - it never overrides a direct lookup.
  const path = asset
    ? `/availability${qs({ asset })}`
    : `/availability${qs({ type, node: scope.node, limit })}`
  const { data, loading, error, reload } = useApi<{
    rows: Row[]
    total?: number
    scope?: ScopeEcho | null
  }>(path, [asset, type, limit, scope.node])

  const columns = data?.rows?.[0]?.tests ?? []

  return (
    <div>
      <SectionHeader
        accent="#5A6B80"
        icon={ListChecks}
        title="Test Data Availability"
        subtitle="Which tests exist for each asset, with record counts and the last test date"
      />

      {!asset && <ScopeBanner label={data?.scope?.label} count={data?.total} />}

      <div className="card card-pad mb-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="label">Single asset</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
              <input
                className="input pl-9 font-mono text-xs"
                placeholder="Exact asset number…"
                value={asset}
                onChange={(e) => setAsset(e.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="label">…or scan by type</label>
            <select
              className="input"
              value={type}
              onChange={(e) => setType(e.target.value)}
              disabled={!!asset}
            >
              <option value="">All types</option>
              <option value="TR">Power Transformer</option>
              <option value="CTVT">Current / Voltage Transformer</option>
              <option value="CB">Circuit Breaker</option>
              <option value="ESDS">Earth Switch / Disconnector</option>
              <option value="SA">Surge Arrester</option>
            </select>
          </div>
          <div>
            <label className="label">Assets to scan</label>
            <select
              className="input"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              disabled={!!asset}
            >
              {[10, 25, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n} assets
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="mt-3 text-[11px] text-ink-muted">
          Each cell runs the same record selection the health-index readers use, so a
          tick here means the scorer would find data too.
        </p>
      </div>

      {error && <ErrorNote message={error} onRetry={reload} />}
      {loading && <Loader label="Checking test tables…" />}

      {data && !loading && (
        <div className="card">
          <div className="scroll-x">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className="th sticky left-0 z-10 bg-brand-50">Asset</th>
                  {columns.map((c) => (
                    <th key={c.testId} className="th" title={`${c.testId} · ${c.table}`}>
                      <span className="block max-w-[86px] truncate">{c.name}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.asset} className="hover:bg-brand-50/40">
                    <td className="td sticky left-0 z-10 bg-white font-mono text-[11px]">
                      {r.asset}
                    </td>
                    {r.tests.map((t) => (
                      <td key={t.testId} className="td text-center">
                        {t.available ? (
                          <span
                            className="inline-flex flex-col items-center"
                            title={`${t.records} record(s), last ${String(t.lastTested ?? '').slice(0, 10)}`}
                          >
                            <Check className="h-4 w-4 text-emerald-600" />
                            <span className="num text-[10px] text-ink-faint">{t.records}</span>
                          </span>
                        ) : (
                          <Minus className="mx-auto h-4 w-4 text-slate-300" />
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
                {!data.rows.length && (
                  <tr>
                    <td colSpan={columns.length + 1} className="td py-10 text-center text-sm text-ink-muted">
                      No assets matched.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {data.total && data.total > data.rows.length && (
            <div className="border-t border-line px-5 py-2.5 text-center text-xs text-ink-muted">
              Showing {data.rows.length} of {data.total.toLocaleString()} assets
            </div>
          )}
        </div>
      )}
    </div>
  )
}
