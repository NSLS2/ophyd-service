import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import type { ElementData } from '../components/ElementPicker'

type DraftField = 'scan' | 'detectorScalar' | 'detectorVortex'
type DraftBundle = Partial<Record<DraftField, unknown>>

interface IosScanSessionValue {
  selectedElement: ElementData | null
  selectedEdge: string | null
  setSelectedElement: (element: ElementData | null) => void
  setSelectedEdge: (edge: string | null) => void
  getDraft: <T>(element: string, edge: string, field: DraftField) => T | undefined
  setDraft: <T>(element: string, edge: string, field: DraftField, value: T) => void
  clear: () => void
}

const IosScanSessionContext = createContext<IosScanSessionValue | null>(null)

const draftKey = (element: string, edge: string) => `${element}::${edge}`

/**
 * App-scoped in-memory store for IOS Scan UI state. Survives route
 * unmount/remount so the page reopens where the user left it; cleared
 * explicitly by the Back button and lost on tab close/reload.
 */
export function IosScanSessionProvider({ children }: { children: ReactNode }) {
  const [selectedElement, setSelectedElement] = useState<ElementData | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null)
  // Drafts are stored in a ref so patch writes don't re-render every consumer;
  // components read once on mount and sync on their own state changes.
  const draftsRef = useRef<Map<string, DraftBundle>>(new Map())

  const getDraft = useCallback(<T,>(element: string, edge: string, field: DraftField): T | undefined => {
    return draftsRef.current.get(draftKey(element, edge))?.[field] as T | undefined
  }, [])

  const setDraft = useCallback(<T,>(element: string, edge: string, field: DraftField, value: T) => {
    const key = draftKey(element, edge)
    const existing = draftsRef.current.get(key) ?? {}
    draftsRef.current.set(key, { ...existing, [field]: value })
  }, [])

  const clear = useCallback(() => {
    setSelectedElement(null)
    setSelectedEdge(null)
    draftsRef.current.clear()
  }, [])

  const value = useMemo<IosScanSessionValue>(() => ({
    selectedElement,
    selectedEdge,
    setSelectedElement,
    setSelectedEdge,
    getDraft,
    setDraft,
    clear,
  }), [selectedElement, selectedEdge, getDraft, setDraft, clear])

  return <IosScanSessionContext.Provider value={value}>{children}</IosScanSessionContext.Provider>
}

export function useIosScanSession(): IosScanSessionValue {
  const ctx = useContext(IosScanSessionContext)
  if (!ctx) throw new Error('useIosScanSession must be used within IosScanSessionProvider')
  return ctx
}
