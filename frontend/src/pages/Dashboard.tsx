import {
  AlertTriangle,
  Cable,
  CircuitBoard,
  Gauge,
  LayoutDashboard,
  RefreshCw,
  Settings2,
  ShieldAlert,
  TrendingDown,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi, qs } from '../api'
import ScopeBanner from '../components/ScopeBanner'
import { useScope } from '../components/ScopeContext'
import { HIDistributionChart } from '../charts/Charts'
import AssetTypeFilter, { TYPE_LABELS, categoryColor } from '../components/AssetTypeFilter'
import SnapshotBar from '../components/SnapshotBar'
import { ErrorNote, HIBadge, Loader, SectionHeader, StatCard } from '../components/ui'
import type { DashboardData } from '../types'

export default function Dashboard() {
  // Opens on transformers - the only asset type with fully configured score
  // bands. Everything else is one click away.
  const [type, setType] = useState('TR')
  const scope = useScope()

  const { data, loading, error, reload } = useApi<DashboardData>(
    `/dashboard${qs({ limit: 250, type, node: scope.node })}`,
    [type, scope.node],
  )

  const untrusted = Object.values(data?.configAudit ?? {}).filter((a) => !a.trustworthy)
  const typeLabel = type === 'all' ? 'all asset types' : (TYPE_LABELS[type] ?? type)
  const scopedTrusted =
    type === 'all' || (data?.availableTypes ?? []).find((t) => t.assetType === type)?.trusted

  return (
    <div>
      <SectionHeader
        accent="#1E72BC"
        icon={LayoutDashboard}
        title="Fleet Dashboard"
        subtitle="Asset inventory and health-index distribution across the transmission fleet"
        actions={
          <button onClick={reload} className="btn-ghost" disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />

      <ScopeBanner label={data?.scope?.label} count={data?.rowsTotal} />
            Refresh
          </button>
        }
      />

      {data && (
        <SnapshotBar status={data.snapshot} source={data.source} onRefreshed={reload} />
      )}

      {error && <ErrorNote message={error} onRetry={reload} />}
      {loading && !data && <Loader label="Loading fleet…" />}

      {data && (
        <>
          {/* Asset counts */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            <StatCard icon={Zap} label="Total Assets" value={data.counts.total.toLocaleString()}
                      sub={`${data.counts.sites} substations`}
                      accent="#123252" />
            <StatCard icon={CircuitBoard} label="Power Transformers"
                      value={data.counts.transformers.toLocaleString()}
                      sub="MT / IBT" accent={categoryColor('TR')} />
            <StatCard icon={Cable} label="Earthing Transformers"
                      value={(data.counts.earthingTransformers ?? 0).toLocaleString()}
                      sub="ET / AT" accent={categoryColor('AET')} />
            <StatCard icon={Settings2} label="OLTC"
                      value={data.counts.oltc.toLocaleString()}
                      sub="tap changers" accent={categoryColor('OLTC')} />
            <StatCard icon={Gauge} label="CT / VT"
                      value={data.counts.ctvt.toLocaleString()}
                      sub={`${data.counts.ct.toLocaleString()} CT · ${data.counts.vt.toLocaleString()} VT`}
                      accent={categoryColor('CTVT')} />
            <StatCard icon={ShieldAlert} label="Surge Arresters"
                      value={data.counts.surgeArresters.toLocaleString()}
                      sub={`${data.counts.circuitBreakers.toLocaleString()} CB · ${data.counts.esds.toLocaleString()} ES/DS`}
                      accent={categoryColor('SA')} />
          </div>

          {/* Configuration health. Types whose bands are unusable would otherwise
              show a near-zero index that reads like a condemned asset. */}
          {/* {untrusted.length > 0 && (
            <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
                <div>
                  <p className="text-sm font-bold text-amber-900">
                    {untrusted.length} asset type
                    {untrusted.length === 1 ? '' : 's'} have incomplete scoring configuration
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-amber-900">
                    Their score bands in <span className="font-mono">SCORE_VALUE</span> are
                    missing or mis-scaled, so their health indices are not valid condition
                    assessments and are excluded from the fleet average.
                  </p>
                  <ul className="mt-2 space-y-1">
                    {untrusted.map((a) => (
                      <li key={a.assetType} className="text-xs text-amber-800">
                        <span className="font-semibold">{a.assetType}</span> — {a.message}{' '}
                        <span className="text-amber-700">
                          ({a.bandsWithIssues}/{a.bandsExpected} band tables affected)
                        </span>
                      </li>
                    ))}
                  </ul>
                  <Link
                    to="/configuration"
                    className="mt-2 inline-block text-xs font-semibold text-amber-900 underline"
                  >
                    Review configuration →
                  </Link>
                </div>
              </div>
            </div>
          )} */}

          {/* Asset-type scope for everything below */}
          <div className="card card-pad mt-4">
            <AssetTypeFilter
              value={type}
              types={data.availableTypes ?? []}
              onChange={setType}
            />
            <p className="mt-2.5 text-[11px] leading-relaxed text-ink-muted">
              The counts above cover the whole fleet. Everything below is scoped to{' '}
              <span className="font-semibold text-ink">{typeLabel}</span>.
              {scopedTrusted === false && (
                <span className="text-amber-800">
                  {' '}
                  Score bands for this type are missing or mis-scaled, so these figures are
                  not condition assessments.
                </span>
              )}
            </p>
          </div>

          {/* Health index summary */}
          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="card lg:col-span-2">
              <div
                className="card-head card-head-accent"
                style={{ '--accent': categoryColor(type) } as React.CSSProperties}
              >
                <h2 className="text-sm font-bold text-ink">
                  Health Index Distribution
                  <span className="ml-1.5 font-normal text-ink-muted">— {typeLabel}</span>
                </h2>
                <span className="num ml-auto text-xs text-ink-muted">
                  {data.scoredCount.toLocaleString()} of {data.evaluated.toLocaleString()} scored
                </span>
              </div>
              <div className="card-pad">
              <HIDistributionChart data={data.distribution} />
              <div className="mt-3 flex flex-wrap gap-3 border-t border-line pt-3">
                {data.bands.map((b) => (
                  <span key={b.key} className="flex items-center gap-1.5 text-[11px] text-ink-soft">
                    <span className="h-2.5 w-2.5 rounded" style={{ background: b.color }} />
                    {b.label}
                    <span className="num text-ink-faint">
                      {Math.max(0, b.min).toFixed(0)}–{Math.min(100, b.max).toFixed(0)}
                    </span>
                  </span>
                ))}
              </div>
              </div>
            </div>

            <div className="card">
              <div
                className="card-pad text-white"
                style={{
                  background: `linear-gradient(150deg, ${categoryColor(type)}, #123252)`,
                }}
              >
                <h2 className="text-sm font-bold">Average — {typeLabel}</h2>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="num text-4xl font-bold">
                    {data.averageHealthIndex?.toFixed(1) ?? '—'}
                  </span>
                  <span className="text-sm text-white/70">/ 100</span>
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-white/75">
                  Higher is healthier. Weighted average of every scored component,
                  normalised over the tests actually available per asset.
                </p>
              </div>
              <div className="card-pad">
              <h3 className="mb-2 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-ink-muted">
                <TrendingDown className="h-3.5 w-3.5" />
                Lowest scoring assets
              </h3>
              <ul className="space-y-1.5">
                {data.worst.slice(0, 8).map((r) => (
                  <li key={r.asset} className="flex items-center justify-between gap-2">
                    <Link
                      to={`/health-index/${encodeURIComponent(r.asset)}`}
                      className="truncate font-mono text-[11px] text-brand-700 hover:underline"
                      title={r.asset}
                    >
                      {r.asset}
                    </Link>
                    <HIBadge value={r.healthIndex} color={r.bandColor} bg={r.bandBg} size="sm" />
                  </li>
                ))}
                {!data.worst.length && (
                  <li className="text-xs text-ink-muted">No assets scored yet.</li>
                )}
              </ul>
              </div>
            </div>
          </div>

          {/* Full table */}
          <div className="card mt-4">
            <div
              className="card-head card-head-accent justify-between"
              style={{ '--accent': categoryColor(type) } as React.CSSProperties}
            >
              <h2 className="text-sm font-bold text-ink">
                Health Index — {typeLabel}, worst first
                {data.rowsTotal ? (
                  <span className="num ml-2 font-normal text-ink-muted">
                    {data.rowsTotal.toLocaleString()} assets
                  </span>
                ) : null}
              </h2>
              <Link
                to={`/health-index${type && type !== 'TR' ? `?type=${type}` : ''}`}
                className="text-xs font-semibold text-brand-700 hover:underline"
              >
                Open full table →
              </Link>
            </div>
            <div className="scroll-x">
              <table className="w-full min-w-[820px] border-collapse">
                <thead>
                  <tr>
                    <th className="th">Asset Number</th>
                    <th className="th">Type</th>
                    <th className="th">Site</th>
                    <th className="th">Health Index</th>
                    <th className="th">Condition</th>
                    <th className="th">Components</th>
                    <th className="th">Coverage</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.slice(0, 60).map((r) => (
                    <tr key={r.asset} className="hover:bg-brand-50/50">
                      <td className="td">
                        <Link
                          to={`/health-index/${encodeURIComponent(r.asset)}`}
                          className="font-mono text-xs text-brand-700 hover:underline"
                        >
                          {r.asset}
                        </Link>
                      </td>
                      <td className="td text-xs text-ink-soft">{r.assetType}</td>
                      <td className="td text-xs text-ink-soft">{r.site}</td>
                      <td className="td">
                        <HIBadge value={r.healthIndex} color={r.bandColor} bg={r.bandBg} />
                      </td>
                      <td className="td text-xs" style={{ color: r.bandColor ?? undefined }}>
                        {r.bandLabel ?? '—'}
                      </td>
                      <td className="td num text-xs text-ink-soft">
                        {r.componentsUsed}/{r.componentsTotal}
                      </td>
                      <td className="td">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-14 overflow-hidden rounded-full bg-brand-100">
                            <div className="h-full rounded-full bg-brand-500"
                                 style={{ width: `${r.coverage}%` }} />
                          </div>
                          <span className="num text-[11px] text-ink-muted">{r.coverage}%</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(data.rowsTotal ?? data.rows.length) > 60 && (
              <div className="border-t border-line px-5 py-2.5 text-center text-xs text-ink-muted">
                Showing 60 of {(data.rowsTotal ?? data.rows.length).toLocaleString()} assets ·{' '}
                <Link to="/health-index" className="font-semibold text-brand-700 hover:underline">
                  see all
                </Link>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
