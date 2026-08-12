import { useState, useEffect, useRef, useMemo } from 'react'
import { useOphydPVSocket, HistogramPlot } from '@blueskyproject/finch'
import type { ElementData } from '../components/ElementPicker'
import { useFullPreset, type EdgeFullPreset, type ScanPresetEntry } from '../api/presets'
import { getEdgesForElement } from '../api/edgeMapping'
import { ScanParameters, SCAN_PARAM_ADDRESSES } from '../components/ScanParameters'
import {
  DetectorSettings,
  detectorPresetToState,
  buildDetectorCaputs,
  DETECTOR_ADDRESSES,
} from '../components/DetectorSettings'
import { ControlsPanel } from '../components/ControlsPanel'
import { Toast, type ToastType } from '../components/Toast'
import { useQueueExecute, useStopScan, useAllowedPlans, isPlanAllowed, useQueueStatus } from '../api/queueserver'
import { useResolveAddresses, usePvSetBatch, usePvSet, type PvCaput } from '../api/directControl'

interface ScanConfigProps {
  element: ElementData
  onBack: () => void
}

export default function ScanConfig({ element, onBack }: ScanConfigProps) {
  const edges = getEdgesForElement(element.symbol)
  const [selectedEdge, setSelectedEdge] = useState(edges[0] ?? '')
  const { data, isLoading, isError, error } = useFullPreset(selectedEdge)

  return (
    <div className="w-full min-h-full">
      <div className="flex flex-col gap-5 px-[clamp(1rem,2vw,1.5rem)] py-[clamp(1rem,2vw,1.5rem)] w-full max-w-[96rem] mx-auto box-border">
        <header className="flex flex-col gap-4 mb-6">
        <button 
          className="self-start flex items-center gap-2 px-3 py-2 bg-gray-100 border border-gray-200 rounded-lg text-gray-700 text-[0.875rem] font-medium cursor-pointer transition-all hover:bg-brand-teal hover:text-white hover:border-brand-teal"
          onClick={onBack}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          Back to Periodic Table
        </button>
        <div className="flex items-center justify-center gap-[clamp(6px,0.8vw,12px)]">
          <h1 className="m-0 text-[clamp(1.4rem,2.6vw,2.1rem)] font-bold text-[#0b3a4d] text-center tracking-[0.01em]">
            {element.name} — Scan Configuration
          </h1>
          <span className="relative inline-flex items-center group">
            <button
              type="button"
              className="inline-flex items-center justify-center w-[clamp(18px,1.6vw,24px)] h-[clamp(18px,1.6vw,24px)] p-0 border-none rounded-full bg-[#0b3a4d] text-white font-[Georgia,'Times_New_Roman',serif] italic font-bold text-[clamp(0.7rem,1vw,0.9rem)] leading-none cursor-help transition-colors hover:bg-[#1976d2] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1976d2] focus-visible:outline-offset-2"
              aria-label="About this page"
            >
              i
            </button>
            <span
              role="tooltip"
              className="absolute top-[calc(100%+10px)] left-1/2 -translate-x-1/2 max-lg:left-auto max-lg:right-0 max-lg:translate-x-0 z-10 hidden w-max max-w-[min(320px,80vw)] px-3 py-2 rounded-lg bg-[#0b3a4d] text-[#f2fafd] text-[clamp(0.72rem,0.9vw,0.9rem)] font-medium leading-[1.35] text-left shadow-[0_4px_14px_rgba(0,0,0,0.22)] group-hover:block group-focus-within:block before:content-[''] before:absolute before:bottom-full before:left-1/2 before:-translate-x-1/2 max-lg:before:left-auto max-lg:before:right-2 max-lg:before:translate-x-0 before:border-[6px] before:border-transparent before:border-b-[#0b3a4d]"
            >
              Configure scan parameters for {element.name}. Adjust energy ranges, 
              step sizes, and detector settings, then click Start to run the scan.
            </span>
          </span>
        </div>
      </header>

      {edges.length === 0 && (
        <div className="text-[0.95rem] text-gray-600 bg-gray-100 border border-dashed border-gray-300 rounded-lg p-8 text-center">
          No presets configured for {element.name}. Contact beamline staff to add edge presets.
        </div>
      )}

      {edges.length > 1 && (
        <div className="flex gap-2">
          {edges.map((edge) => (
            <button
              key={edge}
              className={`px-4 py-[0.375rem] border rounded-md text-[0.875rem] font-semibold cursor-pointer transition-all ${edge === selectedEdge ? 'bg-brand-teal border-brand-teal text-white' : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'}`}
              onClick={() => setSelectedEdge(edge)}
            >
              {edge}
            </button>
          ))}
        </div>
      )}

      {isLoading && <div className="text-[0.875rem] text-gray-600">Loading presets…</div>}
      {isError && (
        <div className="text-[0.875rem] text-red-600">
          Failed to load presets: {(error as Error).message}
        </div>
      )}

        {data && <PresetPanels data={data} />}
      </div>
    </div>
  )
}

