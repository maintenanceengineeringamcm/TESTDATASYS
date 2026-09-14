import jsPDF from 'jspdf'
import autoTable, { type RowInput } from 'jspdf-autotable'
import type { DgaLimit, DgaStatusReport, PentagonResult, TriangleResult } from '../types'

/**
 * The DGA status report as a real PDF file.
 *
 * Built from the report *data*, not by rasterising the screen: an engineer
 * signs this, so the tables must stay selectable text that survives a
 * photocopier, and the page breaks must fall between rows rather than through
 * them. Rendering from data is also what lets the file carry the same section
 * numbering as the on-screen report, so a reviewer can quote "section 4" and
 * mean the same thing in either.
 */

const BRAND = '#195B96'
const INK = '#0B1220'
const INK_MUTED = '#64748B'
const LINE = '#DCE7F3'
const HEAD_BG = '#E3F0FC'
const RED = '#D64545'
const GREEN = '#2F855A'

const GASES = ['H2', 'CH4', 'C2H6', 'C2H4', 'C2H2', 'CO', 'CO2'] as const
const SAMPLE_COLS = [...GASES, 'O2', 'N2'] as const

const MARGIN = 12

/** A chart already rasterised for the page; `aspect` is height / width. */
export interface PdfChart {
  dataUrl: string
  aspect: number
}

/** Optional Duval sections the engineer ticked in the export dialog. */
export interface DuvalPdfExtras {
  sampleDate: string | null
  gases: Record<string, number>
  triangles?: { charts: PdfChart[]; titles: string[]; results: TriangleResult[] }
  pentagons?: { charts: PdfChart[]; titles: string[]; result: PentagonResult }
}

const DUVAL_GASES = ['H2', 'CH4', 'C2H6', 'C2H4', 'C2H2'] as const

/** Two charts side by side, each captioned. Returns the y below them. */
function chartPair(doc: jsPDF, y: number, charts: PdfChart[], titles: string[]): number {
  const pageW = doc.internal.pageSize.getWidth()
  const pageH = doc.internal.pageSize.getHeight()
  const gap = 6
  const w = (pageW - MARGIN * 2 - gap) / 2
  const h = Math.max(...charts.map((c) => w * c.aspect))
  if (y + h + 6 > pageH - MARGIN) {
    doc.addPage()
    y = MARGIN + 6
  }
  charts.forEach((c, i) => {
    const x = MARGIN + i * (w + gap)
    doc.setFont('helvetica', 'bold').setFontSize(8).setTextColor(INK)
    doc.text(titles[i] ?? '', x, y)
    doc.setDrawColor(LINE).setLineWidth(0.2)
    doc.rect(x, y + 1.5, w, w * c.aspect)
    // 'FAST' deflates the pixels; without it jsPDF stores them raw and two
    // chart pages weigh in at well over 10 MB.
    doc.addImage(c.dataUrl, 'PNG', x, y + 1.5, w, w * c.aspect, undefined, 'FAST')
  })
  return y + 1.5 + h + 4
}

const percentText = (p: Record<string, number> | null | undefined) =>
  p ? Object.entries(p).map(([g, v]) => `${g} ${v.toFixed(1)}%`).join(', ') : '—'

/** Height a Duval section needs before its heading may be placed. */
function duvalNeeds(doc: jsPDF, charts: PdfChart[]): number {
  const w = (doc.internal.pageSize.getWidth() - MARGIN * 2 - 6) / 2
  return 20 + Math.max(0, ...charts.map((c) => w * c.aspect))
}

function limitText(limit: DgaLimit): string {
  if (limit === 'ANY_INCREASE') return 'N/A'
  if (limit === null || limit === undefined) return 'n/a'
  return String(limit)
}

const num = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? '—' : v.toFixed(digits)

