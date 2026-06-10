import { useState } from 'react'
import { ElementPicker, type ElementData } from '../components/ElementPicker'
import { hasPresets } from '../api/edgeMapping'
import ScanConfig from './ScanConfig'

export default function IosScan() {
  const [selectedElement, setSelectedElement] = useState<ElementData | null>(null)

  if (selectedElement) {
    return (
      <ScanConfig
        element={selectedElement}
        onBack={() => setSelectedElement(null)}
      />
    )
  }

  return (
    <ElementPicker
      onSelect={setSelectedElement}
      highlightSymbols={hasPresets}
    />
  )
}
