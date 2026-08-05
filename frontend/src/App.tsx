import type { RouteItem } from '@blueskyproject/finch'
import { Atom, SlidersHorizontal, Table } from '@phosphor-icons/react'
import { useAuth } from './contexts/AuthContext'
import { ClientFinchBridge } from './components/ClientFinchBridge'
import IosScan from './pages/IosScan'
import ScanSettings from './pages/ScanSettings'
import PresetsAdmin from './pages/PresetsAdmin'

function App() {
  const auth = useAuth()

  const allRoutes: RouteItem[] = [
    {
      path: '/',
      label: 'IOS Scan',
      element: <IosScan />,
      icon: <Atom size={28} />,
      isBackgroundTransparent: false,
    },
    {
      path: '/settings',
      label: 'Component Testing',
      element: <ScanSettings />,
      icon: <SlidersHorizontal size={28} />,
      isBackgroundTransparent: false,
    },
    {
      path: '/admin/presets',
      label: 'Presets Admin',
      element: <PresetsAdmin />,
      icon: <Table size={28} />,
      isBackgroundTransparent: false,
    },
  ]

  // Filter routes based on user scopes
  const routes = allRoutes.filter((route) => {
    const isAdminRoute = route.path === '/admin' || route.path.startsWith('/admin/')
    return isAdminRoute ? auth.hasScope('admin:read') : auth.isAuthenticated()
  })

  return (
    <ClientFinchBridge
      routes={routes}
      headerTitle="IOS Scan"
      config={{
        ophydApiUrl: import.meta.env.VITE_API_URL || 'http://localhost:8003/api/v1',
      }}
      fallback={<div className="p-4 text-gray-500">Loading interface...</div>}
    />
  )
}

export default App
