import {
  ArrowLeft,
  Calculator,
  CheckSquare,
  Info,
  RotateCcw,
  Square,
  Sigma,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { ConfigWarning, ErrorNote, HIBadge, Loader, SectionHeader } from '../components/ui'
import type { HIComponent, HIDetail } from '../types'

/** The DB values behind one criterion, with the considered one highlighted. */
function CandidateCells({ component }: { component: HIComponent }) {
  const [expanded, setExpanded] = useState(false)
  const cands = component.candidates ?? []

  if (!cands.length) {
    return <span className="text-xs text-ink-faint">—</span>
  }

  const LIMIT = 6
  const shown = expanded ? cands : cands.slice(0, LIMIT)
  const hidden = cands.length - shown.length
  // A blended criterion (DGA) has no single "considered" value — every
  // candidate feeds the result, so highlighting one would misrepresent it.
  const blend = component.mode === 'blend'

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-x-1 gap-y-1">
        {shown.map((c, i) => (
          <span key={`${c.label}-${i}`} className="inline-flex items-center">
            <span
              className={`num rounded px-1.5 py-0.5 text-[11px] ${
                c.used && !blend
                  ? 'bg-brand-600 font-bold text-white'
                  : 'bg-brand-50 text-ink-soft'
              }`}
              title={`${c.label}${c.source ? ` · ${c.source}` : ''}${
                c.date ? ` · ${String(c.date).slice(0, 10)}` : ''
              }${c.reason ? ` — ${c.reason}` : ''}${c.used && !blend ? ' — value used' : ''}`}
            >
              {typeof c.value === 'number'
                ? c.value.toLocaleString(undefined, { maximumFractionDigits: 3 })
                : String(c.value)}
            </span>
            {i < shown.length - 1 && <span className="text-ink-faint">,</span>}
          </span>
        ))}
        {hidden > 0 && (
          <button
            onClick={() => setExpanded(true)}
            className="text-[11px] font-semibold text-brand-700 hover:underline"
          >
            +{hidden} more
          </button>
        )}
        {expanded && cands.length > LIMIT && (
          <button
            onClick={() => setExpanded(false)}
            className="text-[11px] font-semibold text-brand-700 hover:underline"
          >
            show less
          </button>
        )}
      </div>
      {component.rule && (
        <p className="mt-0.5 text-[10px] leading-tight text-ink-faint">{component.rule}</p>
      )}
    </div>
  )
}

