import type { RouteItem } from '@blueskyproject/finch'
import { Atom, SlidersHorizontal, Table } from '@phosphor-icons/react'
import { useAuth } from './contexts/AuthContext'
import { ClientFinchBridge } from './components/ClientFinchBridge'
import IosScan from './pages/IosScan'
import ScanSettings from './pages/ScanSettings'
import PresetsAdmin from './pages/PresetsAdmin'

function App() {
  const auth = useAuth()

  if (auth.isAuthFailed()) {
    return (
      <div className="p-8 text-center">
        <h1 className="text-2xl font-semibold text-gray-900">Authentication Required</h1>
        <p className="mt-2 text-gray-600">This application requires a recognized Entra ID role.</p>
      </div>
    )
  }

  if (auth.isForbidden()) {
    return (
      <div className="p-8 text-center">
        <h1 className="text-2xl font-semibold text-gray-900">Access Denied</h1>
        <p className="mt-2 text-gray-600">You do not have permission to access this part of the application.</p>
      </div>
    )
  }

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
      path: '/presets-admin',
      label: 'Presets Admin',
      element: <PresetsAdmin />,
      icon: <Table size={28} />,
      isBackgroundTransparent: false,
    },
  ]

  // Filter routes based on user permissions
  const routes = allRoutes.filter((route) => {
    // Presets admin is only for admins
    if (route.path === '/presets-admin') {
      return auth.canAccessPresetsAdmin()
    }
    // All other routes are accessible to recognized users
    return auth.isAuthenticated()
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
