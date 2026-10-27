import { Link, useLocation } from 'react-router-dom'
import { locate } from './nav'

/**
 * The tabs of the current section, above the page. Sections with a single
 * screen show nothing. The hierarchy selection rides along in the query string.
 */
export default function SectionTabs() {
  const { pathname, search } = useLocation()
  const { section, tab } = locate(pathname)
  if (!section || section.tabs.length < 2) return null

  const scope = new URLSearchParams(search).get('node')
  const suffix = scope ? `?node=${encodeURIComponent(scope)}` : ''

  return (
    <div className="print-hide mb-4 flex flex-wrap items-center gap-x-1 gap-y-2 border-b border-line">
      <span className="mr-2 pb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
        {section.label}
      </span>
      {section.tabs.map((t) => {
        const active = t.to === tab?.to
        return (
          <Link
            key={t.to}
            to={`${t.to}${suffix}`}
            title={t.hint}
            aria-current={active ? 'page' : undefined}
            className={`-mb-px border-b-2 px-3 pb-2 text-sm font-semibold transition-colors ${
              active
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-ink-soft hover:border-line hover:text-ink'
            }`}
          >
            {t.label}
          </Link>
        )
      })}
    </div>
  )
}
