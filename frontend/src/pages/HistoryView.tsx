import { Cpu, Database, FileClock, History, Search, Table2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { qs, useApi } from '../api'
import ScopeBanner from '../components/ScopeBanner'
import AssetSelect from '../components/AssetSelect'
import { Badge, EmptyState, ErrorNote, Loader, SectionHeader, Toggle } from '../components/ui'
import type { HistoryRecords, HistoryTest } from '../types'
import { TYPE_LABELS } from '../components/AssetTypeFilter'

const CATEGORIES = ['TR', 'AET', 'OLTC', 'CTVT', 'CB', 'ESDS', 'SA', 'CBank', 'BBank', 'OTHER']

const shortDate = (v: unknown) => String(v ?? '').slice(0, 10)

/** Format one cell. Numbers keep four decimals at most; nulls stay visibly
 *  empty rather than rendering as "null". */
function cell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4).replace(/0+$/, '')
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

/** Side panel: every test in the catalogue, with what this asset actually has. */
function TestList({
  tests,
  selected,
  onSelect,
  loading,
  hideEmpty,
  onHideEmpty,
}: {
  tests: HistoryTest[]
  selected: string
  onSelect: (id: string) => void
  loading: boolean
  hideEmpty: boolean
  onHideEmpty: (v: boolean) => void
}) {
  const shown = hideEmpty ? tests.filter((t) => t.available) : tests
  const withData = tests.filter((t) => t.available).length

  return (
    <div className="card lg:sticky lg:top-20">
      <div className="card-head card-head-accent" style={{ ['--accent' as string]: '#41708C' }}>
        <FileClock className="h-4 w-4 text-brand-700" />
        <span className="text-sm font-semibold text-brand-900">Tests</span>
        <span className="num ml-auto text-[11px] text-ink-muted">
          {withData} of {tests.length} with data
        </span>
      </div>

      <div className="border-b border-line px-4 py-2.5">
        <Toggle checked={hideEmpty} onChange={onHideEmpty} label="Only tests with records" />
      </div>

      {loading && <Loader label="Counting records…" />}

      {!loading && (
        <ul className="max-h-[calc(100vh-16rem)] overflow-y-auto py-1">
          {shown.map((t) => {
            const on = t.testId === selected
            const Icon = t.kind === 'omicron' ? Cpu : Database
            return (
              <li key={t.testId}>
                <button
                  onClick={() => onSelect(t.testId)}
                  disabled={!t.available}
                  className={`relative flex w-full items-start gap-2.5 px-4 py-2.5 text-left
                              transition-colors disabled:cursor-not-allowed ${
                                on
                                  ? 'bg-brand-100'
                                  : t.available
                                    ? 'hover:bg-brand-50'
                                    : 'opacity-45'
                              }`}
                >
                  {on && (
                    <span className="absolute inset-y-1.5 left-0 w-[3px] rounded-full bg-brand-600" />
                  )}
                  <Icon
                    className={`mt-0.5 h-4 w-4 shrink-0 ${
                      on ? 'text-brand-700' : 'text-ink-faint'
                    }`}
                  />
                  <span className="min-w-0 flex-1">
                    <span
                      className={`block text-[13px] leading-snug ${
                        on ? 'font-semibold text-brand-900' : 'font-medium text-ink'
                      }`}
                    >
                      {t.name}
                    </span>
                    <span className="mt-0.5 flex items-center gap-1.5 text-[10px] text-ink-faint">
                      <span className="font-mono">{t.testId}</span>
                      {t.available && (
                        <>
                          <span>·</span>
                          <span className="num">{t.records} rec</span>
                          {t.lastTested && (
                            <>
                              <span>·</span>
                              <span className="num">{shortDate(t.lastTested)}</span>
                            </>
                          )}
                        </>
                      )}
                      {!t.available && (
                        <>
                          <span>·</span>
                          <span>no records</span>
                        </>
                      )}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
          {!shown.length && (
            <li className="px-4 py-6 text-center text-xs text-ink-muted">
              {hideEmpty ? 'This asset has no test records.' : 'No tests in the catalogue.'}
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

export default function HistoryView() {
  const [params, setParams] = useSearchParams()
  const [asset, setAsset] = useState(params.get('asset') ?? '')
  const [test, setTest] = useState(params.get('test') ?? '')
  const [type, setType] = useState(params.get('type') ?? '')
  const [site, setSite] = useState(params.get('site') ?? '')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [hideEmpty, setHideEmpty] = useState(true)
  const [filter, setFilter] = useState('')

  // Asset numbers contain slashes, so selection lives in the query string
  // rather than the path — the same choice the trend page makes.
  useEffect(() => {
    setParams(qs({ asset, test, type, site }).replace(/^\?/, ''), { replace: true })
  }, [asset, test, type, site])

  const sites = useApi<{ items: { site: string; total: number }[] }>('/assets/sites')

  const catalogue = useApi<{ items: HistoryTest[] }>(
    asset ? `/history/tests${qs({ asset, from, to })}` : '/history/tests',
    [asset, from, to],
  )
  const tests = catalogue.data?.items ?? []

  // A test selected for the previous asset may have no rows for this one; drop
  // it so the page never shows a heading with an empty table beneath it.
  useEffect(() => {
    if (!asset || !test || !catalogue.data) return
    const match = catalogue.data.items.find((t) => t.testId === test)
    if (match && !match.available) setTest('')
  }, [asset, test, catalogue.data])

  const records = useApi<HistoryRecords>(
    asset && test
      ? `/history/${encodeURIComponent(test)}/${encodeURIComponent(asset)}${qs({ from, to, limit: 200 })}`
      : null,
    [asset, test, from, to],
  )

  const columns = records.data?.columns ?? []
  const rows = useMemo(() => {
    const all = records.data?.rows ?? []
    const q = filter.trim().toLowerCase()
    if (!q) return all
    return all.filter((r) =>
      Object.values(r).some((v) => String(v ?? '').toLowerCase().includes(q)),
    )
  }, [records.data, filter])

  const selectedTest = tests.find((t) => t.testId === test) ?? records.data?.test

  return (
    <div>
      <SectionHeader
        accent="#41708C"
        icon={History}
        title="History View"
        subtitle="Every stored record of a single test for a single asset, newest first"
      />

      <ScopeBanner />

      {/* Filters */}
      <div className="card card-pad mb-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="label">Asset type</label>
            <select
              className="input"
              value={type}
              onChange={(e) => setType(e.target.value)}
            >
              <option value="">All types</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {TYPE_LABELS[c] ?? c}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label">Site</label>
            <select className="input" value={site} onChange={(e) => setSite(e.target.value)}>
              <option value="">All sites</option>
              {(sites.data?.items ?? []).map((s) => (
                <option key={s.site} value={s.site}>
                  {s.site} ({s.total})
                </option>
              ))}
            </select>
          </div>

          <AssetSelect
            value={asset}
            onChange={(v) => {
              setAsset(v)
              setTest('')
            }}
            type={type || undefined}
            site={site || undefined}
            label="Asset"
          />

          {/* <div>
            <label className="label">Tested between</label>
            <div className="flex items-center gap-2">
              <input
                type="date"
                className="input num text-xs"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
              <span className="text-xs text-ink-faint">to</span>
              <input
                type="date"
                className="input num text-xs"
                value={to}
                onChange={(e) => setTo(e.target.value)}
              />
            </div>
          </div> */}
        </div>

        {asset && (
          <p className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
            <span className="font-mono text-xs text-ink">{asset}</span>
            <span>— pick a test on the left to read its records.</span>
          </p>
        )}
      </div>

      {!asset && (
        <div className="card">
          <EmptyState
            icon={Search}
            title="Select an asset"
            hint="Narrow by type and site if it helps, then search for the asset number. The tests it holds records for will be listed alongside."
          />
        </div>
      )}

      {asset && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[19rem_minmax(0,1fr)]">
          <TestList
            tests={tests}
            selected={test}
            onSelect={setTest}
            loading={catalogue.loading}
            hideEmpty={hideEmpty}
            onHideEmpty={setHideEmpty}
          />

          <div className="min-w-0">
            {catalogue.error && <ErrorNote message={catalogue.error} onRetry={catalogue.reload} />}

            {!test && !catalogue.loading && (
              <div className="card">
                <EmptyState
                  icon={Table2}
                  title="No test selected"
                  hint="Choose one of the tests listed on the left to see every record held for this asset."
                />
              </div>
            )}

            {test && records.error && (
              <ErrorNote message={records.error} onRetry={records.reload} />
            )}
            {test && records.loading && <Loader label="Reading records…" />}

            {test && records.data && !records.loading && (
              <div className="card">
                <div
                  className="card-head card-head-accent"
                  style={{ ['--accent' as string]: '#41708C' }}
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-brand-900">
                      {selectedTest?.name ?? test}
                    </p>
                    <p className="mt-0.5 font-mono text-[11px] text-ink-muted">
                      {records.data.test.table}
                      {records.data.dateColumn ? ` · ${records.data.dateColumn}` : ''}
                    </p>
                  </div>
                  <div className="ml-auto flex flex-wrap items-center gap-2">
                    <Badge tone={rows.length ? 'brand' : 'slate'}>
                      {rows.length.toLocaleString()}
                      {filter ? ` of ${records.data.rows.length}` : ''} record
                      {rows.length === 1 ? '' : 's'}
                    </Badge>
                    {records.data.truncated && (
                      <Badge tone="amber">Newest {records.data.limit} only</Badge>
                    )}
                    <div className="relative">
                      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
                      <input
                        className="input w-44 py-1.5 pl-8 text-xs"
                        placeholder="Filter rows…"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                      />
                    </div>
                  </div>
                </div>

                {records.data.message && (
                  <p className="border-b border-line bg-brand-50/60 px-5 py-2 text-[11px] text-ink-muted">
                    {records.data.message}
                  </p>
                )}

                {rows.length > 0 ? (
                  <div className="scroll-x">
                    <table className="w-full border-collapse">
                      <thead>
                        <tr>
                          {columns.map((c, i) => (
                            <th
                              key={c.name}
                              title={c.type}
                              className={`th ${c.numeric ? 'text-right' : ''} ${
                                i === 0 ? 'sticky left-0 z-10 bg-brand-100' : ''
                              }`}
                            >
                              {c.name}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r, ri) => (
                          <tr key={ri} className="hover:bg-brand-50/40">
                            {columns.map((c, ci) => {
                              const raw = r[c.name]
                              const text = c.date ? String(raw ?? '').slice(0, 19) : cell(raw)
                              return (
                                <td
                                  key={c.name}
                                  className={`td whitespace-nowrap ${
                                    c.numeric ? 'num text-right' : ''
                                  } ${
                                    ci === 0
                                      ? 'sticky left-0 z-10 bg-white font-semibold'
                                      : ''
                                  } ${
                                    raw === null || raw === undefined
                                      ? 'text-ink-faint'
                                      : ''
                                  }`}
                                >
                                  {c.date ? text || '—' : text}
                                </td>
                              )
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState
                    icon={Table2}
                    title={filter ? 'No rows match the filter' : 'No records in this window'}
                    hint={
                      filter
                        ? 'Clear the row filter to see the full history.'
                        : 'Widen or clear the tested-between dates — records may exist outside this range.'
                    }
                  />
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
