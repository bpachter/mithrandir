import { useStore } from '../store'

function MetricBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div className="bar-track">
      <div className={`bar-fill ${color}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function colorForTemp(t: number) {
  if (t >= 85) return 'red'
  if (t >= 70) return 'amber'
  return 'green'
}

function colorForUtil(u: number) {
  if (u >= 90) return 'red'
  if (u >= 60) return 'amber'
  return 'cyan'
}

export default function GpuPanel() {
  const stats    = useStore((s) => s.gpuStats)

  // GPU WebSocket is now owned by App.tsx — GpuPanel is a pure display component

  if (!stats) {
    return (
      <div className="panel panel-right-top" style={{ minHeight: 0 }}>
        <div className="panel-title">SYSTEM</div>
        <div className="panel-body dim" style={{ fontSize: 11 }}>connecting...</div>
      </div>
    )
  }

  const vramPct = (stats.vram_used / stats.vram_total * 100).toFixed(0)

  return (
    <div className="panel panel-right-top" style={{ minHeight: 0 }}>
      <div className="panel-title">SYSTEM</div>
      <div className="gpu-grid" style={{ overflow: 'auto' }}>

        {/* GPU Utilization */}
        <div className="metric-block">
          <span className="metric-label">GPU UTIL</span>
          <span className={`metric-value ${colorForUtil(stats.gpu_util)}`}>
            {stats.gpu_util.toFixed(0)}%
          </span>
          <MetricBar value={stats.gpu_util} max={100} color={colorForUtil(stats.gpu_util)} />
        </div>

        {/* Temperature */}
        <div className="metric-block">
          <span className="metric-label">TEMP</span>
          <span className={`metric-value ${colorForTemp(stats.temp)}`}>
            {stats.temp.toFixed(0)}°C
          </span>
          <MetricBar value={stats.temp} max={100} color={colorForTemp(stats.temp)} />
        </div>

        {/* VRAM */}
        <div className="metric-block">
          <span className="metric-label">VRAM  <span className="dim">{stats.vram_used.toFixed(0)}/{stats.vram_total.toFixed(0)} MB</span></span>
          <span className="metric-value cyan">{vramPct}%</span>
          <MetricBar value={stats.vram_used} max={stats.vram_total} color="cyan" />
        </div>

        {/* Power */}
        <div className="metric-block">
          <span className="metric-label">POWER</span>
          <span className="metric-value amber">{stats.power_draw.toFixed(0)}W</span>
          <MetricBar value={stats.power_draw} max={stats.power_limit} color="amber" />
        </div>

        {/* CPU */}
        <div className="metric-block">
          <span className="metric-label">CPU</span>
          <span className="metric-value green">{stats.cpu_percent.toFixed(0)}%</span>
          <MetricBar value={stats.cpu_percent} max={100} color="green" />
        </div>

        {/* RAM */}
        <div className="metric-block">
          <span className="metric-label">RAM  <span className="dim">{stats.ram_used_gb}/{stats.ram_total_gb} GB</span></span>
          <span className="metric-value green">{stats.ram_percent.toFixed(0)}%</span>
          <MetricBar value={stats.ram_percent} max={100} color="green" />
        </div>

      </div>
    </div>
  )
}
