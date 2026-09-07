import { Beaker, Plus, RotateCcw, Trash2, Wand2 } from 'lucide-react'
import { useState } from 'react'
import type { DgaManualSample } from '../types'

/** The seven status gases plus the two the O2/N2 section is chosen from. */
const GAS_COLS: { key: keyof DgaManualSample; label: string; hint: string }[] = [
  { key: 'H2', label: 'H₂', hint: 'Hydrogen' },
  { key: 'CH4', label: 'CH₄', hint: 'Methane' },
  { key: 'C2H6', label: 'C₂H₆', hint: 'Ethane' },
  { key: 'C2H4', label: 'C₂H₄', hint: 'Ethylene' },
  { key: 'C2H2', label: 'C₂H₂', hint: 'Acetylene' },
  { key: 'CO', label: 'CO', hint: 'Carbon monoxide' },
  { key: 'CO2', label: 'CO₂', hint: 'Carbon dioxide' },
  { key: 'O2', label: 'O₂', hint: 'Oxygen — with N₂, selects the limit section' },
  { key: 'N2', label: 'N₂', hint: 'Nitrogen — with O₂, selects the limit section' },
]

export function emptySample(date = ''): DgaManualSample {
  return {
    date, H2: '', CH4: '', C2H6: '', C2H4: '', C2H2: '', CO: '', CO2: '', O2: '', N2: '',
  }
}

/** Two rows is the common once-or-twice-a-year case, and the minimum for a delta. */
export function initialSamples(): DgaManualSample[] {
  return [emptySample(), emptySample()]
}

/**
 * The section 8 known-answer vector, so the port can be checked from the UI.
 *
 * Not decoration: the spec ships this vector precisely so an implementation can
 * be validated, and an engineer who doubts the screen can load it and confirm
 * the expected Status 3 before trusting the classifier with a real unit.
 */
const TEST_VECTOR: { label: string; age: string; rows: DgaManualSample[] } = {
  label: 'Biyagama IBT 02 (R) — spec test vector',
  age: '43',
  rows: [
    { ...emptySample('2024-01-15'), H2: '87', CH4: '0', C2H4: '2', C2H6: '0', C2H2: '1' },
    { ...emptySample('2024-07-15'), H2: '125', CH4: '5', C2H4: '3', C2H6: '0', C2H2: '2' },
  ],
}

/**
 * Hand-entry grid for a DGA status assessment.
 *
 * The rules that matter to the standard are enforced in the UI as well as the
 * backend, because getting them wrong changes the answer silently: a blank cell
 * means "not measured" and is skipped in every comparison, whereas a typed 0 is
 * a real reading that takes part in the delta. The column header says so, and
 * the placeholder is a dash rather than a zero.
 */
