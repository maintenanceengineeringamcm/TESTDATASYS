import {
  Activity,
  Droplets,
  Pentagon as PentagonIcon,
  Plus,
  RotateCcw,
  Table2,
  Trash2,
  TrendingUp,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, qs, useApi } from '../api'
import DgaAssetPicker from '../components/DgaAssetPicker'
import ScopeBanner from '../components/ScopeBanner'
import { GasTrendChart, type ChartMarker } from '../charts/Charts'
import { Badge, EmptyState, ErrorNote, Loader, SectionHeader, Toggle } from '../components/ui'
import type {
  AssetTrend,
  FilterPoint,
  FilterPoints,
} from '../types'

const ALL_GASES = ['H2', 'CH4', 'CO', 'CO2', 'C2H4', 'C2H6', 'C2H2', 'O2', 'N2']

// Marker colours stay off the condition hues (green/amber/red are reserved).
const MARKER = { detected: '#0F6E8C', manual: '#7C3AED', start: '#123252' }

const today = () => new Date().toISOString().slice(0, 10)

/** "CO2 7456→258, CO 455→43" for a detected point. */
function dropSummary(p: FilterPoint) {
  return p.droppedGases
    .map((g) => `${g} ${p.gases[g]?.before ?? '—'}→${p.gases[g]?.after ?? '—'}`)
    .join(', ')
}