const signed = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(digits)}`

/** Where autoTable left the cursor, so the next section starts below it. */
function cursorY(doc: jsPDF): number {
  return (doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable.finalY
}

/**
 * A section heading. Returns the y to start the body at.
 *
 * Takes the height of what follows so a heading is never orphaned at the foot
 * of a page — a numbered heading with its table overleaf reads as a missing
 * section.
 */
function heading(doc: jsPDF, y: number, n: number, title: string, needs = 24): number {
  const pageH = doc.internal.pageSize.getHeight()
  if (y + needs > pageH - MARGIN) {
    doc.addPage()
    y = MARGIN + 6
  }
  doc.setFont('helvetica', 'bold').setFontSize(10).setTextColor(INK)
  doc.text(`${n}. ${title}`, MARGIN, y)
  doc.setDrawColor(BRAND).setLineWidth(0.4)
  doc.line(MARGIN, y + 1.6, doc.internal.pageSize.getWidth() - MARGIN, y + 1.6)
  return y + 7
}

/** Wrapped body text, paginating itself. Returns the y below the last line. */
function paragraph(doc: jsPDF, y: number, text: string, opts: {
  size?: number
  color?: string
  bold?: boolean
  indent?: number
} = {}): number {
  const { size = 8.5, color = INK, bold = false, indent = 0 } = opts
  const pageH = doc.internal.pageSize.getHeight()
  const width = doc.internal.pageSize.getWidth() - MARGIN * 2 - indent
  doc.setFont('helvetica', bold ? 'bold' : 'normal').setFontSize(size).setTextColor(color)
  const lines = doc.splitTextToSize(text, width) as string[]
  const lh = size * 0.44
  for (const line of lines) {
    if (y + lh > pageH - MARGIN) {
      doc.addPage()
      y = MARGIN + 6
      doc.setFont('helvetica', bold ? 'bold' : 'normal').setFontSize(size).setTextColor(color)
    }
    doc.text(line, MARGIN + indent, y)
    y += lh
  }
  return y
}

function bullets(doc: jsPDF, y: number, items: string[], size = 8.5): number {
  for (const item of items) {
    const before = y
    y = paragraph(doc, y, item, { size, indent: 4 })
    doc.setFont('helvetica', 'bold').setFontSize(size).setTextColor(BRAND)
    doc.text('•', MARGIN, before)
    y += 1.2
  }
  return y
}

/**
 * Render the report into a jsPDF document.
 *
 * Separate from the save so the rendering can be exercised without a browser
 * download — and so a caller that wants the bytes for something else (an email
 * attachment, a stored copy) does not have to go through a file dialog.
 *
 * `status.color`/`bg` come from the backend so the status block is the same
 * colour here as on screen — the scale is defined in one place and the PDF
 * borrows it rather than restating it.
 */
export function buildDgaStatusPdf(report: DgaStatusReport, extras?: DuvalPdfExtras): jsPDF {
  const doc = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' })
  const pageW = doc.internal.pageSize.getWidth()
  const s = report.status

  // ---- Masthead ----------------------------------------------------------
  doc.setFillColor(BRAND)
  doc.rect(0, 0, pageW, 26, 'F')
  doc.setFont('helvetica', 'bold').setFontSize(14).setTextColor('#FFFFFF')
  doc.text('DGA Status Report', MARGIN, 11)
  doc.setFont('helvetica', 'normal').setFontSize(8)
  doc.text('Dissolved gas analysis — status assessment, IEEE C57.104-2019', MARGIN, 16.5)
  doc.setFont('helvetica', 'bold').setFontSize(9)
  doc.text(report.asset, MARGIN, 22)

  // The status is set below the masthead rather than inside it: the band is a
  // dark brand blue, and the status colours are chosen to read on white, so a
  // red or amber verdict printed on the band would be barely legible.
  let y = 33
  doc.setFont('helvetica', 'bold').setFontSize(13).setTextColor(s.color)
  doc.text(`${s.statusLabel} - ${s.verdict}`, MARGIN, y)
  y += 8

  // ---- Header facts ------------------------------------------------------
  const facts: [string, string][] = [
    ['Report generated', report.generatedAt],
    ['Latest sample', s.latestSample ?? '—'],
    ['Samples used', String(s.samples)],
    ['History from', s.firstSample ?? '—'],
    ['O2/N2 section', s.ratioBand ?? '—'],
    ['Age band', `${s.ageBand ?? '—'}${s.ageYears !== null ? ` (${s.ageYears} yr)` : ''}`],
    ['Table 4 period', s.periodBand ? `${s.periodBand} months` : 'not applicable'],
    ['Multi-point rate', s.ratesAvailable ? 'available' : 'not available'],
  ]
  autoTable(doc, {
    startY: y,
    margin: { left: MARGIN, right: MARGIN },
    theme: 'plain',
    styles: { fontSize: 7.5, cellPadding: 1.1, textColor: INK },
    body: [0, 1].map((row) =>
      facts.slice(row * 4, row * 4 + 4).flatMap(([k, v]) => [k, v]),
    ) as RowInput[],
    columnStyles: Object.fromEntries(
      [0, 2, 4, 6].flatMap((i) => [
        [i, { textColor: INK_MUTED, cellWidth: 22 }],
        [i + 1, { fontStyle: 'bold' as const, cellWidth: 24.5 }],
      ]),
    ),
  })
  y = cursorY(doc) + 6

  // ---- 1. Verdict --------------------------------------------------------
  y = heading(doc, y, 1, 'Verdict', 26)
  y = paragraph(doc, y, s.reason)
  y += 2
  y = paragraph(doc, y, `Required action — ${s.action}`, { bold: true })
  if (s.ageSource?.manufactureYear) {
    y += 1
    y = paragraph(
      doc,
      y,
      `Age taken from the year of manufacture ${s.ageSource.manufactureYear} (${s.ageSource.source}${
        s.ageSource.inheritedFrom ? `, via ${s.ageSource.inheritedFrom}` : ''
      }).`,
      { size: 7.5, color: INK_MUTED },
    )
  }
  y += 5

  // ---- 2. What drove the status -----------------------------------------
  y = heading(doc, y, 2, 'What drove the status', 20)
  if (s.triggeredBy.length === 0) {
    y = paragraph(
      doc,
      y,
      'Nothing exceeded a limit — every measured gas is below its Table 1 level, with no change or rate outside the allowance.',
    )
  } else {
    y = bullets(
      doc,
      y,
      s.triggeredBy.map((t) => t.text),
    )
  }
  y += 5

  // ---- 3. Decision path --------------------------------------------------
  y = heading(doc, y, 3, 'Decision path', 30)
  autoTable(doc, {
    startY: y,
    margin: { left: MARGIN, right: MARGIN },
    head: [['Step', 'Question', 'Answer', 'Detail']],
    body: s.decisionTrace.map((t) => [t.step, t.question, t.answer, t.detail]),
    styles: { fontSize: 7, cellPadding: 1.3, textColor: INK, lineColor: LINE, lineWidth: 0.1 },
    headStyles: { fillColor: HEAD_BG, textColor: BRAND, fontStyle: 'bold', fontSize: 7 },
    columnStyles: {
      0: { cellWidth: 14, fontStyle: 'bold' },
      1: { cellWidth: 52 },
      2: { cellWidth: 26, fontStyle: 'bold' },
      3: { cellWidth: 'auto', textColor: INK_MUTED },
    },
  })
  y = cursorY(doc) + 6

  // ---- 4. Gas-by-gas evidence -------------------------------------------
  // The heart of the report: the reading, the limit it was tested against and
  // the verdict, so the status can be re-derived by hand from this table alone.
  y = heading(doc, y, 4, 'Gas-by-gas evidence', 34)
  const measured = s.gases.filter((g) => g.measured)
  const unmeasured = s.gases.filter((g) => !g.measured).map((g) => g.gas)

  autoTable(doc, {
    startY: y,
    margin: { left: MARGIN, right: MARGIN },
    head: [
      [
        'Gas', 'Latest\nppm', 'T1', 'T2', 'Level',
        // Spelled out, not a Greek delta: jsPDF's built-in fonts are
        // WinAnsi-encoded and would silently drop the glyph, leaving the
        // column unlabelled in the printed report.
        'Change since\nprevious', 'T3', 'Verdict',
        'Rate\nppm/yr', 'T4', 'Rate',
      ],
    ],
    body: measured.map((g) => [
      g.gas,
      num(g.latest),
      num(g.t1, 0),
      num(g.t2, 0),
      g.exceedsT2 ? 'above T2' : g.exceedsT1 ? 'above T1' : g.atT1 ? 'at T1' : 'within',
      signed(g.delta),
      limitText(g.t3),
      g.delta === null || g.t3 === null ? 'n/a' : g.exceedsT3 ? 'over' : 'within',
      signed(g.rate),
      s.ratesAvailable ? limitText(g.t4) : '—',
      !s.ratesAvailable || g.rate === null ? 'n/a' : g.exceedsT4 ? 'over' : 'within',
    ]),
    styles: { fontSize: 7, cellPadding: 1.3, textColor: INK, lineColor: LINE, lineWidth: 0.1,
              halign: 'right' },
    headStyles: { fillColor: HEAD_BG, textColor: BRAND, fontStyle: 'bold', fontSize: 6.5,
                  halign: 'center', valign: 'middle' },
    columnStyles: {
      0: { halign: 'left', fontStyle: 'bold', cellWidth: 15 },
      4: { halign: 'center' },
      7: { halign: 'center' },
      10: { halign: 'center' },
    },
    // The verdict columns are coloured, but they also carry the word — the
    // report has to survive a monochrome printer.
    didParseCell: (data) => {
      if (data.section !== 'body') return
      if (![4, 7, 10].includes(data.column.index)) return
      const text = String(data.cell.raw)
      if (text === 'n/a') data.cell.styles.textColor = INK_MUTED
      else if (text === 'within') data.cell.styles.textColor = GREEN
      else {
        data.cell.styles.textColor = RED
        data.cell.styles.fontStyle = 'bold'
      }
    },
  })
  y = cursorY(doc) + 3

  if (unmeasured.length) {
    y = paragraph(doc, y, `Not measured, so excluded from every comparison: ${unmeasured.join(', ')}.`,
      { size: 7, color: INK_MUTED })
  }
  if (s.rateWindow && s.ratesAvailable) {
    y = paragraph(
      doc, y,
      `Rates are the slope of a least-squares fit over the ${s.rateWindow.points} samples from ${s.rateWindow.from} to ${s.rateWindow.to} (${s.rateWindow.spanMonths} months).`,
      { size: 7, color: INK_MUTED },
    )
  }
  y += 5

  // ---- 5. Limits applied -------------------------------------------------
  if (report.limitsUsed) {
    const lu = report.limitsUsed
    y = heading(doc, y, 5, 'Limits applied', 30)
    y = paragraph(
      doc, y,
      `Column selected by the standard: O2/N2 ${lu.columns.ratioBand}, age ${lu.columns.ageBand}${
        lu.columns.periodBand ? `, Table 4 period ${lu.columns.periodBand} months` : ', Table 4 not applied'
      }.`,
      { size: 7.5, color: INK_MUTED },
    )
    y += 2
    autoTable(doc, {
      startY: y,
      margin: { left: MARGIN, right: MARGIN },
      head: [['Table', ...GASES]],
      body: ([
        ['Table 1 — 90th percentile level', lu.table1],
        ['Table 2 — 95th percentile level', lu.table2],
        ['Table 3 — change between samples', lu.table3],
        ['Table 4 — rate (ppm/yr)', lu.table4 ?? null],
      ] as [string, Record<string, DgaLimit> | null][]).map(([name, row]) => [
        name,
        ...GASES.map((g) => (row ? limitText(row[g]) : 'not applied')),
      ]),
      styles: { fontSize: 7, cellPadding: 1.3, textColor: INK, lineColor: LINE, lineWidth: 0.1,
                halign: 'right' },
      headStyles: { fillColor: HEAD_BG, textColor: BRAND, fontStyle: 'bold', fontSize: 7,
                    halign: 'center' },
      columnStyles: { 0: { halign: 'left', fontStyle: 'bold', cellWidth: 52 } },
    })
    y = cursorY(doc) + 6
  }

  // ---- 6. Sample history -------------------------------------------------
  y = heading(doc, y, 6, 'Sample history used', 30)
  autoTable(doc, {
    startY: y,
    margin: { left: MARGIN, right: MARGIN },
    head: [['Date', ...SAMPLE_COLS]],
    body: report.sampleTable.map((row) => [
      String(row.date),
      ...SAMPLE_COLS.map((g) => (row[g] === null || row[g] === undefined ? '—' : String(row[g]))),
    ]),
    styles: { fontSize: 7, cellPadding: 1.2, textColor: INK, lineColor: LINE, lineWidth: 0.1,
              halign: 'right' },
    headStyles: { fillColor: HEAD_BG, textColor: BRAND, fontStyle: 'bold', fontSize: 7,
                  halign: 'center' },
    columnStyles: { 0: { halign: 'left', fontStyle: 'bold', cellWidth: 22 } },
  })
  y = cursorY(doc) + 6

  // ---- 7+. Duval diagrams, when requested -------------------------------
  let section = 7
  const duvalSample = extras
    ? `Diagnosed on the DGA sample of ${extras.sampleDate ?? 'unknown date'}: ${DUVAL_GASES.map(
        (g) => `${g} ${extras.gases[g] ?? 0}`,
      ).join(', ')} ppm.`
    : ''

  if (extras?.triangles) {
    const t = extras.triangles
    y = heading(doc, y, section++, 'Duval dual triangles', duvalNeeds(doc, t.charts))
    y = paragraph(doc, y, duvalSample, { size: 7.5, color: INK_MUTED })
    y = chartPair(doc, y + 2, t.charts, t.titles)
    autoTable(doc, {
      startY: y,
      margin: { left: MARGIN, right: MARGIN },
      head: [['Diagram', 'Zone', 'Meaning', 'Gas composition']],
      body: t.results.map((r) => [
        `${r.title}${r.provisional ? ' (provisional zones)' : ''}`,
        r.valid ? (r.zone ?? '—') : '—',
        r.valid ? (r.meaning ?? '—') : (r.reason ?? 'Not diagnosable'),
        r.valid ? percentText(r.percentages) : '—',
      ]),
      styles: { fontSize: 7, cellPadding: 1.3, textColor: INK, lineColor: LINE, lineWidth: 0.1 },
      headStyles: { fillColor: HEAD_BG, textColor: BRAND, fontStyle: 'bold', fontSize: 7 },
      columnStyles: {
        0: { cellWidth: 44, fontStyle: 'bold' },
        1: { cellWidth: 14, fontStyle: 'bold', halign: 'center' },
      },
    })
    y = cursorY(doc) + 6
  }

  if (extras?.pentagons) {
    const p = extras.pentagons
    const r = p.result
    y = heading(doc, y, section++, 'Duval dual pentagons', duvalNeeds(doc, p.charts))
    y = paragraph(doc, y, duvalSample, { size: 7.5, color: INK_MUTED })
    y = chartPair(doc, y + 2, p.charts, p.titles)
    if (r.valid) {
      autoTable(doc, {
        startY: y,
        margin: { left: MARGIN, right: MARGIN },
        head: [['Diagram', 'Zone', 'Meaning']],
        body: [
          [p.titles[0], r.pentagon1?.zone ?? '—', r.pentagon1?.meaning ?? '—'],
          [p.titles[1], r.pentagon2?.zone ?? '—', r.pentagon2?.meaning ?? '—'],
        ],
        styles: { fontSize: 7, cellPadding: 1.3, textColor: INK, lineColor: LINE, lineWidth: 0.1 },
        headStyles: { fillColor: HEAD_BG, textColor: BRAND, fontStyle: 'bold', fontSize: 7 },
        columnStyles: {
          0: { cellWidth: 44, fontStyle: 'bold' },
          1: { cellWidth: 14, fontStyle: 'bold', halign: 'center' },
        },
      })
      y = cursorY(doc) + 3
      y = paragraph(
        doc, y,
        `Gas composition: ${percentText(r.percentages)}${
          r.centroid ? `. Centre of gravity (${r.centroid.x.toFixed(2)}, ${r.centroid.y.toFixed(2)}).` : '.'
        }`,
        { size: 7, color: INK_MUTED },
      )
    } else {
      y = paragraph(doc, y, r.reason ?? 'The sample could not be plotted on the pentagons.',
        { size: 7.5, color: INK_MUTED })
    }
  }

  // ---- Footer on every page ---------------------------------------------
  const pages = doc.getNumberOfPages()
  const pageH = doc.internal.pageSize.getHeight()
  for (let i = 1; i <= pages; i++) {
    doc.setPage(i)
    doc.setDrawColor(LINE).setLineWidth(0.2)
    doc.line(MARGIN, pageH - 10, pageW - MARGIN, pageH - 10)
    doc.setFont('helvetica', 'normal').setFontSize(6.5).setTextColor(INK_MUTED)
    doc.text(
      `${report.asset} — DGA status ${s.statusLabel} — generated ${report.generatedAt} by the Transformer Asset Health Index & Analysis system`,
      MARGIN,
      pageH - 6,
    )
    doc.text(`Page ${i} of ${pages}`, pageW - MARGIN, pageH - 6, { align: 'right' })
  }

  return doc
}

/** The filename an engineer will find in their downloads folder. */
export function dgaStatusPdfName(report: DgaStatusReport): string {
  const safe = (report.asset || 'entered-data').replace(/[^\w.-]+/g, '_')
  return `dga-status-${safe}-${report.generatedAt.slice(0, 10)}.pdf`
}

/** Render the report and hand the browser a file. */
export function exportDgaStatusPdf(report: DgaStatusReport, extras?: DuvalPdfExtras): void {
  buildDgaStatusPdf(report, extras).save(dgaStatusPdfName(report))
}
