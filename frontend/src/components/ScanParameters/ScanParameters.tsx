import { useState } from 'react'
import type { ScanPresetEntry } from '../../api/presets'
import { NumberInput } from '../NumberInput'
import './ScanParameters.css'

export interface ScanParametersProps {
  data: Omit<ScanPresetEntry, 'edge_index'>
  onChange: (updated: Partial<Omit<ScanPresetEntry, 'edge_index'>>) => void
}

export function ScanParameters({ data, onChange }: ScanParametersProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const field = (key: keyof Omit<ScanPresetEntry, 'edge_index'>, label: string) => (
    <NumberInput
      key={key}
      label={label}
      value={data[key] as number}
      onChange={(v) => onChange({ [key]: v })}
    />
  )

  return (
    <section className="scan-parameters">
      <div className="scan-parameters__header">Scan Parameters</div>
      <div className="scan-parameters__body">
        <div className="scan-parameters__fields">
          {field('start', 'start')}
          {field('stop', 'stop')}
          {field('velocity', 'velocity')}
          {field('deadband', 'deadband')}
          {field('epu1offset', 'epu1offset')}
          {field('scan_count', 'scan count')}
          {field('e_align', 'e align')}
          {field('m1b1_sp', 'm1b1 sp')}
        </div>

        <button
          className={`scan-parameters__advanced-toggle ${advancedOpen ? 'scan-parameters__advanced-toggle--open' : ''}`}
          onClick={() => setAdvancedOpen(!advancedOpen)}
        >
          Advanced Settings
          <span className="scan-parameters__chevron">{advancedOpen ? '▲' : '▼'}</span>
        </button>

        {advancedOpen && (
          <div className="scan-parameters__advanced-fields">
            {field('epu_table', 'epu table')}
            {field('intervals', 'intervals')}
            {field('au_mesh', 'au mesh')}
          </div>
        )}
      </div>
    </section>
  )
}