export default function TrendAnalysis() {
  const [params, setParams] = useSearchParams()
  const [asset, setAsset] = useState(params.get('asset') ?? '')
  const [gases, setGases] = useState(['H2', 'CH4', 'C2H4', 'C2H6', 'C2H2'])
  const [showWorkings, setShowWorkings] = useState(false)

  // Analysis window. Empty means "all data" on that side.
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  // Filter point the trend is scored from ('' = no filter point).
  const [startId, setStartId] = useState('')
  const [showEarlier, setShowEarlier] = useState(false)

  // New manual mark.
  const [markDate, setMarkDate] = useState('')
  const [markNote, setMarkNote] = useState('')
  const [markBusy, setMarkBusy] = useState(false)
  const [markError, setMarkError] = useState<string | null>(null)

  useEffect(() => {
    if (asset) setParams({ asset }, { replace: true })
    setStartId('')
    setMarkError(null)
  }, [asset])

  const filters = useApi<FilterPoints>(
    asset ? `/dga/filter-points/${encodeURIComponent(asset)}` : null,
  )
  const points = filters.data?.points ?? []
  const active = useMemo(() => points.filter((p) => !p.rejected), [points])
  const startPoint = active.find((p) => p.id === startId) ?? null

  // A rejected or deleted start point falls back to all data.
  useEffect(() => {
    if (startId && filters.data && !startPoint) setStartId('')
  }, [filters.data, startId, startPoint])

  // Scoring starts at the later of the date-range start and the filter point.
  const analysisFrom = [dateFrom, startPoint?.date ?? '']
    .filter(Boolean)
    .sort()
    .pop() ?? ''
  const windowed = Boolean(analysisFrom || dateTo)

  const trend = useApi<AssetTrend>(
    asset
      ? `/dga/trend/${encodeURIComponent(asset)}${
          windowed ? qs({ fullHistory: 'false', from: analysisFrom, to: dateTo }) : ''
        }`
      : null,
  )
  // The chart can keep the samples before a filter point on screen, greyed.
  const chartFrom = startPoint && showEarlier ? dateFrom : analysisFrom
  const series = useApi<{ points: Record<string, any>[]; gases: string[] }>(
    asset
      ? `/dga/series/${encodeURIComponent(asset)}${qs({
          gases: gases.join(','),
          from: chartFrom,
          to: dateTo,
        })}`
      : null,
  )

  const markers: ChartMarker[] = active.map((p) => ({
    key: p.id,
    date: p.date,
    label: p.id === startId ? 'Start' : p.source === 'manual' ? 'Filter (marked)' : 'Filter?',
    color: p.id === startId ? MARKER.start : MARKER[p.source],
    dashed: p.source === 'detected' && p.id !== startId,
  }))

  async function addMark(date: string, kind: 'manual' | 'rejected', note?: string) {
    setMarkBusy(true)
    setMarkError(null)
    try {
      await api.post(`/dga/filter-points/${encodeURIComponent(asset)}`, { date, kind, note })
      filters.reload()
      if (kind === 'manual') {
        setMarkDate('')
        setMarkNote('')
      }
    } catch (e: any) {
      setMarkError(e.message ?? 'Could not save the filter point')
    } finally {
      setMarkBusy(false)
    }
  }

  async function removeMark(id: number) {
    setMarkBusy(true)
    setMarkError(null)
    try {
      await api.del(`/dga/filter-points${qs({ asset, id })}`)
      filters.reload()
    } catch (e: any) {
      setMarkError(e.message ?? 'Could not remove the filter point')
    } finally {
      setMarkBusy(false)
    }
  }

  function clearWindow() {
    setDateFrom('')
    setDateTo('')
    setStartId('')
  }

  return (
    <div>
      <SectionHeader
        accent="#0F6E8C"
        icon={TrendingUp}
        title="Trend Analysis"
        subtitle="IEEE C57.104 gas trend score, gas concentration charts and oil filtration points for one transformer"
      />

      <ScopeBanner />

      <div className="card card-pad mb-4">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <DgaAssetPicker value={asset} onChange={setAsset} />
          <div className="lg:col-span-2">
            <label className="label">Gases to chart</label>
            <div className="flex flex-wrap gap-1.5">
              {ALL_GASES.map((g) => {
                const on = gases.includes(g)
                return (
                  <button
                    key={g}
                    onClick={() =>
                      setGases((cur) =>
                        cur.includes(g) ? cur.filter((x) => x !== g) : [...cur, g],
                      )
                    }
                    className={`chip text-xs transition-colors ${
                      on
                        ? 'bg-brand-600 text-white'
                        : 'bg-white text-ink-soft border border-line hover:bg-brand-50'
                    }`}
                  >
                    {g}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        {asset && (
          <div className="mt-4 grid grid-cols-1 gap-4 border-t border-line pt-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="label">From date</label>
              <input
                className="input num"
                type="date"
                max={dateTo || today()}
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </div>
            <div>
              <label className="label">To date</label>
              <input
                className="input num"
                type="date"
                min={dateFrom || undefined}
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </div>
            <div>
              <label className="label">Analyse trend from</label>
              <select
                className="input"
                value={startId}
                onChange={(e) => setStartId(e.target.value)}
                disabled={!active.length}
              >
                <option value="">
                  {active.length ? 'All data (no filter point)' : 'No filter points'}
                </option>
                {active.map((p) => (
                  <option key={p.id} value={p.id}>
                    After filter point {p.date} ({p.source === 'manual' ? 'marked' : 'detected'})
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col justify-end gap-2">
              <Toggle
                checked={showEarlier}
                onChange={setShowEarlier}
                label="Show earlier samples on chart"
              />
              <button
                onClick={clearWindow}
                className="btn-ghost !justify-start !px-2 !py-1 !text-[11px]"
                disabled={!dateFrom && !dateTo && !startId}
              >
                <X className="h-3.5 w-3.5" />
                Clear — show all data
              </button>
            </div>
          </div>
        )}
      </div>

      {!asset && (
        <div className="card">
          <EmptyState
            icon={Activity}
            title="Select an asset to begin"
            hint="Pick a transformer with dissolved-gas history to see its trend score, gas
                  charts and Duval diagnosis."
          />
        </div>
      )}

      {asset && (
        <div className="space-y-4">
          {/* --- Trend score --- */}
          <div className="card">
            <div className="card-head !py-3.5">
              <TrendingUp className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">DGA Trend Score (IEEE C57.104)</h2>
            </div>
            {trend.loading && <Loader label="Scoring gas trend…" />}
            {trend.error && <div className="card-pad"><ErrorNote message={trend.error} /></div>}
            {trend.data && (
              <div className="card-pad">
                <div className="flex flex-wrap items-start gap-6">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                      Trend value
                    </p>
                    <div className="mt-1 flex items-baseline gap-2">
                      <span
                        className="num text-4xl font-bold"
                        style={{ color: trend.data.conditionColor }}
                      >
                        {trend.data.trend !== null ? trend.data.trend.toFixed(3) : '—'}
                      </span>
                      <span className="text-sm text-ink-muted">/ 1.000</span>
                    </div>
                    <span
                      className="chip mt-2 text-xs"
                      style={{
                        background: `${trend.data.conditionColor}1A`,
                        color: trend.data.conditionColor,
                      }}
                    >
                      {trend.data.condition}
                    </span>
                  </div>
                  <dl className="grid flex-1 grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
                    <div>
                      <dt className="text-ink-muted">Samples</dt>
                      <dd className="num font-semibold text-ink">{trend.data.samples}</dd>
                    </div>
                    <div>
                      <dt className="text-ink-muted">First sample</dt>
                      <dd className="num font-semibold text-ink">
                        {(trend.data.firstSample || '—').slice(0, 10)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-ink-muted">Latest sample</dt>
                      <dd className="num font-semibold text-ink">
                        {(trend.data.latestSample || '—').slice(0, 10)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-ink-muted">Weight denominator</dt>
                      <dd className="num font-semibold text-ink">{trend.data.denominator} / 18</dd>
                    </div>
                  </dl>
                </div>

                <p className="mt-3 rounded-lg bg-brand-50 p-2.5 text-xs text-ink-soft">
                  {trend.data.message}
                </p>
                <p className="mt-2 text-[11px] text-ink-muted">
                  {windowed ? (
                    <>
                      Scored on samples from{' '}
                      <span className="num font-semibold text-ink-soft">
                        {analysisFrom || 'the first sample'}
                      </span>{' '}
                      to{' '}
                      <span className="num font-semibold text-ink-soft">
                        {dateTo || 'the latest sample'}
                      </span>
                      {startPoint && (
                        <>
                          {' '}— after the {startPoint.source === 'manual' ? 'marked' : 'detected'}{' '}
                          filter point of {startPoint.date}
                        </>
                      )}
                      .
                    </>
                  ) : (
                    'Scored on the full sample history.'
                  )}
                </p>

                {/* Per-gas table */}
                <div className="scroll-x mt-4">
                  <table className="w-full min-w-[860px] border-collapse">
                    <thead>
                      <tr>
                        <th className="th">Gas</th>
                        <th className="th">Latest</th>
                        <th className="th">Previous</th>
                        <th className="th">Difference</th>
                        <th className="th">Table 3 limit</th>
                        <th className="th">Rate (ppm/yr)</th>
                        <th className="th">Table 4 limit</th>
                        <th className="th">Score 1</th>
                        <th className="th">Score 2</th>
                        <th className="th">Sub score</th>
                        <th className="th">Weight</th>
                        <th className="th">Note</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trend.data.gases.map((g) => (
                        <tr key={g.gas} className="hover:bg-brand-50/50">
                          <td className="td font-semibold">{g.gas}</td>
                          <td className="td num text-xs">{g.latest?.toFixed(1) ?? '—'}</td>
                          <td className="td num text-xs">{g.previous?.toFixed(1) ?? '—'}</td>
                          <td className="td num text-xs">
                            {g.difference !== null ? (
                              <span className={g.difference > 0 ? 'text-red-600' : 'text-emerald-600'}>
                                {g.difference > 0 ? '+' : ''}
                                {g.difference.toFixed(1)}
                              </span>
                            ) : (
                              '—'
                            )}
                          </td>
                          <td className="td num text-xs text-ink-muted">{g.table3Limit}</td>
                          <td className="td num text-xs">{g.rate?.toFixed(1) ?? '—'}</td>
                          <td className="td num text-xs text-ink-muted">
                            {g.table4Limit ?? '—'}
                          </td>
                          <td className="td num text-xs">{g.score1?.toFixed(1) ?? '—'}</td>
                          <td className="td num text-xs">{g.score2?.toFixed(1) ?? '—'}</td>
                          <td className="td">
                            {g.subScore !== null ? (
                              <span
                                className="chip num text-xs"
                                style={{
                                  background:
                                    g.subScore >= 1 ? '#E6F6F0' : g.subScore >= 0.5 ? '#FDF6E3' : '#FCEAEA',
                                  color:
                                    g.subScore >= 1 ? '#0E9F6E' : g.subScore >= 0.5 ? '#B7791F' : '#D64545',
                                }}
                              >
                                {g.subScore.toFixed(1)}
                              </span>
                            ) : (
                              <span className="text-xs text-ink-faint">—</span>
                            )}
                          </td>
                          <td className="td num text-xs text-ink-muted">{g.weight}</td>
                          <td className="td text-[11px] text-ink-muted">{g.note || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <button
                  onClick={() => setShowWorkings((v) => !v)}
                  className="btn-ghost mt-3"
                >
                  <Table2 className="h-4 w-4" />
                  {showWorkings ? 'Hide' : 'Show'} full working table (audit trail)
                </button>

                {showWorkings && (
                  <div className="scroll-x mt-3 rounded-lg border border-line">
                    <table className="w-full min-w-[900px] border-collapse">
                      <thead>
                        <tr>
                          <th className="th">Gas</th>
                          <th className="th">Sample</th>
                          <th className="th">Date</th>
                          <th className="th">Days from 01</th>
                          <th className="th">Period (T4)</th>
                          <th className="th">Level (ppm)</th>
                          <th className="th">Difference</th>
                          <th className="th">T3 norm</th>
                          <th className="th">Rate (ppm/yr)</th>
                          <th className="th">T4 norm</th>
                          <th className="th">Score 1</th>
                          <th className="th">Score 2</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trend.data.gases.flatMap((g) =>
                          g.rows.map((r) => (
                            <tr key={`${g.gas}-${r.sampleNo}`} className="hover:bg-brand-50/50">
                              <td className="td text-xs font-semibold">{g.gas}</td>
                              <td className="td num text-xs">{r.sampleNo}</td>
                              <td className="td num text-xs">{r.date}</td>
                              <td className="td num text-xs">{r.daysFromFirst}</td>
                              <td className="td num text-xs">{r.periodDays ?? '—'}</td>
                              <td className="td num text-xs">{r.value.toFixed(1)}</td>
                              <td className="td num text-xs">
                                {r.difference !== null ? r.difference.toFixed(1) : '—'}
                              </td>
                              <td className="td num text-xs text-ink-muted">{r.table3Limit}</td>
                              <td className="td num text-xs">{r.rate?.toFixed(1) ?? '—'}</td>
                              <td className="td num text-xs text-ink-muted">
                                {r.table4Limit ?? '—'}
                              </td>
                              <td className="td num text-xs">{r.score1?.toFixed(1) ?? '—'}</td>
                              <td className="td num text-xs">{r.score2?.toFixed(1) ?? '—'}</td>
                            </tr>
                          )),
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* --- Gas concentration chart --- */}
          <div className="card">
            <div className="card-head !py-3.5">
              <Activity className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Gas Concentration Trend</h2>
            </div>
            <div className="card-pad">
              {series.loading && <Loader />}
              {series.data && (
                <GasTrendChart
                  points={series.data.points}
                  gases={series.data.gases}
                  markers={markers}
                  shadeBefore={startPoint && showEarlier ? analysisFrom : undefined}
                />
              )}
              {active.length > 0 && (
                <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-muted">
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block h-0 w-5 border-t-2 border-dashed" style={{ borderColor: MARKER.detected }} />
                    Possible filter point (detected)
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block h-0 w-5 border-t-2" style={{ borderColor: MARKER.manual }} />
                    Filter point marked by an engineer
                  </span>
                  {startPoint && (
                    <span className="flex items-center gap-1.5">
                      <span className="inline-block h-0 w-5 border-t-2" style={{ borderColor: MARKER.start }} />
                      Analysis start
                    </span>
                  )}
                </p>
              )}
            </div>
          </div>

          {/* --- Oil filtration points --- */}
          <div className="card">
            <div className="card-head !py-3.5">
              <Droplets className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Oil Filtration Points</h2>
              <span className="ml-auto text-[11px] text-ink-muted">
                {active.length} active
                {points.length !== active.length && ` · ${points.length - active.length} rejected`}
              </span>
            </div>
            <div className="card-pad">
              <p className="mb-3 text-[11px] leading-relaxed text-ink-muted">
                Filtering or degassing resets the gas levels, so a fault that was developing can
                look healthy in the next samples. Points are flagged automatically from the gas
                history; you can reject a wrong one, mark one the data does not show, and score
                the trend from after any of them. {filters.data?.rule}
              </p>

              {filters.data?.hiWindow && (
                <div className="mb-3 rounded-lg bg-brand-50 p-2.5 text-xs text-ink-soft">
                  <span className="font-semibold text-ink">Health index DGA level &amp; trend:</span>{' '}
                  {filters.data.hiWindow.enabled ? (
                    <>
                      scored on{' '}
                      <span className="num font-semibold">{filters.data.hiWindow.samplesUsed}</span>{' '}
                      samples
                      {filters.data.hiWindow.fromDate && (
                        <> from <span className="num font-semibold">{filters.data.hiWindow.fromDate}</span></>
                      )}
                      {filters.data.hiWindow.beforeDate && (
                        <> before <span className="num font-semibold">{filters.data.hiWindow.beforeDate}</span></>
                      )}{' '}
                      — {filters.data.hiWindow.reason}. At least{' '}
                      {filters.data.hiWindow.minSamplesAfter} samples are needed after a filter
                      point before the data after it is used.
                    </>
                  ) : (
                    'the filter-point rule is switched off (HI_DGA_FILTER_WINDOW=false); full history is used.'
                  )}
                </div>
              )}

              {filters.loading && <Loader label="Looking for filter points…" />}
              {filters.error && <ErrorNote message={filters.error} />}
              {markError && <ErrorNote message={markError} />}

              {filters.data && (
                <div className="scroll-x">
                  <table className="w-full min-w-[820px] border-collapse">
                    <thead>
                      <tr>
                        <th className="th">Date</th>
                        <th className="th">Source</th>
                        <th className="th">Gas drop (before → after, ppm)</th>
                        <th className="th">Note</th>
                        <th className="th text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {!points.length && (
                        <tr>
                          <td className="td text-xs text-ink-muted" colSpan={5}>
                            No filter points detected or marked for this transformer.
                          </td>
                        </tr>
                      )}
                      {points.map((p) => (
                        <tr
                          key={p.id}
                          className={`${p.rejected ? 'opacity-50' : 'hover:bg-brand-50/50'} ${
                            p.id === startId ? 'bg-brand-50' : ''
                          }`}
                        >
                          <td className="td num text-xs font-semibold">
                            {p.date}
                            {p.previousSample && (
                              <span className="block text-[10px] font-normal text-ink-faint">
                                previous sample {p.previousSample}
                              </span>
                            )}
                          </td>
                          <td className="td">
                            {p.rejected ? (
                              <Badge tone="slate">rejected</Badge>
                            ) : p.source === 'manual' ? (
                              <Badge tone="brand">marked</Badge>
                            ) : (
                              <Badge tone="brand">detected</Badge>
                            )}
                          </td>
                          <td className="td num text-[11px] text-ink-soft">
                            {p.source === 'detected' ? dropSummary(p) : '—'}
                          </td>
                          <td className="td text-[11px] text-ink-muted">
                            {p.note || '—'}
                            {p.createdBy && (
                              <span className="block text-[10px] text-ink-faint">by {p.createdBy}</span>
                            )}
                          </td>
                          <td className="td">
                            <div className="flex justify-end gap-1.5">
                              {!p.rejected && (
                                <button
                                  onClick={() => setStartId(p.id === startId ? '' : p.id)}
                                  className="btn-ghost !px-2 !py-1 !text-[11px]"
                                >
                                  <TrendingUp className="h-3.5 w-3.5" />
                                  {p.id === startId ? 'Use all data' : 'Analyse from here'}
                                </button>
                              )}
                              {p.source === 'detected' && !p.rejected && (
                                <button
                                  onClick={() => addMark(p.date, 'rejected', 'not a filtration')}
                                  className="btn-ghost !px-2 !py-1 !text-[11px]"
                                  disabled={markBusy}
                                  title="Not a filtration (lab error, resample) - hide it"
                                >
                                  <X className="h-3.5 w-3.5" />
                                  Reject
                                </button>
                              )}
                              {p.rejected && p.rejectionId && (
                                <button
                                  onClick={() => removeMark(p.rejectionId!)}
                                  className="btn-ghost !px-2 !py-1 !text-[11px]"
                                  disabled={markBusy}
                                >
                                  <RotateCcw className="h-3.5 w-3.5" />
                                  Restore
                                </button>
                              )}
                              {p.source === 'manual' && (
                                <button
                                  onClick={() => removeMark(Number(p.id.split(':')[1]))}
                                  className="btn-ghost !px-2 !py-1 !text-[11px]"
                                  disabled={markBusy}
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                  Delete
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Add a manual mark */}
              <div className="mt-4 grid grid-cols-1 gap-3 border-t border-line pt-4 sm:grid-cols-[180px_1fr_auto] sm:items-end">
                <div>
                  <label className="label">Filtration date</label>
                  <input
                    className="input num"
                    type="date"
                    max={today()}
                    value={markDate}
                    onChange={(e) => setMarkDate(e.target.value)}
                  />
                </div>
                <div>
                  <label className="label">Note (optional)</label>
                  <input
                    className="input"
                    placeholder="e.g. vacuum degassing by contractor, WO number"
                    value={markNote}
                    onChange={(e) => setMarkNote(e.target.value)}
                  />
                </div>
                <button
                  onClick={() => addMark(markDate, 'manual', markNote)}
                  className="btn-primary"
                  disabled={!markDate || markBusy}
                >
                  <Plus className="h-4 w-4" />
                  Mark filter point
                </button>
              </div>
              <p className="mt-2 text-[11px] text-ink-faint">
                A marked date sits on the first sample taken on or after it. Scoring from a point
                uses the samples from that date onward.
              </p>
            </div>
          </div>

          {/* Duval pentagons and triangles live on the Fault Diagnosis screen
              only, so the same diagnosis is not offered in two places. */}
          <div className="card card-pad flex flex-wrap items-center gap-3">
            <PentagonIcon className="h-5 w-5 text-brand-600" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-bold text-ink">Fault type (Duval pentagons &amp; triangles)</p>
              <p className="text-xs text-ink-muted">
                The fault diagnosis for this transformer is on the Fault Diagnosis tab.
              </p>
            </div>
            <Link to={`/duval?asset=${encodeURIComponent(asset)}`} className="btn-ghost">
              Open fault diagnosis
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
