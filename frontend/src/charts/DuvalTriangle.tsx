import { AlertTriangle } from 'lucide-react'
import type { TriangleGeometry, TriangleResult } from '../types'

const H = Math.sqrt(3) / 2

/**
 * One Duval triangle panel.
 *
 * As with the pentagon, the drawing is flipped once so positive y is up, and
 * text is rendered outside the flipped group so glyphs stay upright.
 */
export function DuvalTriangle({
  geometry,
  result,
}: {
  geometry: TriangleGeometry
  result: TriangleResult | null
}) {
  const zone = result?.valid ? result.zone : null
  // Room on all sides for the vertex labels.
  const pad = 0.13

  return (
    <div className="min-w-0 flex-1">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-bold text-ink">{geometry.title}</h3>
            {geometry.provisional && (
              <span
                className="chip bg-amber-50 text-[10px] text-amber-800"
                title="Zone boundaries for this triangle are not defined in the project
                       specification and come from the published Duval method. Pending
                       engineering sign-off."
              >
                <AlertTriangle className="h-3 w-3" />
                Provisional
              </span>
            )}
          </div>
          <p className="truncate text-[11px] text-ink-muted">{geometry.subtitle}</p>
        </div>
        {zone && (
          <span
            className="chip shrink-0 text-xs"
            style={{ background: result!.color, color: '#0B1220' }}
          >
            {zone}
          </span>
        )}
      </div>

      <svg
        viewBox={`${-pad} ${-H - pad} ${1 + pad * 2} ${H + pad * 2}`}
        className="w-full"
        style={{ aspectRatio: `${1 + pad * 2} / ${H + pad * 2}` }}
        role="img"
        aria-label={`${geometry.title}${zone ? `, zone ${zone}` : ''}`}
      >
        <g transform="scale(1,-1)">
          {/* zones */}
          {geometry.zones.map((z) => (
            <polygon
              key={z.zone}
              points={z.points.map((p) => `${p[0]},${p[1]}`).join(' ')}
              fill={z.color}
              fillOpacity={zone && zone !== z.zone ? 0.45 : 0.9}
              stroke="#64748B"
              strokeWidth={zone === z.zone ? 0.009 : 0.004}
            />
          ))}

          {/* outer triangle */}
          <polygon
            points={geometry.outline.map((p) => `${p[0]},${p[1]}`).join(' ')}
            fill="none"
            stroke="#0B1220"
            strokeWidth={0.008}
          />

          {/* sample point */}
          {result?.valid && result.point && (
            <>
              <circle cx={result.point.x} cy={result.point.y} r={0.032}
                      fill="#0B1220" opacity={0.18} />
              <circle cx={result.point.x} cy={result.point.y} r={0.018}
                      fill="#E01B24" stroke="#ffffff" strokeWidth={0.007} />
            </>
          )}
        </g>

        {/* zone labels */}
        {geometry.zones.map((z) => (
          <text
            key={z.zone}
            x={z.labelX}
            y={-z.labelY}
            fontSize={0.055}
            fontWeight={700}
            fill="#0B1220"
            textAnchor="middle"
            dominantBaseline="middle"
            pointerEvents="none"
          >
            {z.zone}
          </text>
        ))}

        {/* axis labels, matching the projection: a=left, b=right, c=apex */}
        <text x={-0.05} y={0.055} fontSize={0.058} fontWeight={700} fill="#163F64"
              textAnchor="middle">
          {geometry.axisLabels[0]}
        </text>
        <text x={1.05} y={0.055} fontSize={0.058} fontWeight={700} fill="#163F64"
              textAnchor="middle">
          {geometry.axisLabels[1]}
        </text>
        <text x={0.5} y={-H - 0.04} fontSize={0.058} fontWeight={700} fill="#163F64"
              textAnchor="middle">
          {geometry.axisLabels[2]}
        </text>
      </svg>

      {result?.valid && result.percentages && (
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-soft">
          {Object.entries(result.percentages).map(([g, v]) => (
            <span key={g} className="num">
              <span className="font-semibold text-ink">{g}</span> {v.toFixed(1)}%
            </span>
          ))}
        </div>
      )}
      {result?.valid && result.meaning && (
        <p className="mt-1 text-[11px] text-ink-muted">{result.meaning}</p>
      )}
      {result && !result.valid && (
        <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-[11px] text-amber-900">
          {result.reason}
        </p>
      )}
    </div>
  )
}

/** Triangle 1 alongside a refinement triangle — the "dual triangles" view. */
export default function DualTriangles({
  geometries,
  results,
  ids = ['1', '5'],
}: {
  geometries: Record<string, TriangleGeometry>
  results: Record<string, TriangleResult> | null
  ids?: string[]
}) {
  const primary = results?.['1']
  return (
    <div>
      <div className="flex flex-col gap-6 sm:flex-row">
        {ids.map((id) =>
          geometries[id] ? (
            <DuvalTriangle
              key={id}
              geometry={geometries[id]}
              result={results?.[id] ?? null}
            />
          ) : null,
        )}
      </div>

      {primary?.valid && primary.ladderAgrees === false && (
        <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          <span className="font-semibold">Classifier note:</span> the plotted point sits
          in <span className="font-semibold">{primary.zone}</span>, while the
          specification&rsquo;s rectangular rule ladder would report{' '}
          <span className="font-semibold">{primary.ladderZone}</span>. The zone shown is
          taken from the polygon the point actually falls in, so the chart and the verdict
          always agree.
        </p>
      )}
    </div>
  )
}
