/**
 * API hooks for wiring UI fields to live EPICS PVs.
 *
 * Two services are involved and both go through the Vite proxy:
 *   - configuration_service  /api/config/*  → http://localhost:8004/api/v1/*
 *       resolves dotted device addresses (e.g. "pgm.fly.start_sig") to PV names
 *   - direct_control_service /api/control/* → http://localhost:8003/api/v1/*
 *       performs the actual caput(s)
 *
 * The frontend never hardcodes raw PV strings: it resolves addresses so a
 * happi_db prefix change flows through automatically.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

const CONFIG_BASE = '/api/config'
const CONTROL_BASE = '/api/control'

/** Query-key prefix for cached live-PV reads, invalidated after any caput. */
export const PV_QUERY_KEY = ['pv'] as const

/**
 * POST JSON and return the parsed body. On a non-2xx response, throws an
 * Error whose message includes the FastAPI `detail` when present. Shared by
 * the hooks so the fetch + error-parsing logic lives in one place.
 */
async function postJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      if (data?.detail) detail = `${res.status}: ${JSON.stringify(data.detail)}`
    } catch {
      /* response had no JSON body */
    }
    throw new Error(detail)
  }
  return res.json()
}

// ── Resolve (configuration_service) ───────────────────────────────

/** Per-address row from POST /devices/resolve. */
export interface ResolveResultItem {
  address: string
  outcome: string
  pv_name: string | null
  message: string | null
  ok: boolean
}

interface ResolveResponse {
  resolved: ResolveResultItem[]
}

/**
 * Resolve dotted device addresses to PV names. Returns a map of
 * address → pv_name containing only the addresses that resolved.
 * The set of addresses is treated as static, so the result is cached
 * indefinitely for the session.
 */
export function useResolveAddresses(addresses: string[]) {
  // Normalize once: sorting makes the cache key order-independent, and reusing
  // the same list for the request body keeps the key and payload in lockstep.
  const normalized = [...addresses].sort()
  return useQuery({
    queryKey: ['resolve', normalized],
    enabled: normalized.length > 0,
    staleTime: Infinity,
    queryFn: async (): Promise<Record<string, string>> => {
      const data = await postJson<ResolveResponse>(`${CONFIG_BASE}/devices/resolve`, {
        addresses: normalized,
      })
      const map: Record<string, string> = {}
      for (const row of data.resolved) {
        if (row.ok && row.pv_name) map[row.address] = row.pv_name
      }
      return map
    },
  })
}

// ── Batch caput (direct_control_service) ──────────────────────────

export interface PvCaput {
  pv_name: string
  value: number | string | boolean
  wait?: boolean
  timeout?: number
}

export interface PvSetBatchItemResult {
  pv_name: string
  success: boolean
  value_set?: unknown
  timestamp: string
  mode?: string | null
  message?: string | null
  error_type?: string | null
  status_code?: number | null
}

export interface PvSetBatchResponse {
  ok: boolean
  applied: number
  requested: number
  results: PvSetBatchItemResult[]
}

/**
 * Apply a sequence of caputs with fail-hard semantics. The HTTP call is
 * always 200 on a well-formed request; inspect `ok` / per-item
 * `status_code` to branch. Throws only on transport / malformed-request
 * errors (e.g. 422).
 *
 * On settle, any cached live-PV reads under `PV_QUERY_KEY` are invalidated so
 * they refetch the newly written values.
 */
export function usePvSetBatch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationKey: ['pv', 'set', 'batch'],
    mutationFn: (caputs: PvCaput[]) =>
      postJson<PvSetBatchResponse>(`${CONTROL_BASE}/pv/set/batch`, { caputs }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: PV_QUERY_KEY }),
  })
}

// ── Single caput (direct_control_service) ─────────────────────────

export interface PvSetResponse {
  pv_name: string
  success: boolean
  value_set: unknown
  timestamp: string
  mode: string
  message?: string | null
}

/**
 * Set a single PV value. Invalidates cached live-PV reads under
 * `PV_QUERY_KEY` on settle so they refetch the newly written value.
 */
export function usePvSet() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationKey: ['pv', 'set'],
    mutationFn: (caput: PvCaput) => postJson<PvSetResponse>(`${CONTROL_BASE}/pv/set`, caput),
    onSettled: () => queryClient.invalidateQueries({ queryKey: PV_QUERY_KEY }),
  })
}
