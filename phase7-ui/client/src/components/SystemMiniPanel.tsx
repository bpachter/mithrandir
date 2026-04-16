/**
 * SystemMiniPanel.tsx — compact always-visible GPU/CPU/RAM strip
 * Lives at the bottom of the left sidebar. Reads from Zustand store,
 * which is populated by the GPU WebSocket connected in App.tsx.
 */

import { useStore } from '../store'

function colorFor(v: number, warn: number, crit: number) {
  if (v >= crit) return { text: 'var(--red)',   fill: 'var(--red)' }
  if (v >= warn) return { text: 'var(--amber)', fill: 'var(--amber)' }
  return          { text: 'var(--cyan)',  fill: 'var(--cyan)' }
}

interface MiniRowProps {
  label: string
  value: number
  max: number
  display: string
  extra?: string
  warnAt: number
  critAt: number
}

function MiniRow({ label, value, max, display, extra, warnAt, critAt }: MiniRowProps) {
  const pct    = Math.min(100, (value / max) * 100)
  const colors = colorFor(value, warnAt, critAt)
  return (
    <div className="sys-mini-row">
      <span className="sys-mini-label">{label}</span>
      <span className="sys-mini-val" style={{ color: colors.text, textShadow: `0 0 6px ${colors.text}40` }}>
        {display}
      </span>
      <div className="sys-mini-bar">
        <div className="sys-mini-fill" style={{ width: `${pct}%`, background: colors.fill }} />
      </div>
      {extra && <span className="sys-mini-extra">{extra}</span>}
    </div>
  )
}

export default function SystemMiniPanel() {
  const stats = useStore((s) => s.gpuStats)
  if (!stats) return (
    <div className="sys-mini">
      <div className="sys-mini-title">◈ SYS</div>
      <div style={{ fontSize: 10, color: 'var(--white-dim)' }}>connecting…</div>
    </div>
  )

  const vramPct = (stats.vram_used / stats.vram_total) * 100

  return (
    <div className="sys-mini">
      <div className="sys-mini-title">◈ SYS</div>

      <MiniRow
        label="VRAM"
        value={vramPct} max={100}
        display={`${vramPct.toFixed(0)}%`}
        extra={`${(stats.vram_used / 1024).toFixed(1)}G`}
        warnAt={70} critAt={90}
      />
      <MiniRow
        label="GPU"
        value={stats.gpu_util} max={100}
        display={`${stats.gpu_util.toFixed(0)}%`}
        extra={`${stats.temp.toFixed(0)}°`}
        warnAt={70} critAt={90}
      />
      <MiniRow
        label="CPU"
        value={stats.cpu_percent} max={100}
        display={`${stats.cpu_percent.toFixed(0)}%`}
        warnAt={70} critAt={90}
      />
      <MiniRow
        label="RAM"
        value={stats.ram_percent} max={100}
        display={`${stats.ram_percent.toFixed(0)}%`}
        extra={`${stats.ram_used_gb}G`}
        warnAt={70} critAt={90}
      />
    </div>
  )
}
