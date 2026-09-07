import { AlertTriangle, Clock, Database, Loader2, RefreshCw, Zap } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

export interface SnapshotStatus {
  hasData: boolean
  ageHours: number | null
  stale: boolean
  database: string
  lastRun: {
    id: number
    started_at: string
    finished_at: string | null
    status: string
    triggered_by: string
    assets_total: number
    assets_scored: number
    assets_failed: number
    duration_s: number | null
  } | null
  lastAttempt: SnapshotStatus['lastRun']
  inProgress: { running: boolean; done: number; total: number; startedAt: string | null }
}

function relative(hours: number | null): string {
  if (hours === null) return 'unknown'
  if (hours < 1) return `${Math.round(hours * 60)} min ago`
  if (hours < 24) return `${Math.round(hours)} h ago`
  const days = Math.floor(hours / 24)
  return days === 1 ? 'yesterday' : `${days} days ago`
}

/**
 * Shows where the numbers on screen came from and how old they are, with a
 * control to recompute.
 *
 * Precomputed figures are only trustworthy if their age is visible — a stale
 * dashboard that looks live is worse than no dashboard.
 */
export default function SnapshotBar({
  status,
  source,
  onRefreshed,
}: {
  status: SnapshotStatus | null | undefined
  source?: 'snapshot' | 'live'
  onRefreshed: () => void
}) {
  const [starting, setStarting] = useState(false)
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  // Poll only while a sweep is in flight, then stop.
  useEffect(() => {
    const active = running || status?.inProgress?.running
    if (!active) {
      if (timer.current) window.clearInterval(timer.current)
      timer.current = null
      return
    }
    timer.current = window.setInterval(async () => {
      try {
        const s = await api.get<SnapshotStatus>('/snapshot/status')
        setProgress({ done: s.inProgress.done, total: s.inProgress.total })
        if (!s.inProgress.running) {
          setRunning(false)
          setProgress(null)
          onRefreshed()
        }
      } catch {
        /* keep polling; a transient failure is not fatal */
      }
    }, 2000)
    return () => {
      if (timer.current) window.clearInterval(timer.current)
    }
  }, [running, status?.inProgress?.running, onRefreshed])

  async function recompute() {
    setStarting(true)
    setError(null)
    try {
      const res = await api.post<{ started: boolean; reason?: string }>('/snapshot/run', {
        by: 'user',
      })
      if (!res.started) setError(res.reason ?? 'Could not start')
      else setRunning(true)
    } catch (e: any) {
      setError(e.message ?? 'Could not start the recalculation')
    } finally {
      setStarting(false)
    }
  }

  const busy = running || status?.inProgress?.running
  const done = progress?.done ?? status?.inProgress?.done ?? 0
  const total = progress?.total ?? status?.inProgress?.total ?? 0
  const pct = total ? Math.round((done / total) * 100) : 0

  return (
    <div
      className={`mb-4 rounded-xl border p-3 ${
        status?.stale
          ? 'border-amber-300 bg-amber-50'
          : 'border-line bg-white'
      }`}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-2">
          {source === 'live' ? (
            <Zap className="h-4 w-4 text-brand-600" />
          ) : (
            <Database className="h-4 w-4 text-brand-600" />
          )}
          <span className="text-xs font-semibold text-ink">
            {source === 'live' ? 'Calculated live' : 'Daily snapshot'}
          </span>
        </div>

        {status?.hasData && status.lastRun && (
          <span className="flex items-center gap-1.5 text-xs text-ink-muted">
            <Clock className="h-3.5 w-3.5" />
            Updated {relative(status.ageHours)}
            <span className="num text-ink-faint">
              ({String(status.lastRun.finished_at ?? '').slice(0, 16).replace('T', ' ')} UTC)
            </span>
          </span>
        )}

        {status?.hasData && status.lastRun && (
          <span className="num text-xs text-ink-faint">
            {status.lastRun.assets_scored.toLocaleString()} assets ·{' '}
            {status.lastRun.duration_s?.toFixed(0)}s
          </span>
        )}

        {!status?.hasData && !busy && (
          <span className="text-xs text-ink-muted">
            No snapshot yet — showing a live sample. Recalculate to build one.
          </span>
        )}

        {status?.stale && (
          <span className="flex items-center gap-1.5 text-xs font-semibold text-amber-800">
            <AlertTriangle className="h-3.5 w-3.5" />
            Stale — the 08:00 job may not have run
          </span>
        )}

        <button
          onClick={recompute}
          disabled={starting || busy}
          className="btn-ghost ml-auto !py-1.5 !text-xs"
        >
          {busy ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Recalculating {total ? `${pct}%` : ''}
            </>
          ) : (
            <>
              <RefreshCw className="h-3.5 w-3.5" />
              Recalculate now
            </>
          )}
        </button>
      </div>

      {busy && total > 0 && (
        <div className="mt-2">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-brand-100">
            <div
              className="h-full rounded-full bg-brand-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="num mt-1 text-[11px] text-ink-muted">
            {done.toLocaleString()} of {total.toLocaleString()} assets — this runs in the
            background, you can keep using the system.
          </p>
        </div>
      )}

      {error && <p className="mt-2 text-[11px] text-red-700">{error}</p>}
    </div>
  )
}
