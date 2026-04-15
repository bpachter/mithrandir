const BASE = 'http://localhost:8000'

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

export function createChatSocket(
  onStep: (msg: string) => void,
  onToken: (token: string) => void,
  onResponse: (msg: string) => void,
  onDone: () => void,
  onError: (e: string) => void,
): WebSocket {
  const ws = new WebSocket('ws://localhost:8000/ws/chat')
  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data)
    if (data.type === 'step')     onStep(data.content)
    if (data.type === 'token')    onToken(data.content)
    if (data.type === 'response') onResponse(data.content)
    if (data.type === 'done')     onDone()
    if (data.type === 'error')    onError(data.content)
  }
  return ws
}

export function createGpuSocket(onStats: (s: object) => void): WebSocket {
  const ws = new WebSocket('ws://localhost:8000/ws/gpu')
  ws.onmessage = (ev) => onStats(JSON.parse(ev.data))
  return ws
}
