export interface Asset {
  assetNumber: string
  /** Scoring type — selects weights and bands. All transformers share 'TR'. */
  assetType: string
  /** Reporting group — TR | AET | OLTC | CTVT | CB | ESDS | SA | OTHER. */
  category: string
  subType: string
  label: string
  site: string
  bay: string
  phase: string
  isOltc: boolean
  sources: string[]
}

export interface AssetCounts {
  total: number
  /** Power and inter-bus units only — earthing and OLTC are counted separately. */
  transformers: number
  earthingTransformers: number
  oltc: number
  transformersAll: number
  ct: number
  vt: number
  ctvt: number
  surgeArresters: number
  circuitBreakers: number
  esds: number
  capacitorBanks: number
  batteryBanks: number
  other: number
  sites: number
  byType: Record<string, number>
  byCategory: Record<string, number>
}

export interface HIBand {
  key: string
  label: string
  min: number
  max: number
  color: string
  bg: string
}

export interface ConfigAudit {
  assetType: string
  status: string
  trustworthy: boolean
  message: string
  issues: { band: string; status: string; reason: string }[]
  bandsExpected: number
  bandsWithIssues: number
}

export interface HIRow {
  asset: string
  assetType: string
  category?: string
  assetTypeLabel: string
  site: string
  healthIndex: number | null
  bandKey: string | null
  bandLabel: string | null
  bandColor: string | null
  bandBg: string | null
  componentsUsed: number
  componentsTotal: number
  coverage: number
  configTrusted: boolean
  configStatus: string | null
}

export interface Candidate {
  label: string
  value: number
  date: string | null
  source: string | null
  /** True for the measurement that was actually scored. Always false when
   *  `mode` is 'blend', where every candidate contributes instead. */
  used: boolean
  reason: string
}

export interface HIComponent {
  code: string
  label: string
  unit: string | null
  manual: boolean
  bandName: string | null
  value: number | null
  score: number | null
  date: string | null
  source: string | null
  available: boolean
  selected: boolean
  weight: number
  configuredWeight: number
  contribution: number | null
  detail: Record<string, any>
  candidates: Candidate[]
  rule: string
  mode: 'single' | 'pick' | 'blend'
}

export interface HIDetail {
  asset: string
  assetType: string
  assetTypeLabel: string
  site: string
  healthIndex: number | null
  band: HIBand | null
  components: HIComponent[]
  componentsUsed: number
  componentsTotal: number
  missingComponents: string[]
  deselectedComponents?: string[]
  manualAge?: number | null
  coverage: number
  message: string
  configAudit?: ConfigAudit
  storedHistory?: StoredHI[]
}

export interface StoredHI {
  id: number
  asset: string
  testDate: string
  healthIndex: number | null
  description: string | null
  bandLabel: string | null
  bandColor: string | null
  bandBg: string | null
  breakdown: { code: string; label: string; score: number | null; weight: number | null; contribution: number | null }[] | null
}

/**
 * The hierarchy scope echoed back by a listing endpoint.
 *
 * The label cannot be derived from the URL alone, so the server resolves it —
 * that is what lets a pasted `?node=` link name its scope on first paint.
 */
export interface ScopeEcho {
  node: string
  label: string | null
}

export interface DashboardData {
  counts: AssetCounts
  configAudit: Record<string, ConfigAudit>
  untrustedCount: number
  distribution: { key: string; label: string; color: string; bg: string; count: number }[]
  rows: HIRow[]
  rowsTotal?: number
  worst: HIRow[]
  scoredCount: number
  evaluated: number
  averageHealthIndex: number | null
  bands: HIBand[]
  dateFrom?: string
  dateTo?: string
  /** Where these figures came from: the nightly job, or a live sweep. */
  source?: 'snapshot' | 'live'
  snapshot?: import('./components/SnapshotBar').SnapshotStatus
  computedAt?: string
  /** Asset type the health figures are scoped to; null means the whole fleet. */
  assetType?: string | null
  availableTypes?: import('./components/AssetTypeFilter').AvailableType[]
  scope?: ScopeEcho | null
}

