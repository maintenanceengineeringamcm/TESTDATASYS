import {
  AlertTriangle,
  BrainCircuit,
  FlaskConical,
  Info,
  Pentagon as PentagonIcon,
  Ruler,
  ShieldCheck,
  Sigma,
  Triangle as TriangleIcon,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, qs, useApi } from '../api'
import ScopeBanner from '../components/ScopeBanner'
import { useScope } from '../components/ScopeContext'
import { IEEELimitsChart } from '../charts/Charts'
import DualPentagon from '../charts/DualPentagon'
import { DuvalTriangle } from '../charts/DuvalTriangle'
import { Badge, EmptyState, ErrorNote, Loader, SectionHeader } from '../components/ui'
import type { DuvalAnalysis, PentagonGeometry, ScopeEcho, TriangleGeometry } from '../types'

const GAS_FIELDS = ['H2', 'CH4', 'C2H6', 'C2H4', 'C2H2', 'CO', 'CO2', 'O2', 'N2']

export default function DuvalDiagnosis() {
  const [params, setParams] = useSearchParams()
  const [asset, setAsset] = useState(params.get('asset') ?? '')
  const [mode, setMode] = useState<'asset' | 'manual'>(params.get('asset') ? 'asset' : 'asset')
  const [manual, setManual] = useState<Record<string, string>>({})
  const [age, setAge] = useState('')
  const [result, setResult] = useState<DuvalAnalysis | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const geo = useApi<{ pentagon: PentagonGeometry; triangles: Record<string, TriangleGeometry> }>(
    '/duval/geometry',
  )
  // The asset dropdown lists only what the navigator has in scope.
  const scope = useScope()
  const assetList = useApi<{
    items: { assetNumber: string; records: number }[]
    scope?: ScopeEcho | null
  }>(`/dga/assets${qs({ node: scope.node })}`, [scope.node])

  async function run() {
    setBusy(true)
    setErr(null)
    try {
      const body: Record<string, unknown> = {}
      if (mode === 'asset') {
        if (!asset) {
          setErr('Select an asset first.')
          return
        }
        body.asset = asset
        setParams({ asset }, { replace: true })
      } else {
        const gases: Record<string, number> = {}
        for (const g of GAS_FIELDS) {
          const n = Number(manual[g])
          gases[g] = Number.isFinite(n) ? n : 0
        }
        body.gases = gases
      }
      if (age) body.age = Number(age)
      const res = await api.post<DuvalAnalysis>('/duval/analyse', body)
      setResult(res)
    } catch (e: any) {
      setErr(e.message ?? 'Analysis failed')
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (params.get('asset')) run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const severityTone = (s: number): 'red' | 'amber' | 'green' =>
    s === 3 ? 'red' : s === 2 ? 'amber' : 'green'

  return (
    <div>
      <SectionHeader
        accent="#4A3AA7"
        icon={PentagonIcon}
        title="Duval Diagnosis"
        subtitle="Multi-method fault diagnosis — pentagons, triangles, IEEE limits, Rogers ratios and key gas"
      />

      {mode === 'asset' && (
        <ScopeBanner label={assetList.data?.scope?.label} noun="assets with DGA"
                     count={assetList.data?.items.length} />
      )}

      {/* Input */}
      <div className="card card-pad mb-4">
        <div className="mb-4 inline-flex rounded-lg border border-line p-0.5">
          {(['asset', 'manual'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-md px-3.5 py-1.5 text-xs font-semibold transition-colors ${
                mode === m ? 'bg-brand-600 text-white' : 'text-ink-soft hover:bg-brand-50'
              }`}
            >
              {m === 'asset' ? 'From asset' : 'Manual entry'}
            </button>
          ))}
        </div>

        {mode === 'asset' ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="sm:col-span-2">
              <label className="label">Asset</label>
              <select
                className="input font-mono text-xs"
                value={asset}
                onChange={(e) => setAsset(e.target.value)}
              >
                <option value="">Select an asset…</option>
                {(assetList.data?.items ?? [])
                  .filter((a) => a.records > 0)
                  .map((a) => (
                    <option key={a.assetNumber} value={a.assetNumber}>
                      {a.assetNumber} ({a.records} samples)
                    </option>
                  ))}
              </select>
            </div>
            <div>
              <label className="label">Transformer age (years)</label>
              <input
                className="input num"
                type="number"
                min={0}
                placeholder="unknown"
                value={age}
                onChange={(e) => setAge(e.target.value)}
              />
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {GAS_FIELDS.map((g) => (
              <div key={g}>
                <label className="label">{g} (ppm)</label>
                <input
                  className="input num"
                  type="number"
                  min={0}
                  step="any"
                  placeholder="0"
                  value={manual[g] ?? ''}
                  onChange={(e) => setManual((m) => ({ ...m, [g]: e.target.value }))}
                />
              </div>
            ))}
            <div>
              <label className="label">Age (years)</label>
              <input
                className="input num"
                type="number"
                min={0}
                placeholder="unknown"
                value={age}
                onChange={(e) => setAge(e.target.value)}
              />
            </div>
          </div>
        )}

        <button onClick={run} className="btn-primary mt-4" disabled={busy}>
          <FlaskConical className={`h-4 w-4 ${busy ? 'animate-pulse' : ''}`} />
          {busy ? 'Analysing…' : 'Run diagnosis'}
        </button>
      </div>

      {err && <ErrorNote message={err} />}
      {busy && !result && <Loader label="Running multi-method analysis…" />}

      {!result && !busy && !err && (
        <div className="card">
          <EmptyState
            icon={FlaskConical}
            title="No analysis yet"
            hint="Choose an asset or enter gas concentrations manually, then run the diagnosis."
          />
        </div>
      )}

      {result && geo.data && (
        <div className="space-y-4">
          {/* Verdict strip */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            <div className="card card-pad">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                IEEE C57.104 status
              </p>
              <p className="mt-2 text-xl font-bold" style={{ color: result.ieee.color }}>
                {result.ieee.label}
              </p>
              <p className="mt-1 text-[11px] text-ink-muted">{result.ieee.columnLabel}</p>
            </div>
            <div className="card card-pad">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                Duval Triangle 1
              </p>
              <p className="mt-2 text-xl font-bold text-ink">
                {result.triangles['1']?.zone ?? '—'}
              </p>
              <p className="mt-1 text-[11px] text-ink-muted">
                {result.triangles['1']?.meaning ?? ''}
              </p>
            </div>
            <div className="card card-pad">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                Pentagon 1 / 2
              </p>
              <p className="mt-2 text-xl font-bold text-ink">
                {result.pentagon.pentagon1?.zone ?? '—'} /{' '}
                {result.pentagon.pentagon2?.zone ?? '—'}
              </p>
              <p className="mt-1 text-[11px] text-ink-muted">
                {result.pentagon.pentagon1?.meaning ?? ''}
              </p>
            </div>
            <div className="card card-pad">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                Rogers ratios
              </p>
              <p className="mt-2 text-base font-bold text-ink">
                {result.rogers.identified ? `Case ${result.rogers.case}` : 'Not identified'}
              </p>
              <p className="mt-1 text-[11px] text-ink-muted">{result.rogers.diagnosis}</p>
            </div>
          </div>

          {/* Recommended action */}
          <div
            className="rounded-xl border p-4"
            style={{
              borderColor: `${result.ieee.color}55`,
              background: `${result.ieee.color}0F`,
            }}
          >
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" style={{ color: result.ieee.color }} />
              <div>
                <p className="text-sm font-bold text-ink">Recommended action</p>
                <p className="mt-0.5 text-sm text-ink-soft">{result.ieee.action}</p>
              </div>
            </div>
          </div>

          {/* Dual pentagon */}
          <div className="card">
            <div className="card-head !py-3.5">
              <PentagonIcon className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Duval Dual Pentagon</h2>
            </div>
            <div className="card-pad">
              <DualPentagon geometry={geo.data.pentagon} result={result.pentagon} />
            </div>
          </div>

          {/* All three triangles */}
          <div className="card">
            <div className="card-head !py-3.5">
              <TriangleIcon className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Duval Triangles</h2>
            </div>
            <div className="card-pad">
              <div className="flex flex-col gap-6 lg:flex-row">
                {['1', '4', '5'].map((id) =>
                  geo.data!.triangles[id] ? (
                    <DuvalTriangle
                      key={id}
                      geometry={geo.data!.triangles[id]}
                      result={result.triangles[id] ?? null}
                    />
                  ) : null,
                )}
              </div>
              {result.triangles['1']?.ladderAgrees === false && (
                <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                  <span className="font-semibold">Classifier note:</span> the point plots in{' '}
                  <b>{result.triangles['1'].zone}</b>, while the specification&rsquo;s rule
                  ladder reports <b>{result.triangles['1'].ladderZone}</b>. The zone shown is
                  the polygon the point actually falls in.
                </p>
              )}
            </div>
          </div>

          {/* IEEE limits */}
          <div className="card">
            <div className="card-head !py-3.5">
              <Ruler className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">
                Measured Gas Levels vs IEEE C57.104-2019 Limits
              </h2>
            </div>
            <div className="card-pad">
              <IEEELimitsChart rows={result.ieee.gases} />
              <div className="scroll-x mt-4">
                <table className="w-full min-w-[760px] border-collapse">
                  <thead>
                    <tr>
                      <th className="th">Gas</th>
                      <th className="th">Measured</th>
                      <th className="th">Table 1</th>
                      <th className="th">Table 2</th>
                      <th className="th">Δ vs previous</th>
                      <th className="th">Table 3</th>
                      <th className="th">Rate (ppm/yr)</th>
                      <th className="th">Table 4</th>
                      <th className="th">Severity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.ieee.gases.map((g) => (
                      <tr key={g.gas} className="hover:bg-brand-50/50">
                        <td className="td font-semibold">{g.gas}</td>
                        <td className="td num text-xs font-semibold">{g.value.toFixed(1)}</td>
                        <td className={`td num text-xs ${g.aboveTable1 ? 'font-bold text-amber-700' : 'text-ink-muted'}`}>
                          {g.table1}
                        </td>
                        <td className={`td num text-xs ${g.aboveTable2 ? 'font-bold text-red-600' : 'text-ink-muted'}`}>
                          {g.table2}
                        </td>
                        <td className="td num text-xs">
                          {g.delta !== null ? (g.delta > 0 ? `+${g.delta.toFixed(1)}` : g.delta.toFixed(1)) : '—'}
                        </td>
                        <td className={`td num text-xs ${g.aboveTable3 ? 'font-bold text-amber-700' : 'text-ink-muted'}`}>
                          {g.table3}
                        </td>
                        <td className="td num text-xs">{g.rate?.toFixed(1) ?? '—'}</td>
                        <td className={`td num text-xs ${g.aboveTable4 ? 'font-bold text-red-600' : 'text-ink-muted'}`}>
                          {g.table4}
                        </td>
                        <td className="td">
                          <Badge tone={severityTone(g.severity)}>
                            {g.severity === 3 ? 'High' : g.severity === 2 ? 'Elevated' : 'Normal'}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Key gas / paper / AI */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="card card-pad">
              <div className="mb-3 flex items-center gap-2">
                <Sigma className="h-4 w-4 text-brand-600" />
                <h3 className="text-sm font-bold text-ink">Key Gas Method</h3>
              </div>
              <p className="text-sm font-semibold text-ink">
                {result.keyGas.dominant ?? '—'}
              </p>
              <p className="mt-0.5 text-xs text-ink-muted">{result.keyGas.interpretation}</p>
              <div className="mt-3 space-y-1.5">
                {result.keyGas.shares.map((s) => (
                  <div key={s.gas} className="flex items-center gap-2">
                    <span className="w-12 shrink-0 text-[11px] font-medium text-ink-soft">
                      {s.gas}
                    </span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-brand-100">
                      <div className="h-full rounded-full bg-brand-500" style={{ width: `${s.percent}%` }} />
                    </div>
                    <span className="num w-12 shrink-0 text-right text-[11px] text-ink-muted">
                      {s.percent}%
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="card card-pad">
              <div className="mb-3 flex items-center gap-2">
                <Info className="h-4 w-4 text-brand-600" />
                <h3 className="text-sm font-bold text-ink">Paper Involvement</h3>
              </div>
              <dl className="space-y-1 text-xs">
                <div className="flex justify-between">
                  <dt className="text-ink-muted">CO</dt>
                  <dd className="num font-semibold">{result.paper.co.toFixed(0)} ppm</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">CO₂</dt>
                  <dd className="num font-semibold">{result.paper.co2.toFixed(0)} ppm</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">CO₂ / CO</dt>
                  <dd className="num font-semibold">{result.paper.co2CoRatio ?? '—'}</dd>
                </div>
              </dl>
              <ul className="mt-3 space-y-1.5">
                {result.paper.notes.map((n, i) => (
                  <li key={i} className="text-[11px] leading-relaxed text-ink-soft">
                    {n}
                  </li>
                ))}
              </ul>
            </div>

            <div className="card card-pad">
              <div className="mb-3 flex items-center gap-2">
                <BrainCircuit className="h-4 w-4 text-brand-600" />
                <h3 className="text-sm font-bold text-ink">AI Fault Classifier</h3>
              </div>
              {result.ai.available ? (
                <>
                  <p className="text-sm font-semibold text-ink">{result.ai.fault}</p>
                  <div className="mt-2 flex items-center gap-2">
                    <span
                      className="chip num text-xs"
                      style={{
                        background: `${result.ai.flag?.color}1A`,
                        color: result.ai.flag?.color,
                      }}
                    >
                      {result.ai.confidence.toFixed(1)}% confidence
                    </span>
                    <span className="text-[11px] text-ink-muted">{result.ai.flag?.text}</span>
                  </div>
                  <div className="mt-3 space-y-1.5">
                    {Object.entries(result.ai.probabilities)
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 5)
                      .map(([k, v]) => (
                        <div key={k} className="flex items-center gap-2">
                          <span className="min-w-0 flex-1 truncate text-[11px] text-ink-soft">
                            {k}
                          </span>
                          <div className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-brand-100">
                            <div
                              className="h-full rounded-full bg-brand-500"
                              style={{ width: `${v}%` }}
                            />
                          </div>
                          <span className="num w-10 shrink-0 text-right text-[11px] text-ink-muted">
                            {v}%
                          </span>
                        </div>
                      ))}
                  </div>
                </>
              ) : result.ai.applicable === false ? (
                <div className="rounded-lg border border-line bg-slate-50 p-3">
                  <p className="text-xs font-medium text-ink-soft">Not applicable</p>
                  <p className="mt-1 text-[11px] leading-relaxed text-ink-muted">
                    {result.ai.reason}
                  </p>
                </div>
              ) : (
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-xs font-medium text-ink-soft">Model not available</p>
                  <p className="mt-1 text-[11px] leading-relaxed text-ink-muted">
                    {result.ai.reason}
                  </p>
                  <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
                    Every other method on this page works without it.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Agreement + caveats */}
          {result.agreement && (
            <div
              className={`rounded-xl border p-4 ${
                result.agreement.match
                  ? 'border-emerald-200 bg-emerald-50'
                  : 'border-amber-200 bg-amber-50'
              }`}
            >
              <p className="text-sm text-ink-soft">
                <span className="font-bold">Method agreement: </span>
                {result.agreement.message}
              </p>
            </div>
          )}

          {result.caveats.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <div className="mb-2 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-600" />
                <p className="text-sm font-bold text-ink">Data integrity caveats</p>
              </div>
              <ul className="space-y-1">
                {result.caveats.map((c, i) => (
                  <li key={i} className="text-xs leading-relaxed text-amber-900">
                    • {c}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="rounded-xl border border-line bg-white p-4 text-[11px] leading-relaxed text-ink-muted">
            {result.disclaimer}
          </p>
        </div>
      )}
    </div>
  )
}
