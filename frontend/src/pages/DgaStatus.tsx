import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  Download,
  FileText,
  Layers,
  ShieldAlert,
  Table2,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, useApi } from '../api'
import DgaAssetPicker from '../components/DgaAssetPicker'
import DgaStatusReportView from '../components/DgaStatusReport'
import ScopeBanner from '../components/ScopeBanner'
import { useScope } from '../components/ScopeContext'
import { EmptyState, ErrorNote, Loader, SectionHeader, StatCard } from '../components/ui'
import { limitText, saveStatusCsv } from '../lib/dgaStatusCsv'
import type {
  DgaAgeSource,
  DgaFleetStatusRow,
  DgaLimitTables,
  DgaStatusReport,
  DgaStatusResult,
  DgaStatusSummary,
} from '../types'

type Tab = 'assessment' | 'fleet' | 'tables'

const TABS: { id: Tab; label: string; icon: typeof Table2 }[] = [
  { id: 'assessment', label: 'Status assessment', icon: ClipboardList },
  { id: 'fleet', label: 'Fleet status', icon: Layers },
  { id: 'tables', label: 'Reference tables', icon: Table2 },
]

/** Status colours come from the backend so the scale is defined in one place. */
function StatusPill({
  status,
  label,
  color,
  bg,
  size = 'md',
}: {
  status: number | null
  label: string
  color: string
  bg: string
  size?: 'sm' | 'md'
}) {
  return (
    <span
      className={`chip ${size === 'sm' ? 'text-[11px]' : 'text-xs'}`}
      style={{ background: bg, color }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {label}
      {status === null && <span className="opacity-70">· no data</span>}
    </span>
  )
}

/**
 * The Figure 2 decision path, drawn as the flowchart it is.
 *
 * The status alone is not defensible on its own; an engineer signing it off has
 * to see which box the unit fell out of. Each step carries its answer in words
 * as well as in colour.
 */
function DecisionFlow({ result }: { result: DgaStatusResult }) {
  return (
    <ol className="space-y-0">
      {result.decisionTrace.map((step, i) => {
        const last = i === result.decisionTrace.length - 1
        const tone = last
          ? { border: result.color, bg: result.bg, text: result.color }
          : step.pass
            ? { border: '#A7E0C8', bg: '#E6F6F0', text: '#0E7C58' }
            : { border: '#F3B9B9', bg: '#FCEAEA', text: '#B02F2F' }
        return (
          <li key={step.step}>
            <div
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border px-4 py-2.5"
              style={{ borderColor: tone.border, background: tone.bg }}
            >
              <span className="text-xs font-bold" style={{ color: tone.text }}>
                {step.step}
              </span>
              <span className="min-w-0 flex-1 text-xs text-ink-soft">{step.question}</span>
              <span className="text-xs font-semibold" style={{ color: tone.text }}>
                {step.answer}
              </span>
              <span className="num text-[11px] text-ink-muted">{step.detail}</span>
            </div>
            {!last && (
              <div className="flex justify-center py-1">
                <ArrowRight className="h-3.5 w-3.5 rotate-90 text-ink-faint" />
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}

function Assessment({ asset }: { asset: string }) {
  const [showReport, setShowReport] = useState(false)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [pdfError, setPdfError] = useState<string | null>(null)
  const path = asset ? `/dga/status/${encodeURIComponent(asset)}` : null
  const status = useApi<DgaStatusResult>(path, [asset])
  const report = useApi<DgaStatusReport>(
    showReport && asset ? `/dga/status/report/${encodeURIComponent(asset)}` : null,
    [asset, showReport],
  )

  // A new asset invalidates the open report rather than showing the old one.
  useEffect(() => setShowReport(false), [asset])

  function downloadCsv() {
    if (status.data) saveStatusCsv(status.data)
  }

  // The PDF is built from the full report payload, which the summary view has
  // not fetched. Pulling it on demand keeps the assessment screen light while
  // still letting an engineer take the signed document in one click.
  async function downloadPdf() {
    if (!asset) return
    setPdfBusy(true)
    setPdfError(null)
    try {
      const [{ exportDgaStatusPdf }, full] = await Promise.all([
        import('../lib/dgaStatusPdf'),
        report.data
          ? Promise.resolve(report.data)
          : api.get<DgaStatusReport>(`/dga/status/report/${encodeURIComponent(asset)}`),
      ])
      exportDgaStatusPdf(full)
    } catch (err) {
      setPdfError(err instanceof Error ? err.message : 'Could not build the PDF.')
    } finally {
      setPdfBusy(false)
    }
  }

  if (!asset) {
    return (
      <div className="card">
        <EmptyState
          icon={ClipboardList}
          title="Select an asset to classify"
          hint="Pick a transformer with dissolved-gas history to run the IEEE C57.104-2019
                Figure 2 status decision and produce its report."
        />
      </div>
    )
  }

  if (status.loading) return <Loader label="Classifying against IEEE C57.104-2019…" />
  if (status.error) return <ErrorNote message={status.error} onRetry={status.reload} />
  if (!status.data) return null

  const s = status.data

  if (showReport) {
    return (
      <div>
        {report.loading && <Loader label="Building report…" />}
        {report.error && <ErrorNote message={report.error} onRetry={report.reload} />}
        {report.data && (
          <DgaStatusReportView
            report={report.data}
            onClose={() => setShowReport(false)}
            onCsv={downloadCsv}
          />
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* ---- Verdict ---- */}
      <div className="card">
        <div className="card-head !py-3">
          <ShieldAlert className="h-4 w-4 text-brand-600" />
          <h2 className="text-sm font-bold text-ink">
            Status classification — IEEE C57.104-2019, Figure 2
          </h2>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <button className="btn-ghost !py-1.5 text-xs" onClick={downloadCsv}>
              <Table2 className="h-3.5 w-3.5" /> Evidence CSV
            </button>
            <button
              className="btn-ghost !py-1.5 text-xs"
              onClick={downloadPdf}
              disabled={pdfBusy}
            >
              <Download className="h-3.5 w-3.5" />
              {pdfBusy ? 'Building…' : 'Download PDF'}
            </button>
            <button className="btn-primary !py-1.5 text-xs" onClick={() => setShowReport(true)}>
              <FileText className="h-3.5 w-3.5" /> Full report
            </button>
          </div>
        </div>
        <div className="card-pad">
          {pdfError && (
            <p className="mb-3 rounded-lg bg-red-50 p-2.5 text-xs text-red-700">{pdfError}</p>
          )}
          <div className="flex flex-wrap items-start gap-6">
            <div
              className="rounded-xl px-6 py-4 text-center"
              style={{ background: s.bg, border: `2px solid ${s.color}` }}
            >
              <p className="text-3xl font-bold leading-none" style={{ color: s.color }}>
                {s.statusLabel}
              </p>
              <p className="mt-1.5 text-sm font-semibold" style={{ color: s.color }}>
                {s.verdict}
              </p>
            </div>
            <div className="min-w-[260px] flex-1">
              <p className="text-sm leading-relaxed text-ink">{s.reason}</p>
              <p className="mt-2.5 rounded-lg bg-brand-50 p-3 text-sm leading-relaxed text-ink-soft">
                <span className="font-semibold">Action — </span>
                {s.action}
              </p>
            </div>
          </div>

          <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2.5 border-t border-line pt-3 text-xs sm:grid-cols-4 lg:grid-cols-6">
            {[
              ['O₂/N₂ section', s.ratioBand ?? '—'],
              ['O₂/N₂ ratio', s.o2n2 === null ? 'not measured' : s.o2n2.toFixed(3)],
              ['Age band', s.ageBand ?? '—'],
              ['Age', s.ageYears === null ? 'unknown' : `${s.ageYears} yr`],
              ['Table 4 period', s.periodBand ? `${s.periodBand} mo` : 'not applied'],
              ['Samples', String(s.samples)],
              ['First sample', s.firstSample ?? '—'],
              ['Latest sample', s.latestSample ?? '—'],
              ['Multi-point rate', s.ratesAvailable ? 'available' : 'not available'],
              ['Gases measured', s.measuredGases.join(', ') || '—'],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="text-ink-muted">{k}</dt>
                <dd className="num font-semibold text-ink">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      {/* ---- Flags that change what an engineer should do next ---- */}
      {(s.pendingConfirmation || s.extreme.length > 0 || s.deEscalationCandidate) && (
        <div className="space-y-3">
          {s.extreme.length > 0 && (
            <div className="rounded-xl border border-red-300 bg-red-50 p-4">
              <div className="flex items-start gap-3">
                <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-red-600" />
                <div>
                  <p className="text-sm font-bold text-red-900">
                    Extreme values — expert review, not a routine status
                  </p>
                  <ul className="mt-1.5 space-y-1">
                    {s.extreme.map((f, i) => (
                      <li key={i} className="text-sm text-red-900">
                        {f.text}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-xs text-red-800">
                    Section 6.1.2.4 of the guide treats values this far past the tables as an
                    immediate escalation regardless of the computed status.
                  </p>
                </div>
              </div>
            </div>
          )}

          {s.pendingConfirmation && s.confirmation && (
            <div className="rounded-xl border border-amber-300 bg-amber-50 p-4">
              <div className="flex items-start gap-3">
                <CalendarClock className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
                <div>
                  <p className="text-sm font-bold text-amber-900">
                    Confirmation sample due within {s.confirmation.dueWithin}
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-amber-900">
                    {s.confirmation.reason}
                  </p>
                  <p className="mt-1.5 text-xs text-amber-800">
                    Counted from the sample of {s.confirmation.fromSample}.
                  </p>
                </div>
              </div>
            </div>
          )}

          {s.deEscalationCandidate && (
            <div className="rounded-xl border border-brand-300 bg-brand-50 p-4">
              <div className="flex items-start gap-3">
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
                <div>
                  <p className="text-sm font-bold text-brand-900">
                    Candidate for engineer de-escalation
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-ink-soft">
                    This Status 3 rests only on carbon-oxide levels with no active gassing. Step 7
                    of the guide allows a downgrade after a year of quiet results — a manual
                    decision, never an automatic one, so the status above stands until an engineer
                    changes it.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ---- Decision path ---- */}
      <div className="card">
        <div className="card-head !py-3">
          <ArrowRight className="h-4 w-4 text-brand-600" />
          <h2 className="text-sm font-bold text-ink">Decision path</h2>
        </div>
        <div className="card-pad">
          <DecisionFlow result={s} />
        </div>
      </div>

      {/* ---- Triggers ---- */}
      <div className="card">
        <div className="card-head !py-3">
          <AlertTriangle className="h-4 w-4 text-brand-600" />
          <h2 className="text-sm font-bold text-ink">
            What drove the status ({s.triggeredBy.length})
          </h2>
        </div>
        <div className="card-pad">
          {s.triggeredBy.length === 0 ? (
            <p className="text-sm text-ink-soft">
              Nothing exceeded a limit — every measured gas is below its Table 1 level, with no
              change or rate outside the allowance.
            </p>
          ) : (
            <ol className="space-y-2">
              {s.triggeredBy.map((t, i) => (
                <li key={`${t.gas}-${t.kind}-${i}`} className="flex items-start gap-3">
                  <span
                    className="chip shrink-0 font-mono text-[11px]"
                    style={{
                      background: t.severity >= 3 ? '#FCEAEA' : '#FDF6E3',
                      color: t.severity >= 3 ? '#D64545' : '#B7791F',
                    }}
                  >
                    {t.kind}
                  </span>
                  <span className="text-sm text-ink">
                    {t.text}
                    {t.verify && (
                      <span className="ml-1.5 text-[11px] text-amber-700">
                        (limit flagged for verification)
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>

      {/* ---- Per-gas evidence ---- */}
      <div className="card">
        <div className="card-head !py-3">
          <Table2 className="h-4 w-4 text-brand-600" />
          <h2 className="text-sm font-bold text-ink">Gas-by-gas evidence</h2>
        </div>
        <div className="card-pad">
          <div className="scroll-x">
            <table className="w-full min-w-[940px] border-collapse">
              <thead>
                <tr>
                  <th className="th">Gas</th>
                  <th className="th">Latest</th>
                  <th className="th">Date</th>
                  <th className="th">T1</th>
                  <th className="th">T2</th>
                  <th className="th">Δ</th>
                  <th className="th">T3</th>
                  <th className="th">Rate</th>
                  <th className="th">T4</th>
                  <th className="th">Verdict</th>
                  <th className="th">Note</th>
                </tr>
              </thead>
              <tbody>
                {s.gases.map((g) => {
                  const flags = [
                    g.exceedsT2 && 'level > T2',
                    !g.exceedsT2 && g.exceedsT1 && 'level > T1',
                    g.exceedsT3 && 'Δ > T3',
                    g.exceedsT4 && 'rate > T4',
                  ].filter(Boolean) as string[]
                  return (
                    <tr
                      key={g.gas}
                      className={g.measured ? 'hover:bg-brand-50/50' : 'opacity-50'}
                    >
                      <td className="td font-semibold">{g.gas}</td>
                      <td className="td num text-xs font-semibold">
                        {g.latest === null ? '—' : g.latest.toFixed(1)}
                      </td>
                      <td className="td num text-[11px] text-ink-muted">{g.latestDate ?? '—'}</td>
                      <td className="td num text-xs text-ink-muted">
                        {g.t1 ?? '—'}
                        {g.t1Verify && <span className="text-amber-600"> ‡</span>}
                      </td>
                      <td className="td num text-xs text-ink-muted">
                        {g.t2 ?? '—'}
                        {g.t2Verify && <span className="text-amber-600"> ‡</span>}
                      </td>
                      <td className="td num text-xs">
                        {g.delta === null ? (
                          '—'
                        ) : (
                          <span className={g.delta > 0 ? 'text-red-600' : 'text-emerald-600'}>
                            {g.delta > 0 ? '+' : ''}
                            {g.delta.toFixed(1)}
                          </span>
                        )}
                      </td>
                      <td className="td num text-xs text-ink-muted">
                        {limitText(g.t3)}
                        {g.t3Verify && <span className="text-amber-600"> ‡</span>}
                      </td>
                      <td className="td num text-xs">
                        {g.rate === null
                          ? '—'
                          : `${g.rate > 0 ? '+' : ''}${g.rate.toFixed(1)}`}
                      </td>
                      <td className="td num text-xs text-ink-muted">
                        {s.ratesAvailable ? limitText(g.t4) : '—'}
                        {g.t4Verify && <span className="text-amber-600"> ‡</span>}
                      </td>
                      <td className="td">
                        {!g.measured ? (
                          <span className="text-xs text-ink-faint">not measured</span>
                        ) : flags.length === 0 ? (
                          <span className="chip bg-emerald-50 text-[11px] text-emerald-700">
                            <CheckCircle2 className="h-3 w-3" /> within limits
                          </span>
                        ) : (
                          <span className="flex flex-wrap gap-1">
                            {flags.map((f) => (
                              <span
                                key={f}
                                className="chip bg-red-50 text-[11px] text-red-700"
                              >
                                {f}
                              </span>
                            ))}
                          </span>
                        )}
                      </td>
                      <td className="td text-[11px] text-ink-muted">{g.note || '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-ink-muted">
            ‡ marks a limit taken from a cell the source scan rendered ambiguously — verify it
            against a printed copy of the standard before acting on it.
          </p>
        </div>
      </div>

      {/* ---- Assumptions ---- */}
      {s.assumptions.length > 0 && (
        <div className="card">
          <div className="card-head !py-3">
            <AlertTriangle className="h-4 w-4 text-brand-600" />
            <h2 className="text-sm font-bold text-ink">Assumptions made</h2>
          </div>
          <div className="card-pad">
            <ul className="space-y-1.5">
              {s.assumptions.map((a, i) => (
                <li key={i} className="flex items-start gap-2 text-sm leading-relaxed text-ink-soft">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
                  {a}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}

function Fleet({ onOpen }: { onOpen: (asset: string) => void }) {
  const scope = useScope()
  const [rows, setRows] = useState<DgaFleetStatusRow[] | null>(null)
  const [summary, setSummary] = useState<DgaStatusSummary | null>(null)
  const [ageSource, setAgeSource] = useState<DgaAgeSource | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<number | 'all'>('all')

  // A fleet sweep classifies every asset with history, so it is a button press
  // rather than something that fires on arrival.
  async function run() {
    setLoading(true)
    setError(null)
    try {
      const res = await api.post<{
        rows: DgaFleetStatusRow[]
        summary: DgaStatusSummary
        ageSource: DgaAgeSource
      }>('/dga/status/fleet', { node: scope.node || undefined })
      setRows(res.rows)
      setSummary(res.summary)
      setAgeSource(res.ageSource)
    } catch (e: any) {
      setError(e.message || 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  const shown = useMemo(
    () => (rows ?? []).filter((r) => filter === 'all' || r.status === filter),
    [rows, filter],
  )

  return (
    <div className="space-y-4">
      <div className="card card-pad flex flex-wrap items-center gap-3">
        <p className="min-w-0 flex-1 text-sm text-ink-soft">
          Classify every asset with DGA history in the current scope against Figure 2.
        </p>
        <button className="btn-primary text-sm" onClick={run} disabled={loading}>
          <Layers className="h-4 w-4" />
          {loading ? 'Classifying…' : rows ? 'Re-run sweep' : 'Run fleet sweep'}
        </button>
      </div>

      {error && <ErrorNote message={error} onRetry={run} />}
      {loading && <Loader label="Classifying the fleet…" />}

      {/* A sweep with no age map is still valid, but it used different limit
          columns than a single-asset run would — say so rather than letting the
          two screens quietly disagree. */}
      {ageSource === 'unavailable' && rows && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
            <div className="text-sm leading-relaxed text-amber-900">
              <p className="font-bold">Ages unavailable — every asset used the “Unknown” column</p>
              <p className="mt-1">
                The CMMS manufacture-year map is not primed, and looking each asset up
                individually would take minutes. Tables 1 and 2 have an age-independent column for
                exactly this, so the statuses below are valid — but they use the age-blind limits.
                Open an individual asset for its true age band, or run the daily snapshot job to
                refresh the map.
              </p>
            </div>
          </div>
        </div>
      )}

      {summary && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatCard icon={CheckCircle2} label="Status 1" value={summary.status1}
                    sub="probably normal" accent="#0E9F6E" />
          <StatCard icon={AlertTriangle} label="Status 2" value={summary.status2}
                    sub="possibly suspicious" accent="#B7791F" />
          <StatCard icon={ShieldAlert} label="Status 3" value={summary.status3}
                    sub="probably suspicious" accent="#D64545" />
          <StatCard icon={CalendarClock} label="Confirmation due" value={summary.pendingConfirmation}
                    sub="re-sample within a month" accent="#1E72BC" />
          <StatCard icon={ClipboardList} label="Classified" value={summary.total}
                    sub={`${summary.unclassified} with no usable data`} accent="#5A6B80" />
        </div>
      )}

      {rows && (
        <div className="card">
          <div className="card-head !py-3">
            <Layers className="h-4 w-4 text-brand-600" />
            <h2 className="text-sm font-bold text-ink">Fleet status ({shown.length})</h2>
            <div className="ml-auto flex flex-wrap gap-1.5">
              {([['all', 'All'], [3, 'Status 3'], [2, 'Status 2'], [1, 'Status 1']] as const).map(
                ([id, label]) => (
                  <button
                    key={String(id)}
                    onClick={() => setFilter(id as number | 'all')}
                    className={`chip text-[11px] transition-colors ${
                      filter === id
                        ? 'bg-brand-600 text-white'
                        : 'border border-line bg-white text-ink-soft hover:bg-brand-50'
                    }`}
                  >
                    {label}
                  </button>
                ),
              )}
            </div>
          </div>
          <div className="scroll-x">
            <table className="w-full min-w-[860px] border-collapse">
              <thead>
                <tr>
                  <th className="th">Asset</th>
                  <th className="th">Status</th>
                  <th className="th">Latest sample</th>
                  <th className="th">Samples</th>
                  <th className="th">Age band</th>
                  <th className="th">O₂/N₂</th>
                  <th className="th">Rate</th>
                  <th className="th">Leading trigger</th>
                  <th className="th"></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.asset} className="hover:bg-brand-50/50">
                    <td className="td font-mono text-[11px]">{r.asset}</td>
                    <td className="td">
                      <StatusPill status={r.status} label={r.statusLabel} color={r.color}
                                  bg={r.bg} size="sm" />
                      {r.pendingConfirmation && (
                        <span className="chip ml-1 bg-amber-50 text-[10px] text-amber-800">
                          re-sample
                        </span>
                      )}
                      {r.extreme > 0 && (
                        <span className="chip ml-1 bg-red-50 text-[10px] text-red-700">
                          extreme
                        </span>
                      )}
                    </td>
                    <td className="td num text-xs">{r.latestSample ?? '—'}</td>
                    <td className="td num text-xs">{r.samples}</td>
                    <td className="td text-xs text-ink-muted">{r.ageBand ?? '—'}</td>
                    <td className="td text-xs text-ink-muted">{r.ratioBand ?? '—'}</td>
                    <td className="td text-xs text-ink-muted">
                      {r.ratesAvailable ? 'yes' : 'no'}
                    </td>
                    <td className="td text-xs text-ink-soft">{r.topTrigger ?? '—'}</td>
                    <td className="td">
                      <button
                        className="btn-ghost !px-2 !py-1 text-[11px]"
                        onClick={() => onOpen(r.asset)}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
                {shown.length === 0 && (
                  <tr>
                    <td className="td text-sm text-ink-muted" colSpan={9}>
                      No asset in this status.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!rows && !loading && !error && (
        <div className="card">
          <EmptyState
            icon={Layers}
            title="No sweep run yet"
            hint="A fleet sweep classifies every asset with dissolved-gas history in the current
                  scope. It reads the whole DGA table, so it runs on request rather than on
                  arrival."
          />
        </div>
      )}
    </div>
  )
}

function ReferenceTables() {
  const { data, loading, error, reload } = useApi<DgaLimitTables>('/dga/status/tables')
  const [ratio, setRatio] = useState('>0.2')

  if (loading) return <Loader label="Loading reference tables…" />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  const cell = (c: { limit: number | string | null; verify: boolean } | undefined) => (
    <>
      {limitText((c?.limit ?? null) as never)}
      {c?.verify && <span className="text-amber-600"> ‡</span>}
    </>
  )

  return (
    <div className="space-y-4">
      <div className="card card-pad flex flex-wrap items-center gap-3">
        <span className="label !mb-0">O₂/N₂ section</span>
        {data.ratioBands.map((b) => (
          <button
            key={b}
            onClick={() => setRatio(b)}
            className={`chip text-xs transition-colors ${
              ratio === b
                ? 'bg-brand-600 text-white'
                : 'border border-line bg-white text-ink-soft hover:bg-brand-50'
            }`}
          >
            O₂/N₂ {b}
          </button>
        ))}
        <p className="ml-auto text-[11px] text-ink-muted">{data.source}</p>
      </div>

      {([
        ['Table 1 — 90th percentile levels (ppm)', data.table1, data.ageBands, 'Age band'],
        ['Table 2 — 95th percentile levels (ppm)', data.table2, data.ageBands, 'Age band'],
      ] as const).map(([title, table, bands, header]) => (
        <div key={title} className="card">
          <div className="card-head !py-3">
            <Table2 className="h-4 w-4 text-brand-600" />
            <h2 className="text-sm font-bold text-ink">{title}</h2>
          </div>
          <div className="scroll-x">
            <table className="w-full min-w-[620px] border-collapse">
              <thead>
                <tr>
                  <th className="th">{header}</th>
                  {data.gases.map((g) => (
                    <th key={g} className="th">{g}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bands.map((b) => (
                  <tr key={b}>
                    <td className="td text-xs font-semibold">{b}</td>
                    {data.gases.map((g) => (
                      <td key={g} className="td num text-xs">
                        {cell(table[ratio]?.[b]?.[g])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      <div className="card">
        <div className="card-head !py-3">
          <Table2 className="h-4 w-4 text-brand-600" />
          <h2 className="text-sm font-bold text-ink">
            Table 3 — allowable change between consecutive samples (ppm)
          </h2>
        </div>
        <div className="scroll-x">
          <table className="w-full min-w-[620px] border-collapse">
            <thead>
              <tr>
                <th className="th">O₂/N₂ section</th>
                {data.gases.map((g) => (
                  <th key={g} className="th">{g}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.ratioBands.map((b) => (
                <tr key={b}>
                  <td className="td text-xs font-semibold">{b}</td>
                  {data.gases.map((g) => (
                    <td key={g} className="td num text-xs">{cell(data.table3[b]?.[g])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-head !py-3">
          <Table2 className="h-4 w-4 text-brand-600" />
          <h2 className="text-sm font-bold text-ink">
            Table 4 — allowable multi-point rate (ppm/year), O₂/N₂ {ratio}
          </h2>
        </div>
        <div className="scroll-x">
          <table className="w-full min-w-[620px] border-collapse">
            <thead>
              <tr>
                <th className="th">Sampling period</th>
                {data.gases.map((g) => (
                  <th key={g} className="th">{g}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.periodBands.map((p) => (
                <tr key={p}>
                  <td className="td text-xs font-semibold">{p} months</td>
                  {data.gases.map((g) => (
                    <td key={g} className="td num text-xs">{cell(data.table4[ratio]?.[p]?.[g])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-xl border border-amber-300 bg-amber-50 p-4">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
          <div className="text-sm leading-relaxed text-amber-900">
            <p className="font-bold">Verify these numbers before production use.</p>
            <p className="mt-1">
              The decision logic is exact, but the tables were reconstructed from a scanned copy
              of the standard. Cells marked ‡ were faint or merged in the source; the one Table 3
              cell shown as “not available” could not be read at all, so that comparison is
              skipped rather than guessed and every affected result says so.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * DGA Status — the IEEE C57.104-2019 Figure 2 classifier.
 *
 * Deliberately a separate section from Trend Analysis. The trend screen answers
 * "what number does this feed the health index"; this one answers "what status
 * does the standard put this unit in, and can I sign the report".
 */
export default function DgaStatus() {
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<Tab>((params.get('tab') as Tab) || 'assessment')
  const [asset, setAsset] = useState(params.get('asset') ?? '')

  useEffect(() => {
    const next: Record<string, string> = { tab }
    if (asset) next.asset = asset
    setParams(next, { replace: true })
  }, [asset, tab])

  return (
    <div>
      <div className="print-hide">
        <SectionHeader
          accent="#195B96"
          icon={ShieldAlert}
          title="DGA Status"
          subtitle="IEEE C57.104-2019 Figure 2 — Status 1 / 2 / 3 from gas levels, change and rate,
                    with the signed report"
        />
        <ScopeBanner />

        <div className="mb-4 flex flex-wrap gap-1.5">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`btn text-sm ${
                tab === id
                  ? 'bg-brand-600 text-white'
                  : 'border border-line bg-white text-ink-soft hover:bg-brand-50'
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </div>

        {tab === 'assessment' && (
          <div className="card card-pad mb-4">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <DgaAssetPicker value={asset} onChange={setAsset} />
              <p className="self-end text-xs leading-relaxed text-ink-muted lg:col-span-2">
                The classification reads the asset's full DGA history: levels from the newest
                reading of each gas, the change since the previous one, and — where three or more
                samples span four months or more — a least-squares rate. Clipping the date window
                would change which samples form the rate group, so it is deliberately not offered
                here. To classify figures that are not on record yet, use{' '}
                <Link className="link" to="/dga-entry">
                  DGA Status Entry
                </Link>
                .
              </p>
            </div>
          </div>
        )}
      </div>

      {tab === 'assessment' && <Assessment asset={asset} />}
      {tab === 'fleet' && (
        <div className="print-hide">
          <Fleet
            onOpen={(a) => {
              setAsset(a)
              setTab('assessment')
            }}
          />
        </div>
      )}
      {tab === 'tables' && (
        <div className="print-hide">
          <ReferenceTables />
        </div>
      )}
    </div>
  )
}
