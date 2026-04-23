import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Map as MapIcon, Settings2, BookText, Code2 } from 'lucide-react'
import Header           from './components/Header'
import ChatPanel        from './components/ChatPanel'
import GpuHistoryPanel  from './components/GpuHistoryPanel'
import ModelParamsPanel from './components/ModelParamsPanel'
import MarketPanel      from './components/MarketPanel'
import MemoryPanel      from './components/MemoryPanel'
import DocsPanel        from './components/DocsPanel'
import SitingPanel      from './components/SitingPanel'
import DevPanel         from './components/DevPanel'
import { useStore }     from './store'
import { createGpuSocket } from './api'

type LeftTab = 'params' | 'docs'
type AppMode = 'terminal' | 'avalon' | 'dev'

export default function App() {
  const setGpuStats          = useStore((s) => s.setGpuStats)
  const pushGpuHistory       = useStore((s) => s.pushGpuHistory)
  const setPendingChatInput  = useStore((s) => s.setPendingChatInput)
  const [leftTab, setLeftTab] = useState<LeftTab>('params')
  const [mode,    setMode]    = useState<AppMode>('terminal')

  // GPU WebSocket lives here — always connected regardless of which panel is visible.
  useEffect(() => {
    const ws = createGpuSocket((raw) => {
      const s = raw as Record<string, number>
      setGpuStats(s as never)
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
  }, [setGpuStats, pushGpuHistory])

  if (mode === 'avalon') {
    return <SitingPanel onClose={() => setMode('terminal')} />
  }

  if (mode === 'dev') {
    return <DevPanel onClose={() => setMode('terminal')} />
  }

  return (
    <div className="app-grid">
      <Header />

      {/* Avalon launch button — pinned to header, themed cyan operator action */}
      <button
        onClick={() => setMode('avalon')}
        title="Open Avalon — datacenter siting console"
        className="
          group fixed top-2 right-[230px] z-50
          inline-flex items-center gap-2 rounded-sm border border-cyan-dim bg-cyan-soft
          px-3 py-1 font-display text-[10.5px] font-semibold uppercase tracking-[0.22em]
          text-cyan transition-all duration-150
          hover:border-cyan hover:bg-cyan/10 hover:shadow-[0_0_14px_-4px_var(--cyan-glow)]
          focus-visible:outline focus-visible:outline-1 focus-visible:outline-cyan focus-visible:outline-offset-2
        "
      >
        <MapIcon className="h-3 w-3" strokeWidth={2.4} />
        Avalon
      </button>

      {/* Dev panel launch button */}
      <button
        onClick={() => setMode('dev')}
        title="Open Enkidu Dev — AI-driven code orchestration"
        className="
          group fixed top-2 right-[320px] z-50
          inline-flex items-center gap-2 rounded-sm border border-violet-800/50 bg-violet-900/20
          px-3 py-1 font-display text-[10.5px] font-semibold uppercase tracking-[0.22em]
          text-violet-400 transition-all duration-150
          hover:border-violet-500 hover:bg-violet-900/40 hover:shadow-[0_0_14px_-4px_rgba(139,92,246,0.5)]
          focus-visible:outline focus-visible:outline-1 focus-visible:outline-violet-500 focus-visible:outline-offset-2
        "
      >
        <Code2 className="h-3 w-3" strokeWidth={2.4} />
        Dev
      </button>

      {/* Hardware monitoring strip */}
      <div className="hw-bar-row">
        <GpuHistoryPanel />
      </div>

      {/* Left column: Params / Docs */}
      <div className="col-left">
        <div className="tab-bar">
          <button
            className={`tab-btn ${leftTab === 'params' ? 'active' : ''}`}
            onClick={() => setLeftTab('params')}
          >
            <Settings2 className="mr-1.5 inline h-3 w-3 -translate-y-px" strokeWidth={2.2} />
            Params
          </button>
          <button
            className={`tab-btn ${leftTab === 'docs' ? 'active' : ''}`}
            onClick={() => setLeftTab('docs')}
          >
            <BookText className="mr-1.5 inline h-3 w-3 -translate-y-px" strokeWidth={2.2} />
            CUDA
          </button>
        </div>
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
          <AnimatePresence mode="wait">
            <motion.div
              key={leftTab}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.18 }}
              style={{ height: '100%' }}
            >
              {leftTab === 'params' && <ModelParamsPanel />}
              {leftTab === 'docs'   && (
                <DocsPanel onAskEnkidu={(q) => setPendingChatInput(q)} />
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      {/* Center column: Chat + Memory */}
      <div className="col-chat">
        <ChatPanel />
        <div
          className="border-t border-border overflow-hidden flex flex-col flex-shrink-0"
          style={{ height: 180 }}
        >
          <MemoryPanel />
        </div>
      </div>

      {/* Right column: Market intelligence */}
      <div className="col-right">
        <div className="flex-1 min-h-0 overflow-hidden">
          <MarketPanel />
        </div>
      </div>
    </div>
  )
}
