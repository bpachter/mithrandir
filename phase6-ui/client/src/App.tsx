import { useEffect, useState } from 'react'
import Header           from './components/Header'
import ChatPanel        from './components/ChatPanel'
import GpuHistoryPanel  from './components/GpuHistoryPanel'
import ModelParamsPanel from './components/ModelParamsPanel'
import MarketPanel      from './components/MarketPanel'
import MemoryPanel      from './components/MemoryPanel'
import HistoryPanel     from './components/HistoryPanel'
import DocsPanel        from './components/DocsPanel'
import DemoPanel        from './components/DemoPanel'
import { useStore }     from './store'
import { createGpuSocket } from './api'

type LeftTab = 'params' | 'docs' | 'demo'

export default function App() {
  const setGpuStats          = useStore((s) => s.setGpuStats)
  const pushGpuHistory       = useStore((s) => s.pushGpuHistory)
  const setPendingChatInput  = useStore((s) => s.setPendingChatInput)
  const [leftTab, setLeftTab] = useState<LeftTab>('params')

  // GPU WebSocket lives here — always connected regardless of which panel is visible
  useEffect(() => {
    const ws = createGpuSocket((raw) => {
      const s = raw as any
      setGpuStats(s)
      pushGpuHistory({
        ts:          Date.now(),
        gpu_util:    s.gpu_util,
        vram_pct:    (s.vram_used / s.vram_total) * 100,
        temp:        s.temp,
        power:       s.power_draw,
        clock_sm:    s.clock_sm  ?? 0,
        clock_mem:   s.clock_mem ?? 0,
        cpu_percent: s.cpu_percent,
      })
    })
    return () => ws.close()
  }, [])

  return (
    <div className="app-grid">
      {/* ── Row 1: header ── */}
      <Header />

      {/* ── Row 2: hardware bar — spans full width ── */}
      <div className="hw-bar-row">
        <GpuHistoryPanel />
      </div>

      {/* ── Left column: Params / Cuda docs / Demos ── */}
      <div className="col-left">
        <div className="tab-bar">
          <button className={`tab-btn ${leftTab === 'params' ? 'active' : ''}`} onClick={() => setLeftTab('params')}>PARAMS</button>
          <button className={`tab-btn ${leftTab === 'docs'   ? 'active' : ''}`} onClick={() => setLeftTab('docs')}>CUDA</button>
          <button className={`tab-btn ${leftTab === 'demo'   ? 'active' : ''}`} onClick={() => setLeftTab('demo')}>DEMOS</button>
        </div>
        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
          {leftTab === 'params' && <ModelParamsPanel />}
          {leftTab === 'docs'   && (
            <DocsPanel onAskEnkidu={(q) => {
              setPendingChatInput(q)
            }} />
          )}
          {leftTab === 'demo'   && (
            <DemoPanel onAskEnkidu={(q) => {
              setPendingChatInput(q)
            }} />
          )}
        </div>
      </div>

      {/* ── Middle column: Chat (with integrated voice) + History ── */}
      <div className="col-chat">
        <ChatPanel />
        <div style={{ flexShrink: 0, height: 180, borderTop: '1px solid var(--border)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <HistoryPanel />
        </div>
      </div>

      {/* ── Right column: Market + Memory ── */}
      <div className="col-right">
        <div style={{ flex: 3, minHeight: 0, overflow: 'hidden' }}>
          <MarketPanel />
        </div>
        <div style={{ flex: 2, minHeight: 0, display: 'flex', flexDirection: 'column', borderTop: '1px solid var(--border)', overflow: 'hidden' }}>
          <MemoryPanel />
        </div>
      </div>
    </div>
  )
}
