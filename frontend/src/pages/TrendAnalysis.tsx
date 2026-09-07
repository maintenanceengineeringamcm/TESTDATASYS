import {
  Activity,
  Pentagon as PentagonIcon,
  Table2,
  TrendingUp,
  Triangle as TriangleIcon,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { qs, useApi } from '../api'
import DgaAssetPicker from '../components/DgaAssetPicker'
import ScopeBanner from '../components/ScopeBanner'
import { GasTrendChart } from '../charts/Charts'
import DualPentagon from '../charts/DualPentagon'
import DualTriangles from '../charts/DuvalTriangle'
import { Badge, EmptyState, ErrorNote, Loader, SectionHeader } from '../components/ui'
import type {
  AssetTrend,
  DuvalAnalysis,
  PentagonGeometry,
  TriangleGeometry,
} from '../types'

const ALL_GASES = ['H2', 'CH4', 'CO', 'CO2', 'C2H4', 'C2H6', 'C2H2', 'O2', 'N2']

export default function TrendAnalysis() {
  const [params, setParams] = useSearchParams()
  const [asset, setAsset] = useState(params.get('asset') ?? '')
  const [gases, setGases] = useState(['H2', 'CH4', 'C2H4', 'C2H6', 'C2H2'])
  const [showWorkings, setShowWorkings] = useState(false)

  useEffect(() => {
    if (asset) setParams({ asset }, { replace: true })
  }, [asset])

  const trend = useApi<AssetTrend>(asset ? `/dga/trend/${encodeURIComponent(asset)}` : null)
  const series = useApi<{ points: Record<string, any>[]; gases: string[] }>(
    asset ? `/dga/series/${encodeURIComponent(asset)}${qs({ gases: gases.join(',') })}` : null,
  )
  const geo = useApi<{
    pentagon: PentagonGeometry
    triangles: Record<string, TriangleGeometry>
  }>('/duval/geometry')
  const duval = useApi<DuvalAnalysis>(
    asset ? `/duval/analyse${qs({ asset })}` : null,
  )

  return (
    <div>
      <SectionHeader
        accent="#0F6E8C"
        icon={TrendingUp}
        title="Trend Analysis"
        subtitle="IEEE C57.104 gas trend scoring, dual Duval pentagons and dual Duval triangles"
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
                <GasTrendChart points={series.data.points} gases={series.data.gases} />
              )}
            </div>
          </div>

          {/* --- Dual pentagon --- */}
          <div className="card">
            <div className="card-head !py-3.5">
              <PentagonIcon className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Duval Dual Pentagon</h2>
              {duval.data?.sampleDate && (
                <span className="ml-auto text-[11px] text-ink-muted">
                  Sample {String(duval.data.sampleDate).slice(0, 10)}
                </span>
              )}
            </div>
            <div className="card-pad">
              {(geo.loading || duval.loading) && <Loader label="Building pentagons…" />}
              {duval.error && <ErrorNote message={duval.error} />}
              {geo.data && duval.data && (
                <DualPentagon
                  geometry={geo.data.pentagon}
                  result={duval.data.pentagon}
                />
              )}
            </div>
          </div>

          {/* --- Dual triangles --- */}
          <div className="card">
            <div className="card-head !py-3.5">
              <TriangleIcon className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Duval Dual Triangles</h2>
            </div>
            <div className="card-pad">
              {(geo.loading || duval.loading) && <Loader label="Building triangles…" />}
              {geo.data && duval.data && (
                <DualTriangles
                  geometries={geo.data.triangles}
                  results={duval.data.triangles}
                  ids={['1', '5']}
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