export interface GasTrendRow {
  sampleNo: number
  date: string
  daysFromFirst: number
  periodDays: number | null
  value: number
  difference: number | null
  table3Limit: number
  rate: number | null
  table4Limit: number | null
  score1: number | null
  score2: number | null
}

export interface GasTrend {
  gas: string
  weight: number
  subScore: number | null
  score1: number | null
  score2: number | null
  latest: number | null
  previous: number | null
  difference: number | null
  rate: number | null
  table3Limit: number
  table4Limit: number | null
  note: string
  rows: GasTrendRow[]
}

export interface AssetTrend {
  asset: string
  trend: number | null
  condition: string
  conditionColor: string
  samples: number
  firstSample: string | null
  latestSample: string | null
  denominator: number
  excludedGases: string[]
  message: string
  gases: GasTrend[]
}

/* --------------------------------------------------------------------------
 * DGA status - IEEE C57.104-2019
 *
 * A different question from `AssetTrend` above: the trend gives the health
 * index a 0-1 number, this puts the unit in Status 1/2/3 against the standard's
 * population tables. `null` limits are real - the source scan left one Table 3
 * cell illegible, and that comparison is skipped rather than guessed.
 * ------------------------------------------------------------------------ */

/** `"ANY_INCREASE"` is the C2H2 sentinel: any positive change counts. */
export type DgaLimit = number | 'ANY_INCREASE' | null

export interface DgaStatusGas {
  gas: string
  measured: boolean
  latest: number | null
  latestDate: string | null
  previous: number | null
  previousDate: string | null
  delta: number | null
  rate: number | null
  ratePoints: number
  rateSpanDays: number | null
  t1: number | null
  t1Verify: boolean
  t2: number | null
  t2Verify: boolean
  t3: DgaLimit
  t3Verify: boolean
  t4: DgaLimit
  t4Verify: boolean
  exceedsT1: boolean
  /** Exactly on the Table 1 level - not below it, so not Status 1. */
  atT1: boolean
  exceedsT2: boolean
  exceedsT3: boolean
  exceedsT4: boolean
  note: string
}

export interface DgaStatusTrigger {
  gas: string
  kind: 'level>T2' | 'level>T1' | 'level=T1' | 'delta>T3' | 'rate>T4'
  value: number | null
  limit: DgaLimit
  /** 3 = pushes the unit to Status 3, 2 = to Status 2. Sorted worst first. */
  severity: number
  verify: boolean
  text: string
}

export interface DgaStatusTraceStep {
  step: string
  question: string
  answer: string
  pass: boolean
  detail: string
}

export interface DgaStatusResult {
  asset: string
  /** null when there is nothing on record to classify. */
  status: 1 | 2 | 3 | null
  statusLabel: string
  verdict: string
  color: string
  bg: string
  action: string
  reason: string
  ratioBand: string | null
  ageBand: string | null
  periodBand: string | null
  ageYears: number | null
  o2n2: number | null
  ratesAvailable: boolean
  assumptions: string[]
  triggeredBy: DgaStatusTrigger[]
  gases: DgaStatusGas[]
  measuredGases: string[]
  /** Levels are all below Table 1 but a delta tripped - re-sample within a month. */
  pendingConfirmation: boolean
  confirmation: { required: boolean; reason: string; dueWithin: string; fromSample: string } | null
  extreme: { gas: string; kind: string; text: string }[]
  deEscalationCandidate: boolean
  samples: number
  firstSample: string | null
  latestSample: string | null
  rateWindow: { points: number; from: string; to: string; spanDays: number; spanMonths: number } | null
  decisionTrace: DgaStatusTraceStep[]
  verifyCells: { gas: string; table: string; limit: string }[]
  ageSource?: {
    manufactureYear: number | null
    label: string | null
    source: string | null
    inheritedFrom: string | null
  } | null
  standard: string
}

/** One hand-entered sample row. A blank gas means "not measured", never zero. */
export interface DgaManualSample {
  date: string
  H2: string
  CH4: string
  C2H6: string
  C2H4: string
  C2H2: string
  CO: string
  CO2: string
  O2: string
  N2: string
}

