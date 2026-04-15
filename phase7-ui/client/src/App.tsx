import Header from './components/Header'
import ChatPanel from './components/ChatPanel'
import GpuPanel from './components/GpuPanel'
import ModelParamsPanel from './components/ModelParamsPanel'
import MarketPanel from './components/MarketPanel'
import MemoryPanel from './components/MemoryPanel'
import HistoryPanel from './components/HistoryPanel'
import { useStore } from './store'

export default function App() {
  const rightTab    = useStore((s) => s.rightTab)
  const setRightTab = useStore((s) => s.setRightTab)

  return (
    <div className="app-grid">
      {/* Row 1: Header spans full width */}
      <Header />

      {/* Row 2: Chat (left) + Right panel (right) */}
      <ChatPanel />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 0, minHeight: 0, overflow: 'hidden' }}>
        <div className="tab-bar">
          <button
            className={`tab-btn ${rightTab === 'gpu' ? 'active' : ''}`}
            onClick={() => setRightTab('gpu')}
          >
            SYSTEM
          </button>
          <button
            className={`tab-btn ${rightTab === 'params' ? 'active' : ''}`}
            onClick={() => setRightTab('params')}
          >
            PARAMS
          </button>
          <button
            className={`tab-btn ${rightTab === 'market' ? 'active' : ''}`}
            onClick={() => setRightTab('market')}
          >
            MARKET
          </button>
          <button
            className={`tab-btn ${rightTab === 'memory' ? 'active' : ''}`}
            onClick={() => setRightTab('memory')}
          >
            MEMORY
          </button>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
          {rightTab === 'gpu'    && <GpuPanel />}
          {rightTab === 'params' && <ModelParamsPanel />}
          {rightTab === 'market' && <MarketPanel />}
          {rightTab === 'memory' && <MemoryPanel />}
        </div>
      </div>

      {/* Row 3: History spans full width */}
      <HistoryPanel />
    </div>
  )
}
