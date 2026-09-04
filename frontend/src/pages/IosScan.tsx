import { ElementPicker } from '../components/ElementPicker'
import { hasPresets } from '../api/edgeMapping'
import ScanConfig from './ScanConfig'
import { useIosScanSession } from '../contexts/IosScanSessionContext'

export default function IosScan() {
  const session = useIosScanSession()

  if (session.selectedElement) {
    return (
      <ScanConfig
        element={session.selectedElement}
        onBack={() => session.clear()}
      />
    )
  }

  return (
    <ElementPicker
      onSelect={(el) => session.setSelectedElement(el)}
      highlightSymbols={hasPresets}
    />
  )
}
