import './ControlsPanel.css'

interface ControlsPanelProps {
  onPdScan?: () => void
  onSingleScan?: () => void
  onAddToQueue?: () => void
  onStop?: () => void
}

export function ControlsPanel({
  onPdScan,
  onSingleScan,
  onAddToQueue,
  onStop,
}: ControlsPanelProps) {
  return (
    <section className="controls-panel" aria-label="Controls">
      <div className="controls-panel__header">Controls</div>
      <div className="controls-panel__body">
        <button
          className="controls-panel__button controls-panel__button--primary"
          type="button"
          onClick={onPdScan}
        >
          PD Scan
        </button>
        <button
          className="controls-panel__button controls-panel__button--primary"
          type="button"
          onClick={onSingleScan}
        >
          Single Scan
        </button>
        <button
          className="controls-panel__button controls-panel__button--queue"
          type="button"
          onClick={onAddToQueue}
        >
          Add to Queue
        </button>
        <button
          className="controls-panel__button controls-panel__button--stop"
          type="button"
          onClick={onStop}
        >
          Stop
        </button>
      </div>
    </section>
  )
}