export default function ManualCalculation() {
  const params = useParams()
  const [search] = useSearchParams()
  const asset = decodeURIComponent(params['*'] ?? search.get('asset') ?? '')

  const [result, setResult] = useState<HIDetail | null>(null)
  const [baseline, setBaseline] = useState<HIDetail | null>(null)
  const [selected, setSelected] = useState<Set<string> | null>(null)
  const [manual, setManual] = useState<Record<string, string>>({})
  const [age, setAge] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(
    async (sel: Set<string> | null, man: Record<string, string>, ageValue: string,
           asBaseline = false) => {
      setBusy(true)
      setError(null)
      try {
        const manualScores: Record<string, number> = {}
        for (const [k, v] of Object.entries(man)) {
          const n = Number(v)
          if (v !== '' && !Number.isNaN(n)) manualScores[k] = Math.max(0, Math.min(1, n))
        }
        const body: Record<string, unknown> = { manual: manualScores }
        if (sel) body.selected = [...sel]
        if (ageValue !== '') body.age = Number(ageValue)

        const res = await api.post<HIDetail>(
          `/health-index/${encodeURIComponent(asset)}`,
          body,
        )
        setResult(res)
        if (asBaseline) setBaseline(res)
      } catch (e: any) {
        setError(e.message ?? 'Calculation failed')
      } finally {
        setBusy(false)
      }
    },
    [asset],
  )

  // First load scores everything, which also tells us which criteria exist.
  useEffect(() => {
    if (asset) run(null, {}, '', true)
  }, [asset, run])

  const components = result?.components ?? []
  // AGE now resolves for ~9,000 of the 13,109 scored assets, from the CMMS
  // year of manufacture, so the placeholder shows the year behind the age
  // rather than just the number.
  const ageComponent = components.find((c) => c.code === 'AGE')
  const selectable = useMemo(
    () => components.filter((c) => c.available || c.manual),
    [components],
  )

  const isSelected = (code: string) =>
    selected ? selected.has(code) : (components.find((c) => c.code === code)?.selected ?? true)

  function toggle(code: string) {
    const current = new Set(
      selected ?? components.filter((c) => c.selected).map((c) => c.code),
    )
    if (current.has(code)) current.delete(code)
    else current.add(code)
    setSelected(current)
  }

  function selectAll() {
    setSelected(new Set(selectable.map((c) => c.code)))
  }

  function selectNone() {
    setSelected(new Set())
  }

  function reset() {
    setSelected(null)
    setManual({})
    setAge('')
    run(null, {}, '', true)
  }

  const chosenCount = selected
    ? selected.size
    : components.filter((c) => c.selected && c.available).length

  return (
    <div>
      <Link
        to={`/health-index/${encodeURIComponent(asset)}`}
        className="mb-3 inline-flex items-center gap-1.5 text-xs font-semibold text-brand-700 hover:underline"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to automatic health index
      </Link>

      <SectionHeader
        accent="#4A3AA7"
        icon={Calculator}
        title="Manual Health Index Calculation"
        subtitle={asset}
        actions={
          <>
            <button onClick={reset} className="btn-ghost" disabled={busy}>
              <RotateCcw className="h-4 w-4" />
              Reset
            </button>
            <button
              onClick={() => run(selected, manual, age)}
              className="btn-primary"
              disabled={busy}
            >
              <Calculator className={`h-4 w-4 ${busy ? 'animate-pulse' : ''}`} />
              {busy ? 'Calculating…' : 'Calculate'}
            </button>
          </>
        }
      />

      {error && <ErrorNote message={error} />}
      {busy && !result && <Loader label="Reading measurements…" />}

      {result && (
        <>
          {result.configAudit && !result.configAudit.trustworthy && (
            <div className="mb-4">
              <ConfigWarning audit={result.configAudit} />
            </div>
          )}

          {/* Result + inputs */}
          <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-4">
            <div className="card card-pad">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                Health Index
              </p>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="num text-4xl font-bold" style={{ color: result.band?.color }}>
                  {result.healthIndex?.toFixed(2) ?? '—'}
                </span>
                <span className="text-sm text-ink-muted">/ 100</span>
              </div>
              {result.band && (
                <div className="mt-2">
                  <HIBadge
                    value={result.healthIndex}
                    label={result.band.label}
                    color={result.band.color}
                    bg={result.band.bg}
                    size="lg"
                  />
                </div>
              )}
              {baseline && baseline.healthIndex !== result.healthIndex && (
                <p className="mt-2 text-[11px] text-ink-muted">
                  All criteria:{' '}
                  <span className="num font-semibold">
                    {baseline.healthIndex?.toFixed(2) ?? '—'}
                  </span>{' '}
                  (
                  <span
                    className="num font-semibold"
                    style={{
                      color:
                        (result.healthIndex ?? 0) >= (baseline.healthIndex ?? 0)
                          ? '#0E9F6E'
                          : '#D64545',
                    }}
                  >
                    {(result.healthIndex ?? 0) >= (baseline.healthIndex ?? 0) ? '+' : ''}
                    {((result.healthIndex ?? 0) - (baseline.healthIndex ?? 0)).toFixed(2)}
                  </span>
                  )
                </p>
              )}
            </div>

            <div className="card card-pad">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                Criteria selected
              </p>
              <p className="num mt-2 text-3xl font-bold text-ink">
                {chosenCount}
                <span className="text-base font-medium text-ink-muted">
                  /{result.componentsTotal}
                </span>
              </p>
              <div className="mt-3 flex gap-2">
                <button onClick={selectAll} className="btn-ghost !px-2 !py-1 !text-[11px]">
                  Select all
                </button>
                <button onClick={selectNone} className="btn-ghost !px-2 !py-1 !text-[11px]">
                  Clear
                </button>
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
                Weights re-normalise over the criteria you keep, so the index always
                lands on 0–100.
              </p>
            </div>

            <div className="card card-pad">
              <label className="label">Asset age (years)</label>
              <input
                className="input num"
                type="number"
                min={0}
                step={1}
                placeholder={
                  ageComponent?.value != null
                    ? `${ageComponent.value}${
                        ageComponent.detail?.manufactureYear
                          ? ` — manufactured ${ageComponent.detail.manufactureYear}`
                          : ''
                      }`
                    : 'no year of manufacture on record'
                }
                value={age}
                onChange={(e) => setAge(e.target.value)}
              />
              <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
                Counted from the year of manufacture in the Tomms CMMS
                (<span className="font-mono">ast_det_datetime1</span>). Enter a value
                here to override it — for the assets whose CMMS row is blank, or
                where you know the register is wrong.
              </p>
            </div>

            <div className="card card-pad">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                Weight check
              </p>
              <p className="num mt-2 text-3xl font-bold text-ink">
                {components
                  .filter((c) => c.selected && c.available)
                  .reduce((s, c) => s + (c.weight ?? 0), 0)
                  .toFixed(1)}
                <span className="text-base font-medium text-ink-muted">%</span>
              </p>
              <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
                Sum of normalised weights across the scored criteria. Should read 100
                whenever at least one criterion is scored.
              </p>
            </div>
          </div>

          {/* Criteria table */}
          <div className="card">
            <div className="card-head !py-3.5">
              <Sigma className="h-4 w-4 text-brand-600" />
              <h2 className="text-sm font-bold text-ink">Criteria</h2>
              <span className="ml-auto flex items-center gap-1.5 text-[11px] text-ink-muted">
                <span className="inline-block h-2.5 w-4 rounded bg-brand-600" />
                value used in the calculation
              </span>
            </div>

            <div className="scroll-x">
              <table className="w-full min-w-[1080px] border-collapse">
                <thead>
                  <tr>
                    <th className="th w-10"></th>
                    <th className="th">Criterion</th>
                    <th className="th">Values from database</th>
                    <th className="th">Considered</th>
                    <th className="th">Score</th>
                    <th className="th">Weight</th>
                    <th className="th">Sub HI</th>
                    <th className="th">Tested</th>
                  </tr>
                </thead>
                <tbody>
                  {components.map((c) => {
                    const on = isSelected(c.code)
                    const usable = c.available || c.manual
                    return (
                      <tr
                        key={c.code}
                        className={
                          !usable
                            ? 'bg-slate-50/70'
                            : on
                              ? 'hover:bg-brand-50/50'
                              : 'bg-slate-50/40 opacity-60'
                        }
                      >
                        <td className="td">
                          <button
                            onClick={() => toggle(c.code)}
                            disabled={!usable}
                            aria-label={`${on ? 'Exclude' : 'Include'} ${c.label}`}
                            className="disabled:opacity-30"
                          >
                            {on && usable ? (
                              <CheckSquare className="h-4 w-4 text-brand-600" />
                            ) : (
                              <Square className="h-4 w-4 text-ink-faint" />
                            )}
                          </button>
                        </td>
                        <td className="td">
                          <div className="flex items-center gap-1.5">
                            <span className="font-semibold text-ink">{c.label}</span>
                            {c.manual && (
                              <span className="chip bg-amber-50 text-[9px] text-amber-800">
                                manual
                              </span>
                            )}
                            {c.mode === 'blend' && (
                              <span
                                className="chip bg-brand-50 text-[9px] text-brand-800"
                                title="Every value below contributes to the result; none is picked over the others."
                              >
                                blended
                              </span>
                            )}
                          </div>
                          <span className="font-mono text-[10px] text-ink-faint">
                            {c.code}
                            {c.bandName ? ` · band ${c.bandName}` : ''}
                          </span>
                        </td>
                        <td className="td">
                          <CandidateCells component={c} />
                        </td>
                        <td className="td num text-xs font-semibold">
                          {c.value !== null ? (
                            <>
                              {Number(c.value).toLocaleString(undefined, {
                                maximumFractionDigits: 3,
                              })}
                              {c.unit && (
                                <span className="ml-1 font-normal text-ink-faint">{c.unit}</span>
                              )}
                            </>
                          ) : c.manual ? (
                            <input
                              className="input num !w-24 !py-1 !text-xs"
                              type="number"
                              min={0}
                              max={1}
                              step={0.05}
                              placeholder="0–1"
                              value={manual[c.code] ?? ''}
                              onChange={(e) =>
                                setManual((m) => ({ ...m, [c.code]: e.target.value }))
                              }
                            />
                          ) : (
                            <span className="text-ink-faint">no data</span>
                          )}
                        </td>
                        <td className="td num text-xs">
                          {c.score !== null ? (
                            <span
                              className="chip"
                              style={{
                                background:
                                  c.score >= 0.75
                                    ? '#E6F6F0'
                                    : c.score >= 0.5
                                      ? '#E8F1FC'
                                      : c.score >= 0.25
                                        ? '#FDF6E3'
                                        : '#FCEAEA',
                                color:
                                  c.score >= 0.75
                                    ? '#0E9F6E'
                                    : c.score >= 0.5
                                      ? '#2E7DD1'
                                      : c.score >= 0.25
                                        ? '#B7791F'
                                        : '#D64545',
                              }}
                            >
                              {c.score.toFixed(2)}
                            </span>
                          ) : (
                            <span className="text-ink-faint">—</span>
                          )}
                        </td>
                        <td className="td num text-xs text-ink-soft">
                          {on && c.available ? `${c.weight.toFixed(2)}%` : '—'}
                          {c.configuredWeight ? (
                            <span className="ml-1 text-[10px] text-ink-faint">
                              (cfg {c.configuredWeight})
                            </span>
                          ) : null}
                        </td>
                        <td className="td num text-xs font-bold text-ink">
                          {c.contribution !== null && on ? c.contribution.toFixed(2) : '—'}
                        </td>
                        <td className="td num text-[11px] text-ink-muted">
                          {c.date ? String(c.date).slice(0, 10) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr className="bg-brand-50/70">
                    <td className="td"></td>
                    <td className="td text-xs font-bold text-ink">Health Index</td>
                    <td className="td"></td>
                    <td className="td"></td>
                    <td className="td"></td>
                    <td className="td num text-xs font-bold text-ink">
                      {components
                        .filter((c) => c.selected && c.available)
                        .reduce((s, c) => s + (c.weight ?? 0), 0)
                        .toFixed(2)}
                      %
                    </td>
                    <td className="td num text-sm font-bold" style={{ color: result.band?.color }}>
                      {result.healthIndex?.toFixed(2) ?? '—'}
                    </td>
                    <td className="td"></td>
                  </tr>
                </tfoot>
              </table>
            </div>

            <p className="flex items-start gap-1.5 border-t border-line px-5 py-3 text-[11px] leading-relaxed text-ink-muted">
              <Info className="mt-px h-3.5 w-3.5 shrink-0" />
              Where a criterion is measured by more than one test — oil BDV is recorded
              by both the dedicated test and the transformer routine, for instance — every
              recorded value is listed and the one actually scored is highlighted. Hover
              any value for its source table, phase or tap, and test date.
            </p>
          </div>
        </>
      )}
    </div>
  )
}
