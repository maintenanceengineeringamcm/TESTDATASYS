import {
  ArrowLeft,
  Calculator,
  ClipboardList,
  Database,
  FileClock,
  Gauge,
  Pencil,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { useApi } from '../api'
import { HIHistoryChart } from '../charts/Charts'
import {
  ConfigWarning,
  ErrorNote,
  HIBadge,
  Loader,
  ScoreBar,
  SectionHeader,
} from '../components/ui'
import type { HIDetail } from '../types'

export default function AssetDetail() {
  // Asset numbers contain slashes (G001/PE/1/02/MT01_X/01), so the route is a
  // splat and the whole tail arrives under the '*' param.
  const params = useParams()
  const decoded = decodeURIComponent(params['*'] ?? '')

  const { data, loading, error, reload } = useApi<HIDetail>(
    `/health-index/${encodeURIComponent(decoded)}`,
  )

  const view = data

  // Age and year of manufacture come from the AGE criterion rather than a
  // second request, so the header can never disagree with the score below it.
  // The year is read from the CMMS (`ast_det_datetime1`, "Year of
  // Manufacture(G)"); assets whose CMMS row is blank or holds the 1900
  // placeholder legitimately have neither.
  const ageComponent = view?.components.find((c) => c.code === 'AGE')
  const manufactureYear = ageComponent?.detail?.manufactureYear as number | undefined
  const ageYears = ageComponent?.available ? ageComponent.value : null

  const history = (data?.storedHistory ?? [])
    .filter((h) => h.healthIndex !== null)
    .map((h) => ({ date: (h.testDate || '').slice(0, 10), value: h.healthIndex as number }))
    .reverse()

  return (
    <div>
      <Link to="/health-index" className="mb-3 inline-flex items-center gap-1.5 text-xs font-semibold text-brand-700 hover:underline">
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Health Index
      </Link>

      <SectionHeader
        accent="#2A78D6"
        icon={Gauge}
        title={decoded}
        subtitle={view ? `${view.assetTypeLabel} · ${view.site || 'unknown site'}` : 'Loading…'}
        actions={
          <Link
            to={`/manual-calculation/${encodeURIComponent(decoded)}`}
            className="btn-ghost"
          >
            <Calculator className="h-4 w-4" />
            Manual calculation
          </Link>
        }
      />

      {error && <ErrorNote message={error} onRetry={reload} />}
      {loading && !data && <Loader label="Computing health index…" />}

      {view && (
        <>
          {view.configAudit && !view.configAudit.trustworthy && (
            <div className="mb-4">
              <ConfigWarning audit={view.configAudit} />
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
            {/* Score summary */}
            <div className="card card-pad">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                Health Index
              </p>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="num text-4xl font-bold" style={{ color: view.band?.color }}>
                  {view.healthIndex?.toFixed(2) ?? '—'}
                </span>
                <span className="text-sm text-ink-muted">/ 100</span>
              </div>
              {view.band && (
                <div className="mt-2">
                  <HIBadge
                    value={view.healthIndex}
                    label={view.band.label}
                    color={view.band.color}
                    bg={view.band.bg}
                    size="lg"
                  />
                </div>
              )}
              <dl className="mt-4 space-y-1.5 border-t border-line pt-3 text-xs">
                <div className="flex justify-between">
                  <dt className="text-ink-muted">Components used</dt>
                  <dd className="num font-semibold text-ink">
                    {view.componentsUsed}/{view.componentsTotal}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">Data coverage</dt>
                  <dd className="num font-semibold text-ink">{view.coverage}%</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">Asset type</dt>
                  <dd className="font-semibold text-ink">{view.assetType}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">Year of manufacture</dt>
                  <dd className="num font-semibold text-ink">
                    {manufactureYear ?? <span className="text-ink-faint">not recorded</span>}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">Age</dt>
                  <dd className="num font-semibold text-ink">
                    {ageYears !== null && ageYears !== undefined ? (
                      `${Number(ageYears).toFixed(0)} yr`
                    ) : (
                      <span className="text-ink-faint">unknown</span>
                    )}
                  </dd>
                </div>
              </dl>
              {ageComponent?.source && (
                <p className="mt-2 text-[10px] leading-relaxed text-ink-faint">
                  Age from{' '}
                  <span className="font-mono">{ageComponent.source}</span>
                  {manufactureYear ? ` · manufactured ${manufactureYear}` : ''}
                </p>
              )}
              {view.message && (
                <p className="mt-3 rounded-lg bg-amber-50 p-2 text-[11px] text-amber-900">
                  {view.message}
                </p>
              )}
            </div>

            {/* Component breakdown */}
            <div className="card lg:col-span-3">
              <div className="card-head !py-3.5">
                <ClipboardList className="h-4 w-4 text-brand-600" />
                <h2 className="text-sm font-bold text-ink">Component Breakdown</h2>
              </div>
              <div className="scroll-x">
                <table className="w-full min-w-[760px] border-collapse">
                  <thead>
                    <tr>
                      <th className="th">Component</th>
                      <th className="th">Measured Value</th>
                      <th className="th">Score</th>
                      <th className="th">Weight</th>
                      <th className="th">Contribution</th>
                      <th className="th">Tested</th>
                      <th className="th">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.components.map((c) => (
                      <tr
                        key={c.code}
                        className={c.available ? 'hover:bg-brand-50/50' : 'bg-slate-50/60'}
                      >
                        <td className="td">
                          <div className="flex items-center gap-1.5">
                            <span className="font-semibold text-ink">{c.label}</span>
                            {c.manual && (
                              <Pencil className="h-3 w-3 text-ink-faint" aria-label="Manual entry" />
                            )}
                          </div>
                          <span className="font-mono text-[10px] text-ink-faint">{c.code}</span>
                        </td>
                        <td className="td num text-xs">
                          {c.value !== null ? (
                            <>
                              {Number(c.value).toLocaleString(undefined, {
                                maximumFractionDigits: 3,
                              })}
                              {c.unit && <span className="ml-1 text-ink-faint">{c.unit}</span>}
                            </>
                          ) : (
                            <span className="text-ink-faint">—</span>
                          )}
                        </td>
                        <td className="td">
                          <ScoreBar score={c.score} />
                        </td>
                        <td className="td num text-xs text-ink-soft">
                          {c.available ? `${c.weight.toFixed(2)}%` : '—'}
                        </td>
                        <td className="td num text-xs font-semibold text-ink">
                          {c.contribution !== null ? c.contribution.toFixed(2) : '—'}
                        </td>
                        <td className="td num text-[11px] text-ink-muted">
                          {c.date ? String(c.date).slice(0, 10) : '—'}
                        </td>
                        <td className="td">
                          {c.source ? (
                            <span className="font-mono text-[10px] text-ink-muted">{c.source}</span>
                          ) : (
                            <span className="text-[11px] text-ink-faint">no data</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="border-t border-line px-5 py-2.5 text-[11px] text-ink-muted">
                Components with no measurement are excluded from weight normalisation
                rather than scored zero, so a missing test never counts as a bad result.
              </p>
            </div>
          </div>

          {/* Manual calculation entry point */}
          <div className="card mt-4">
            <div className="card-pad flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-start gap-3">
                <div className="rounded-xl bg-brand-100 p-2.5">
                  <Calculator className="h-5 w-5 text-brand-700" />
                </div>
                <div>
                  <p className="text-sm font-bold text-ink">Manual calculation</p>
                  <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-ink-muted">
                    Choose exactly which criteria to score on, enter the asset age and any
                    manually assessed components, and see every value the database holds
                    for each criterion with the considered one highlighted.
                  </p>
                </div>
              </div>
              <Link
                to={`/manual-calculation/${encodeURIComponent(decoded)}`}
                className="btn-primary shrink-0"
              >
                <Calculator className="h-4 w-4" />
                Open workbench
              </Link>
            </div>
          </div>

          {/* Stored history */}
          <div className="card mt-4">
            <div className="card-head !py-3.5">
              <FileClock className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Stored Health-Index History</h2>
              <span className="ml-auto text-[11px] text-ink-muted">
                from the HEALTH_INDEX table
              </span>
            </div>
            <div className="card-pad">
              <HIHistoryChart data={history} />
              {(data?.storedHistory ?? []).length > 0 && (
                <div className="scroll-x mt-4">
                  <table className="w-full min-w-[520px] border-collapse">
                    <thead>
                      <tr>
                        <th className="th">Test Date</th>
                        <th className="th">Result</th>
                        <th className="th">Condition</th>
                        <th className="th">Recorded components</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data!.storedHistory!.slice(0, 12).map((h) => (
                        <tr key={h.id} className="hover:bg-brand-50/50">
                          <td className="td num text-xs">{(h.testDate || '').slice(0, 16)}</td>
                          <td className="td">
                            <HIBadge value={h.healthIndex} color={h.bandColor} bg={h.bandBg} />
                          </td>
                          <td className="td text-xs" style={{ color: h.bandColor ?? undefined }}>
                            {h.bandLabel ?? '—'}
                          </td>
                          <td className="td">
                            {h.breakdown ? (
                              <div className="flex flex-wrap gap-1">
                                {h.breakdown.map((b) => (
                                  <span
                                    key={b.code}
                                    className="chip bg-brand-50 text-[10px] text-brand-800"
                                    title={`${b.label}: score ${b.score ?? '—'}, weight ${b.weight ?? '—'}%`}
                                  >
                                    {b.code} <span className="num">{b.score?.toFixed(2)}</span>
                                  </span>
                                ))}
                              </div>
                            ) : (
                              <span className="text-[11px] text-ink-faint">not recorded</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <Link to={`/trend-analysis?asset=${encodeURIComponent(decoded)}`} className="btn-ghost">
              <Database className="h-4 w-4" />
              Trend analysis for this asset
            </Link>
            <Link to={`/duval?asset=${encodeURIComponent(decoded)}`} className="btn-ghost">
              <Gauge className="h-4 w-4" />
              Duval diagnosis
            </Link>
            <Link to={`/availability?asset=${encodeURIComponent(decoded)}`} className="btn-ghost">
              <ClipboardList className="h-4 w-4" />
              Test availability
            </Link>
          </div>
        </>
      )}
    </div>
  )
}
