/// <reference types="vite/client" />

// In dev: empty string — vite proxies /api/* and /ws/* to localhost:8000
// In production: set VITE_API_BASE to the Railway gateway URL
const _raw = (import.meta.env.VITE_API_BASE ?? '').trim()
export const API_BASE = _raw && !_raw.startsWith('http') ? `https://${_raw}` : _raw

function inferredBackendBase(): string {
  if (API_BASE || typeof window === 'undefined') return ''

  const { protocol, host, hostname, port } = window.location
  if (port === '8000') return `${protocol}//${host}`
  return `${protocol}//${hostname}:8000`
}

function candidateApiUrls(url: string): string[] {
  const candidates = [url]
  const fallbackBase = inferredBackendBase()

  if (fallbackBase && url.startsWith('/')) {
    candidates.push(`${fallbackBase}${url}`)
  }

  return [...new Set(candidates)]
}

export function wsBase(): string {
  if (API_BASE) {
    return API_BASE.replace('https://', 'wss://').replace('http://', 'ws://')
  }
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}`
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
      'Ensure Mithrandir backend is running and refresh.',
    )
  }

  try {
    return JSON.parse(body) as T
  } catch {
    throw new Error(
      `${endpointLabel} returned non-JSON (content-type: ${ct || 'unknown'}). ` +
      `Body: ${body.slice(0, 120)}`,
    )
  }
}

async function fetchJsonWithRetry<T>(
  url: string,
  endpointLabel: string,
  init?: RequestInit,
  attempts = 3,
): Promise<T> {
  let lastError: unknown = null

  for (const candidateUrl of candidateApiUrls(url)) {
    for (let i = 0; i < attempts; i++) {
      try {
        const r = await fetch(candidateUrl, init)
        return await parseJsonOrThrow<T>(r, endpointLabel)
      } catch (e) {
        lastError = e
        const isHtml = e instanceof Error && e.message.includes('returned HTML instead of JSON')
        const isNetwork = e instanceof TypeError

        if ((isHtml || isNetwork) && candidateUrl !== candidateApiUrls(url).slice(-1)[0]) {
          break
        }

        if (!isHtml || i === attempts - 1) {
          break
        }

        await new Promise(res => setTimeout(res, 120 * (i + 1)))
      }
    }
  }

  if (lastError instanceof Error) throw lastError
  throw new Error(`${endpointLabel}: exhausted ${attempts} attempts`)
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyJson = any

export async function fetchParams(): Promise<AnyJson> {
  return fetchJsonWithRetry<AnyJson>(`${API_BASE}/api/params`, 'params')
}

export async function saveParams(params: object): Promise<AnyJson> {
  return fetchJsonWithRetry<AnyJson>(`${API_BASE}/api/params`, 'params', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
}

export async function fetchHistory(): Promise<AnyJson[]> {
  const data = await fetchJsonWithRetry<{ exchanges?: AnyJson[] }>(`${API_BASE}/api/history`, 'history')
  return data.exchanges ?? []
}

export async function fetchHistoryItem(id: string): Promise<AnyJson> {
  return fetchJsonWithRetry<AnyJson>(`${API_BASE}/api/history/${id}`, 'history/item')
}

export async function fetchPortfolio(): Promise<AnyJson[]> {
  const data = await fetchJsonWithRetry<{ picks?: AnyJson[] }>(`${API_BASE}/api/portfolio`, 'portfolio')
  return data.picks ?? []
}

export async function fetchRegime(): Promise<AnyJson> {
  return fetchJsonWithRetry<AnyJson>(`${API_BASE}/api/regime`, 'regime')
}

export async function fetchMemory(): Promise<AnyJson> {
  return fetchJsonWithRetry<AnyJson>(`${API_BASE}/api/memory`, 'memory')
}

export async function fetchMind(): Promise<AnyJson> {
  return fetchJsonWithRetry<AnyJson>(`${API_BASE}/api/mind`, 'mind')
}

export async function generateMindReflection(prompt: string): Promise<string> {
  const data = await fetchJsonWithRetry<{ response?: string }>(`${API_BASE}/api/chat`, 'chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: prompt,
      response_mode: 'visual',
      tts: false,
    }),
  })
  return String(data.response ?? '').trim()
}

export async function rateMemory(id: string, rating: number | null): Promise<void> {
  const r = await fetch(`${API_BASE}/api/memory/${id}/rate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rating }),
  })
  if (!r.ok) throw new Error(`rateMemory ${r.status}: ${(await r.text()).slice(0, 200)}`)
}