export default function DgaManualEntry({
  samples,
  onChange,
  ageYears,
  onAgeChange,
  label,
  onLabelChange,
  onRun,
  onReset,
  busy,
}: {
  samples: DgaManualSample[]
  onChange: (next: DgaManualSample[]) => void
  ageYears: string
  onAgeChange: (v: string) => void
  label: string
  onLabelChange: (v: string) => void
  onRun: () => void
  onReset: () => void
  busy: boolean
}) {
  const [hint, setHint] = useState<string | null>(null)

  function setCell(i: number, key: keyof DgaManualSample, value: string) {
    onChange(samples.map((s, n) => (n === i ? { ...s, [key]: value } : s)))
  }

  function addRow() {
    onChange([...samples, emptySample()])
  }

  function removeRow(i: number) {
    // Always leave one row standing — an empty grid has nothing to type into.
    onChange(samples.length > 1 ? samples.filter((_, n) => n !== i) : [emptySample()])
  }

  function loadVector() {
    onChange(TEST_VECTOR.rows.map((r) => ({ ...r })))
    onAgeChange(TEST_VECTOR.age)
    onLabelChange(TEST_VECTOR.label)
    setHint('Loaded the spec test vector — this must classify as Status 3 on H₂ 125 ppm above the Table 2 limit of 90.')
  }

  // Rows are ordered by the user, but the standard reads them oldest-first, so
  // show which row the delta will actually come from rather than assuming the
  // last row typed is the newest.
  const dated = samples
    .map((s, i) => ({ i, date: s.date }))
    .filter((r) => r.date)
    .sort((a, b) => a.date.localeCompare(b.date))
  const newest = dated.length ? dated[dated.length - 1].i : -1

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-head !py-3">
          <Beaker className="h-4 w-4 text-brand-600" />
          <h2 className="text-sm font-bold text-ink">Enter dissolved-gas results</h2>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <button className="btn-ghost !py-1.5 text-xs" onClick={loadVector} type="button">
              <Wand2 className="h-3.5 w-3.5" /> Load test vector
            </button>
            <button className="btn-ghost !py-1.5 text-xs" onClick={onReset} type="button">
              <RotateCcw className="h-3.5 w-3.5" /> Clear
            </button>
          </div>
        </div>

        <div className="card-pad space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label className="label">Label for the report</label>
              <input
                className="input text-xs"
                placeholder="e.g. Biyagama IBT 02 — certificate 4471"
                value={label}
                onChange={(e) => onLabelChange(e.target.value)}
              />
            </div>
            <div>
              <label className="label">Transformer age (years)</label>
              <input
                className="input num text-xs"
                type="number"
                min={0}
                max={120}
                placeholder="blank = unknown"
                value={ageYears}
                onChange={(e) => onAgeChange(e.target.value)}
              />
            </div>
            <p className="self-end pb-1 text-[11px] leading-relaxed text-ink-muted">
              Age picks the column of Tables 1 and 2 (≤9, 10–30, &gt;30). Leaving it blank uses the
              Unknown column, which is not the same limits.
            </p>
          </div>

          <div className="scroll-x">
            <table className="w-full min-w-[860px] border-collapse">
              <thead>
                <tr>
                  <th className="th w-8"></th>
                  <th className="th">Date sampled</th>
                  {GAS_COLS.map((g) => (
                    <th key={g.key} className="th text-right" title={g.hint}>
                      {g.label}
                    </th>
                  ))}
                  <th className="th w-10"></th>
                </tr>
              </thead>
              <tbody>
                {samples.map((s, i) => (
                  <tr key={i} className={i === newest ? 'bg-brand-50/50' : undefined}>
                    <td className="td text-[10px] text-ink-faint">
                      {i === newest && dated.length > 1 ? (
                        <span className="chip bg-brand-100 text-[9px] text-brand-800">latest</span>
                      ) : (
                        i + 1
                      )}
                    </td>
                    <td className="td">
                      <input
                        className="input num !py-1 text-xs"
                        type="date"
                        value={s.date}
                        onChange={(e) => setCell(i, 'date', e.target.value)}
                      />
                    </td>
                    {GAS_COLS.map((g) => (
                      <td key={g.key} className="td">
                        <input
                          className="input num !w-20 !py-1 text-right text-xs"
                          type="number"
                          min={0}
                          step="any"
                          placeholder="—"
                          value={s[g.key]}
                          onChange={(e) => setCell(i, g.key, e.target.value)}
                        />
                      </td>
                    ))}
                    <td className="td">
                      <button
                        className="rounded p-1.5 text-ink-faint hover:bg-red-50 hover:text-red-600"
                        onClick={() => removeRow(i)}
                        title="Remove this sample"
                        aria-label={`Remove sample ${i + 1}`}
                        type="button"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-ghost !py-1.5 text-xs" onClick={addRow} type="button">
              <Plus className="h-3.5 w-3.5" /> Add sample
            </button>
            <p className="text-[11px] text-ink-muted">
              A blank cell means <span className="font-semibold">not measured</span> and is skipped in
              every comparison. A typed <span className="num font-semibold">0</span> is a real reading
              that counts towards the change since the previous sample.
            </p>
          </div>

          <div className="rounded-lg bg-brand-50 p-3 text-[11px] leading-relaxed text-ink-soft">
            <span className="font-semibold">How many samples to enter — </span>
            one gives levels only. Two gives the change against Table 3. Three or more spanning four
            months or more also gives the least-squares rate against Table 4, which is the part of
            the guide that catches slow, steady gassing. The rate is fitted over the newest six
            samples, discarding any that would stretch the window past two years.
          </div>

          {hint && (
            <p className="rounded-lg bg-amber-50 p-2.5 text-[11px] text-amber-800">{hint}</p>
          )}

          <div className="flex justify-end">
            <button
              className="btn-primary text-sm"
              onClick={onRun}
              disabled={busy}
              type="button"
            >
              <Beaker className="h-4 w-4" />
              {busy ? 'Classifying…' : 'Run classification'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
