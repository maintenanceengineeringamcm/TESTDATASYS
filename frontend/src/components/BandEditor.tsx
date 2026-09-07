import { Check, Plus, RotateCcw, Save, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'

export interface EditableBand {
  sequence: number
  rangeFrom: number
  rangeTo: number
  score: number
  descending?: boolean
}

export interface BandTable {
  overridden: boolean
  updatedAt: string | null
  updatedBy: string | null
  note: string
  bands: EditableBand[]
}

const scoreTone = (s: number) =>
  s >= 0.75
    ? { bg: '#E6F6F0', fg: '#0E9F6E' }
    : s >= 0.5
      ? { bg: '#E8F1FC', fg: '#2E7DD1' }
      : s >= 0.25
        ? { bg: '#FDF6E3', fg: '#B7791F' }
        : { bg: '#FCEAEA', fg: '#D64545' }

/**
 * Editable range table for one scoring band.
 *
 * Values are edited exactly as they are stored, including descending tables
 * (BDV, IFT, IR), where `rangeFrom` is the upper edge. Rewriting those to
 * ascending order in the editor would silently disagree with the source system
 * an engineer is comparing against.
 */
export default function BandEditor({
  assetType,
  bandName,
  table,
  onSaved,
}: {
  assetType: string
  bandName: string
  table: BandTable
  onSaved: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [rows, setRows] = useState<EditableBand[]>(table.bands)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!editing) setRows(table.bands)
  }, [table, editing])

  function update(i: number, key: keyof EditableBand, value: string) {
    setRows((r) =>
      r.map((row, idx) => (idx === i ? { ...row, [key]: value === '' ? 0 : Number(value) } : row)),
    )
  }

  function addRow() {
    setRows((r) => [
      ...r,
      { sequence: r.length + 1, rangeFrom: 0, rangeTo: 0, score: 0 },
    ])
  }

  function removeRow(i: number) {
    setRows((r) => r.filter((_, idx) => idx !== i).map((row, idx) => ({ ...row, sequence: idx + 1 })))
  }

  const path = `/config/bands/${assetType}/${encodeURIComponent(bandName)}`

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.put(path, {
        bands: rows.map((r, i) => ({ ...r, sequence: i + 1 })),
        note,
      })
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
      await api.del(path)
      setEditing(false)
      onSaved()
    } catch (e: any) {
      setError(e.message ?? 'Reset failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border border-line">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-brand-50/60 px-3 py-2">
        <span className="font-mono text-[11px] font-bold text-ink">{bandName}</span>
        {table.bands.some((b) => b.descending) && (
          <span
            className="chip bg-white text-[10px] text-ink-muted"
            title="Stored highest-first because higher values are healthier for this quantity."
          >
            descending
          </span>
        )}
        {table.overridden && (
          <span
            className="chip bg-amber-50 text-[10px] text-amber-800"
            title={`Edited by ${table.updatedBy} on ${String(table.updatedAt).slice(0, 19)}${
              table.note ? ` — ${table.note}` : ''
            }`}
          >
            edited
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {!editing ? (
            <>
              <button
                onClick={() => setEditing(true)}
                className="rounded px-2 py-0.5 text-[11px] font-semibold text-brand-700 hover:bg-white"
              >
                Edit
              </button>
              {table.overridden && (
                <button
                  onClick={reset}
                  disabled={busy}
                  title="Discard the override and go back to the source configuration"
                  className="rounded px-2 py-0.5 text-[11px] font-semibold text-ink-muted hover:bg-white"
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
                  setRows(table.bands)
                  setError(null)
                }}
                className="rounded px-2 py-0.5 text-[11px] font-semibold text-ink-muted hover:bg-white"
              >
                <X className="h-3 w-3" />
              </button>
            </>
          )}
        </div>
      </div>

      {error && (
        <p className="border-b border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-800">
          {error}
        </p>
      )}

      <table className="w-full">
        <thead>
          <tr>
            <th className="px-3 py-1 text-left text-[10px] font-semibold uppercase text-ink-faint">
              From
            </th>
            <th className="px-3 py-1 text-left text-[10px] font-semibold uppercase text-ink-faint">
              To
            </th>
            <th className="px-3 py-1 text-right text-[10px] font-semibold uppercase text-ink-faint">
              Score
            </th>
            {editing && <th className="w-8"></th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((b, i) => {
            const tone = scoreTone(b.score)
            return (
              <tr key={i} className="border-b border-line/60 last:border-0">
                {editing ? (
                  <>
                    <td className="px-2 py-1">
                      <input
                        className="input num !py-0.5 !text-[11px]"
                        type="number"
                        step="any"
                        value={b.rangeFrom}
                        onChange={(e) => update(i, 'rangeFrom', e.target.value)}
                      />
                    </td>
                    <td className="px-2 py-1">
                      <input
                        className="input num !py-0.5 !text-[11px]"
                        type="number"
                        step="any"
                        value={b.rangeTo}
                        onChange={(e) => update(i, 'rangeTo', e.target.value)}
                      />
                    </td>
                    <td className="px-2 py-1">
                      <input
                        className="input num !py-0.5 !text-right !text-[11px]"
                        type="number"
                        step="any"
                        value={b.score}
                        onChange={(e) => update(i, 'score', e.target.value)}
                      />
                    </td>
                    <td className="px-1 py-1">
                      <button
                        onClick={() => removeRow(i)}
                        className="text-ink-faint hover:text-red-600"
                        aria-label="Remove band"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </>
                ) : (
                  <>
                    <td className="num px-3 py-1.5 text-[11px] text-ink-soft">{b.rangeFrom}</td>
                    <td className="num px-3 py-1.5 text-[11px] text-ink-soft">{b.rangeTo}</td>
                    <td className="px-3 py-1.5 text-right">
                      <span
                        className="num chip text-[11px]"
                        style={{ background: tone.bg, color: tone.fg }}
                      >
                        {b.score}
                      </span>
                    </td>
                  </>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>

      {editing && (
        <div className="border-t border-line px-3 py-2">
          <button
            onClick={addRow}
            className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-700 hover:underline"
          >
            <Plus className="h-3 w-3" />
            Add band
          </button>
          <input
            className="input mt-2 !py-1 !text-[11px]"
            placeholder="Why is this changing? (kept in the change log)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
      )}

      {!editing && table.overridden && table.updatedBy && (
        <p className="border-t border-line px-3 py-1.5 text-[10px] text-ink-faint">
          {table.updatedBy} · {String(table.updatedAt).slice(0, 16).replace('T', ' ')}
          {table.note ? ` · ${table.note}` : ''}
        </p>
      )}
    </div>
  )
}
