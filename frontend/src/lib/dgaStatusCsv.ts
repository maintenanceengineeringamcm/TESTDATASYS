import type { DgaLimit, DgaStatusResult } from '../types'

/** A Table 3/4 limit as text: the C2H2 sentinel has no number to print. */
export function limitText(limit: DgaLimit): string {
  if (limit === 'ANY_INCREASE') return 'N/A'
  if (limit === null || limit === undefined) return 'not available'
  return String(limit)
}

/**
 * The gas-by-gas evidence as a CSV.
 *
 * Module scope rather than a closure because both the stored-asset and the
 * hand-entered assessment export the identical evidence - the classifier does
 * not care where the numbers came from, and neither should the export.
 */
export function saveStatusCsv(s: DgaStatusResult) {
  const head = [
    'Gas', 'Measured', 'Latest ppm', 'Latest date', 'Previous ppm', 'Previous date',
    'Delta ppm', 'Rate ppm/yr', 'T1', 'T2', 'T3', 'T4',
    'Above T1', 'At T1', 'Above T2', 'Delta over T3', 'Rate over T4', 'Note',
  ]
  const rows = s.gases.map((g) => [
    g.gas, g.measured ? 'yes' : 'no', g.latest ?? '', g.latestDate ?? '',
    g.previous ?? '', g.previousDate ?? '', g.delta ?? '',
    g.rate === null ? '' : g.rate.toFixed(2),
    g.t1 ?? '', g.t2 ?? '', limitText(g.t3), s.ratesAvailable ? limitText(g.t4) : '',
    g.exceedsT1 ? 'yes' : 'no', g.atT1 ? 'yes' : 'no', g.exceedsT2 ? 'yes' : 'no',
    g.exceedsT3 ? 'yes' : 'no', g.exceedsT4 ? 'yes' : 'no', g.note,
  ])
  const meta = [
    ['Asset', s.asset], ['Status', s.statusLabel], ['Verdict', s.verdict],
    ['O2/N2 section', s.ratioBand ?? ''], ['Age band', s.ageBand ?? ''],
    ['Table 4 period', s.periodBand ?? 'not applied'],
    ['Latest sample', s.latestSample ?? ''], ['Standard', s.standard], [],
  ]
  // Quote every field: gas notes and the standard's own text contain commas.
  const csv = [...meta, head, ...rows]
    .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(','))
    .join('\r\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `dga-status-${(s.asset || 'entered-data').replace(/[^\w.-]+/g, '_')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
