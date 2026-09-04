import { NumberInput } from '../NumberInput'
import { SelectInput } from '../SelectInput'
import type { DetectorPresetEntry } from '../../api/presets'
import type { PvCaput } from '../../api/directControl'

// Real SR570 enum states served by ioc_ios_curramp.py
// (XF:23ID2-ES{CurrAmp:N}Gain:Val-SP / Gain:Decade-SP). The presets store
// exactly these strings, and the happi entries are string=True enums, so the
// selected label is caput verbatim.
const GAIN_OPTIONS = ['1', '2', '5', '10', '20', '50', '100', '200', '500']
const DECADE_OPTIONS = [
  '1 pA/V', '10 pA/V', '100 pA/V', '1 nA/V', '10 nA/V',
  '100 nA/V', '1 uA/V', '10 uA/V', '100 uA/V', '1 mA/V',
]

export interface ScalarState {
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

export interface VortexState {
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

/**
 * Detector-form fields → dotted device addresses the configuration_service
 * resolves to live PVs. Scalar counts (pd/aumesh/sample) and ROI count sums
 * are read-only readbacks and are intentionally absent — they're displayed,
 * not written.
 *
 * PFY = MCA ROI R2, IPFY = MCA ROI R4 (per ioc_ios_vortex.py). The UI shows
 * ROIs as start/size; the PV pair is absolute lo_chan/hi_chan, so the caput
 * builder converts hi = start + size.
 */
export const DETECTOR_ADDRESSES = {
  dwellTime: 'sclr_time',
  pdGain: 'pd_sclr_gain',
  pdDecade: 'pd_sclr_decade',
  aumeshGain: 'aumesh_sclr_gain',
  aumeshDecade: 'aumesh_sclr_decade',
  sampleGain: 'sample_sclr_gain',
  sampleDecade: 'sample_sclr_decade',
  vortexTime: 'vortex.mca.preset_real_time',
  pfyLo: 'vortex.mca.rois.roi2.lo_chan',
  pfyHi: 'vortex.mca.rois.roi2.hi_chan',
  ipfyLo: 'vortex.mca.rois.roi4.lo_chan',
  ipfyHi: 'vortex.mca.rois.roi4.hi_chan',
} as const

/** Seed the detector form from a stored detector preset (null → dummy defaults). */
export function detectorPresetToState(
  preset: Omit<DetectorPresetEntry, 'edge_index'> | null,
): { scalar: ScalarState; vortex: VortexState } {
  if (!preset) return { scalar: initialScalar, vortex: initialVortex }
  return {
    scalar: {
      dwellTime: preset.sclr_time,
      pd: 0,
      pdGain: preset.pd_gain,
      pdDecade: preset.pd_decade,
      aumesh: 0,
      aumeshGain: preset.aumeshgain,
      aumeshDecade: preset.aumeshdecade,
      sample: 0,
      sampleGain: preset.samplegain,
      sampleDecade: preset.sampledecade,
    },
    vortex: {
      vortexTime: preset.vortex_time,
      pfyStart: preset.vortex_low,
      pfySize: preset.vortex_high - preset.vortex_low,
      pfyCounts: 0,
      ipfyStart: preset.ipfy_low,
      ipfySize: preset.ipfy_high - preset.ipfy_low,
      ipfyCounts: 0,
    },
  }
}

/**
 * Build the caput list for the writable detector fields. Skips any address
 * that didn't resolve and any unselected enum (empty string). ROI size is
 * converted back to an absolute hi channel.
 */
export function buildDetectorCaputs(
  scalar: ScalarState,
  vortex: VortexState,
  pvMap: Record<string, string>,
): PvCaput[] {
  const caputs: PvCaput[] = []
  const add = (address: string, value: number | string) => {
    const pv = pvMap[address]
    if (pv !== undefined && value !== '') caputs.push({ pv_name: pv, value })
  }
  add(DETECTOR_ADDRESSES.dwellTime, scalar.dwellTime)
  add(DETECTOR_ADDRESSES.pdGain, scalar.pdGain)
  add(DETECTOR_ADDRESSES.pdDecade, scalar.pdDecade)
  add(DETECTOR_ADDRESSES.aumeshGain, scalar.aumeshGain)
  add(DETECTOR_ADDRESSES.aumeshDecade, scalar.aumeshDecade)
  add(DETECTOR_ADDRESSES.sampleGain, scalar.sampleGain)
  add(DETECTOR_ADDRESSES.sampleDecade, scalar.sampleDecade)
  add(DETECTOR_ADDRESSES.vortexTime, vortex.vortexTime)
  add(DETECTOR_ADDRESSES.pfyLo, vortex.pfyStart)
  add(DETECTOR_ADDRESSES.pfyHi, vortex.pfyStart + vortex.pfySize)
  add(DETECTOR_ADDRESSES.ipfyLo, vortex.ipfyStart)
  add(DETECTOR_ADDRESSES.ipfyHi, vortex.ipfyStart + vortex.ipfySize)
  return caputs
}

export interface DetectorSettingsProps {
  scalar: ScalarState
  vortex: VortexState
  onScalarChange: (patch: Partial<ScalarState>) => void
  onVortexChange: (patch: Partial<VortexState>) => void
  /** Page-level handler that writes the current settings to the beamline. */
  onApply?: () => void
  /** True while a caput batch is in flight; disables the Apply button. */
  isApplying?: boolean
  /** Toggles the continuous Vortex acquisition loop (Erase/Start equivalent). */
  onCount?: () => void
  /** True while the acquisition loop is running; flips the button to "Stop". */
  isCounting?: boolean
}

export function DetectorSettings({
  scalar,
  vortex,
  onScalarChange,
  onVortexChange,
  onApply,
  isApplying,
  onCount,
  isCounting,
}: DetectorSettingsProps) {
  const patchScalar = onScalarChange
  const patchVortex = onVortexChange

  const gainRow = 'flex items-center justify-between gap-2 py-[0.55rem] px-1 border-b border-[#e3e8ec]'
  const gainLabel = 'text-[1.1rem] text-brand-slate whitespace-nowrap'
  const gainControls = 'flex items-center gap-[0.35rem]'
  const gainX = 'text-[#6b7280] text-[1.05rem]'
  const rangeRow = 'flex items-center justify-between gap-2 py-[0.55rem] px-1 border-b border-[#e3e8ec]'
  const rangeLabel = 'text-[1.1rem] text-brand-slate whitespace-nowrap'
  const rangeControls = 'flex items-center gap-[0.3rem] [&>div]:p-0 [&>div]:gap-1 [&>div]:border-b-0 [&_input]:w-[68px]'
  const rangeSub = 'text-[1rem] text-[#6b7280]'
  const card = 'bg-white border border-panel-border rounded-lg overflow-hidden'
  const cardHeader = 'bg-brand-teal text-white px-3 py-[0.45rem] text-[1.05rem] font-bold'
  const cardBody = 'flex flex-col px-3 pt-2 pb-3'

  return (
    <section className="detector-settings min-w-0 max-xl:w-full min-h-[clamp(24rem,42vh,32rem)] flex flex-col bg-white border border-panel-border rounded-xl overflow-hidden shadow-[0_1px_3px_rgba(16,92,120,0.08)]">
      <div className="bg-brand-teal text-white text-center px-4 py-[0.7rem] text-lg font-bold tracking-[0.02em]">Detector Settings</div>
      <div className="grid grid-cols-[2fr_1fr] gap-3 flex-1 px-4 pt-3 pb-4 max-lg:grid-cols-1">
        {/* ── Scalar Settings ─────────────────────────────────── */}
        <div className={card}>
          <div className={cardHeader}>Scalar Settings</div>
          <div className={cardBody}>
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
            <div className={gainRow}>
              <span className={gainLabel}>pd gain</span>
              <div className={gainControls}>
                <SelectInput
                  value={scalar.pdGain}
                  options={GAIN_OPTIONS}
                  onChange={(v) => patchScalar({ pdGain: v })}
                />
                <span className={gainX}>×</span>
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
            <div className={gainRow}>
              <span className={gainLabel}>aumesh gain</span>
              <div className={gainControls}>
                <SelectInput
                  value={scalar.aumeshGain}
                  options={GAIN_OPTIONS}
                  onChange={(v) => patchScalar({ aumeshGain: v })}
                />
                <span className={gainX}>×</span>
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
            <div className={gainRow}>
              <span className={gainLabel}>sample gain</span>
              <div className={gainControls}>
                <SelectInput
                  value={scalar.sampleGain}
                  options={GAIN_OPTIONS}
                  onChange={(v) => patchScalar({ sampleGain: v })}
                />
                <span className={gainX}>×</span>
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
        <div className={card}>
          <div className={cardHeader}>Vortex Settings</div>
          <div className={cardBody}>
            <NumberInput
              label="vortex time"
              value={vortex.vortexTime}
              onChange={(v) => patchVortex({ vortexTime: v })}
            />
            <div className={rangeRow}>
              <span className={rangeLabel}>PFY</span>
              <div className={rangeControls}>
                <span className={rangeSub}>start</span>
                <NumberInput
                  label=""
                  value={vortex.pfyStart}
                  onChange={(v) => patchVortex({ pfyStart: v })}
                />
                <span className={rangeSub}>size</span>
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
            <div className={rangeRow}>
              <span className={rangeLabel}>IPFY</span>
              <div className={rangeControls}>
                <span className={rangeSub}>start</span>
                <NumberInput
                  label=""
                  value={vortex.ipfyStart}
                  onChange={(v) => patchVortex({ ipfyStart: v })}
                />
                <span className={rangeSub}>size</span>
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
            <button
              className={`mt-3 px-4 py-[0.55rem] text-white rounded-md text-[0.9rem] font-semibold cursor-pointer transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${
                isCounting
                  ? 'bg-red-600 hover:bg-red-700'
                  : 'bg-brand-cyan hover:bg-brand-teal'
              }`}
              type="button"
              onClick={onCount}
              disabled={!onCount}
            >
              {isCounting ? 'Stop' : 'Counter'}
            </button>
          </div>
        </div>
      </div>

      {/* ── Apply to Beamline ─────────────────────────────────── */}
      <div className="px-4 pb-4">
        <div className="relative group">
          <button
            className="w-full px-4 py-[0.7rem] bg-brand-teal text-white rounded-md text-[1.05rem] font-semibold cursor-pointer transition-colors hover:bg-brand-cyan disabled:opacity-60 disabled:cursor-not-allowed"
            type="button"
            onClick={onApply}
            disabled={isApplying || !onApply}
            aria-describedby="apply-beamline-tip"
          >
            {isApplying ? 'Applying…' : 'Apply to Beamline'}
          </button>
          <span
            id="apply-beamline-tip"
            role="tooltip"
            className="pointer-events-none absolute bottom-[calc(100%+8px)] left-1/2 -translate-x-1/2 z-10 hidden w-max max-w-[min(360px,80vw)] px-3 py-2 rounded-lg bg-[#0b3a4d] text-[#f2fafd] text-[0.8rem] font-medium leading-[1.4] text-left shadow-[0_4px_14px_rgba(0,0,0,0.22)] group-hover:block group-focus-within:block after:content-[''] after:absolute after:top-full after:left-1/2 after:-translate-x-1/2 after:border-[6px] after:border-transparent after:border-t-[#0b3a4d]"
          >
            Writes the current Scan Parameters and Detector Settings to the
            live beamline — sends each value to its EPICS PV via direct control.
            This can move hardware (e.g. the monochromator via <em>e align</em>).
            Applies all values at once and stops on the first failure.
          </span>
        </div>
      </div>
    </section>
  )
}