interface ToastState {
  message: string
  type: ToastType
}

// Live-readback addresses for the Vortex MCA. Resolved to raw EPICS PV names
// and streamed over Finch's ophyd WebSocket (not REST polling).
const SPECTRUM_ADDRESS = 'vortex.mca.spectrum'
const PFY_COUNT_ADDRESS = 'vortex.mca.rois.roi2.count'
const IPFY_COUNT_ADDRESS = 'vortex.mca.rois.roi4.count'
// How often to re-trigger the sim MCA while counting. In the simulated IOC the
// spectrum + ROI sums only refresh on a write to the preset-real-time (PRTM)
// PV, so the loop re-writes the same dwell to keep new frames coming.
// PRODUCTION SWAP: replace this loop with a single write to the real
// `EraseStart` PV; a real MCA streams ArrayData live during acquisition.
const COUNT_INTERVAL_MS = 1000

function PresetPanels({ data }: { data: EdgeFullPreset }) {
  const [scanData, setScanData] = useState<Omit<ScanPresetEntry, 'edge_index'> | null>(data.scan)
  const [detectorScalar, setDetectorScalar] = useState(() => detectorPresetToState(data.detector).scalar)
  const [detectorVortex, setDetectorVortex] = useState(() => detectorPresetToState(data.detector).vortex)
  const [scanStatus, setScanStatus] = useState<'idle' | 'running'>('idle')
  const [activeScan, setActiveScan] = useState<'pd' | 'single' | null>(null)
  const [hasObservedManagerBusy, setHasObservedManagerBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const executeQueue = useQueueExecute()
  const stopScan = useStopScan()
  const { data: allowedPlansData } = useAllowedPlans()
  const allowedPlans = allowedPlansData?.plans_allowed
  const { data: queueStatus } = useQueueStatus()

  // Resolve the scan + detector device addresses to live PV names once, then
  // caput them all in one fail-hard batch when the operator clicks Apply.
  const scanAddresses = Object.values(SCAN_PARAM_ADDRESSES) as string[]
  const detectorAddresses = Object.values(DETECTOR_ADDRESSES)
  const { data: pvMap } = useResolveAddresses([
    ...scanAddresses,
    ...detectorAddresses,
    SPECTRUM_ADDRESS,
    PFY_COUNT_ADDRESS,
    IPFY_COUNT_ADDRESS,
  ])
  const applyBatch = usePvSetBatch()

  // ── Live Vortex counter (Erase/Start equivalent) ────────────────
  const spectrumPv = pvMap?.[SPECTRUM_ADDRESS]
  const pfyCountPv = pvMap?.[PFY_COUNT_ADDRESS]
  const ipfyCountPv = pvMap?.[IPFY_COUNT_ADDRESS]
  const prtmPv = pvMap?.[DETECTOR_ADDRESSES.vortexTime]

  const socketPvs = useMemo(
    () => [spectrumPv, pfyCountPv, ipfyCountPv].filter((p): p is string => Boolean(p)),
    [spectrumPv, pfyCountPv, ipfyCountPv],
  )
  const { devices } = useOphydPVSocket(socketPvs)

  const [isCounting, setIsCounting] = useState(false)
  const pvSet = usePvSet()

  // Keep the trigger logic in a ref so the interval always fires with the
  // latest dwell value without restarting on every keystroke.
  const triggerRef = useRef<() => void>(() => {})
  triggerRef.current = () => {
    if (!prtmPv) return
    const dwell = Number(detectorVortex.vortexTime) || 1
    pvSet.mutate({ pv_name: prtmPv, value: dwell })
  }

  useEffect(() => {
    if (!isCounting) return
    triggerRef.current()
    const id = setInterval(() => triggerRef.current(), COUNT_INTERVAL_MS)
    return () => clearInterval(id)
  }, [isCounting])

  // While counting, drive the PFY/IPFY count fields from the live ROI sums.
  const pfyLive = pfyCountPv ? devices[pfyCountPv]?.value : undefined
  const ipfyLive = ipfyCountPv ? devices[ipfyCountPv]?.value : undefined
  useEffect(() => {
    if (!isCounting) return
    setDetectorVortex((prev) => ({
      ...prev,
      ...(typeof pfyLive === 'number' ? { pfyCounts: pfyLive } : {}),
      ...(typeof ipfyLive === 'number' ? { ipfyCounts: ipfyLive } : {}),
    }))
  }, [isCounting, pfyLive, ipfyLive])

  const handleCount = () => {
    if (!isCounting && !prtmPv) {
      showToast('Vortex trigger PV not resolved yet — try again in a moment', 'warning')
      return
    }
    setIsCounting((c) => !c)
  }

  // The MCA spectrum arrives from the WebSocket as a JSON array of channel
  // counts; the socket value type is scalar, so narrow it here.
  const spectrumValue = spectrumPv ? (devices[spectrumPv]?.value as unknown) : undefined
  const spectrumArray = Array.isArray(spectrumValue) ? (spectrumValue as number[]) : null

  const showToast = (message: string, type: ToastType) => {
    setToast({ message, type })
  }

  const handleApply = async () => {
    if (!pvMap) {
      showToast('PV names not resolved yet — try again in a moment', 'warning')
      return
    }
    const caputs: PvCaput[] = []
    if (scanData) {
      for (const [field, address] of Object.entries(SCAN_PARAM_ADDRESSES)) {
        const pvName = pvMap[address]
        if (!pvName) continue
        caputs.push({ pv_name: pvName, value: scanData[field as keyof typeof scanData] as number })
      }
    }
    caputs.push(...buildDetectorCaputs(detectorScalar, detectorVortex, pvMap))
    if (caputs.length === 0) {
      showToast('No writable PVs resolved for these fields', 'error')
      return
    }
    try {
      const result = await applyBatch.mutateAsync(caputs)
      if (result.ok) {
        showToast(`Applied ${result.applied} value${result.applied === 1 ? '' : 's'} to the beamline`, 'success')
      } else {
        const failed = result.results.find((r) => !r.success)
        const reason = failed?.message || failed?.error_type || 'unknown error'
        showToast(`Applied ${result.applied}/${result.requested}; ${failed?.pv_name ?? 'a PV'} failed: ${reason}`, 'error')
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to apply values', 'error')
    }
  }

  // Check if RE Manager is busy (running or paused). Missing status means
  // "not known yet", not busy.
  const isManagerBusy = queueStatus
    ? queueStatus.manager_state !== 'idle' || queueStatus.re_state !== 'idle'
    : false

  // Sync local scan status with server state and show completion toast
  useEffect(() => {
    if (scanStatus !== 'running') {
      return
    }

    if (isManagerBusy) {
      setHasObservedManagerBusy(true)
      return
    }

    if (hasObservedManagerBusy) {
      // Scan just completed - show success toast
      const scanName = activeScan === 'pd' ? 'PD Scan' : activeScan === 'single' ? 'XAS Scan' : 'Scan'
      showToast(`${scanName} Complete!`, 'success')
      setScanStatus('idle')
      setActiveScan(null)
      setHasObservedManagerBusy(false)
    }
  }, [hasObservedManagerBusy, isManagerBusy, scanStatus, activeScan])

  const handlePdScan = async () => {
    if (!scanData) {
      showToast('No scan parameters available', 'error')
      return
    }
    if (!isPlanAllowed(allowedPlans, 'PD_scan')) {
      showToast('PD_scan is not available in this profile collection', 'error')
      return
    }
    if (isManagerBusy) {
      showToast('RE Manager is busy. Stop the current scan first.', 'error')
      return
    }
    setActiveScan('pd')
    setHasObservedManagerBusy(false)
    setScanStatus('running')
    try {
      const result = await executeQueue.mutateAsync({
        name: 'PD_scan',
        args: [scanData.start, scanData.stop, scanData.velocity, scanData.deadband],
        item_type: 'plan',
      })
      if (!result.success) {
        throw new Error(result.msg || 'Failed to execute PD_scan')
      }
    } catch (err) {
      setScanStatus('idle')
      setActiveScan(null)
      setHasObservedManagerBusy(false)
      showToast(err instanceof Error ? err.message : 'Unknown error', 'error')
    }
  }

  const handleSingleScan = async () => {
    if (!scanData) {
      showToast('No scan parameters available', 'error')
      return
    }
    if (!isPlanAllowed(allowedPlans, 'XAS_scan')) {
      showToast('XAS_scan is not available in this profile collection', 'error')
      return
    }
    if (isManagerBusy) {
      showToast('RE Manager is busy. Stop the current scan first.', 'error')
      return
    }
    setActiveScan('single')
    setHasObservedManagerBusy(false)
    setScanStatus('running')
    try {
      const result = await executeQueue.mutateAsync({
        name: 'XAS_scan',
        args: [scanData.start, scanData.stop, scanData.velocity, scanData.deadband],
        item_type: 'plan',
      })
      if (!result.success) {
        throw new Error(result.msg || 'Failed to execute XAS_scan')
      }
    } catch (err) {
      setScanStatus('idle')
      setActiveScan(null)
      setHasObservedManagerBusy(false)
      showToast(err instanceof Error ? err.message : 'Unknown error', 'error')
    }
  }

  const handleStop = async () => {
    try {
      const result = await stopScan.mutateAsync()
      if (!result.success) {
        throw new Error(result.msg || 'Failed to stop scan')
      }
      setScanStatus('idle')
      setActiveScan(null)
      setHasObservedManagerBusy(false)
      showToast('Scan stopped', 'warning')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to stop scan', 'error')
    }
  }

  return (
    <div className="flex flex-col gap-4 w-full">
      <div className="grid grid-cols-[minmax(20rem,0.9fr)_minmax(32rem,1.35fr)] gap-4 items-stretch max-xl:grid-cols-1 max-xl:w-full">
        {/* Scan Presets — interactive component */}
        {scanData ? (
          <ScanParameters
            data={scanData}
            onChange={(patch) => setScanData((prev) => prev ? { ...prev, ...patch } : prev)}
          />
        ) : (
          <section className="flex-[1_1_0] min-w-0 max-xl:w-full bg-gray-100 border border-gray-300 rounded-lg p-4 px-5">
            <h2 className="text-base font-bold text-gray-800 m-0 mb-3 pb-2 border-b border-gray-300">Scan Parameters</h2>
            <p className="text-gray-600 text-[0.85rem] italic m-0">Not configured</p>
          </section>
        )}

        {/* Detector Presets — interactive component */}
        <DetectorSettings
          scalar={detectorScalar}
          vortex={detectorVortex}
          onScalarChange={(patch) => setDetectorScalar((prev) => ({ ...prev, ...patch }))}
          onVortexChange={(patch) => setDetectorVortex((prev) => ({ ...prev, ...patch }))}
          onApply={handleApply}
          isApplying={applyBatch.isPending}
          onCount={handleCount}
          isCounting={isCounting}
        />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(14rem,18rem)] gap-4 items-stretch max-lg:grid-cols-1">
        <section className="flex min-w-0 min-h-[clamp(18rem,32vh,24rem)] flex-col bg-white border border-panel-border rounded-xl overflow-hidden shadow-[0_1px_3px_rgba(16,92,120,0.08)]" aria-label="Live Spectrum">
          <div className="bg-brand-teal text-white text-center px-4 py-[0.66rem] text-lg font-bold tracking-[0.02em]">Live Spectrum (Vortex MCA)</div>
          <div className="flex min-h-0 flex-1 px-4 pt-3 pb-4">
            <HistogramPlot
              arrayData={spectrumArray}
              title="Vortex MCA Spectrum"
              className="min-h-[14rem] flex-1"
            />
          </div>
        </section>
        <ControlsPanel onPdScan={handlePdScan} onSingleScan={handleSingleScan} onStop={handleStop} isRunning={scanStatus === 'running' || isManagerBusy} activeScan={activeScan} />
      </div>

      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  )
}
