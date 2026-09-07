import { AlertTriangle, CheckCircle2, Download, FileText, Printer, Table2, X } from 'lucide-react'
import { limitText } from '../lib/dgaStatusCsv'
import type { DgaStatusGas, DgaStatusReport, DgaLimit } from '../types'

const GAS_LABEL: Record<string, string> = {
  H2: 'Hydrogen',
  CH4: 'Methane',
  C2H6: 'Ethane',
  C2H4: 'Ethylene',
  C2H2: 'Acetylene',
  CO: 'Carbon monoxide',
  CO2: 'Carbon dioxide',
}

const num = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? '—' : v.toFixed(digits)

/** A verdict cell: the word, not just a colour, so it survives a mono printer. */
function Verdict({ over, na }: { over: boolean; na?: boolean }) {
  if (na) return <span className="text-xs text-ink-faint">n/a</span>
  return over ? (
    <span className="chip bg-red-50 text-[11px] text-red-700">
      <AlertTriangle className="h-3 w-3" /> over
    </span>
  ) : (
    <span className="chip bg-emerald-50 text-[11px] text-emerald-700">
      <CheckCircle2 className="h-3 w-3" /> within
    </span>
  )
}

function Section({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 break-inside-avoid">
      <h3 className="mb-2 flex items-center gap-2 border-b border-line pb-1.5 text-sm font-bold text-ink">
        <span className="num inline-flex h-5 w-5 items-center justify-center rounded bg-brand-100 text-[11px] text-brand-800">
          {n}
        </span>
        {title}
      </h3>
      {children}
    </section>
  )
}

/**
 * The printable DGA status report.
 *
 * Everything an engineer needs to re-derive the verdict by hand: the columns
 * the standard selected, the reading and the limit for every gas, and the
 * decision path. Print styling lives in `index.css` under `@media
 * print` — the app shell is a fixed-height scrolling frame, which would
 * otherwise print as one clipped page.
 */
/** jsPDF is heavy and most visits never export, so it is fetched on click. */
async function downloadPdf(report: DgaStatusReport) {
  const { exportDgaStatusPdf } = await import('../lib/dgaStatusPdf')
  exportDgaStatusPdf(report)
}

