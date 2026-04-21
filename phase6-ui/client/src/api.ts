/// <reference types="vite/client" />

// In dev: empty string — vite proxies /api/* and /ws/* to localhost:8000
// In production: set VITE_API_BASE to the Railway gateway URL
const _raw = (import.meta.env.VITE_API_BASE ?? '').trim()
const API_BASE = _raw && !_raw.startsWith('http') ? `https://${_raw}` : _raw

function wsBase(): string {
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
      'Ensure Enkidu backend is running and refresh.',
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
  for (let i = 0; i < attempts; i++) {
    const r = await fetch(url, init)
    try {
      return await parseJsonOrThrow<T>(r, endpointLabel)
    } catch (e) {
      const isHtml = e instanceof Error && e.message.includes('returned HTML instead of JSON')
      if (!isHtml || i === attempts - 1) throw e
      await new Promise(res => setTimeout(res, 120 * (i + 1)))
    }
  }
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
    if (data.type === 'done')      onDone()
    if (data.type === 'error')     onError(data.content)
    if (data.type === 'tts_error' && onTtsError) onTtsError(data.content)
    if ((data.type === 'tts_chunk' || data.type === 'tts_audio') && onAudio)
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
