import {
  CheckSquare,
  Download,
  FileSpreadsheet,
  Info,
  Search,
  ShieldAlert,
  Square,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { BASE, api, qs, useApi } from '../api'
import { TYPE_LABELS } from '../components/AssetTypeFilter'
import ScopeBanner from '../components/ScopeBanner'
import { useScope } from '../components/ScopeContext'
import { ErrorNote, Loader, SectionHeader, Toggle } from '../components/ui'

interface ExportOptions {
  categories: { key: string; assetType: string; count: number }[]
  criteria: Record<string, { code: string; label: string; manual: boolean; configuredWeight: number }[]>
  dgaCorrectionDefaults: Record<string, number>
  filterWindow: { enabled: boolean; minSamplesAfter: number }
}

interface ExportJob {
  id: string
  status: 'running' | 'complete' | 'failed'
  total: number
  done: number
  failed: number
  error: string | null
  fileName: string | null
  ready: boolean
}

interface AssetItem {
  assetNumber: string
  label: string
  site: string
  category: string
}

const download = (id: string) => {
  const a = document.createElement('a')
  a.href = `${BASE}/hi-export/${id}/file`
  a.click()
}

export default function HiExport() {
  const scope = useScope()
  const opts = useApi<ExportOptions>('/hi-export/options')

  const [category, setCategory] = useState('TR')
  const [mode, setMode] = useState<'all' | 'selected'>('all')
  const [picked, setPicked] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [criteria, setCriteria] = useState<Set<string> | null>(null) // null = all
  const [dgaOn, setDgaOn] = useState(false)
  const [factors, setFactors] = useState<Record<string, string>>({ '1': '0', '2': '0.1', '3': '0.3' })

  const [job, setJob] = useState<ExportJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  const cat = opts.data?.categories.find((c) => c.key === category)
  const assetType = cat?.assetType ?? 'TR'
  const allCriteria = opts.data?.criteria[assetType] ?? []
  const isTransformer = assetType === 'TR'

  // Changing category resets everything that depends on it.
  useEffect(() => {
    setPicked([])
    setCriteria(null)
    if (assetType !== 'TR') setDgaOn(false)
  }, [category])

  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current)
  }, [])

  const inScope = useApi<{ total: number }>(
    `/assets${qs({ type: category, node: scope.node, limit: 1 })}`,
  )
  const search = useApi<{ items: AssetItem[]; total: number }>(
    mode === 'selected'
      ? `/assets${qs({ type: category, node: scope.node, q: query, limit: 60 })}`
      : null,
  )

  const chosen = useMemo(
    () => criteria ?? new Set(allCriteria.filter((c) => !c.manual).map((c) => c.code)),
    [criteria, allCriteria],
  )

  const computable = allCriteria.filter((c) => !c.manual)
  const allChosen = computable.every((c) => chosen.has(c.code))

  function toggleCriterion(code: string) {
    const next = new Set(chosen)
    if (next.has(code)) next.delete(code)
    else next.add(code)
    setCriteria(next)
  }

  function togglePick(n: string) {
    setPicked((cur) => (cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n]))
  }

  const assetCount = mode === 'all' ? inScope.data?.total ?? 0 : picked.length
  const running = job?.status === 'running'

  async function start() {
    setError(null)
    setJob(null)
    try {
      const body: Record<string, unknown> = {
        category,
        node: scope.node || undefined,
        assets: mode === 'selected' ? picked : null,
        // Every computable criterion ticked means "all" - the engine default.
        criteria: allChosen ? null : [...chosen],
      }
      if (dgaOn && isTransformer) {
        const f: Record<string, number> = {}
        for (const [k, v] of Object.entries(factors)) {
          const n = Number(v)
          if (v !== '' && !Number.isNaN(n)) f[k] = Math.max(0, Math.min(1, n))
        }
        body.dgaCorrection = { enabled: true, factors: f }
      }
      const started = await api.post<ExportJob>('/hi-export', body)
      setJob(started)
      timer.current = window.setInterval(async () => {
        try {
          const s = await api.get<ExportJob>(`/hi-export/${started.id}`)
          setJob(s)
          if (s.status !== 'running') {
            if (timer.current) window.clearInterval(timer.current)
            if (s.ready) download(s.id)
          }
        } catch (e: any) {
          if (timer.current) window.clearInterval(timer.current)
          setError(e.message ?? 'Lost track of the export')
        }
      }, 1500)
    } catch (e: any) {
      setError(e.message ?? 'Could not start the export')
    }
  }

  const pct = job && job.total ? Math.round((job.done / job.total) * 100) : 0

  return (
    <div>
      <SectionHeader
        accent="#1E72BC"
        icon={FileSpreadsheet}
        title="Health Index Export"
        subtitle="Calculate the health index for chosen assets and criteria, and download it as Excel"
      />
      <ScopeBanner />

      {opts.loading && <Loader label="Loading export options…" />}
      {opts.error && <ErrorNote message={opts.error} />}

      {opts.data && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          {/* --- Assets --- */}
          <div className="card card-pad xl:col-span-2">
            <h2 className="mb-3 text-sm font-bold text-ink">1. Assets</h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="label">Asset category</label>
                <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
                  {opts.data.categories.map((c) => (
                    <option key={c.key} value={c.key}>
                      {TYPE_LABELS[c.key] ?? c.key} ({c.count.toLocaleString()})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Which assets</label>
                <div className="flex gap-2">
                  {(['all', 'selected'] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setMode(m)}
                      className={`chip text-xs ${
                        mode === m ? 'bg-brand-600 text-white' : 'border border-line bg-white text-ink-soft'
                      }`}
                    >
                      {m === 'all'
                        ? `All${scope.node ? ' in scope' : ''} (${(inScope.data?.total ?? 0).toLocaleString()})`
                        : `Selected (${picked.length})`}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {mode === 'selected' && (
              <div className="mt-4">
                <div className="relative">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-ink-faint" />
                  <input
                    className="input !pl-8"
                    placeholder="Search asset number or type…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
                {picked.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {picked.map((n) => (
                      <span key={n} className="chip bg-brand-50 text-[11px] text-brand-800">
                        <span className="font-mono">{n}</span>
                        <button onClick={() => togglePick(n)} aria-label={`Remove ${n}`}>
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                    <button onClick={() => setPicked([])} className="text-[11px] font-semibold text-brand-700 hover:underline">
                      clear all
                    </button>
                  </div>
                )}
                <div className="mt-2 max-h-72 overflow-y-auto rounded-lg border border-line">
                  {search.loading && <Loader />}
                  {search.data?.items.map((a) => {
                    const on = picked.includes(a.assetNumber)
                    return (
                      <button
                        key={a.assetNumber}
                        onClick={() => togglePick(a.assetNumber)}
                        className="flex w-full items-center gap-2 border-b border-line px-3 py-1.5 text-left text-xs last:border-0 hover:bg-brand-50"
                      >
                        {on ? (
                          <CheckSquare className="h-4 w-4 shrink-0 text-brand-600" />
                        ) : (
                          <Square className="h-4 w-4 shrink-0 text-ink-faint" />
                        )}
                        <span className="font-mono">{a.assetNumber}</span>
                        <span className="ml-auto text-ink-muted">{a.label}</span>
                      </button>
                    )
                  })}
                  {search.data && search.data.total > search.data.items.length && (
                    <p className="px-3 py-1.5 text-[11px] text-ink-faint">
                      Showing {search.data.items.length} of {search.data.total} — refine the search to find more.
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* --- Options --- */}
          <div className="card card-pad">
            <h2 className="mb-3 text-sm font-bold text-ink">3. Options</h2>
            {isTransformer ? (
              <>
                <div className="flex items-center gap-2">
                  <ShieldAlert className="h-4 w-4 text-brand-600" />
                  <Toggle checked={dgaOn} onChange={setDgaOn} label="Apply DGA correction factor" />
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2">
                  {(['1', '2', '3'] as const).map((st) => (
                    <div key={st}>
                      <label className="label">Status {st}</label>
                      <input
                        className="input num"
                        type="number"
                        min={0}
                        max={1}
                        step={0.05}
                        disabled={!dgaOn}
                        value={factors[st]}
                        onChange={(e) => setFactors((f) => ({ ...f, [st]: e.target.value }))}
                      />
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
                  Final HI × (1 − factor) by the IEEE C57.104-2019 DGA status. 0.3 = reduce by 30 %.
                </p>
              </>
            ) : (
              <p className="text-[11px] text-ink-muted">
                The DGA correction factor applies to transformers only.
              </p>
            )}
            <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-brand-50 p-2.5 text-[11px] leading-relaxed text-ink-soft">
              <Info className="mt-px h-3.5 w-3.5 shrink-0" />
              {opts.data.filterWindow.enabled
                ? `Oil filtration points are applied automatically: DGA level and trend use the samples after the last filter point when there are at least ${opts.data.filterWindow.minSamplesAfter}, otherwise the data before it.`
                : 'The oil-filtration rule is switched off on the server; DGA uses the full history.'}
            </p>
          </div>

          {/* --- Criteria --- */}
          <div className="card card-pad xl:col-span-3">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <h2 className="text-sm font-bold text-ink">2. Criteria</h2>
              <span className="text-[11px] text-ink-muted">
                {chosen.size} of {computable.length} selected · weights re-normalise
                over the selected criteria that have data
              </span>
              <div className="ml-auto flex gap-2">
                <button onClick={() => setCriteria(null)} className="btn-ghost !px-2 !py-1 !text-[11px]">
                  Select all
                </button>
                <button onClick={() => setCriteria(new Set())} className="btn-ghost !px-2 !py-1 !text-[11px]">
                  Clear
                </button>
              </div>
            </div>
            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
              {allCriteria.map((c) => {
                const on = chosen.has(c.code)
                return (
                  <button
                    key={c.code}
                    onClick={() => !c.manual && toggleCriterion(c.code)}
                    disabled={c.manual}
                    title={c.manual ? 'Entered manually - no test data to calculate from' : undefined}
                    className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5 text-left text-xs hover:bg-brand-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {on && !c.manual ? (
                      <CheckSquare className="h-4 w-4 shrink-0 text-brand-600" />
                    ) : (
                      <Square className="h-4 w-4 shrink-0 text-ink-faint" />
                    )}
                    <span className="font-semibold text-ink">{c.label}</span>
                    <span className="ml-auto font-mono text-[10px] text-ink-faint">
                      {c.manual ? 'manual' : `w ${c.configuredWeight}`}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* --- Run --- */}
          <div className="card card-pad xl:col-span-3">
            <div className="flex flex-wrap items-center gap-4">
              <button
                onClick={start}
                className="btn-primary"
                disabled={running || !assetCount || chosen.size === 0}
              >
                <FileSpreadsheet className={`h-4 w-4 ${running ? 'animate-pulse' : ''}`} />
                {running ? 'Calculating…' : `Export ${assetCount.toLocaleString()} asset${assetCount === 1 ? '' : 's'}`}
              </button>
              {job && (
                <div className="min-w-[240px] flex-1">
                  <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                    <div className="h-full bg-brand-500 transition-all" style={{ width: `${pct}%` }} />
                  </div>
                  <p className="mt-1 text-[11px] text-ink-muted">
                    {job.status === 'running' && `Calculated ${job.done} of ${job.total} (${pct} %)…`}
                    {job.status === 'complete' &&
                      `Done — ${job.total} assets${job.failed ? `, ${job.failed} failed` : ''}. The download should start automatically.`}
                    {job.status === 'failed' && `Export failed: ${job.error}`}
                  </p>
                </div>
              )}
              {job?.ready && (
                <button onClick={() => download(job.id)} className="btn-ghost">
                  <Download className="h-4 w-4" />
                  {job.fileName ?? 'Download'}
                </button>
              )}
            </div>
            {assetCount > 300 && !running && (
              <p className="mt-2 text-[11px] text-ink-muted">
                Every asset is calculated live, so a large export can take several minutes.
              </p>
            )}
            {error && (
              <div className="mt-3">
                <ErrorNote message={error} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
