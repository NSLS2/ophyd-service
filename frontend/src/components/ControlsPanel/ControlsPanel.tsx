interface ControlsPanelProps {
  onPdScan?: () => void
  onSingleScan?: () => void
  onAddToQueue?: () => void
  onStop?: () => void
  isRunning?: boolean
  activeScan?: 'pd' | 'single' | null
}

function ScanButtonContent({ label, isActive }: { label: string; isActive: boolean }) {
  return (
    <>
      <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center" aria-hidden="true">
        {isActive && (
          <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        )}
      </span>
      <span className="min-w-0 flex-1 text-center">{label}</span>
      <span className="h-4 w-4 shrink-0" aria-hidden="true" />
    </>
  )
}

export function ControlsPanel({
  onPdScan,
  onSingleScan,
  onAddToQueue,
  onStop,
  isRunning = false,
  activeScan = null,
}: ControlsPanelProps) {
  return (
    <section 
      className="min-w-[14rem] max-lg:w-full max-lg:min-w-0 min-h-[clamp(18rem,32vh,24rem)] flex flex-col bg-white border border-panel-border rounded-xl overflow-hidden shadow-[0_1px_3px_rgba(16,92,120,0.08)]"
      aria-label="Controls"
    >
      <div className="bg-brand-teal text-white text-center px-4 py-[0.66rem] text-lg font-bold tracking-[0.02em]">
        Controls
      </div>
      <div className="flex flex-col flex-1 items-center justify-around gap-4 p-[0.9rem_0.8rem] max-md:p-[0.8rem_0.7rem] max-md:gap-2">
        <button
          className="flex w-full items-center gap-2 px-4 py-[0.65rem] border-none rounded-md text-white text-lg font-semibold leading-tight cursor-pointer transition-all active:scale-[0.98] bg-brand-cyan hover:bg-[#009dc8] disabled:opacity-50 disabled:cursor-not-allowed"
          type="button"
          onClick={onPdScan}
          disabled={isRunning}
        >
          <ScanButtonContent label="PD Scan" isActive={activeScan === 'pd'} />
        </button>
        <button
          className="flex w-full items-center gap-2 px-4 py-[0.65rem] border-none rounded-md text-white text-lg font-semibold leading-tight cursor-pointer transition-all active:scale-[0.98] bg-brand-cyan hover:bg-[#009dc8] disabled:opacity-50 disabled:cursor-not-allowed"
          type="button"
          onClick={onSingleScan}
          disabled={isRunning}
        >
          <ScanButtonContent label="Single Scan" isActive={activeScan === 'single'} />
        </button>
        <button
          className="w-full px-4 py-[0.65rem] border-none rounded-md text-white text-lg font-semibold leading-tight cursor-pointer transition-all active:scale-[0.98] mt-2 mb-2 bg-brand-teal hover:bg-[#0e5068] disabled:opacity-50 disabled:cursor-not-allowed"
          type="button"
          onClick={onAddToQueue}
          disabled={isRunning}
        >
          Add to Queue
        </button>
        <button
          className="w-full px-4 py-[0.65rem] border-none rounded-md text-white text-lg font-semibold leading-tight cursor-pointer transition-all active:scale-[0.98] bg-brand-red hover:bg-[#cc0000]"
          type="button"
          onClick={onStop}
        >
          Stop
        </button>
      </div>
    </section>
  )
}