export interface DgaStatusReport {
  generatedAt: string
  asset: string
  /** CMMS description of the unit, e.g. 'Three Phase Power Transformer 02'. */
  assetName?: string | null
  /** CMMS name of the substation, e.g. 'Kerawalapitiya GSS'. */
  siteName?: string | null
  /** The substation's code, the first segment of the asset number. */
  siteCode?: string | null
  /** 'stored' = read from CEB_DGA_DATA, 'manual' = classified from typed-in values. */
  source?: 'stored' | 'manual'
  status: DgaStatusResult
  sampleTable: Record<string, number | string | null>[]
  limitsUsed: {
    table1: Record<string, number | null>
    table2: Record<string, number | null>
    table3: Record<string, DgaLimit>
    table4: Record<string, DgaLimit> | null
    columns: { ratioBand: string; ageBand: string; periodBand: string | null }
  } | null
  recommendations: string[]
  caveats: string[]
  standard: string
}

export interface DgaFleetStatusRow {
  asset: string
  status: 1 | 2 | 3 | null
  statusLabel: string
  verdict: string
  color: string
  bg: string
  ratioBand: string | null
  ageBand: string | null
  ageYears: number | null
  ratesAvailable: boolean
  samples: number
  latestSample: string | null
  triggers: number
  topTrigger: string | null
  pendingConfirmation: boolean
  extreme: number
}

/** Whether a fleet sweep could put ages on its rows — see `age_source()`. */
export type DgaAgeSource = 'cmms-map' | 'unavailable'

export interface DgaStatusSummary {
  status1: number
  status2: number
  status3: number
  unclassified: number
  total: number
  pendingConfirmation: number
  extreme: number
}

export interface DgaLimitCell {
  limit: DgaLimit
  verify: boolean
}

export interface DgaLimitTables {
  gases: string[]
  ratioBands: string[]
  ageBands: string[]
  periodBands: string[]
  table1: Record<string, Record<string, Record<string, DgaLimitCell>>>
  table2: Record<string, Record<string, Record<string, DgaLimitCell>>>
  table3: Record<string, Record<string, DgaLimitCell>>
  table4: Record<string, Record<string, Record<string, DgaLimitCell>>>
  anyIncrease: string
  source: string
}

export interface PentagonZone {
  zone: string
  meaning: string
  color: string
  points: number[][]
  labelX: number
  labelY: number
  labelSize: number
}

export interface PentagonGeometry {
  radius: number
  gasOrder: string[]
  vertices: { gas: string; label: string; x: number; y: number; labelX: number; labelY: number; anchor: string; baseline: string }[]
  viewBox: { xMin: number; xMax: number; yMin: number; yMax: number }
  pentagon1: { title: string; subtitle: string; zones: PentagonZone[] }
  pentagon2: { title: string; subtitle: string; zones: PentagonZone[] }
  zoneMeanings: Record<string, string>
}

export interface TriangleGeometry {
  id: string
  title: string
  subtitle: string
  gases: string[]
  axisLabels: string[]
  provisional: boolean
  zones: { zone: string; meaning: string; color: string; points: number[][]; labelX: number; labelY: number }[]
  outline: number[][]
}

export interface PentagonResult {
  asset: string | null
  sampleDate: string | null
  valid: boolean
  reason?: string
  gases?: Record<string, number>
  percentages: Record<string, number> | null
  points: { gas: string; x: number; y: number; percent: number }[] | null
  centroid: { x: number; y: number } | null
  pentagon1: { zone: string | null; meaning: string; color: string } | null
  pentagon2: { zone: string | null; meaning: string; color: string } | null
}

export interface TriangleResult {
  id: string
  title: string
  subtitle?: string
  provisional: boolean
  valid: boolean
  reason?: string
  gases?: string[]
  percentages: Record<string, number> | null
  point: { x: number; y: number } | null
  zone: string | null
  meaning?: string
  color?: string
  ladderZone?: string
  ladderAgrees?: boolean
}

