import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'
import { loadFinch } from './finchLoader'
import type { VortexState } from './DetectorSettings'

type FinchModule = Awaited<ReturnType<typeof loadFinch>>

interface LiveSpectrumPanelProps {
  spectrumPv?: string
  pfyCountPv?: string
  ipfyCountPv?: string
  isCounting: boolean
  setDetectorVortex: Dispatch<SetStateAction<VortexState>>
}

export function LiveSpectrumPanel(props: LiveSpectrumPanelProps) {
  const [finchModule, setFinchModule] = useState<FinchModule | null>(null)

  useEffect(() => {
    let cancelled = false
    loadFinch().then((finch) => {
      if (!cancelled) setFinchModule(finch)
    }).catch((error) => {
      console.error('Failed to load Finch live spectrum components', error)
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (!finchModule) {
    return (
      <SpectrumShell>
        <div className="flex min-h-[14rem] flex-1 items-center justify-center text-[0.875rem] text-gray-500">
          Loading live spectrum...
        </div>
      </SpectrumShell>
    )
  }

  return <LoadedLiveSpectrumPanel finchModule={finchModule} {...props} />
}

function LoadedLiveSpectrumPanel({
  finchModule,
  spectrumPv,
  pfyCountPv,
  ipfyCountPv,
  isCounting,
  setDetectorVortex,
}: LiveSpectrumPanelProps & { finchModule: FinchModule }) {
  const socketPvs = [spectrumPv, pfyCountPv, ipfyCountPv].filter((pv): pv is string => Boolean(pv))
  const { devices } = finchModule.useOphydPVSocket(socketPvs)

  const spectrumValue = spectrumPv ? (devices[spectrumPv]?.value as unknown) : undefined
  const spectrumArray = Array.isArray(spectrumValue) ? (spectrumValue as number[]) : null
  const pfyLive = pfyCountPv ? devices[pfyCountPv]?.value : undefined
  const ipfyLive = ipfyCountPv ? devices[ipfyCountPv]?.value : undefined

  useEffect(() => {
    if (!isCounting) return
    setDetectorVortex((prev) => ({
      ...prev,
      ...(typeof pfyLive === 'number' ? { pfyCounts: pfyLive } : {}),
      ...(typeof ipfyLive === 'number' ? { ipfyCounts: ipfyLive } : {}),
    }))
  }, [isCounting, pfyLive, ipfyLive, setDetectorVortex])

  return (
    <SpectrumShell>
      <finchModule.HistogramPlot
        arrayData={spectrumArray}
        title="Vortex MCA Spectrum"
        className="min-h-[14rem] flex-1"
      />
    </SpectrumShell>
  )
}

function SpectrumShell({ children }: { children: React.ReactNode }) {
  return (
    <section className="flex min-w-0 min-h-[clamp(18rem,32vh,24rem)] flex-col bg-white border border-panel-border rounded-xl overflow-hidden shadow-[0_1px_3px_rgba(16,92,120,0.08)]" aria-label="Live Spectrum">
      <div className="bg-brand-teal text-white text-center px-4 py-[0.66rem] text-lg font-bold tracking-[0.02em]">Live Spectrum (Vortex MCA)</div>
      <div className="flex min-h-0 flex-1 px-4 pt-3 pb-4">
        {children}
      </div>
    </section>
  )
}