export default function DgaStatusReportView({
  report,
  onClose,
  onCsv,
}: {
  report: DgaStatusReport
  onClose: () => void
  onCsv: () => void
}) {
  const s = report.status
  const gases = s.gases.filter((g) => g.measured)
  const unmeasured = s.gases.filter((g) => !g.measured).map((g) => g.gas)

  return (
    <div className="card">
      {/* Controls — never printed. */}
      <div className="card-head print-hide !py-3">
        <FileText className="h-4 w-4 text-brand-600" />
        <h2 className="text-sm font-bold text-ink">DGA Status Report</h2>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button className="btn-ghost !py-1.5 text-xs" onClick={onCsv}>
            <Table2 className="h-3.5 w-3.5" /> Evidence CSV
          </button>
          <button className="btn-ghost !py-1.5 text-xs" onClick={() => window.print()}>
            <Printer className="h-3.5 w-3.5" /> Print
          </button>
          <button className="btn-primary !py-1.5 text-xs" onClick={() => downloadPdf(report)}>
            <Download className="h-3.5 w-3.5" /> Download PDF
          </button>
          <button className="btn-ghost !py-1.5 text-xs" onClick={onClose}>
            <X className="h-3.5 w-3.5" /> Close
          </button>
        </div>
      </div>

      <div className="card-pad print-area">
        {/* ---- Masthead ---- */}
        <div className="flex flex-wrap items-start justify-between gap-4 border-b-2 border-brand-600 pb-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-widest text-brand-700">
              Dissolved gas analysis — status assessment
            </p>
            <h1 className="mt-1 font-mono text-xl font-bold text-ink">{report.asset}</h1>
            <p className="mt-1 text-xs text-ink-muted">{report.standard}</p>
          </div>
          {/* The status carries its meaning in the words and their colour; the
              filled card it used to sit in added weight without adding
              information, and cost ink on every printed copy. */}
          <div className="text-right">
            <p className="text-2xl font-bold leading-none" style={{ color: s.color }}>
              {s.statusLabel}
            </p>
            <p className="mt-1 text-xs font-semibold" style={{ color: s.color }}>
              {s.verdict}
            </p>
          </div>
        </div>

        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
          {[
            ['Report generated', report.generatedAt],
            ['Latest sample', s.latestSample ?? '—'],
            ['Samples on record', String(s.samples)],
            ['History from', s.firstSample ?? '—'],
            ['O₂/N₂ section', s.ratioBand ?? '—'],
            ['Age band', `${s.ageBand ?? '—'}${s.ageYears !== null ? ` (${s.ageYears} yr)` : ''}`],
            ['Table 4 period', s.periodBand ? `${s.periodBand} months` : 'not applicable'],
            ['Multi-point rate', s.ratesAvailable ? 'available' : 'not available'],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-ink-muted">{k}</dt>
              <dd className="num font-semibold text-ink">{v}</dd>
            </div>
          ))}
        </dl>

        {/* ---- 1. Verdict ---- */}
        <Section n={1} title="Verdict">
          <p className="text-sm leading-relaxed text-ink">{s.reason}</p>
          <p className="mt-2 rounded-lg bg-brand-50 p-3 text-sm leading-relaxed text-ink-soft">
            <span className="font-semibold">Required action — </span>
            {s.action}
          </p>
          {s.ageSource?.manufactureYear && (
            <p className="mt-2 text-[11px] text-ink-muted">
              Age taken from the year of manufacture {s.ageSource.manufactureYear} (
              {s.ageSource.source}
              {s.ageSource.inheritedFrom ? `, via ${s.ageSource.inheritedFrom}` : ''}).
            </p>
          )}
        </Section>

        {/* ---- 2. What triggered it ---- */}
        <Section n={2} title="What drove the status">
          {s.triggeredBy.length === 0 ? (
            <p className="text-sm text-ink-soft">
              Nothing exceeded a limit — every measured gas is below its Table 1 level, with no
              change or rate outside the allowance.
            </p>
          ) : (
            <ol className="space-y-1.5">
              {s.triggeredBy.map((t, i) => (
                <li key={`${t.gas}-${t.kind}-${i}`} className="flex items-start gap-2.5 text-sm">
                  <span
                    className="num mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-[11px] font-bold"
                    style={{
                      background: t.severity >= 3 ? '#FCEAEA' : '#FDF6E3',
                      color: t.severity >= 3 ? '#D64545' : '#B7791F',
                    }}
                  >
                    {i + 1}
                  </span>
                  <span className="text-ink">
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
        </Section>

        {/* ---- 3. The Figure 2 path ---- */}
        <Section n={3} title="Decision path (Figure 2)">
          <div className="scroll-x">
            <table className="w-full min-w-[560px] border-collapse">
              <thead>
                <tr>
                  <th className="th">Step</th>
                  <th className="th">Question</th>
                  <th className="th">Answer</th>
                  <th className="th">Detail</th>
                </tr>
              </thead>
              <tbody>
                {s.decisionTrace.map((step) => (
                  <tr key={step.step}>
                    <td className="td text-xs font-semibold">{step.step}</td>
                    <td className="td text-xs text-ink-soft">{step.question}</td>
                    <td className="td text-xs font-semibold">{step.answer}</td>
                    <td className="td text-xs text-ink-muted">{step.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        {/* ---- 4. The evidence ---- */}
        <Section n={4} title="Gas-by-gas evidence">
          <div className="scroll-x">
            <table className="w-full min-w-[900px] border-collapse">
              <thead>
                <tr>
                  <th className="th">Gas</th>
                  <th className="th">Latest (ppm)</th>
                  <th className="th">T1 / 90th</th>
                  <th className="th">T2 / 95th</th>
                  <th className="th">Level</th>
                  <th className="th">Δ since previous</th>
                  <th className="th">T3 limit</th>
                  <th className="th">Change</th>
                  <th className="th">Rate (ppm/yr)</th>
                  <th className="th">T4 limit</th>
                  <th className="th">Rate</th>
                </tr>
              </thead>
              <tbody>
                {gases.map((g) => (
                  <GasRow key={g.gas} g={g} ratesAvailable={s.ratesAvailable} />
                ))}
              </tbody>
            </table>
          </div>
          {unmeasured.length > 0 && (
            <p className="mt-2 text-[11px] text-ink-muted">
              Not measured, so excluded from every comparison: {unmeasured.join(', ')}.
            </p>
          )}
          {s.rateWindow && s.ratesAvailable && (
            <p className="mt-1 text-[11px] text-ink-muted">
              Rates are the slope of a least-squares fit over the {s.rateWindow.points} samples
              from {s.rateWindow.from} to {s.rateWindow.to} ({s.rateWindow.spanMonths} months).
            </p>
          )}
        </Section>

        {/* ---- 5. Limits used ---- */}
        {report.limitsUsed && (
          <Section n={5} title="Limits applied">
            <p className="mb-2 text-xs text-ink-muted">
              Column selected by the standard: O₂/N₂ {report.limitsUsed.columns.ratioBand}, age{' '}
              {report.limitsUsed.columns.ageBand}
              {report.limitsUsed.columns.periodBand
                ? `, Table 4 period ${report.limitsUsed.columns.periodBand} months`
                : ', Table 4 not applied'}
              .
            </p>
            <div className="scroll-x">
              <table className="w-full min-w-[620px] border-collapse">
                <thead>
                  <tr>
                    <th className="th">Table</th>
                    {Object.keys(report.limitsUsed.table1).map((g) => (
                      <th key={g} className="th">
                        {g}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {([
                    ['Table 1 — 90th percentile level', report.limitsUsed.table1],
                    ['Table 2 — 95th percentile level', report.limitsUsed.table2],
                    ['Table 3 — change between samples', report.limitsUsed.table3],
                    [
                      'Table 4 — rate (ppm/yr)',
                      report.limitsUsed.table4 ?? {},
                    ],
                  ] as [string, Record<string, DgaLimit>][]).map(([name, row]) => (
                    <tr key={name}>
                      <td className="td text-xs font-semibold">{name}</td>
                      {Object.keys(report.limitsUsed!.table1).map((g) => (
                        <td key={g} className="td num text-xs">
                          {g in row ? limitText(row[g]) : '—'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {/* ---- 6. Sample history ---- */}
        <Section n={6} title="Sample history used">
          <div className="scroll-x">
            <table className="w-full min-w-[720px] border-collapse">
              <thead>
                <tr>
                  <th className="th">Date</th>
                  {['H2', 'CH4', 'C2H6', 'C2H4', 'C2H2', 'CO', 'CO2', 'O2', 'N2'].map((g) => (
                    <th key={g} className="th">
                      {g}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {report.sampleTable.map((row, i) => (
                  <tr key={`${row.date}-${i}`}>
                    <td className="td num text-xs font-semibold">{String(row.date)}</td>
                    {['H2', 'CH4', 'C2H6', 'C2H4', 'C2H2', 'CO', 'CO2', 'O2', 'N2'].map((g) => (
                      <td key={g} className="td num text-xs">
                        {row[g] === null || row[g] === undefined ? '—' : String(row[g])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        <p className="mt-6 border-t border-line pt-2 text-[10px] text-ink-faint">
          Generated {report.generatedAt} by the Transformer Asset Health Index &amp; Analysis
          system. The status is a screening result against the population statistics in{' '}
          {report.standard}; it does not replace an engineer's judgement.
        </p>
      </div>
    </div>
  )
}

function GasRow({ g, ratesAvailable }: { g: DgaStatusGas; ratesAvailable: boolean }) {
  const levelOver = g.exceedsT2 || g.exceedsT1
  return (
    <tr>
      <td className="td">
        <span className="font-semibold">{g.gas}</span>
        <span className="ml-1.5 text-[10px] text-ink-faint">{GAS_LABEL[g.gas]}</span>
      </td>
      <td className="td num text-xs font-semibold">{num(g.latest)}</td>
      <td className="td num text-xs text-ink-muted">
        {num(g.t1, 0)}
        {g.t1Verify && <span className="text-amber-600"> ‡</span>}
      </td>
      <td className="td num text-xs text-ink-muted">
        {num(g.t2, 0)}
        {g.t2Verify && <span className="text-amber-600"> ‡</span>}
      </td>
      <td className="td">
        {g.exceedsT2 ? (
          <span className="chip bg-red-50 text-[11px] text-red-700">
            <AlertTriangle className="h-3 w-3" /> above T2
          </span>
        ) : (
          <Verdict over={levelOver} />
        )}
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
      <td className="td">
        <Verdict over={g.exceedsT3} na={g.delta === null || g.t3 === null} />
      </td>
      <td className="td num text-xs">
        {g.rate === null ? '—' : `${g.rate > 0 ? '+' : ''}${g.rate.toFixed(1)}`}
      </td>
      <td className="td num text-xs text-ink-muted">
        {ratesAvailable ? limitText(g.t4) : '—'}
        {g.t4Verify && <span className="text-amber-600"> ‡</span>}
      </td>
      <td className="td">
        <Verdict over={g.exceedsT4} na={!ratesAvailable || g.rate === null} />
      </td>
    </tr>
  )
}
