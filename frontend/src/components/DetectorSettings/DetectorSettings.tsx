import { useState } from 'react'
import { NumberInput } from '../NumberInput'
import { SelectInput } from '../SelectInput'
import './DetectorSettings.css'

// Dummy dropdown options — replace with values from presets_service later.
const GAIN_OPTIONS = ['Low', 'Med', 'High']
const DECADE_OPTIONS = ['1e3', '1e4', '1e5', '1e6', '1e7']

interface ScalarState {
  dwellTime: number
  pd: number
  pdGain: string
  pdDecade: string
  aumesh: number
  aumeshGain: string
  aumeshDecade: string
  sample: number
  sampleGain: string
  sampleDecade: string
}

interface VortexState {
  vortexTime: number
  pfyStart: number
  pfySize: number
  pfyCounts: number
  ipfyStart: number
  ipfySize: number
  ipfyCounts: number
}

// Dummy initial values — replace with presets_service data later.
const initialScalar: ScalarState = {
  dwellTime: 1051,
  pd: 1051,
  pdGain: '',
  pdDecade: '',
  aumesh: 1051,
  aumeshGain: '',
  aumeshDecade: '',
  sample: 1051,
  sampleGain: '',
  sampleDecade: '',
}

const initialVortex: VortexState = {
  vortexTime: 1051,
  pfyStart: 620,
  pfySize: 230,
  pfyCounts: 1051,
  ipfyStart: 450,
  ipfySize: 150,
  ipfyCounts: 0,
}

export function DetectorSettings() {
  const [scalar, setScalar] = useState<ScalarState>(initialScalar)
  const [vortex, setVortex] = useState<VortexState>(initialVortex)

  const patchScalar = (patch: Partial<ScalarState>) =>
    setScalar((prev) => ({ ...prev, ...patch }))
  const patchVortex = (patch: Partial<VortexState>) =>
    setVortex((prev) => ({ ...prev, ...patch }))

  return (
    <section className="detector-settings">
      <div className="detector-settings__header">Detector Settings</div>
      <div className="detector-settings__body">
        {/* ── Scalar Settings ─────────────────────────────────── */}
        <div className="detector-settings__card">
          <div className="detector-settings__card-header">Scalar Settings</div>
          <div className="detector-settings__card-body">
            <NumberInput
              label="Dwell Time"
              value={scalar.dwellTime}
              onChange={(v) => patchScalar({ dwellTime: v })}
            />
            <NumberInput
              label="pd"
              value={scalar.pd}
              onChange={(v) => patchScalar({ pd: v })}
            />
            <div className="detector-settings__gain-row">
              <span className="detector-settings__gain-label">pd gain</span>
              <div className="detector-settings__gain-controls">
                <SelectInput
                  value={scalar.pdGain}
                  options={GAIN_OPTIONS}
                  onChange={(v) => patchScalar({ pdGain: v })}
                />
                <span className="detector-settings__gain-x">×</span>
                <SelectInput
                  value={scalar.pdDecade}
                  options={DECADE_OPTIONS}
                  onChange={(v) => patchScalar({ pdDecade: v })}
                />
              </div>
            </div>
            <NumberInput
              label="aumesh"
              value={scalar.aumesh}
              onChange={(v) => patchScalar({ aumesh: v })}
            />
            <div className="detector-settings__gain-row">
              <span className="detector-settings__gain-label">aumesh gain</span>
              <div className="detector-settings__gain-controls">
                <SelectInput
                  value={scalar.aumeshGain}
                  options={GAIN_OPTIONS}
                  onChange={(v) => patchScalar({ aumeshGain: v })}
                />
                <span className="detector-settings__gain-x">×</span>
                <SelectInput
                  value={scalar.aumeshDecade}
                  options={DECADE_OPTIONS}
                  onChange={(v) => patchScalar({ aumeshDecade: v })}
                />
              </div>
            </div>
            <NumberInput
              label="sample"
              value={scalar.sample}
              onChange={(v) => patchScalar({ sample: v })}
            />
            <div className="detector-settings__gain-row">
              <span className="detector-settings__gain-label">sample gain</span>
              <div className="detector-settings__gain-controls">
                <SelectInput
                  value={scalar.sampleGain}
                  options={GAIN_OPTIONS}
                  onChange={(v) => patchScalar({ sampleGain: v })}
                />
                <span className="detector-settings__gain-x">×</span>
                <SelectInput
                  value={scalar.sampleDecade}
                  options={DECADE_OPTIONS}
                  onChange={(v) => patchScalar({ sampleDecade: v })}
                />
              </div>
            </div>
          </div>
        </div>

        {/* ── Vortex Settings ─────────────────────────────────── */}
        <div className="detector-settings__card">
          <div className="detector-settings__card-header">Vortex Settings</div>
          <div className="detector-settings__card-body">
            <NumberInput
              label="vortex time"
              value={vortex.vortexTime}
              onChange={(v) => patchVortex({ vortexTime: v })}
            />
            <div className="detector-settings__range-row">
              <span className="detector-settings__range-label">PFY</span>
              <div className="detector-settings__range-controls">
                <span className="detector-settings__range-sub">start</span>
                <NumberInput
                  label=""
                  value={vortex.pfyStart}
                  onChange={(v) => patchVortex({ pfyStart: v })}
                />
                <span className="detector-settings__range-sub">size</span>
                <NumberInput
                  label=""
                  value={vortex.pfySize}
                  onChange={(v) => patchVortex({ pfySize: v })}
                />
              </div>
            </div>
            <NumberInput
              label="PFY counts"
              value={vortex.pfyCounts}
              onChange={(v) => patchVortex({ pfyCounts: v })}
            />
            <div className="detector-settings__range-row">
              <span className="detector-settings__range-label">IPFY</span>
              <div className="detector-settings__range-controls">
                <span className="detector-settings__range-sub">start</span>
                <NumberInput
                  label=""
                  value={vortex.ipfyStart}
                  onChange={(v) => patchVortex({ ipfyStart: v })}
                />
                <span className="detector-settings__range-sub">size</span>
                <NumberInput
                  label=""
                  value={vortex.ipfySize}
                  onChange={(v) => patchVortex({ ipfySize: v })}
                />
              </div>
            </div>
            <NumberInput
              label="IPFY counts"
              value={vortex.ipfyCounts}
              onChange={(v) => patchVortex({ ipfyCounts: v })}
            />
            <button className="detector-settings__erase-start" type="button">
              Counter
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