export async function deleteMemory(id: string): Promise<void> {
  const r = await fetch(`${API_BASE}/api/memory/${id}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`deleteMemory ${r.status}: ${(await r.text()).slice(0, 200)}`)
}

export async function submitSpeechFeedback(body: {
  exchange_id?: string
  user_text?: string
  assistant_text?: string
  spoken_text?: string
  feedback?: string
  corrected_text?: string
  issue_tags?: string | string[]
}): Promise<AnyJson> {
  return fetchJsonWithRetry<AnyJson>(`${API_BASE}/api/speech/feedback`, 'speech/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function fetchDocs(): Promise<AnyJson> {
  return fetchJsonWithRetry<AnyJson>(`${API_BASE}/api/docs`, 'docs')
}

export async function searchDocs(query: string): Promise<AnyJson> {
  return fetchJsonWithRetry<AnyJson>(
    `${API_BASE}/api/docs/search?q=${encodeURIComponent(query)}`,
    'docs/search',
  )
}

export function createChatSocket(
  onStep: (msg: string) => void,
  onToken: (token: string) => void,
  onResponse: (msg: string) => void,
  onSpokenPreview: (msg: string) => void,
  onDone: () => void,
  onError: (e: string) => void,
  onAudio?: (b64: string, fmt: string) => void,
  onTtsError?: (msg: string) => void,
): WebSocket {
  const ws = new WebSocket(`${wsBase()}/ws/chat`)
  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data)
    if (data.type === 'step')      onStep(data.content)
    if (data.type === 'token')     onToken(data.content)
    if (data.type === 'response')  onResponse(data.content)
    if (data.type === 'spoken_preview') onSpokenPreview(data.content)
    if (data.type === 'done')      onDone()
    if (data.type === 'error')     onError(data.content)
    if (data.type === 'tts_error' && onTtsError) onTtsError(data.content)
    if ((data.type === 'tts_chunk' || data.type === 'tts_audio' || data.type === 'tts_prelude_chunk') && onAudio)
      onAudio(data.data, data.format ?? 'wav')
  }
  ws.onclose = () => { try { onDone() } catch {} }
  ws.onerror = () => { try { onError('chat socket error'); onDone() } catch {} }
  return ws
}

export function createGpuSocket(onStats: (s: object) => void): WebSocket {
  const ws = new WebSocket(`${wsBase()}/ws/gpu`)
  ws.onmessage = (ev) => onStats(JSON.parse(ev.data))
  return ws
}

// ─────────────────────────────────────────────────────────────────────────────
// Avalon — datacenter siting (phase7 bridge)
// ─────────────────────────────────────────────────────────────────────────────

export interface SitingSite {
  site_id: string
  name:    string
  lat:     number
  lon:     number
  acres?:  number | null
  state?:  string
  notes?:  string
}

export interface SitingFactor {
  name:        string
  implemented: boolean
  provenance:  Record<string, unknown>
}

export interface SitingScore {
  site_id:        string
  name:           string
  state:          string
  lat:            number | null
  lon:            number | null
  acres:          number | null
  composite:      number
  archetype:      string
  sub_scores:     Record<string, number>
  raw_sub_scores: Record<string, number | null>
  kill_flags:     Record<string, boolean>
  weights_used:   Record<string, number>
  provenance:     Record<string, unknown>
}

export async function fetchSitingSample(): Promise<{ sites: SitingSite[] }> {
  return fetchJsonWithRetry(`${API_BASE}/api/siting/sample`, 'siting/sample')
}

export async function fetchSitingFactors(): Promise<{ factors: SitingFactor[] }> {
  return fetchJsonWithRetry(`${API_BASE}/api/siting/factors`, 'siting/factors')
}

export async function fetchSitingWeights(
  archetype: 'training' | 'inference' | 'mixed',
): Promise<{ archetype: string; weights: Record<string, number> }> {
  return fetchJsonWithRetry(
    `${API_BASE}/api/siting/weights?archetype=${archetype}`,
    'siting/weights',
  )
}

export async function scoreSites(body: {
  archetype?: 'training' | 'inference' | 'mixed'
  weight_overrides?: Record<string, number>
  sites?: SitingSite[]
}): Promise<{ archetype: string; count: number; results: SitingScore[] }> {
  return fetchJsonWithRetry(`${API_BASE}/api/siting/score`, 'siting/score', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// Mind panel live tools — Orator snapshot, Avalon site scout, regime pulse
// ─────────────────────────────────────────────────────────────────────────────

export interface MacroSnapshotBrief {
  date: string
  recession_composite: number
  recession_label: string
  stagflation_score: number
  yield_curve_spread_2_10: number
  yield_curve_inverted: boolean
  vix: number
  vix_regime: string
  hy_spread: number
  unemployment: number
  cpi_yoy: number
  fed_funds_rate: number
  top_signals: Array<{ name: string; value: string; state: string }>
  narrative: string
}

export async function fetchOratorSnapshot(): Promise<MacroSnapshotBrief> {
  return fetchJsonWithRetry(`${API_BASE}/api/mind/orator-snapshot`, 'mind/orator-snapshot')
}

export interface SiteScoutResult {
  site_id: string
  name: string
  state: string
  composite: number
  archetype: string
}

export async function fetchSiteScout(query: string, archetype: string): Promise<{ results: SiteScoutResult[]; query: string }> {
  return fetchJsonWithRetry(
    `${API_BASE}/api/mind/site-scout?q=${encodeURIComponent(query)}&archetype=${encodeURIComponent(archetype)}`,
    'mind/site-scout',
  )
}

export interface RegimePulse {
  regime: string
  confidence: number
  signals: Array<{ name: string; value: string; direction: string }>
  updated: string
}

export async function fetchRegimePulse(): Promise<RegimePulse> {
  return fetchJsonWithRetry(`${API_BASE}/api/mind/regime-pulse`, 'mind/regime-pulse')
}
