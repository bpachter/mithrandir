import { useEffect, useState } from 'react'
import { Activity, Cpu, Thermometer, Zap, RadioTower } from 'lucide-react'
import { useStore } from '../store'
import { StatusDot, Tooltip } from './ui'

export default function Header() {
  const busy   = useStore((s) => s.busy)
  const regime = useStore((s) => s.regime)
  const gpu    = useStore((s) => s.gpuStats)

  // Live wall clock — updates once a second so the header feels alive.
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  const date = now.toISOString().slice(0, 10)
  const time = now.toISOString().slice(11, 19)

  const vramPct   = gpu ? Math.round((gpu.vram_used / gpu.vram_total) * 100) : null
  const vramGB    = gpu ? (gpu.vram_used / 1024).toFixed(1) : null
  const tempTone  = gpu
    ? gpu.temp >= 85 ? 'text-rose'
    : gpu.temp >= 70 ? 'text-amber'
    : 'text-emerald'
    : 'text-muted'

  return (
    <header className="app-header panel">
      <span className="header-logo">MITHRANDIR</span>
      <span className="hidden h-5 w-px bg-border md:inline-block" />
      <div className="hidden items-center gap-2 text-2xs uppercase tracking-[0.18em] text-muted md:flex">
        <span className="font-display font-semibold text-fg-strong">v8.0</span>
        <span className="text-subtle">·</span>
        <span>THE GREY</span>
        <span className="text-subtle">·</span>
        <span>RTX 4090</span>
        <span className="text-subtle">·</span>
        <span className="tabular">{date}</span>
        <span className="text-subtle">·</span>
        <span className="tabular text-cyan">{time}Z</span>
      </div>

      {regime && (
        <Tooltip content={`Regime confidence: ${Math.round(regime.confidence * 100)}%`}>
          <span className={`regime-badge ${regime.regime.toLowerCase()}`} style={{ marginLeft: 12 }}>
            <RadioTower className="h-3 w-3" strokeWidth={2.2} />
            {regime.regime}
            <span className="opacity-70 ml-1 text-[10px] tabular">{Math.round(regime.confidence * 100)}%</span>
          </span>
        </Tooltip>
      )}

      {gpu && (
        <div className="ml-auto hidden items-center gap-3 lg:flex">
          <Tooltip content={`VRAM: ${(gpu.vram_used / 1024).toFixed(2)} / ${(gpu.vram_total / 1024).toFixed(0)} GB`}>
            <div className="flex items-center gap-1.5 text-2xs uppercase tracking-[0.14em] text-muted">
              <Cpu className="h-3 w-3 text-cyan" strokeWidth={2.2} />
              <span className="font-display text-[13px] font-semibold text-cyan tabular">{vramPct}%</span>
              <span className="text-subtle tabular">{vramGB}G</span>
            </div>
          </Tooltip>
          <span className="h-3 w-px bg-border" />
          <Tooltip content={`GPU temp: ${gpu.temp.toFixed(1)}°C`}>
            <div className={`flex items-center gap-1.5 text-2xs uppercase tracking-[0.14em] ${tempTone}`}>
              <Thermometer className="h-3 w-3" strokeWidth={2.2} />
              <span className="font-display text-[13px] font-semibold tabular">{gpu.temp.toFixed(0)}°</span>
            </div>
          </Tooltip>
          <span className="h-3 w-px bg-border" />
          <Tooltip content={`Power draw: ${gpu.power_draw.toFixed(0)} / ${gpu.power_limit.toFixed(0)} W`}>
            <div className="flex items-center gap-1.5 text-2xs uppercase tracking-[0.14em] text-muted">
              <Zap className="h-3 w-3 text-amber" strokeWidth={2.2} />
              <span className="font-display text-[13px] font-semibold text-amber tabular">{gpu.power_draw.toFixed(0)}</span>
              <span className="text-subtle">W</span>
            </div>
          </Tooltip>
        </div>
      )}

      <div className="header-status ml-auto lg:ml-4">
        <StatusDot tone={busy ? 'amber' : 'green'} />
        <span className="font-display font-medium">
          <Activity className="mr-1.5 inline h-3 w-3 -translate-y-px" strokeWidth={2.2} />
          {busy ? 'IN COUNCIL' : 'AT WATCH'}
        </span>
      </div>
    </header>
  )
}
