import { useState } from 'react'
import { api } from '../api'
import { saveStatusCsv } from '../lib/dgaStatusCsv'
import type { DgaManualSample, DgaStatusReport } from '../types'
import DgaManualEntry, { initialSamples } from './DgaManualEntry'
import DgaStatusReportView from './DgaStatusReport'
import { ErrorNote } from './ui'

/**
 * Assessment from hand-entered values.
 *
 * The same classifier as the stored path, and deliberately the same report
 * component: an assessment run off a test certificate has to be as auditable as
 * one run off the database, so it gets the identical evidence table, decision
 * trace and export. Only the provenance differs, and that is stated on the
 * report rather than left for the reader to infer.
 */
export default function DgaManualAssessment() {
  const [samples, setSamples] = useState<DgaManualSample[]>(initialSamples)
  const [ageYears, setAgeYears] = useState('')
  const [label, setLabel] = useState('')
  const [result, setResult] = useState<DgaStatusReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      // Blank cells are dropped here rather than sent as empty strings: the
      // backend reads "absent" as not measured, which is what a blank means.
      const payload = {
        label,
        ageYears: ageYears.trim() === '' ? null : Number(ageYears),
        samples: samples.map((s) => {
          const row: Record<string, string | number> = { date: s.date }
          for (const [k, v] of Object.entries(s)) {
            if (k !== 'date' && String(v).trim() !== '') row[k] = Number(v)
          }
          return row
        }),
      }
      const res = await api.post<DgaStatusReport>('/dga/status/manual', payload)
      setResult(res)
    } catch (err) {
      setResult(null)
      setError(err instanceof Error ? err.message : 'Could not classify these values.')
    } finally {
      setBusy(false)
    }
  }

  function reset() {
    setSamples(initialSamples())
    setAgeYears('')
    setLabel('')
    setResult(null)
    setError(null)
  }

  return (
    <div className="space-y-4">
      <DgaManualEntry
        samples={samples}
        onChange={(next) => {
          setSamples(next)
          // An edited grid no longer describes the report on screen, so the
          // stale verdict is cleared rather than left to be exported by mistake.
          setResult(null)
        }}
        ageYears={ageYears}
        onAgeChange={(v) => {
          setAgeYears(v)
          setResult(null)
        }}
        label={label}
        onLabelChange={setLabel}
        onRun={run}
        onReset={reset}
        busy={busy}
      />

      {error && <ErrorNote message={error} onRetry={run} />}

      {result && (
        <DgaStatusReportView
          report={result}
          onClose={() => setResult(null)}
          onCsv={() => saveStatusCsv(result.status)}
        />
      )}
    </div>
  )
}
