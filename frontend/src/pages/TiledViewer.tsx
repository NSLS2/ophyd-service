import { useEffect, useState, type ComponentType } from 'react'
import { loadFinch } from '../components/finchLoader'

// Finch touches `window` at module load, so its components must be resolved
// at runtime on the client — never as a top-level import (crashes SSR).
export default function TiledViewer() {
  const [TiledLookup, setTiledLookup] = useState<ComponentType<{ backgroundClassName?: string }> | null>(null)

  useEffect(() => {
    let cancelled = false
    loadFinch()
      .then((finch) => { if (!cancelled) setTiledLookup(() => finch.TiledLookup) })
      .catch((error) => { console.error('Failed to load Finch', error) })
    return () => { cancelled = true }
  }, [])

  return (
    <div className="flex flex-col w-full h-full min-h-[600px]">
      {TiledLookup ? <TiledLookup backgroundClassName="text-slate-700" /> : null}
    </div>
  )
}
