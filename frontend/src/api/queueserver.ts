/**
 * API hooks for the Bluesky Queue Server.
 *
 * All requests go through the Vite proxy:
 *   /api/queueserver/* → http://localhost:60610/api/*
 */

import { useMutation, useQuery } from '@tanstack/react-query'

const BASE = '/api/queueserver'

// Default API key for development — in production this would come from auth
const API_KEY = 'b927abb6addb3363f97db96fcecbf795'

// ── Types ─────────────────────────────────────────────────────────

export interface PlanItem {
  name: string
  args?: unknown[]
  kwargs?: Record<string, unknown>
  item_type: 'plan' | 'instruction'
}

export interface QueueItemResponse {
  success: boolean
  msg: string
  item?: PlanItem & { item_uid?: string }
  qsize?: number
}

export interface QueueExecuteResponse {
  success: boolean
  msg: string
  item?: PlanItem & { item_uid?: string }
}

export interface QueueStatusResponse {
  success: boolean
  msg: string
  manager_state: 'idle' | 'executing_queue' | 'paused' | string
  re_state: 'idle' | 'running' | 'paused' | string
  items_in_queue: number
  running_item: Record<string, unknown> | null
  running_item_uid: string | null
  plan_queue_uid: string
  worker_environment_exists: boolean
  worker_environment_state: string
}

// ── Helpers ───────────────────────────────────────────────────────

async function queueFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `ApiKey ${API_KEY}`,
      ...options.headers,
    },
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      if (data?.msg) detail = data.msg
      else if (data?.detail) detail = data.detail
    } catch {
      /* no JSON body */
    }
    throw new Error(detail)
  }
  return res.json()
}

// ── Query Hooks ───────────────────────────────────────────────────

/**
 * Get queue server status (manager state, queue size, running item, etc.)
 */
export function useQueueStatus() {
  return useQuery({
    queryKey: ['queueserver', 'status'],
    queryFn: () => queueFetch<QueueStatusResponse>('/status'),
    refetchInterval: 2000, // Poll every 2 seconds
  })
}

export interface PlanInfo {
  name: string
  description?: string
  parameters?: Array<{
    name: string
    kind: { name: string; value: number }
    default?: unknown
    annotation?: { type: string }
  }>
}

export interface AllowedPlansResponse {
  success: boolean
  msg: string
  plans_allowed: Record<string, PlanInfo>
}

/**
 * Get list of allowed plans from the queue server.
 */
export function useAllowedPlans() {
  return useQuery({
    queryKey: ['queueserver', 'plans', 'allowed'],
    queryFn: () => queueFetch<AllowedPlansResponse>('/plans/allowed'),
    staleTime: 60000, // Cache for 1 minute
  })
}

/**
 * Check if a plan is in the allowed plans list.
 */
export function isPlanAllowed(
  allowedPlans: Record<string, PlanInfo> | undefined,
  planName: string
): boolean {
  if (!allowedPlans) return false
  return planName in allowedPlans
}

// ── Mutation Hooks ────────────────────────────────────────────────

/**
 * Execute a plan immediately (bypasses the queue).
 * Use for interactive scans like PD_scan.
 */
export function useQueueExecute() {
  return useMutation({
    mutationFn: (item: PlanItem) =>
      queueFetch<QueueExecuteResponse>('/queue/item/execute', {
        method: 'POST',
        body: JSON.stringify({ item }),
      }),
  })
}

/**
 * Add a plan to the queue (does not start execution).
 */
export function useQueueAdd() {
  return useMutation({
    mutationFn: (item: PlanItem) =>
      queueFetch<QueueItemResponse>('/queue/item/add', {
        method: 'POST',
        body: JSON.stringify({ item }),
      }),
  })
}

/**
 * Start executing the queue.
 */
export function useQueueStart() {
  return useMutation({
    mutationFn: () =>
      queueFetch<{ success: boolean; msg: string }>('/queue/start', {
        method: 'POST',
      }),
  })
}

/**
 * Stop the queue (finish current plan, don't start next).
 */
export function useQueueStop() {
  return useMutation({
    mutationFn: () =>
      queueFetch<{ success: boolean; msg: string }>('/queue/stop', {
        method: 'POST',
      }),
  })
}

/**
 * Abort the currently running plan immediately.
 */
export function useReAbort() {
  return useMutation({
    mutationFn: () =>
      queueFetch<{ success: boolean; msg: string }>('/re/abort', {
        method: 'POST',
      }),
  })
}

/**
 * Pause the run engine immediately.
 */
export function useRePause() {
  return useMutation({
    mutationFn: () =>
      queueFetch<{ success: boolean; msg: string }>('/re/pause', {
        method: 'POST',
        body: JSON.stringify({ option: 'immediate' }),
      }),
  })
}

/**
 * Stop the currently running plan: pause immediately, then stop gracefully.
 * This saves data with exit_status='success' and returns motors to start positions.
 */
export async function stopRunningScan(): Promise<{ success: boolean; msg: string }> {
  // First check the current state
  const status = await queueFetch<QueueStatusResponse>('/status')
  
  // If already idle, nothing to stop
  if (status.re_state === 'idle' && status.manager_state === 'idle') {
    return { success: true, msg: 'No scan running' }
  }
  
  // If already paused, just stop
  if (status.re_state === 'paused' || status.manager_state === 'paused') {
    return queueFetch<{ success: boolean; msg: string }>('/re/stop', {
      method: 'POST',
    })
  }
  
  // If running, pause first then stop
  const pauseRes = await queueFetch<{ success: boolean; msg: string }>('/re/pause', {
    method: 'POST',
    body: JSON.stringify({ option: 'immediate' }),
  })
  
  if (!pauseRes.success) {
    return pauseRes
  }
  
  // Then stop gracefully (saves data, returns motors)
  return queueFetch<{ success: boolean; msg: string }>('/re/stop', {
    method: 'POST',
  })
}

export function useStopScan() {
  return useMutation({
    mutationFn: stopRunningScan,
  })
}
