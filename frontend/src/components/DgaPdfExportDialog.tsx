import {
  Download,
  FileText,
  LineChart as LineChartIcon,
  Pentagon as PentagonIcon,
  Triangle as TriangleIcon,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import type { DgaStatusReport } from '../types'

/**
 * Asks what to add to the DGA status PDF before building it.
 *
 * The status report itself is always included; the Duval diagrams are optional
 * because they need a second diagnosis round-trip and add two pages. The dialog
 * owns the whole export so every "Download PDF" button behaves identically.
 */
export default function DgaPdfExportDialog({
  open,
  onClose,
  loadReport,
}: {
  open: boolean
  onClose: () => void
  /** The full report payload - fetched on demand where the caller lacks it. */
  loadReport: () => Promise<DgaStatusReport>
}) {
  const [trends, setTrends] = useState(false)
  const [triangles, setTriangles] = useState(false)
  const [pentagons, setPentagons] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, busy, onClose])

  if (!open) return null

  async function download() {
    setBusy(true)
    setError(null)
    try {
      // jsPDF and the chart renderer are heavy and most visits never export.
      const [{ exportDgaStatusPdf }, report] = await Promise.all([
        import('../lib/dgaStatusPdf'),
        loadReport(),
      ])
      let extras
      if (triangles || pentagons) {
        const { buildDuvalExtras } = await import('../lib/duvalPdfCharts')
        extras = await buildDuvalExtras(report, { triangles, pentagons })
      }
      exportDgaStatusPdf(report, extras, { trends })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not build the PDF.')
    } finally {
      setBusy(false)
    }
  }

  const options = [
    {
      checked: trends,
      set: setTrends,
      icon: LineChartIcon,
      title: 'Gas trend charts',
      hint: 'Three line charts over the sample history: H2 with C2H2, the three hydrocarbons together, and all five fault gases in one.',
    },
    {
      checked: triangles,
      set: setTriangles,
      icon: TriangleIcon,
      title: 'Duval dual triangles',
      hint: 'Triangle 1 (fault type) and Triangle 5 (thermal refinement), with zones and gas percentages.',
    },
    {
      checked: pentagons,
      set: setPentagons,
      icon: PentagonIcon,
      title: 'Duval dual pentagons',
      hint: 'Pentagon 1 and Pentagon 2, with the diagnosed zones and centre of gravity.',
    },
  ]

  return (
    <div
      className="print-hide fixed inset-0 z-[1000] flex items-center justify-center bg-ink/40 p-4"
      onClick={() => !busy && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dga-pdf-dialog-title"
        className="card w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="card-head !py-3">
          <FileText className="h-4 w-4 text-brand-600" />
          <h2 id="dga-pdf-dialog-title" className="text-sm font-bold text-ink">
            Download PDF report
          </h2>
          <button
            className="btn-ghost ml-auto !px-2 !py-1"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="card-pad space-y-3">
          <p className="text-xs text-ink-muted">
            The DGA status report is always included. Select anything to add to it:
          </p>

          {options.map(({ checked, set, icon: Icon, title, hint }) => (
            <label
              key={title}
              className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors ${
                checked ? 'border-brand-400 bg-brand-50' : 'border-line hover:bg-brand-50/50'
              }`}
            >
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-[#195B96]"
                checked={checked}
                onChange={(e) => set(e.target.checked)}
                disabled={busy}
              />
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-ink">{title}</span>
                <span className="block text-[11px] leading-relaxed text-ink-muted">{hint}</span>
              </span>
            </label>
          ))}

          {error && <p className="rounded-lg bg-red-50 p-2.5 text-xs text-red-700">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button className="btn-ghost !py-1.5 text-xs" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button className="btn-primary !py-1.5 text-xs" onClick={download} disabled={busy}>
              <Download className="h-3.5 w-3.5" />
              {busy ? 'Building…' : 'Download PDF'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
