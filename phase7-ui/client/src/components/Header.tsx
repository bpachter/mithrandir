import { useStore } from '../store'

export default function Header() {
  const busy   = useStore((s) => s.busy)
  const regime = useStore((s) => s.regime)
  const gpu    = useStore((s) => s.gpuStats)
  const now    = new Date().toISOString().slice(0, 10).replace(/-/g, '.')

  const vramPct   = gpu ? Math.round(gpu.vram_used / gpu.vram_total * 100) : null
  const vramGB    = gpu ? (gpu.vram_used / 1024).toFixed(1) : null
  const tempColor = gpu
    ? gpu.temp >= 85 ? 'var(--red)' : gpu.temp >= 70 ? 'var(--amber)' : 'var(--green)'
    : 'var(--white-dim)'

  return (
    <header className="app-header panel">
      <span className="header-logo">ENKIDU</span>
      <span className="dim" style={{ fontSize: 13 }}>░</span>
      <span className="header-meta">v8.0 · RTX 4090 · {now}</span>

      {regime && (
        <span className={`regime-badge ${regime.regime.toLowerCase()}`} style={{ marginLeft: 12 }}>
          {regime.regime}
          <span style={{ fontSize: 12, opacity: 0.7 }}> {Math.round(regime.confidence * 100)}%</span>
        </span>
      )}

      {gpu && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginLeft: 16, fontSize: 11, color: 'var(--white-dim)' }}>
          <span>
            VRAM{' '}
            <span style={{ color: 'var(--cyan)', fontFamily: 'var(--font-display)', fontSize: 14 }}>{vramPct}%</span>
            {' '}<span style={{ color: 'var(--white-dim)' }}>{vramGB}G</span>
          </span>
          <span style={{ color: 'var(--border)' }}>·</span>
          <span style={{ color: tempColor, fontFamily: 'var(--font-display)', fontSize: 14 }}>{gpu.temp.toFixed(0)}°C</span>
          <span style={{ color: 'var(--border)' }}>·</span>
          <span>
            <span style={{ color: 'var(--amber)', fontFamily: 'var(--font-display)', fontSize: 14 }}>{gpu.power_draw.toFixed(0)}</span>W
          </span>
        </div>
      )}

      <div className="header-status">
        <span className={`status-dot ${busy ? 'busy' : ''}`} />
        <span>{busy ? 'PROCESSING' : 'ONLINE'}</span>
      </div>
    </header>
  )
}
