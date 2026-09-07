import { AlertTriangle, Layers } from 'lucide-react'

export interface AvailableType {
  assetType: string
  label?: string
  count: number
  scored: number
  trusted: boolean
}

// Reporting categories. Power transformers, earthing/auxiliary transformers and
// tap changers are separate populations even though they share one scoring
// configuration.
export const TYPE_LABELS: Record<string, string> = {
  TR: 'Power Transformers',
  AET: 'Earthing Transformers',
  OLTC: 'OLTC',
  CTVT: 'CT / VT',
  CB: 'Circuit Breakers',
  ESDS: 'ES / DS',
  SA: 'Surge Arresters',
  CBank: 'Capacitor Banks',
  BBank: 'Battery Banks',
  OTHER: 'Other',
}

/**
 * Identity colours for the asset categories.
 *
 * The three transformer populations carry the validated categorical hues; the
 * remaining categories stay in muted blue-greys, which keeps the eye on the
 * transformer fleet and leaves the green/amber/red scale exclusively to
 * condition. Validated all-pairs on both the card and page surfaces:
 * CVD ΔE 13.0, normal-vision ΔE 16.3, every slot ≥ 3:1 contrast.
 */
export const CATEGORY_COLORS: Record<string, `#${string}`> = {
  TR: '#2A78D6',
  AET: '#4A3AA7',
  OLTC: '#D55181',
  CTVT: '#4E7A9E',
  CB: '#5A6B80',
  ESDS: '#6B7A8F',
  SA: '#41708C',
  CBank: '#5A6B80',
  BBank: '#5A6B80',
  OTHER: '#8494A6',
}

export const categoryColor = (key: string): `#${string}` =>
  CATEGORY_COLORS[key] ?? '#5A6B80'

/**
 * Asset-type selector for the dashboard and health-index table.
 *
 * Defaults to transformers because they are the only type whose score bands are
 * fully configured. Types whose configuration is incomplete are still offered,
 * but carry a warning triangle so nobody reads their scores as condition.
 */
export default function AssetTypeFilter({
  value,
  types,
  onChange,
}: {
  value: string
  types: AvailableType[]
  onChange: (v: string) => void
}) {
  const total = types.reduce((s, t) => s + t.count, 0)

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
        <Layers className="h-3.5 w-3.5" />
        Asset type
      </span>

      {types.map((t) => {
        const on = value === t.assetType
        const color = categoryColor(t.assetType)
        return (
          <button
            key={t.assetType}
            onClick={() => onChange(t.assetType)}
            title={
              t.trusted
                ? `${t.scored.toLocaleString()} of ${t.count.toLocaleString()} scored`
                : `Score bands for ${t.assetType} are missing or mis-scaled — these values are not condition assessments.`
            }
            className="chip text-xs transition-all"
            style={
              on
                ? { background: color, color: '#fff', boxShadow: `0 1px 6px ${color}55` }
                : { background: '#fff', color: '#334155', border: `1px solid ${color}44` }
            }
          >
            {/* The dot ties the chip to its inventory tile; the label carries the
                identity too, so colour is never the only cue. */}
            {!on && (
              <span className="h-2 w-2 rounded-full" style={{ background: color }} />
            )}
            {!t.trusted && (
              <AlertTriangle
                className={`h-3 w-3 ${on ? 'text-white/90' : 'text-amber-500'}`}
              />
            )}
            {TYPE_LABELS[t.assetType] ?? t.label ?? t.assetType}
            <span className="num" style={{ color: on ? '#ffffffcc' : '#94A3B8' }}>
              {t.count.toLocaleString()}
            </span>
          </button>
        )
      })}

      <button
        onClick={() => onChange('all')}
        className={`chip text-xs transition-colors ${
          value === 'all'
            ? 'bg-navy-800 text-white'
            : 'border border-line bg-white text-ink-soft hover:bg-brand-50'
        }`}
      >
        All types
        <span className={`num ${value === 'all' ? 'text-white/80' : 'text-ink-faint'}`}>
          {total.toLocaleString()}
        </span>
      </button>
    </div>
  )
}
