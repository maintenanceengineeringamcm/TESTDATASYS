import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { GAS_COLORS } from './gasColors'

// Defined in its own module so the PDF builder can share it; re-exported here
// because every chart in the app already imports it from this file.
export { GAS_COLORS } from './gasColors'

const axisStyle = { fontSize: 11, fill: '#64748B' }

function TooltipBox({ active, payload, label, unit = '' }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2 shadow-pop">
      <p className="mb-1 text-xs font-semibold text-ink">{label}</p>
      {payload
        .filter((p: any) => p.value !== null && p.value !== undefined)
        .map((p: any) => (
          <p key={p.dataKey} className="num text-xs" style={{ color: p.color }}>
            <span className="font-medium">{p.name}</span>: {Number(p.value).toFixed(2)}
            {unit}
          </p>
        ))}
    </div>
  )
}

/** Gas concentration vs sampling date. */
export function GasTrendChart({
  points,
  gases,
  height = 320,
}: {
  points: Record<string, any>[]
  gases: string[]
  height?: number
}) {
  if (!points.length) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-ink-muted">
        No samples in the selected range.
      </div>
    )
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={points} margin={{ top: 8, right: 16, bottom: 8, left: 4 }}>
        <CartesianGrid stroke="#E3F0FC" vertical={false} />
        <XAxis dataKey="date" tick={axisStyle} tickLine={false} axisLine={{ stroke: '#DCE7F3' }}
               angle={-30} textAnchor="end" height={54} />
        <YAxis tick={axisStyle} tickLine={false} axisLine={{ stroke: '#DCE7F3' }}
               label={{ value: 'Concentration (ppm)', angle: -90, position: 'insideLeft',
                        style: { fontSize: 11, fill: '#64748B' } }} />
        <Tooltip content={<TooltipBox unit=" ppm" />} />
        <Legend wrapperStyle={{ fontSize: 12, paddingTop: 4 }} iconType="line" />
        {gases.map((g) => (
          <Line
            key={g}
            type="monotone"
            dataKey={g}
            name={g}
            stroke={GAS_COLORS[g] ?? '#64748B'}
            strokeWidth={2}
            dot={{ r: 3 }}
            activeDot={{ r: 5 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

/** Health-index band distribution. */
export function HIDistributionChart({
  data,
  height = 260,
}: {
  data: { label: string; count: number; color: string }[]
  height?: number
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
        <CartesianGrid stroke="#E3F0FC" vertical={false} />
        <XAxis dataKey="label" tick={{ ...axisStyle, fontSize: 10 }} tickLine={false}
               axisLine={{ stroke: '#DCE7F3' }} interval={0} />
        <YAxis tick={axisStyle} tickLine={false} axisLine={{ stroke: '#DCE7F3' }}
               allowDecimals={false} />
        <Tooltip
          cursor={{ fill: '#F2F8FE' }}
          content={({ active, payload }: any) =>
            active && payload?.length ? (
              <div className="rounded-lg border border-line bg-white px-3 py-2 shadow-pop">
                <p className="text-xs font-semibold text-ink">{payload[0].payload.label}</p>
                <p className="num text-xs text-ink-soft">{payload[0].value} assets</p>
              </div>
            ) : null
          }
        />
        <Bar dataKey="count" radius={[5, 5, 0, 0]} maxBarSize={64}>
          {data.map((d) => (
            <Cell key={d.label} fill={d.color} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Stored health-index history for one asset. */
export function HIHistoryChart({
  data,
  height = 240,
}: {
  data: { date: string; value: number }[]
  height?: number
}) {
  if (!data.length) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-ink-muted">
        No stored health-index history for this asset.
      </div>
    )
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
        <CartesianGrid stroke="#E3F0FC" vertical={false} />
        <XAxis dataKey="date" tick={axisStyle} tickLine={false}
               axisLine={{ stroke: '#DCE7F3' }} />
        <YAxis domain={[0, 100]} tick={axisStyle} tickLine={false}
               axisLine={{ stroke: '#DCE7F3' }} />
        <Tooltip content={<TooltipBox />} />
        {/* Band thresholds, so a point can be read against its grade at a glance. */}
        <ReferenceLine y={85} stroke="#0E9F6E" strokeDasharray="4 4" />
        <ReferenceLine y={70} stroke="#2E7DD1" strokeDasharray="4 4" />
        <ReferenceLine y={55} stroke="#B7791F" strokeDasharray="4 4" />
        <ReferenceLine y={40} stroke="#DD6B20" strokeDasharray="4 4" />
        <Line type="monotone" dataKey="value" name="Health Index" stroke="#1E72BC"
              strokeWidth={2.5} dot={{ r: 3.5 }} />
      </LineChart>
    </ResponsiveContainer>
  )
}

/** Measured gas levels against IEEE Table 1 / Table 2 limits, log scale. */
export function IEEELimitsChart({
  rows,
  height = 300,
}: {
  rows: { gas: string; value: number; table1: number; table2: number; severity: number }[]
  height?: number
}) {
  const data = rows.map((r) => ({ ...r, value: Math.max(r.value, 0.01) }))
  const severityColor = (s: number) =>
    s === 3 ? '#D64545' : s === 2 ? '#DD6B20' : '#2E8FDD'
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
        <CartesianGrid stroke="#E3F0FC" vertical={false} />
        <XAxis dataKey="gas" tick={axisStyle} tickLine={false}
               axisLine={{ stroke: '#DCE7F3' }} />
        {/* Log scale is mandatory: C2H2 sits near 1 ppm and CO2 near 10 000 ppm,
            so on a linear axis every gas but CO2 collapses to zero height. */}
        <YAxis scale="log" domain={[0.01, 'auto']} allowDataOverflow tick={axisStyle}
               tickLine={false} axisLine={{ stroke: '#DCE7F3' }}
               label={{ value: 'ppm (log)', angle: -90, position: 'insideLeft',
                        style: { fontSize: 11, fill: '#64748B' } }} />
        <Tooltip content={<TooltipBox unit=" ppm" />} cursor={{ fill: '#F2F8FE' }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="value" name="Measured" radius={[4, 4, 0, 0]} maxBarSize={30}>
          {data.map((d) => (
            <Cell key={d.gas} fill={severityColor(d.severity)} />
          ))}
        </Bar>
        <Bar dataKey="table1" name="Table 1 (90th pct)" fill="#F1C40F" fillOpacity={0.7}
             radius={[4, 4, 0, 0]} maxBarSize={30} />
        <Bar dataKey="table2" name="Table 2 (95th pct)" fill="#E8833A" fillOpacity={0.7}
             radius={[4, 4, 0, 0]} maxBarSize={30} />
      </BarChart>
    </ResponsiveContainer>
  )
}
