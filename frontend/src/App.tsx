import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import AssetDetail from './pages/AssetDetail'
import AssetRegister from './pages/AssetRegister'
import Availability from './pages/Availability'
import Configuration from './pages/Configuration'
import Dashboard from './pages/Dashboard'
import DgaExplorer from './pages/DgaExplorer'
import DgaStatus from './pages/DgaStatus'
import DuvalDiagnosis from './pages/DuvalDiagnosis'
import HealthIndex from './pages/HealthIndex'
import HistoryView from './pages/HistoryView'
import ManualCalculation from './pages/ManualCalculation'
import TrendAnalysis from './pages/TrendAnalysis'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="health-index" element={<HealthIndex />} />
        {/* Asset numbers contain slashes, so these routes take a wildcard. The
            manual route is declared first so it is not swallowed by the detail one. */}
        <Route path="manual-calculation/*" element={<ManualCalculation />} />
        <Route path="health-index/*" element={<AssetDetail />} />
        <Route path="trend-analysis" element={<TrendAnalysis />} />
        <Route path="duval" element={<DuvalDiagnosis />} />
        <Route path="dga-explorer" element={<DgaExplorer />} />
        <Route path="dga-status" element={<DgaStatus />} />
        <Route path="assets" element={<AssetRegister />} />
        <Route path="availability" element={<Availability />} />
        <Route path="history" element={<HistoryView />} />
        <Route path="configuration" element={<Configuration />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
