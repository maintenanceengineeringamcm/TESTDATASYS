import { RotateCcw, Save, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'

export default function WeightEditor({
  assetType,
  label,
  components,
  total,
  overridden,
  manualComponents,
  componentLabels,
  onSaved,
}: {
  assetType: string
  label: string
  components: Record<string, number>
  total: number
  overridden: boolean
  manualComponents: string[]
  componentLabels: Record<string, string>
  onSaved: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!editing) {
      setValues(Object.fromEntries(Object.entries(components).map(([k, v]) => [k, String(v)])))
    }
  }, [components, editing])

  const liveTotal = Object.values(values).reduce((s, v) => s + (Number(v) || 0), 0)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const payload: Record<string, number> = {}
      for (const [k, v] of Object.entries(values)) payload[k] = Number(v) || 0
      await api.put(`/config/weights/${assetType}`, { components: payload, note })
      setEditing(false)
      setNote('')
      onSaved()
    } catch (e: any) {
      setError(e.message ?? 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  async function reset() {
    setBusy(true)
    setError(null)
    try {
      await api.del(`/config/weights/${assetType}`)
      setEditing(false)
      onSaved()
    } catch (e: any) {
      setError(e.message ?? 'Reset failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <h3 className="text-xs font-bold uppercase tracking-wide text-ink">{label}</h3>
        <span className="num text-[11px] text-ink-muted">
          total {editing ? liveTotal.toFixed(2) : total}
        </span>
        {overridden && (
          <span className="chip bg-amber-50 text-[10px] text-amber-800">edited</span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {!editing ? (
            <>
              <button
                onClick={() => setEditing(true)}
                className="rounded px-2 py-0.5 text-[11px] font-semibold text-brand-700 hover:bg-brand-50"
              >
                Edit weights
              </button>
              {overridden && (
                <button
                  onClick={reset}
                  disabled={busy}
                  title="Discard the override and go back to the source configuration"
                  className="rounded px-2 py-0.5 text-[11px] text-ink-muted hover:bg-brand-50"
                >
                  <RotateCcw className="h-3 w-3" />
                </button>
              )}
            </>
          ) : (
            <>
              <button
                onClick={save}
                disabled={busy}
                className="inline-flex items-center gap-1 rounded bg-brand-600 px-2 py-0.5 text-[11px] font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
              >
                <Save className="h-3 w-3" />
                Save
              </button>
              <button
                onClick={() => {
                  setEditing(false)
                  setError(null)
                }}
                className="rounded px-2 py-0.5 text-[11px] text-ink-muted hover:bg-brand-50"
              >
                <X className="h-3 w-3" />
              </button>
            </>
          )}
        </div>
      </div>

      {error && (
        <p className="mb-2 rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-800">
          {error}
        </p>
      )}

      {editing ? (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
            {Object.keys(components).map((code) => (
              <div key={code}>
                <label
                  className="mb-0.5 block truncate text-[10px] font-semibold text-ink-muted"
                  title={componentLabels[code] ?? code}
                >
                  {code}
                </label>
                <input
                  className="input num !py-1 !text-[11px]"
                  type="number"
                  min={0}
                  step="any"
                  value={values[code] ?? ''}
                  onChange={(e) => setValues((v) => ({ ...v, [code]: e.target.value }))}
                />
              </div>
            ))}
          </div>
          <input
            className="input mt-2 !py-1 !text-[11px]"
            placeholder="Why is this changing? (kept in the change log)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <p className="mt-1.5 text-[10px] leading-relaxed text-ink-faint">
            Weights need not sum to 100 — they are re-normalised over whichever criteria
            an asset actually has data for. The total is shown so a deliberate scale is
            easy to keep.
          </p>
        </>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(components)
            .sort((a, b) => b[1] - a[1])
            .map(([code, value]) => (
              <span
                key={code}
                className={`chip text-[11px] ${
                  value > 0 ? 'bg-brand-50 text-brand-800' : 'bg-slate-100 text-slate-400'
                }`}
                title={componentLabels[code] ?? code}
              >
                {code} <span className="num font-bold">{value}</span>
                {manualComponents.includes(code) && (
                  <span className="text-[9px] opacity-60">manual</span>
                )}
              </span>
            ))}
        </div>
      )}
    </div>
  )
}
