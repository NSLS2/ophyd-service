import { useState } from 'react'
import { ScanParameters } from '../components/ScanParameters'
import type { ScanPresetEntry } from '../api/presets'

const DEMO_SCAN: Omit<ScanPresetEntry, 'edge_index'> = {
  start: 1051,
  stop: 1051,
  velocity: 1051,
  deadband: 1051,
  epu1offset: 1051,
  scan_count: 1051,
  e_align: 1051,
  m1b1_sp: 1051,
  epu_table: 1051,
  intervals: 1051,
  au_mesh: 1051,
}

export default function ScanSettings() {
  const [scanData, setScanData] = useState(DEMO_SCAN)

  return (
    <div style={{ maxWidth: 520, padding: '1.5rem' }}>
      <ScanParameters
        data={scanData}
        onChange={(patch) => setScanData((prev) => ({ ...prev, ...patch }))}
      />
    </div>
  )
}
