import { create } from 'zustand'

export interface Message {
  id: string
  role: 'user' | 'bot'
  content: string
  steps?: string[]
  ts: number
}

export interface GpuStats {
  gpu_util: number
  mem_util: number
  vram_used: number
  vram_total: number
  temp: number
  power_draw: number
  power_limit: number
  cpu_percent: number
  ram_used_gb: number
  ram_total_gb: number
  ram_percent: number
  ts: number
}

export interface GemmaParams {
  temperature: number
  top_p: number
  top_k: number
  repeat_penalty: number
  num_ctx: number
  seed: number
}

export interface HistoryItem {
  id: string
  timestamp: string
  user: string
  assistant: string
}

export interface PortfolioPick {
  ticker: string
  sector?: string
  ev_ebit?: number
  value_composite?: number
  quality_score?: number
  f_score?: number
}

export interface RegimeInfo {
  regime: string
  confidence: number
  weekly_return?: number
  volatility_30d?: number
  as_of?: string
}

interface AppState {
  messages: Message[]
  busy: boolean
  gpuStats: GpuStats | null
  params: GemmaParams
  history: HistoryItem[]
  portfolio: PortfolioPick[]
  regime: RegimeInfo | null
  rightTab: 'gpu' | 'params' | 'market'
  bottomTab: 'history'
  activeConversationId: string | null

  addMessage: (m: Message) => void
  appendStep: (id: string, step: string) => void
  setBusy: (b: boolean) => void
  setGpuStats: (s: GpuStats) => void
  setParams: (p: Partial<GemmaParams>) => void
  setHistory: (h: HistoryItem[]) => void
  setPortfolio: (p: PortfolioPick[]) => void
  setRegime: (r: RegimeInfo) => void
  setRightTab: (t: AppState['rightTab']) => void
  clearMessages: () => void
  setActiveConversationId: (id: string | null) => void
}

export const useStore = create<AppState>((set) => ({
  messages:  [],
  busy:      false,
  gpuStats:  null,
  params: {
    temperature: 0.7, top_p: 0.9, top_k: 40,
    repeat_penalty: 1.1, num_ctx: 8192, seed: -1,
  },
  history:   [],
  portfolio: [],
  regime:    null,
  rightTab:  'gpu',
  bottomTab: 'history',
  activeConversationId: null,

  addMessage:  (m)    => set((s) => ({ messages: [...s.messages, m] })),
  appendStep:  (id, step) => set((s) => ({
    messages: s.messages.map((m) =>
      m.id === id ? { ...m, steps: [...(m.steps ?? []), step] } : m
    ),
  })),
  setBusy:     (b)    => set({ busy: b }),
  setGpuStats: (stats)=> set({ gpuStats: stats }),
  setParams:   (p)    => set((s) => ({ params: { ...s.params, ...p } })),
  setHistory:  (h)    => set({ history: h }),
  setPortfolio:(p)    => set({ portfolio: p }),
  setRegime:   (r)    => set({ regime: r }),
  setRightTab: (t)    => set({ rightTab: t }),
  clearMessages: ()   => set({ messages: [], busy: false, activeConversationId: null }),
  setActiveConversationId: (id) => set({ activeConversationId: id }),
}))
