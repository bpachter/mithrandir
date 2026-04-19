const BASE = 'http://localhost:8000'

function isHtmlInsteadOfJsonError(e: unknown): boolean {
  return e instanceof Error && e.message.includes('returned HTML instead of JSON')
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function fetchJsonWithRetry<T>(
  url: string,
  endpointLabel: string,
  init?: RequestInit,
  attempts = 3,
): Promise<T> {
  let lastErr: unknown
  for (let i = 0; i < attempts; i++) {
    try {
      const r = await fetch(url, init)
      return await parseJsonOrThrow<T>(r, endpointLabel)
    } catch (e) {
      lastErr = e
      if (!isHtmlInsteadOfJsonError(e) || i === attempts - 1) {
        throw e
      }
      await delay(120 * (i + 1))
    }
  }
  throw lastErr
}

async function parseJsonOrThrow<T>(r: Response, endpointLabel: string): Promise<T> {
  const ct = (r.headers.get('content-type') || '').toLowerCase()
  const body = await r.text()

  if (!r.ok) {
    throw new Error(`${endpointLabel} ${r.status}: ${body.slice(0, 200)}`)
  }

  const trimmed = body.trimStart().toLowerCase()
  if (trimmed.startsWith('<!doctype') || trimmed.startsWith('<html')) {
    throw new Error(
      `${endpointLabel} returned HTML instead of JSON. ` +
      'Ensure phase6-ui backend is running on http://localhost:8000 and refresh the browser.',
    )
  }

  try {
    return JSON.parse(body) as T
  } catch {
    throw new Error(
      `${endpointLabel} returned non-JSON payload (content-type: ${ct || 'unknown'}). ` +
      `Body head: ${body.slice(0, 120)}`,
    )
  }
}

export async function fetchParams() {
  const r = await fetch(`${BASE}/api/params`)
  return r.json()
}

export async function saveParams(params: object) {
  const r = await fetch(`${BASE}/api/params`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  return r.json()
}

export async function fetchHistoryItem(id: string) {
  const r = await fetch(`${BASE}/api/history/${id}`)
  return r.json()
}

export async function fetchHistory() {
  const r = await fetch(`${BASE}/api/history`)
  const data = await r.json()
  return data.exchanges ?? []
}

export async function fetchPortfolio() {
  const r = await fetch(`${BASE}/api/portfolio`)
  const data = await r.json()
  return data.picks ?? []
}

export async function fetchRegime() {
  const r = await fetch(`${BASE}/api/regime`)
  return r.json()
}

export async function fetchMemory() {
  const r = await fetch(`${BASE}/api/memory`)
  return r.json()
}

export async function rateMemory(id: string, rating: number | null) {
  await fetch(`${BASE}/api/memory/${id}/rate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rating }),
  })
}

export async function deleteMemory(id: string) {
  await fetch(`${BASE}/api/memory/${id}`, { method: 'DELETE' })
}

export async function fetchDocs() {
  const r = await fetch(`${BASE}/api/docs`)
  return r.json()  // { docs: DocEntry[], categories: string[] }
}

export async function searchDocs(query: string) {
  const r = await fetch(`${BASE}/api/docs/search?q=${encodeURIComponent(query)}`)
  return r.json()  // { results: string, query: string }
}

export function createChatSocket(
  onStep: (msg: string) => void,
  onToken: (token: string) => void,
  onResponse: (msg: string) => void,
  onDone: () => void,
  onError: (e: string) => void,
  onAudio?: (b64: string, fmt: string) => void,
  onTtsError?: (msg: string) => void,
): WebSocket {
  const ws = new WebSocket('ws://localhost:8000/ws/chat')
  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data)
    if (data.type === 'step')      onStep(data.content)
    if (data.type === 'token')     onToken(data.content)
    if (data.type === 'response')  onResponse(data.content)
    if (data.type === 'done')      onDone()
    if (data.type === 'error')     onError(data.content)
    if (data.type === 'tts_error' && onTtsError) onTtsError(data.content)
    // tts_chunk: sentence-by-sentence streaming (primary path)
    // tts_audio: single-shot legacy (kept for backward compat)
    if ((data.type === 'tts_chunk' || data.type === 'tts_audio') && onAudio)
      onAudio(data.data, data.format ?? 'wav')
  }
  // If the socket drops mid-response, synthesize a "done" event so the UI
  // releases the busy spinner and the buttons become clickable again.
  ws.onclose = () => { try { onDone() } catch {} }
  ws.onerror = () => { try { onError('chat socket error'); onDone() } catch {} }
  return ws
}

export function createGpuSocket(onStats: (s: object) => void): WebSocket {
  const ws = new WebSocket('ws://localhost:8000/ws/gpu')
  ws.onmessage = (ev) => onStats(JSON.parse(ev.data))
  return ws
}


// ─────────────────────────────────────────────────────────────────────────
// Phase 7 — Data Center Siting
// ─────────────────────────────────────────────────────────────────────────

export type Archetype = 'training' | 'inference' | 'mixed'

export interface FactorResultDTO {
  factor: string
  raw_value: number | null
  normalized: number          // 0..1
  weight: number
  weighted: number            // weight * normalized
  killed: boolean
  provenance: Record<string, unknown>
}

export interface SiteResultDTO {
  site_id: string
  lat: number
  lon: number
  composite: number           // 0..10
  factors: Record<string, FactorResultDTO>
  kill_flags: Record<string, boolean>
  imputed: string[]
  provenance: Record<string, unknown>
  extras?: Record<string, unknown>
}

export interface SitingFactorsResponse {
  factors: string[]
  default_archetype: Archetype
  weights: Record<Archetype, Record<string, number>>
  kill_criteria: Record<string, unknown>
}

export interface SitingLayer {
  key: string
  source: string
  layer: string
  name: string
  cached: boolean
}

export async function fetchSitingFactors(): Promise<SitingFactorsResponse> {
  return fetchJsonWithRetry<SitingFactorsResponse>(
    `${BASE}/api/siting/factors`,
    'siting/factors',
  )
}

export async function fetchSitingSample(): Promise<{ results?: SiteResultDTO[]; sites?: Array<{ site_id: string; lat: number; lon: number; [k: string]: unknown }> }> {
  return fetchJsonWithRetry<{
    results?: SiteResultDTO[]
    sites?: Array<{ site_id: string; lat: number; lon: number; [k: string]: unknown }>
  }>(
    `${BASE}/api/siting/sample`,
    'siting/sample',
  )
}

export async function scoreSites(payload: {
  sites: Array<{ site_id: string; lat: number; lon: number; [k: string]: unknown }>
  archetype?: Archetype
  weight_overrides?: Record<string, number>
}): Promise<{ results: SiteResultDTO[] }> {
  return fetchJsonWithRetry<{ results: SiteResultDTO[] }>(
    `${BASE}/api/siting/score`,
    'siting/score',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export async function fetchSitingLayers(): Promise<{
  layers: SitingLayer[]
  data_sources: Record<string, unknown>
}> {
  return fetchJsonWithRetry<{
    layers: SitingLayer[]
    data_sources: Record<string, unknown>
  }>(
    `${BASE}/api/siting/layers`,
    'siting/layers',
  )
}

export interface SitingLayerGeoJSON {
  type: 'FeatureCollection'
  features: GeoJSON.Feature[]
  _meta: {
    layer: string
    name: string
    source: string
    returned: number
    limit: number
    bbox: string | null
    cache_path: string
  }
}

export async function fetchSitingLayerGeoJSON(
  layerKey: string,
  bbox?: [number, number, number, number],
  limit = 5000,
): Promise<SitingLayerGeoJSON | { error: string }> {
  const params = new URLSearchParams()
  if (bbox) params.set('bbox', bbox.join(','))
  params.set('limit', String(limit))
  const url = `${BASE}/api/siting/layer/${layerKey}?${params.toString()}`
  let lastErr: unknown
  for (let i = 0; i < 3; i++) {
    const r = await fetch(url)
    if (r.status === 404) {
      const text = await r.text()
      let j: { error?: string } = {}
      try {
        j = JSON.parse(text)
      } catch {
        j = {}
      }
      return { error: j.error ?? 'not cached' }
    }
    try {
      return await parseJsonOrThrow<SitingLayerGeoJSON>(r, `siting/layer/${layerKey}`)
    } catch (e) {
      lastErr = e
      if (!isHtmlInsteadOfJsonError(e) || i === 2) {
        throw e
      }
      await delay(120 * (i + 1))
    }
  }
  throw lastErr
}
