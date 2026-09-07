import type { PentagonGeometry, PentagonResult } from '../types'

/**
 * One Duval pentagon panel.
 *
 * The SVG y-axis points down while the pentagon maths uses a conventional
 * upward y, so the whole drawing is flipped once with a group transform rather
 * than negating every coordinate individually.
 */
function Panel({
  title,
  subtitle,
  zones,
  geometry,
  result,
  side,
}: {
  title: string
  subtitle: string
  zones: PentagonGeometry['pentagon1']['zones']
  geometry: PentagonGeometry
  result: PentagonResult | null
  side: 'pentagon1' | 'pentagon2'
}) {
  const { xMin, xMax, yMin, yMax } = geometry.viewBox
  const width = xMax - xMin
  const height = yMax - yMin
  const diagnosed = result?.valid ? result[side]?.zone : null

  const outer = geometry.vertices.map((v) => `${v.x},${v.y}`).join(' ')

  return (
    <div className="min-w-0 flex-1">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-ink">{title}</h3>
          <p className="text-[11px] text-ink-muted">{subtitle}</p>
        </div>
        {diagnosed && (
          <span
            className="chip text-xs"
            style={{
              background: result![side]!.color,
              color: '#0B1220',
            }}
          >
            {diagnosed}
          </span>
        )}
      </div>

      <svg
        viewBox={`${xMin} ${-yMax} ${width} ${height}`}
        className="w-full"
        style={{ aspectRatio: `${width} / ${height}` }}
        role="img"
        aria-label={`${title}${diagnosed ? `, diagnosed zone ${diagnosed}` : ''}`}
      >
        {/* Flip so positive y is up. */}
        <g transform="scale(1,-1)">
          {/* axes cross */}
          <line x1={xMin} y1={0} x2={xMax} y2={0} stroke="#aaa" strokeWidth={0.35}
                strokeDasharray="2 2" opacity={0.6} />
          <line x1={0} y1={yMin} x2={0} y2={yMax} stroke="#aaa" strokeWidth={0.35}
                strokeDasharray="2 2" opacity={0.6} />

          {/* zones */}
          {zones.map((z) => (
            <polygon
              key={z.zone}
              points={z.points.map((p) => `${p[0]},${p[1]}`).join(' ')}
              fill={z.color}
              fillOpacity={diagnosed && diagnosed !== z.zone ? 0.42 : 0.9}
              stroke="#0B1220"
              strokeWidth={diagnosed === z.zone ? 1.1 : 0.5}
            />
          ))}

          {/* spokes to each vertex */}
          {geometry.vertices.map((v) => (
            <line key={v.gas} x1={0} y1={0} x2={v.x} y2={v.y} stroke="#666"
                  strokeWidth={0.3} strokeDasharray="1.5 1.5" opacity={0.7} />
          ))}

          {/* outer boundary */}
          <polygon points={outer} fill="none" stroke="#0B1220" strokeWidth={1.2} />

          {/* gas polygon */}
          {result?.valid && result.points && (
            <>
              <polygon
                points={result.points.map((p) => `${p.x},${p.y}`).join(' ')}
                fill="#DC143C"
                fillOpacity={0.18}
                stroke="#DC143C"
                strokeWidth={1}
                strokeLinejoin="round"
              />
              {result.points.map((p) => (
                <circle key={p.gas} cx={p.x} cy={p.y} r={1} fill="#DC143C" />
              ))}
            </>
          )}

          {/* centre of gravity */}
          {result?.valid && result.centroid && (
            <>
              <circle cx={result.centroid.x} cy={result.centroid.y} r={2.4}
                      fill="#E01B24" stroke="#7A0C12" strokeWidth={0.8} />
            </>
          )}
        </g>

        {/* Text is drawn outside the flipped group so glyphs are not mirrored;
            each y is negated to land in the same place. */}
        {zones.map((z) => (
          <text
            key={z.zone}
            x={z.labelX}
            y={-z.labelY}
            fontSize={z.labelSize * 0.42}
            fontWeight={700}
            fill="#0B1220"
            textAnchor="middle"
            dominantBaseline="middle"
            pointerEvents="none"
          >
            {z.zone}
          </text>
        ))}

        {geometry.vertices.map((v) => (
          <text
            key={v.gas}
            x={v.labelX}
            y={-v.labelY}
            fontSize={4.6}
            fontWeight={700}
            fill="#163F64"
            textAnchor={v.anchor === 'start' ? 'start' : v.anchor === 'end' ? 'end' : 'middle'}
            dominantBaseline={
              v.baseline === 'bottom' ? 'auto' : v.baseline === 'hanging' ? 'hanging' : 'middle'
            }
          >
            {v.label}
          </text>
        ))}
      </svg>
    </div>
  )
}

export default function DualPentagon({
  geometry,
  result,
}: {
  geometry: PentagonGeometry
  result: PentagonResult | null
}) {
  return (
    <div>
      <div className="flex flex-col gap-6 sm:flex-row">
        <Panel
          title={geometry.pentagon1.title}
          subtitle={geometry.pentagon1.subtitle}
          zones={geometry.pentagon1.zones}
          geometry={geometry}
          result={result}
          side="pentagon1"
        />
        <Panel
          title={geometry.pentagon2.title}
          subtitle={geometry.pentagon2.subtitle}
          zones={geometry.pentagon2.zones}
          geometry={geometry}
          result={result}
          side="pentagon2"
        />
      </div>

      {result?.valid && result.percentages && result.centroid && (
        <div className="mt-4 rounded-lg border border-line bg-brand-50/60 p-3">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-ink-soft">
            {geometry.gasOrder.map((g) => (
              <span key={g} className="num">
                <span className="font-semibold text-ink">{g}</span>{' '}
                {result.percentages![g]?.toFixed(1)}%
              </span>
            ))}
            <span className="num text-ink-muted">
              Centre of gravity ({result.centroid.x.toFixed(2)}, {result.centroid.y.toFixed(2)})
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs">
            <span className="text-ink-soft">
              <span className="font-semibold">Pentagon 1:</span>{' '}
              {result.pentagon1?.zone ?? '—'} — {result.pentagon1?.meaning}
            </span>
            <span className="text-ink-soft">
              <span className="font-semibold">Pentagon 2:</span>{' '}
              {result.pentagon2?.zone ?? '—'} — {result.pentagon2?.meaning}
            </span>
          </div>
        </div>
      )}

      {result && !result.valid && (
        <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          {result.reason}
        </p>
      )}
    </div>
  )
}
