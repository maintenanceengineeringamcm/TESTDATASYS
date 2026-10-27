import { Database, FlaskConical, Gauge, LayoutDashboard, Settings } from 'lucide-react'

/**
 * The one map of where every function lives.
 *
 * Each task has exactly one home: the rail lists the five sections, and a
 * section with more than one screen shows them as tabs. Routes are unchanged,
 * so bookmarks and links between screens keep working.
 */
export interface NavTab {
  to: string
  label: string
  hint: string
  /** The screen honours the hierarchy selection. */
  scopable?: boolean
}

export interface NavSection {
  id: string
  label: string
  hint: string
  icon: typeof Gauge
  tabs: NavTab[]
  /** Extra path prefixes that belong to the section without a tab of their own. */
  also?: string[]
}

export const SECTIONS: NavSection[] = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    hint: 'Fleet overview & counts',
    icon: LayoutDashboard,
    tabs: [{ to: '/', label: 'Dashboard', hint: 'Fleet overview', scopable: true }],
  },
  {
    id: 'hi',
    label: 'Health Index',
    hint: 'Scores, asset detail & Excel export',
    icon: Gauge,
    tabs: [
      { to: '/health-index', label: 'Fleet Health Index', hint: 'Scored table for all assets', scopable: true },
      { to: '/hi-export', label: 'Export to Excel', hint: 'Calculate & download HI', scopable: true },
    ],
    also: ['/health-index/', '/manual-calculation'],
  },
  {
    id: 'dga',
    label: 'DGA Analysis',
    hint: 'Status, trend, fault diagnosis',
    icon: FlaskConical,
    tabs: [
      { to: '/dga-status', label: 'DGA Status', hint: 'IEEE C57.104-2019 status & report', scopable: true },
      { to: '/trend-analysis', label: 'Trend', hint: 'Gas trend score & filtration points', scopable: true },
      { to: '/duval', label: 'Fault Diagnosis', hint: 'Duval pentagons, triangles, ratios', scopable: true },
      { to: '/dga-explorer', label: 'Compare & Rank', hint: 'Several assets on one chart, fleet ranking', scopable: true },
      { to: '/dga-entry', label: 'Check Typed-in Results', hint: 'Classify values from a test certificate' },
    ],
  },
  {
    id: 'data',
    label: 'Asset Data',
    hint: 'Register, test availability, history',
    icon: Database,
    tabs: [
      { to: '/assets', label: 'Asset Register', hint: 'Inventory by type and site', scopable: true },
      { to: '/availability', label: 'Test Availability', hint: 'Which tests exist per asset', scopable: true },
      { to: '/history', label: 'Test History', hint: 'All records of one test for one asset', scopable: true },
    ],
  },
  {
    id: 'config',
    label: 'Configuration',
    hint: 'Weights, bands & engine flags',
    icon: Settings,
    tabs: [{ to: '/configuration', label: 'Configuration', hint: 'Weights, bands & engine flags' }],
  },
]

function matches(path: string, to: string) {
  return to === '/' ? path === '/' : path === to || path.startsWith(`${to}/`)
}

/** The section a path belongs to, and the tab within it (if any). */
export function locate(path: string): { section?: NavSection; tab?: NavTab } {
  for (const section of SECTIONS) {
    const tab = section.tabs.find((t) => matches(path, t.to))
    if (tab) return { section, tab }
    if (section.also?.some((p) => path.startsWith(p))) return { section, tab: section.tabs[0] }
  }
  return {}
}
