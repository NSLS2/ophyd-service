import { HubAppLayout, RouteItem } from '@blueskyproject/finch'
import { Atom } from '@phosphor-icons/react'
import IosScan from './pages/IosScan'

function App() {
  const routes: RouteItem[] = [
    {
      path: '/',
      label: 'IOS Scan',
      element: <IosScan />,
      icon: <Atom size={28} />,
      isBackgroundTransparent: true,
    },
  ]

  return (
    <HubAppLayout
      routes={routes}
      headerTitle="IOS Scan"
    />
  )
}

export default App
