import { Network, X } from 'lucide-react'
import { useScope } from './ScopeContext'

/**
 * "You are looking at a branch, not the fleet."
 *
 * Shown on every screen the navigator filters. It gets its own banner rather
 * than sitting among the on-page filter controls because it is the one filter
 * set from outside the screen — a user who forgets it is on will misread every
 * count below it.
 */
export default function ScopeBanner({
  /** Label echoed by the API, which resolves a scope opened from a cold link. */
  label,
  /** What the scope is narrowing, e.g. 'assets', 'transformers with DGA'. */
  noun = 'assets',
  /** Assets in scope, when the screen knows the number. */
  count,
}: {
  label?: string | null
  noun?: string
  count?: number
}) {
  const scope = useScope()
  if (!scope.node) return null

  const shown = label || scope.label || scope.node

  return (
    <div
      className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-brand-300
                 bg-brand-50 px-4 py-2.5"
    >
      <Network className="h-4 w-4 shrink-0 text-brand-600" />
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-brand-700">
          Scoped to hierarchy
          {count !== undefined && (
            <span className="ml-1.5 font-normal normal-case tracking-normal text-ink-muted">
              · {count.toLocaleString()} {noun}
            </span>
          )}
        </p>
        <p className="truncate text-sm font-medium text-ink">{shown}</p>
        <p className="truncate font-mono text-[11px] text-ink-muted">{scope.node}</p>
      </div>
      <button onClick={scope.clear} className="btn-ghost !py-1.5 !text-xs">
        <X className="h-3.5 w-3.5" />
        Clear scope
      </button>
    </div>
  )
}
