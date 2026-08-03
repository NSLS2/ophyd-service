<<<<<<< HEAD
import type { RouteItem } from '@blueskyproject/finch'
import { Atom, SlidersHorizontal, Table } from '@phosphor-icons/react'
import { useAuth } from './contexts/AuthContext'
import { ClientFinchBridge } from './components/ClientFinchBridge'
=======
import { HubAppLayout, RouteItem } from '@blueskyproject/finch'
import { Atom, SlidersHorizontal, Table, Database } from '@phosphor-icons/react'
>>>>>>> ab20eea (Add scan data and fix the app dimensions)
import IosScan from './pages/IosScan'
import ScanSettings from './pages/ScanSettings'
import PresetsAdmin from './pages/PresetsAdmin'
import TiledViewer from './pages/TiledViewer'

function App() {
  const auth = useAuth()

  const allRoutes: RouteItem[] = [
    {
      path: '/',
      label: 'IOS Scan',
      element: <IosScan />,
      icon: <Atom size={28} />,
      isBackgroundTransparent: false,
      classNameContainer: 'w-full max-w-none !h-auto min-h-full p-0 overflow-visible',
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
      classNameContainer: 'w-full max-w-none min-h-screen p-0',
    },
    {
      path: '/data',
      label: 'Scan Data',
      element: <TiledViewer />,
      icon: <Database size={28} />,
      isBackgroundTransparent: false,
      classNameContainer: 'w-full max-w-none min-h-screen p-0',
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
