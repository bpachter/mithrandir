import { useEffect, useState } from 'react'
import Header          from './components/Header'
import ChatPanel       from './components/ChatPanel'
import GpuPanel        from './components/GpuPanel'
import SystemMiniPanel from './components/SystemMiniPanel'
import ModelParamsPanel from './components/ModelParamsPanel'
import MarketPanel     from './components/MarketPanel'
import MemoryPanel     from './components/MemoryPanel'
import HistoryPanel    from './components/HistoryPanel'
import VoicePanel      from './components/VoicePanel'
import { useStore }    from './store'
import { createGpuSocket } from './api'

type RightBottomTab = 'params' | 'memory'

export default function App() {
  const setGpuStats          = useStore((s) => s.setGpuStats)
  const [rbTab, setRbTab]    = useState<RightBottomTab>('params')

  // GPU WebSocket lives here — always connected regardless of which panel is visible
  useEffect(() => {
    const ws = createGpuSocket((s) => setGpuStats(s as any))
    return () => ws.close()
  }, [])

  return (
    <div className="app-grid">
      {/* ── Row 1: header ── */}
      <Header />

      {/* ── Left column: Voice + compact system stats ── */}
      <div className="col-left">
        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
          <VoicePanel />
        </div>
        <SystemMiniPanel />
      </div>

      {/* ── Center column: Chat + History ── */}
      <div className="col-center">
        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
          <ChatPanel />
        </div>
        <div style={{ flexShrink: 0, height: 180, borderTop: '1px solid var(--border)', overflow: 'hidden' }}>
          <HistoryPanel />
        </div>
      </div>

      {/* ── Right column: Market (top) + Params/Memory tabs (bottom) ── */}
      <div className="col-right">
        {/* Market — takes remaining space */}
        <div style={{ flex: 3, minHeight: 0, overflow: 'hidden' }}>
          <MarketPanel />
        </div>

        {/* Params / Memory tab strip */}
        <div style={{ flex: 2, minHeight: 0, display: 'flex', flexDirection: 'column', borderTop: '1px solid var(--border)', overflow: 'hidden' }}>
          <div className="tab-bar">
            <button
              className={`tab-btn ${rbTab === 'params' ? 'active' : ''}`}
              onClick={() => setRbTab('params')}
            >
              PARAMS
            </button>
            <button
              className={`tab-btn ${rbTab === 'memory' ? 'active' : ''}`}
              onClick={() => setRbTab('memory')}
            >
              MEMORY
            </button>
            <button
              className="tab-btn"
              onClick={() => {
                const ws = createGpuSocket((s) => setGpuStats(s as any))
                setTimeout(() => ws.close(), 100)
              }}
              title="Full GPU breakdown (SYSTEM tab removed — stats always visible)"
              style={{ display: 'none' }}
            >
              SYSTEM
            </button>
          </div>
          <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
            {rbTab === 'params' && <ModelParamsPanel />}
            {rbTab === 'memory' && <MemoryPanel />}
          </div>
        </div>

        {/* Full GPU detail panel — accessible via a collapsible */}
        <details style={{ flexShrink: 0, borderTop: '1px solid var(--border)' }}>
          <summary style={{
            padding: '4px 12px', fontSize: 10, letterSpacing: '0.12em',
            color: 'var(--amber-dim)', cursor: 'pointer', listStyle: 'none',
            background: 'var(--bg-panel)',
          }}>
            ▸ GPU DETAIL
          </summary>
          <div style={{ maxHeight: 220, overflow: 'auto' }}>
            <GpuPanel />
          </div>
        </details>
      </div>
    </div>
  )
}
