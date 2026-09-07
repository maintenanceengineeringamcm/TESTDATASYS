import {
  BrainCircuit,
  Flag,
  History,
  Info,
  Scale,
  Settings,
  ShieldQuestion,
  SlidersHorizontal,
} from 'lucide-react'
import { useState } from 'react'
import { api, useApi } from '../api'
import BandEditor, { type BandTable } from '../components/BandEditor'
import WeightEditor from '../components/WeightEditor'
import { Badge, ErrorNote, Loader, SectionHeader } from '../components/ui'

interface ConfigData {
  hiBands: { key: string; label: string; min: number; max: number; color: string; bg: string }[]
  audit: Record<
    string,
    {
      assetType: string
      status: string
      trustworthy: boolean
      message: string
      issues: { band: string; status: string; reason: string }[]
      bandsExpected: number
      bandsWithIssues: number
    }
  >
  weights: Record<
    string,
    { components: Record<string, number>; total: number; overridden: boolean }
  >
  scoreBands: Record<string, Record<string, BandTable>>
  overrides: {
    serviceUrl: string
    reachable: boolean
    bands: Record<string, { updatedAt: string; updatedBy: string; note: string }>
  }
  componentLabels: Record<string, string>
  componentUnits: Record<string, string>
  manualComponents: Record<string, string[]>
  assetTypeLabels: Record<string, string>
  flags: Record<string, boolean>
}

// Each flag corresponds to a documented discrepancy in the automation spec.
const FLAG_NOTES: Record<string, { title: string; detail: string }> = {
  dgaPerGasOwnField: {
    title: 'DGA scores each gas against its own field',
    detail:
      'The legacy logic compared every gas against H2ppm. Enabled means each gas is banded against its own column.',
  },
  diranaScoreOwnValue: {
    title: 'DIRANA bands its own value',
    detail:
      'The legacy logic banded the tan-delta value against the DIRANA range. Enabled means the moisture-in-paper value is banded instead.',
  },
  aioIftoUncrossed: {
    title: 'Acidity and IFT read their own tables',
    detail:
      'The legacy Get* functions referenced each other’s table. Enabled means acidity reads TRANS_ACIDITY and IFT reads TRANS_ITO.',
  },
  saIrUsesIrField: {
    title: 'Surge-arrester IR reads an IR column',
    detail:
      'The legacy function read CounterReading, identical to the CR component. Enabled means it reads InsulationResistanceHVEGOhm.',
  },
  oltcUsesCebOltc: {
    title: 'OLTC reads CEB_OLTC',
    detail:
      'The table mapping pointed PRM010 at CEB_OUT_CT, the CT table. Enabled means OLTC oil tests read the real CEB_OLTC table.',
  },
  ecBandAscending: {
    title: 'Exciting current uses deterministic banding',
    detail:
      'The legacy condition mixed two deviations across both range bounds with an OR, which cannot select a band deterministically. Enabled means the larger deviation is banded normally.',
  },
}