export interface DuvalAnalysis {
  asset: string | null
  sampleDate: string | null
  gases: Record<string, number>
  pentagon: PentagonResult
  triangles: Record<string, TriangleResult>
  ieee: {
    status: number
    label: string
    color: string
    action: string
    columnLabel: string
    o2n2Ratio: number | null
    gases: {
      gas: string; value: number; table1: number; table2: number; table3: number
      table4: number; delta: number | null; rate: number | null
      aboveTable1: boolean; aboveTable2: boolean; aboveTable3: boolean
      aboveTable4: boolean; severity: number
    }[]
  }
  rogers: { R1: number; R2: number; R3: number; case: number | null; diagnosis: string; identified: boolean }
  keyGas: { dominant: string | null; interpretation: string; shares: { gas: string; value: number; percent: number }[]; totalCombustible?: number }
  paper: { co: number; co2: number; co2CoRatio: number | null; notes: string[] }
  caveats: string[]
  assetType?: string
  ai: {
    available: boolean
    /** False when the asset is not a transformer — the model does not apply. */
    applicable?: boolean
    fault: string
    confidence: number
    flag?: { level: string; color: string; text: string }
    probabilities: Record<string, number>
    reason?: string
  }
  agreement: { match: boolean; message: string } | null
  disclaimer: string
}

export interface AvailabilityTest {
  testId: string
  name: string
  table: string
  available: boolean
  records: number
  lastTested: string | null
}

/** One browsable test in the history catalogue. `kind` decides where its rows
 *  come from: a CEB_* table keyed on the asset, or the Omicron job path. */
export interface HistoryTest {
  testId: string
  name: string
  table: string
  dateColumn: string
  kind: 'table' | 'omicron'
  omicronName?: string
  available?: boolean
  records?: number
  lastTested?: string | null
}

export interface HistoryColumn {
  name: string
  type: string
  numeric: boolean
  date: boolean
}

export interface HistoryRecords {
  asset: string
  test: HistoryTest
  columns: HistoryColumn[]
  rows: Record<string, unknown>[]
  dateColumn?: string
  limit: number
  /** The row cap was reached, so older records exist beyond this page. */
  truncated: boolean
  message?: string
}

/**
 * One node of the asset hierarchy (see ASSET_HIERARCHY_INTEGRATION.md).
 *
 * `assetNo` is a materialised path, so a node's subtree is itself plus every
 * asset number prefixed by it — that is what a scope filter matches on.
 */
export interface HierarchyNode {
  assetNo: string
  parentId: string | null
  /** The last path segment, e.g. 'MT01_X'. */
  code: string
  /** Human name — `ast_mst_asset_shortdesc` when available, synthesised otherwise. */
  label: string
  /** True when `label` is the CMMS description rather than a derived name. */
  named?: boolean
  kind: 'site' | 'discipline' | 'voltage' | 'bay' | 'equipment' | 'oltc' | 'unit' | 'unassigned'
  depth: number
  /** Root-first breadcrumb of labels. */
  path: string
  /** HI assets in this subtree, inclusive. */
  assetCount: number
  categories: string[]
  isAsset: boolean
  childCount: number
  assetType?: string
  category?: string
  /** CMMS status code — 'ISF' etc. Null while no status feed exists. */
  status?: string | null
}

/** Outcome of the in-service status filter (see doc 9.10 / 14). */
export interface HierarchyStatus {
  /** Status codes admitted to the tree — ['ISF'] by default. */
  keep: string[]
  kept: number
  excluded: number
  /** Assets the status feed says nothing about. */
  unknown: number
  /** False while nothing feeds a status through — the filter is inert. */
  available: boolean
  keepUnknown: boolean
}

export interface HierarchyLevel {
  parent: string | null
  items: HierarchyNode[]
  /**
   * Where the names came from: 'cmms' reads `ast_mst` live, 'staging' the local
   * `Tomms_CEBT` copy, 'derived' means no CMMS text was available at all.
   */
  source: 'cmms' | 'staging' | 'derived'
  nodes: number
  assets: number
  roots: number
  /** Nodes whose name is the CMMS short description. */
  named: number
  maxDepth: number
  status: HierarchyStatus
}
