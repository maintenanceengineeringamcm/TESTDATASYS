import { CircleGauge, Menu, Network, PanelLeftOpen, X } from 'lucide-react'
import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { useApi } from '../api'
import HierarchyPanel from './HierarchyPanel'
import IconRail from './IconRail'
import { ScopeProvider, useScope } from './ScopeContext'

function ConnectionPill() {
  const { data } = useApi<{ database: { connected: boolean; database: string; latencyMs: number } }>(
    '/health',
  )
  const connected = data?.database?.connected
  return (
    <div className="flex items-center gap-2 rounded-lg bg-white/10 px-2.5 py-1.5 ring-1 ring-white/15">
      <span
        className={`h-2 w-2 rounded-full ${
          connected === undefined
            ? 'bg-brand-300/50'
            : connected
              ? 'bg-emerald-400'
              : 'bg-red-400'
        }`}
      />
      <span className="text-xs font-medium text-brand-100">
        {connected === undefined
          ? 'Checking…'
          : connected
            ? data!.database.database
            : 'Database offline'}
      </span>
      {connected && (
        <span className="num text-[11px] text-brand-300/70">{data!.database.latencyMs}ms</span>
      )}
    </div>
  )
}

/** Marks the collapsed strip when a filter is still applied behind it. */
function ScopeDot() {
  const scope = useScope()
  if (!scope.node) return null
  return (
    <span
      className="mt-1 h-2 w-2 shrink-0 rounded-full bg-brand-500"
      title={`Filtering: ${scope.label || scope.node}`}
    />
  )
}

/** Reopens the navigator and shows what is currently filtered while it is hidden. */
function NavigatorPill({ onOpen }: { onOpen: () => void }) {
  const scope = useScope()
  return (
    <button
      onClick={onOpen}
      className="flex items-center gap-2 rounded-lg bg-white/10 px-2.5 py-1.5 text-xs
                 font-medium text-brand-100 ring-1 ring-white/15 hover:bg-white/20"
      title="Show the asset navigator"
    >
      <Network className="h-3.5 w-3.5" />
      {scope.node ? (
        <span className="max-w-[16rem] truncate">{scope.label || scope.node}</span>
      ) : (
        'Navigator'
      )}
    </button>
  )
}

function Shell() {
  // Two independent panels: the icon rail is always present on desktop, the
  // navigator is a working tool the user can put away when the screen is busy.
  const [railOpen, setRailOpen] = useState(false)
  const [navOpen, setNavOpen] = useState(true)

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* Header */}
      <header
        className="z-30 shrink-0 shadow-sm"
        style={{
          background: 'linear-gradient(90deg, #0C2138 0%, #123252 42%, #1A4272 100%)',
        }}
      >
        <div className="flex h-16 items-center gap-3 px-4 lg:px-6">
          <button
            className="rounded-lg p-2 text-brand-200 hover:bg-white/10 lg:hidden"
            onClick={() => setRailOpen((v) => !v)}
            aria-label="Toggle navigation"
          >
            {railOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>

          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-brand-500/25 p-2 ring-1 ring-brand-300/30">
              <CircleGauge className="h-5 w-5 text-brand-200" />
            </div>
            <div className="leading-tight">
              <p className="text-sm font-bold tracking-tight text-white">
                Asset Health Index &amp; DGA Analysis
              </p>
              <p className="text-[11px] text-brand-200/70">
                Transmission fleet condition assessment
              </p>
            </div>
          </div>

          <div className="ml-auto flex items-center gap-2">
            {!navOpen && <NavigatorPill onOpen={() => setNavOpen(true)} />}
            <ConnectionPill />
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Icon rail — off-canvas on small screens, fixed on desktop. */}
        <div
          className={`fixed inset-y-16 left-0 z-20 transition-transform lg:static lg:translate-x-0 ${
            railOpen ? 'translate-x-0' : '-translate-x-full'
          }`}
        >
          <IconRail onNavigate={() => setRailOpen(false)} />
        </div>

        {/* Asset navigator */}
        {navOpen ? (
          <div
            className={`fixed inset-y-16 left-14 z-20 lg:static lg:z-auto ${
              railOpen ? '' : 'hidden lg:block'
            }`}
          >
            <HierarchyPanel onCollapse={() => setNavOpen(false)} />
          </div>
        ) : (
          /* Collapsed rail. The panel hides to a strip rather than vanishing,
             so the way back is where the panel was — the header pill alone
             left no clue that a navigator existed at all. */
          <button
            onClick={() => setNavOpen(true)}
            className="group hidden w-7 shrink-0 flex-col items-center gap-2 border-r
                       border-line bg-white pt-3 hover:bg-brand-50 lg:flex"
            title="Show the asset navigator"
            aria-label="Show the asset navigator"
            aria-expanded={false}
          >
            <PanelLeftOpen className="h-4 w-4 text-ink-faint group-hover:text-brand-700" />
            <span
              className="text-[10px] font-semibold uppercase tracking-wider
                         text-ink-muted group-hover:text-brand-700"
              style={{ writingMode: 'vertical-rl' }}
            >
              Asset Navigator
            </span>
            {/* A filter still applies while the panel is shut, so say so. */}
            <ScopeDot />
          </button>
        )}

        {railOpen && (
          <div
            className="fixed inset-0 z-10 bg-ink/20 lg:hidden"
            onClick={() => setRailOpen(false)}
          />
        )}

        {/* Content scrolls on its own so the two sidebars stay put. */}
        <main className="min-w-0 flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default function Layout() {
  return (
    <ScopeProvider>
      <Shell />
    </ScopeProvider>
  )
}
