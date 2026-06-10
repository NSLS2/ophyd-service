import { useState } from 'react'
import type { ElementData } from '../components/ElementPicker'
import { useFullPreset, type EdgeFullPreset, type ScanPresetEntry } from '../api/presets'
import { getEdgesForElement } from '../api/edgeMapping'
import { ScanParameters } from '../components/ScanParameters'
import './ScanConfig.css'

interface ScanConfigProps {
  element: ElementData
  onBack: () => void
}

export default function ScanConfig({ element, onBack }: ScanConfigProps) {
  const edges = getEdgesForElement(element.symbol)
  const [selectedEdge, setSelectedEdge] = useState(edges[0] ?? '')
  const { data, isLoading, isError, error } = useFullPreset(selectedEdge)

  return (
    <div className="scan-config">
      <header className="scan-config__header">
        <button className="scan-config__back" onClick={onBack}>
          ← Back to periodic table
        </button>
        <h1 className="scan-config__title">
          <span
            className="scan-config__element-badge"
            style={{ backgroundColor: `var(--ep-${element.category})` }}
          >
            {element.symbol}
          </span>
          {element.name} — Scan Configuration
        </h1>
      </header>

      {edges.length === 0 && (
        <div className="scan-config__empty">
          No presets configured for {element.name}. Contact beamline staff to add edge presets.
        </div>
      )}

      {edges.length > 1 && (
        <div className="scan-config__edge-tabs">
          {edges.map((edge) => (
            <button
              key={edge}
              className={`scan-config__edge-tab ${edge === selectedEdge ? 'scan-config__edge-tab--active' : ''}`}
              onClick={() => setSelectedEdge(edge)}
            >
              {edge}
            </button>
          ))}
        </div>
      )}

      {edges.length === 1 && (
        <div className="scan-config__edge-label">Edge: {selectedEdge}</div>
      )}

      {isLoading && <div className="scan-config__status">Loading presets…</div>}
      {isError && (
        <div className="scan-config__status scan-config__status--error">
          Failed to load presets: {(error as Error).message}
        </div>
      )}

      {data && <PresetPanels data={data} />}
    </div>
  )
}

function PresetPanels({ data }: { data: EdgeFullPreset }) {
  const [scanData, setScanData] = useState<Omit<ScanPresetEntry, 'edge_index'> | null>(data.scan)

  return (
    <div className="scan-config__panels">
      {/* Scan Presets — interactive component */}
      {scanData ? (
        <ScanParameters
          data={scanData}
          onChange={(patch) => setScanData((prev) => prev ? { ...prev, ...patch } : prev)}
        />
      ) : (
        <section className="scan-config__panel">
          <h2 className="scan-config__panel-title">Scan Parameters</h2>
          <p className="scan-config__no-data">Not configured</p>
        </section>
      )}

      {/* Detector Presets */}
      <section className="scan-config__panel">
        <h2 className="scan-config__panel-title">Detector Settings</h2>
        {data.detector ? (
          <dl className="scan-config__fields">
            <Field label="Sample Gain" value={data.detector.samplegain} />
            <Field label="Sample Decade" value={data.detector.sampledecade} />
            <Field label="Au Mesh Gain" value={data.detector.aumeshgain} />
            <Field label="Au Mesh Decade" value={data.detector.aumeshdecade} />
            <Field label="PD Gain" value={data.detector.pd_gain} />
            <Field label="PD Decade" value={data.detector.pd_decade} />
            <Field label="Vortex Low" value={data.detector.vortex_low} />
            <Field label="Vortex High" value={data.detector.vortex_high} />
            <Field label="IPFY Low" value={data.detector.ipfy_low} />
            <Field label="IPFY High" value={data.detector.ipfy_high} />
            <Field label="Vortex Pos" value={data.detector.vortex_pos} />
            <Field label="Vortex Time (s)" value={data.detector.vortex_time} />
            <Field label="Scaler Time (s)" value={data.detector.sclr_time} />
          </dl>
        ) : (
          <p className="scan-config__no-data">Not configured</p>
        )}
      </section>
    </div>
  )
}

function Field({ label, value }: { label: string; value: string | number }) {
  return (
    <>
      <dt className="scan-config__field-label">{label}</dt>
      <dd className="scan-config__field-value">{value}</dd>
    </>
  )
}
