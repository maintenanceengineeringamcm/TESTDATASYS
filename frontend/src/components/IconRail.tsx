import {
  Activity,
  Gauge,
  History,
  LayoutDashboard,
  ListChecks,
  Pentagon,
  Settings,
  ShieldAlert,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { NavLink, useLocation } from 'react-router-dom'

export interface RailItem {
  to: string
  label: string
  hint: string
  icon: typeof Gauge
  end?: boolean
  /** The screen honours the hierarchy selection. Shown as a dot on the icon. */
  scopable?: boolean
}

export const RAIL: RailItem[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true,
    hint: 'Fleet overview & counts' },
  { to: '/health-index', label: 'Health Index', icon: Gauge,
    hint: 'Scored table for all assets', scopable: true },
  { to: '/trend-analysis', label: 'Trend Analysis', icon: TrendingUp,
    hint: 'DGA trend, pentagons & triangles' },
  { to: '/duval', label: 'Duval Diagnosis', icon: Pentagon,
    hint: 'Dual pentagon & dual triangles' },
  { to: '/dga-status', label: 'DGA Status', icon: ShieldAlert,
    hint: 'IEEE C57.104-2019 status & report', scopable: true },
  { to: '/dga-explorer', label: 'DGA Explorer', icon: Activity,
    hint: 'Gas charts & sample history' },
  { to: '/assets', label: 'Asset Register', icon: Zap,
    hint: 'Inventory by type and site' },
  { to: '/availability', label: 'Test Availability', icon: ListChecks,
    hint: 'Which tests exist per asset' },
  { to: '/history', label: 'History View', icon: History,
    hint: 'All records of one test per asset' },
  { to: '/configuration', label: 'Configuration', icon: Settings,
    hint: 'Weights, bands & engine flags' },
]

/**
 * The primary navigation rail — icons only, with the section name revealed on
 * hover.
 *
 * The label is not hover-only decoration: it is also the icon's accessible
 * name, so the section is reachable by keyboard and screen reader without
 * depending on the tooltip appearing.
 */
export default function IconRail({ onNavigate }: { onNavigate?: () => void }) {
  const { search } = useLocation()

  // The hierarchy selection is carried in the query string, so it must survive
  // a section change — otherwise switching screens silently drops the filter.
  const scope = new URLSearchParams(search).get('node')
  const suffix = scope ? `?node=${encodeURIComponent(scope)}` : ''

  return (
    <nav
      className="flex h-full w-14 shrink-0 flex-col items-center gap-1 py-3"
      style={{
        background: 'linear-gradient(175deg, #123252 0%, #0C2138 55%, #08172A 100%)',
      }}
      aria-label="Sections"
    >
      {RAIL.map(({ to, label, hint, icon: Icon, end, scopable }) => (
        <NavLink
          key={to}
          to={`${to}${suffix}`}
          end={end}
          onClick={onNavigate}
          title={label}
          aria-label={label}
          className={({ isActive }) =>
            `group relative flex h-10 w-10 items-center justify-center rounded-lg
             transition-colors ${
               isActive
                 ? 'bg-white/20 text-white'
                 : 'text-brand-300/80 hover:bg-white/10 hover:text-white'
             }`
          }
        >
          {({ isActive }) => (
            <>
              {/* The active marker is a bar as well as a colour, so selection
                  never rests on hue alone. */}
              {isActive && (
                <span className="absolute -left-3 inset-y-2 w-[3px] rounded-full bg-brand-400" />
              )}
              <Icon style={{ width: 19, height: 19 }} />

              {/* Scope-aware sections carry a dot so it is obvious which
                  screens the tree selection actually filters. */}
              {scopable && scope && (
                <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-brand-400 ring-2 ring-navy-900" />
              )}

              {/* Hover card. pointer-events-none keeps it from swallowing the
                  click that lands on the icon underneath it. */}
              <span
                className="pointer-events-none absolute left-full z-50 ml-2 hidden
                           whitespace-nowrap rounded-lg bg-navy-950 px-3 py-2
                           text-left shadow-pop ring-1 ring-white/10
                           group-hover:block group-focus-visible:block"
                role="tooltip"
              >
                <span className="block text-xs font-semibold text-white">{label}</span>
                <span className="block text-[11px] text-brand-300/70">{hint}</span>
              </span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}
