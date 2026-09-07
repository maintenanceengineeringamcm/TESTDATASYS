import { AlertTriangle, Inbox, Loader2, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

export function Loader({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-14 text-ink-muted">
      <Loader2 className="h-5 w-5 animate-spin text-brand-500" />
      <span className="text-sm">{label}</span>
    </div>
  )
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4">
      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-red-900">Something went wrong</p>
        <p className="mt-1 break-words text-sm text-red-800">{message}</p>
        {onRetry && (
          <button onClick={onRetry} className="btn-ghost mt-3 !border-red-200">
            Try again
          </button>
        )}
      </div>
    </div>
  )
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  hint,
}: {
  icon?: LucideIcon
  title: string
  hint?: string
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
      <div className="rounded-full bg-brand-100 p-3">
        <Icon className="h-6 w-6 text-brand-600" />
      </div>
      <p className="text-sm font-semibold text-ink">{title}</p>
      {hint && <p className="max-w-md text-sm text-ink-muted">{hint}</p>}
    </div>
  )
}

export function SectionHeader({
  icon: Icon,
  title,
  subtitle,
  actions,
  accent = '#1E72BC',
}: {
  icon: LucideIcon
  title: string
  subtitle?: string
  actions?: ReactNode
  accent?: HexColor
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-start gap-3.5">
        <div
          className="rounded-xl p-2.5 shadow-sm"
          style={{ background: `linear-gradient(145deg, ${accent}, ${accent}CC)` }}
        >
          <Icon className="h-5 w-5 text-white" />
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-ink">{title}</h1>
          {subtitle && <p className="mt-0.5 text-sm text-ink-muted">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/**
 * Inventory tile.
 *
 * `accent` is an identity colour for the asset category, taken from a validated
 * categorical set that is deliberately clear of the green/amber/red condition
 * scale — a tile counts assets, and must never be mistaken for a health verdict.
 * The icon and label carry the identity too, so colour is never alone.
 */
/** A CSS hex colour. Typed so a stale keyword like "amber" - which is not a
 *  valid CSS colour and would silently render as nothing - fails the build. */
export type HexColor = `#${string}`

export function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent = '#1E72BC',
}: {
  icon: LucideIcon
  label: string
  value: ReactNode
  sub?: string
  accent?: HexColor
}) {
  return (
    <div className="card relative overflow-hidden">
      <span className="absolute inset-x-0 top-0 h-1" style={{ background: accent }} />
      <div className="flex items-start justify-between gap-3 p-5">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold uppercase tracking-wide text-ink-muted">
            {label}
          </p>
          <p className="num mt-2 text-2xl font-bold leading-none text-ink">{value}</p>
          {sub && <p className="mt-1.5 truncate text-xs text-ink-muted">{sub}</p>}
        </div>
        <div
          className="shrink-0 rounded-xl p-2.5"
          style={{ background: `${accent}1A`, color: accent }}
        >
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  )
}

/** Colour-coded health-index pill. Colour comes from the backend band table so
 *  the thresholds live in exactly one place. */
export function HIBadge({
  value,
  label,
  color,
  bg,
  size = 'md',
}: {
  value: number | null
  label?: string | null
  color?: string | null
  bg?: string | null
  size?: 'sm' | 'md' | 'lg'
}) {
  if (value === null || value === undefined) {
    return (
      <span className="chip bg-slate-100 text-slate-500">
        <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
        Not scored
      </span>
    )
  }
  const sizes = {
    sm: 'text-[11px] px-2 py-0.5',
    md: 'text-xs px-2.5 py-1',
    lg: 'text-sm px-3 py-1.5',
  }
  return (
    <span
      className={`chip num ${sizes[size]}`}
      style={{ background: bg ?? '#E8F1FC', color: color ?? '#1E72BC' }}
      title={label ?? undefined}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color ?? '#1E72BC' }} />
      {value.toFixed(2)}
      {label && <span className="font-medium opacity-80">· {label}</span>}
    </span>
  )
}

/** Horizontal score bar used in component breakdown tables. */
export function ScoreBar({ score }: { score: number | null }) {
  if (score === null || score === undefined) {
    return <span className="text-xs text-ink-faint">—</span>
  }
  const pct = Math.max(0, Math.min(1, score)) * 100
  const color = score >= 0.75 ? '#0E9F6E' : score >= 0.5 ? '#2E7DD1' : score >= 0.25 ? '#B7791F' : '#D64545'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-brand-100">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="num text-xs font-semibold" style={{ color }}>
        {score.toFixed(2)}
      </span>
    </div>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex items-center gap-2.5 text-sm text-ink-soft"
    >
      <span
        className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
          checked ? 'bg-brand-500' : 'bg-slate-300'
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${
            checked ? 'left-[18px]' : 'left-0.5'
          }`}
        />
      </span>
      {label}
    </button>
  )
}

export interface ConfigAudit {
  assetType: string
  status: string
  trustworthy: boolean
  message: string
  issues: { band: string; status: string; reason: string }[]
  bandsExpected: number
  bandsWithIssues: number
}

/**
 * Warns when an asset type's score bands are missing or mis-scaled.
 *
 * Without this, an unconfigured type produces a near-zero index that reads like
 * a condemned asset when the real problem is an empty configuration table.
 */
export function ConfigWarning({
  audit,
  compact = false,
}: {
  audit: ConfigAudit | null | undefined
  compact?: boolean
}) {
  if (!audit || audit.trustworthy) return null
  return (
    <div className="rounded-xl border border-amber-300 bg-amber-50 p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
        <div className="min-w-0">
          <p className="text-sm font-bold text-amber-900">
            Scoring configuration incomplete for {audit.assetType}
          </p>
          <p className="mt-1 text-sm leading-relaxed text-amber-900">{audit.message}</p>
          {!compact && audit.issues.length > 0 && (
            <ul className="mt-2 space-y-1">
              {audit.issues.map((i) => (
                <li key={i.band} className="text-xs leading-relaxed text-amber-800">
                  <span className="font-mono font-semibold">{i.band}</span> — {i.reason}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-amber-800">
            Fix this in <span className="font-mono">SCORE_VALUE</span> for this asset type;
            the engine will pick the new bands up on the next refresh.
          </p>
        </div>
      </div>
    </div>
  )
}

export function Badge({
  children,
  tone = 'brand',
}: {
  children: ReactNode
  tone?: 'brand' | 'green' | 'amber' | 'red' | 'slate'
}) {
  const tones: Record<string, string> = {
    brand: 'bg-brand-100 text-brand-800',
    green: 'bg-emerald-50 text-emerald-700',
    amber: 'bg-amber-50 text-amber-800',
    red: 'bg-red-50 text-red-700',
    slate: 'bg-slate-100 text-slate-600',
  }
  return <span className={`chip ${tones[tone]}`}>{children}</span>
}