export default function Configuration() {
  const { data, loading, error, reload: reloadConfig } = useApi<ConfigData>('/config')
  const history = useApi<{
    items: {
      id: number; kind: string; assetType: string; bandName: string; action: string
      before: unknown; after: unknown; changedAt: string; changedBy: string; note: string
    }[]
  }>('/config/history?limit=25')

  // A saved edit changes both the configuration and its audit trail.
  const reload = () => {
    reloadConfig()
    history.reload()
  }

  const ml = useApi<{
    available: boolean
    error: string | null
    modelDir: string
    dataDirs: string[]
    trainingFiles: Record<string, string | null>
    supportedAssetTypes: string[]
    metrics: any
  }>('/ml/status')
  const [training, setTraining] = useState(false)
  const [assetType, setAssetType] = useState('TR')

  async function trainModel() {
    setTraining(true)
    try {
      await api.post('/ml/train')
      ml.reload()
    } finally {
      setTraining(false)
    }
  }

  return (
    <div>
      <SectionHeader
        accent="#123252"
        icon={Settings}
        title="Configuration"
        subtitle="Score bands, component weights and engine behaviour, read live from the configuration tables"
      />

      {error && <ErrorNote message={error} onRetry={reload} />}
      {loading && <Loader />}

      {data && !data.overrides.reachable && (
        <div className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-4">
          <p className="text-sm font-bold text-amber-900">
            Configuration service is not running
          </p>
          <p className="mt-1 text-sm leading-relaxed text-amber-900">
            Scoring continues on the values held in{' '}
            <span className="font-mono">CEB_TRANSMISSION</span>, but thresholds cannot be
            edited until the service is started. Run{' '}
            <span className="font-mono">py config-service/app.py</span> — it is expected at{' '}
            <span className="font-mono">{data.overrides.serviceUrl}</span>.
          </p>
        </div>
      )}

      {data && (
        <div className="space-y-4">
          {/* Configuration audit */}
          {/* <div className="card">
            <div className="card-head !py-3.5">
              <ShieldQuestion className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Configuration Health</h2>
            </div>
            <div className="card-pad space-y-2">
              {Object.values(data.audit).map((a) => (
                <div
                  key={a.assetType}
                  className={`rounded-lg border p-3 ${
                    a.trustworthy ? 'border-line' : 'border-amber-300 bg-amber-50'
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-bold text-ink">
                      {data.assetTypeLabels[a.assetType] ?? a.assetType}
                    </span>
                    <Badge
                      tone={
                        a.status === 'ok'
                          ? 'green'
                          : a.status === 'manual-only'
                            ? 'slate'
                            : a.status === 'partial'
                              ? 'amber'
                              : 'red'
                      }
                    >
                      {a.status}
                    </Badge>
                    {a.bandsExpected > 0 && (
                      <span className="num text-[11px] text-ink-muted">
                        {a.bandsExpected - a.bandsWithIssues}/{a.bandsExpected} band tables usable
                      </span>
                    )}
                  </div>
                  {a.message && (
                    <p className="mt-1 text-[11px] leading-relaxed text-ink-soft">{a.message}</p>
                  )}
                  {a.issues.length > 0 && (
                    <ul className="mt-1.5 space-y-0.5">
                      {a.issues.map((i) => (
                        <li key={i.band} className="text-[11px] leading-relaxed text-amber-900">
                          <span className="font-mono font-semibold">{i.band}</span> — {i.reason}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </div> */}

          {/* HI bands */}
          <div className="card">
            <div className="card-head !py-3.5">
              <SlidersHorizontal className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Health Index Colour Bands</h2>
            </div>
            <div className="card-pad">
              <div className="flex flex-wrap gap-3">
                {data.hiBands.map((b) => (
                  <div
                    key={b.key}
                    className="flex min-w-[150px] flex-1 items-center gap-3 rounded-lg border border-line p-3"
                    style={{ background: b.bg }}
                  >
                    <span className="h-8 w-1.5 rounded-full" style={{ background: b.color }} />
                    <div>
                      <p className="text-sm font-bold" style={{ color: b.color }}>
                        {b.label}
                      </p>
                      <p className="num text-xs text-ink-soft">
                        {Math.max(0, b.min).toFixed(0)} – {Math.min(100, b.max).toFixed(0)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Weights */}
          <div className="card">
            <div className="card-head !py-3.5">
              <Scale className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Component Weights</h2>
              <span className="ml-auto text-[11px] text-ink-muted">
                edits are stored by the configuration service
              </span>
            </div>
            <div className="card-pad space-y-6">
              {Object.entries(data.weights).map(([type, w]) => (
                <WeightEditor
                  key={type}
                  assetType={type}
                  label={data.assetTypeLabels[type] ?? type}
                  components={w.components}
                  total={w.total}
                  overridden={w.overridden}
                  manualComponents={data.manualComponents[type] ?? []}
                  componentLabels={data.componentLabels}
                  onSaved={reload}
                />
              ))}
            </div>
          </div>

          {/* Score bands */}
          <div className="card">
            <div className="card-head !py-3.5">
              <SlidersHorizontal className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Score Range Tables</h2>
              <select
                className="input ml-auto w-auto py-1 text-xs"
                value={assetType}
                onChange={(e) => setAssetType(e.target.value)}
              >
                {Object.keys(data.scoreBands).map((t) => (
                  <option key={t} value={t}>
                    {data.assetTypeLabels[t] ?? t}
                  </option>
                ))}
              </select>
            </div>
            <div className="card-pad">
              <p className="mb-4 flex items-start gap-1.5 rounded-lg bg-brand-50 p-3 text-[11px] leading-relaxed text-ink-soft">
                <Info className="mt-px h-3.5 w-3.5 shrink-0 text-brand-600" />
                Edits are saved to the configuration service&rsquo;s own database and layered
                over the source values — <span className="font-mono">CEB_TRANSMISSION</span> is
                never written to. Health indices pick up a change immediately. Use the revert
                arrow on any edited table to go back to the source configuration.
              </p>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {Object.entries(data.scoreBands[assetType] ?? {}).map(([name, table]) => (
                  <BandEditor
                    key={`${assetType}/${name}`}
                    assetType={assetType}
                    bandName={name}
                    table={table}
                    onSaved={reload}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* Change history */}
          {/* <div className="card">
            <div className="card-head !py-3.5">
              <History className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Configuration Change Log</h2>
              <span className="ml-auto text-[11px] text-ink-muted">
                append-only, from the configuration service
              </span>
            </div>
            {history.data?.items?.length ? (
              <div className="scroll-x">
                <table className="w-full min-w-[720px] border-collapse">
                  <thead>
                    <tr>
                      <th className="th">When</th>
                      <th className="th">Who</th>
                      <th className="th">Action</th>
                      <th className="th">Target</th>
                      <th className="th">Change</th>
                      <th className="th">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.data.items.map((h) => (
                      <tr key={h.id} className="hover:bg-brand-50/50">
                        <td className="td num text-[11px]">
                          {String(h.changedAt).slice(0, 19).replace('T', ' ')}
                        </td>
                        <td className="td text-xs font-semibold">{h.changedBy}</td>
                        <td className="td">
                          <Badge tone={h.action === 'reset' ? 'slate' : 'brand'}>{h.action}</Badge>
                        </td>
                        <td className="td font-mono text-[11px]">
                          {h.assetType}
                          {h.bandName ? `/${h.bandName}` : ' weights'}
                        </td>
                        <td className="td text-[11px] text-ink-muted">
                          {h.before ? 'replaced previous values' : 'first override'}
                          {h.after ? '' : ' · reverted to source'}
                        </td>
                        <td className="td text-[11px] text-ink-muted">{h.note || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="card-pad text-xs text-ink-muted">
                No configuration changes recorded yet.
              </p>
            )}
          </div> */}

          {/* Engine flags */}
          {/* <div className="card">
            <div className="card-head !py-3.5">
              <Flag className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Engine Behaviour Flags</h2>
            </div>
            <div className="card-pad">
              <p className="mb-4 flex items-start gap-1.5 rounded-lg bg-brand-50 p-3 text-[11px] leading-relaxed text-ink-soft">
                <Info className="mt-px h-3.5 w-3.5 shrink-0 text-brand-600" />
                Each flag corresponds to a documented discrepancy in the automation
                specification. The default implements the intended reading; set the matching
                environment variable to <span className="font-mono">0</span> to restore the
                literal legacy behaviour.
              </p>
              <div className="space-y-2">
                {Object.entries(data.flags).map(([key, on]) => (
                  <div key={key} className="flex items-start gap-3 rounded-lg border border-line p-3">
                    <span
                      className={`mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full ${
                        on ? 'bg-emerald-500' : 'bg-slate-300'
                      }`}
                    />
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-ink">
                        {FLAG_NOTES[key]?.title ?? key}
                      </p>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-ink-muted">
                        {FLAG_NOTES[key]?.detail}
                      </p>
                    </div>
                    <Badge tone={on ? 'green' : 'slate'}>{on ? 'intended' : 'legacy'}</Badge>
                  </div>
                ))}
              </div>
            </div>
          </div> */}

          {/* ML */}
          <div className="card">
            <div className="card-head !py-3.5">
              <BrainCircuit className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">AI Fault Classifier</h2>
              <Badge tone={ml.data?.available ? 'green' : 'slate'}>
                {ml.data?.available ? 'ready' : 'not available'}
              </Badge>
            </div>
            <div className="card-pad">
              {ml.data?.available && ml.data.metrics ? (
                <>
                  <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                    <div>
                      <dt className="text-ink-muted">Training rows</dt>
                      <dd className="num text-lg font-bold text-ink">
                        {ml.data.metrics.samples?.toLocaleString()}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-ink-muted">5-fold CV accuracy</dt>
                      <dd className="num text-lg font-bold text-ink">
                        {ml.data.metrics.cvMean}%
                        <span className="text-xs font-normal text-ink-muted">
                          {' '}± {ml.data.metrics.cvStd}
                        </span>
                      </dd>
                    </div>
                    <div>
                      <dt className="text-ink-muted">Hold-out accuracy</dt>
                      <dd className="num text-lg font-bold text-ink">
                        {ml.data.metrics.testAccuracy}%
                      </dd>
                    </div>
                    <div>
                      <dt className="text-ink-muted">Fault classes</dt>
                      <dd className="num text-lg font-bold text-ink">
                        {ml.data.metrics.classes?.length}
                      </dd>
                    </div>
                  </dl>

                  <p className="mt-3 rounded-lg bg-brand-50 p-2.5 text-[11px] leading-relaxed text-ink-soft">
                    Applies to <span className="font-semibold">power transformers with DGA
                    data only</span> — it is trained on transformer oil gas
                    concentrations and is refused for any other asset type. The
                    cross-validated figure is the honest one to quote.
                  </p>

                  {/* Class balance — a class with few examples is predicted less reliably. */}
                  {ml.data.metrics.classCounts && (
                    <div className="mt-4">
                      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
                        Training data by fault class
                      </p>
                      <div className="space-y-1">
                        {Object.entries(ml.data.metrics.classCounts)
                          .sort((a, b) => (b[1] as number) - (a[1] as number))
                          .map(([label, n]) => {
                            const max = Math.max(
                              ...Object.values(ml.data!.metrics!.classCounts as Record<string, number>),
                            )
                            return (
                              <div key={label} className="flex items-center gap-2">
                                <span className="w-56 shrink-0 truncate text-[11px] text-ink-soft">
                                  {label}
                                </span>
                                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-brand-100">
                                  <div
                                    className="h-full rounded-full bg-brand-500"
                                    style={{ width: `${((n as number) / max) * 100}%` }}
                                  />
                                </div>
                                <span className="num w-10 shrink-0 text-right text-[11px] text-ink-muted">
                                  {n as number}
                                </span>
                              </div>
                            )
                          })}
                      </div>
                    </div>
                  )}

                  {/* What the data preparation had to resolve. */}
                  {/* {ml.data.metrics.data && (
                    <div className="mt-4 rounded-lg border border-line p-3">
                      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
                        Data preparation
                      </p>
                      <ul className="space-y-1 text-[11px] leading-relaxed text-ink-soft">
                        {(ml.data.metrics.data.sources ?? []).map((s: any) => (
                          <li key={s.file}>
                            <span className="font-mono">{s.file}</span> —{' '}
                            <span className="num">{s.rows}</span> rows
                          </li>
                        ))}
                        <li>
                          Merged <span className="num">{ml.data.metrics.data.mergedRows}</span>{' '}
                          rows, dropped{' '}
                          <span className="num">{ml.data.metrics.data.duplicatesDropped}</span>{' '}
                          exact duplicates — left in, the same row lands in both the
                          training and test split and inflates accuracy.
                        </li>
                        <li>{ml.data.metrics.data.coarseLabelAction}</li>
                      </ul>
                    </div>
                  )} */}

                  {/* Top features */}
                  {ml.data.metrics.featureImportance && (
                    <div className="mt-4">
                      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
                        Most influential features
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {ml.data.metrics.featureImportance.slice(0, 8).map((f: any) => (
                          <span key={f.feature} className="chip bg-brand-50 text-[10px] text-brand-800">
                            <span className="font-mono">{f.feature}</span>
                            <span className="num font-bold">{f.gain.toFixed(3)}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <p className="mt-3 font-mono text-[10px] text-ink-faint">
                    weights: {ml.data.modelDir}
                    {ml.data.metrics.trainedAt
                      ? ` · trained ${String(ml.data.metrics.trainedAt).slice(0, 16).replace('T', ' ')} UTC`
                      : ''}
                  </p>
                </>
              ) : (
                <div className="rounded-lg bg-slate-50 p-4">
                  <p className="text-xs font-medium text-ink-soft">
                    {ml.data?.error ?? 'Checking…'}
                  </p>
                  <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
                    This module is optional — every other diagnostic method works without
                    it. Place these files in the project root and train:
                  </p>
                  <ul className="mt-1.5 space-y-0.5">
                    {Object.entries(ml.data?.trainingFiles ?? {}).map(([f, path]) => (
                      <li key={f} className="font-mono text-[11px]">
                        <span className={path ? 'text-emerald-700' : 'text-ink-muted'}>
                          {path ? '·' : '·'} {f} {path ? '(found)' : '(missing)'}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <button onClick={trainModel} className="btn-ghost mt-4" disabled={training}>
                <BrainCircuit className={`h-4 w-4 ${training ? 'animate-pulse' : ''}`} />
                {training ? 'Training…' : 'Train / retrain model'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
