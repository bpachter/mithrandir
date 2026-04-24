/**
 * GpuHistoryPanel.tsx — full-width hardware monitoring bar
 * Always visible across the top of the UI (row 2 of the app grid).
 * Each metric shows a live value + 60-second sparkline history at 2 Hz.
 */

import {
  AreaChart, Area, YAxis, ResponsiveContainer, Tooltip,
} from 'recharts'
import { useStore } from '../store'
import type { GpuHistoryPoint } from '../store'

// Palette aligned with v10 Matrix design tokens
const C = {
  gpu:      { stroke: '#00ffcc', fill: '#00ffcc18' },
  vram:     { stroke: '#00ff41', fill: '#00ff4118' },
  temp:     { stroke: '#7fff00', fill: '#7fff0018' },
  power:    { stroke: '#ff4444', fill: '#ff444418' },
  clock_sm: { stroke: '#00f5d4', fill: '#00f5d415' },
  clock_mem:{ stroke: '#00ccaa', fill: '#00ccaa15' },
  cpu:      { stroke: '#3d7a4a', fill: '#3d7a4a12' },
}

function threshold(val: number, warn: number, crit: number): string {
  if (val >= crit) return 'var(--red)'
  if (val >= warn) return 'var(--amber)'
  return 'var(--cyan)'
}

function SparkTip({ active, payload, unit }: any) {
  if (!active || !payload?.length) return null
  const v = payload[0]?.value
  return (
    <div
      style={{
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border-strong)',
        padding: '3px 7px',
        fontSize: 10,
        fontFamily: 'var(--font-mono)',
        fontVariantNumeric: 'tabular-nums',
        color: payload[0]?.color ?? 'var(--amber)',
        borderRadius: 3,
        boxShadow: '0 4px 12px -4px rgba(0,0,0,0.6)',
      }}
    >
      {typeof v === 'number' ? v.toFixed(1) : '—'}{unit}
    </div>
  )
}

// ── Single metric cell ────────────────────────────────────────────────────

interface CellProps {
  label:   string
  value:   string
  color:   string          // current value color
  data:    GpuHistoryPoint[]
  dataKey: keyof GpuHistoryPoint
  stroke:  string
  domain:  [number, number]
  unit:    string
  sub?:    string          // secondary line (e.g. "of 24G")
}

function MetricCell({ label, value, color, data, dataKey, stroke, domain, unit, sub }: CellProps) {
  return (
    <div className="hw-cell">
      <div className="hw-cell-header">
        <span className="hw-cell-label">{label}</span>
        <div>
          <span className="hw-cell-value" style={{ color, textShadow: `0 0 8px ${color}60` }}>
            {value}
          </span>
          {sub && <div className="hw-cell-sub">{sub}</div>}
        </div>
      </div>
      <div className="hw-cell-spark">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 1, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id={`hg-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={stroke} stopOpacity={0.3} />
                <stop offset="95%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <YAxis domain={domain} hide />
            <Tooltip
              content={<SparkTip unit={unit} />}
              cursor={{ stroke, strokeWidth: 1, strokeOpacity: 0.35 }}
            />
            <Area
              type="monotone"
              dataKey={dataKey as string}
              stroke={stroke}
              strokeWidth={1.5}
              fill={`url(#hg-${dataKey})`}
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ── Static cell (no sparkline — RAM, fan) ─────────────────────────────────

interface StaticCellProps {
  label:    string
  value:    string
  color:    string
  barPct?:  number
  barColor?:string
  sub?:     string
}

function StaticCell({ label, value, color, barPct, barColor, sub }: StaticCellProps) {
  return (
    <div className="hw-cell">
      <div className="hw-cell-header">
        <span className="hw-cell-label">{label}</span>
        <div>
          <span className="hw-cell-value" style={{ color, textShadow: `0 0 8px ${color}60` }}>
            {value}
          </span>
          {sub && <div className="hw-cell-sub">{sub}</div>}
        </div>
      </div>
      {barPct !== undefined && (
        <div className="hw-cell-bar-track">
          <div
            className="hw-cell-bar-fill"
            style={{ width: `${Math.min(100, barPct)}%`, background: barColor ?? color, transition: 'width 400ms ease' }}
          />
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────

export default function GpuHistoryPanel() {
  const history = useStore((s) => s.gpuHistory)
  const stats   = useStore((s) => s.gpuStats)

  if (!stats || history.length === 0) {
    return (
      <div className="hw-bar" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <span
          className="font-display animate-pulse-soft"
          style={{
            fontSize: 11,
            color: 'var(--white-dim)',
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
          }}
        >
          ◈ Collecting telemetry…
        </span>
      </div>
    )
  }

  const latest    = history[history.length - 1]
  const vramPct   = (stats.vram_used / stats.vram_total) * 100
  const vramUsedG = (stats.vram_used / 1024).toFixed(1)
  const vramTotG  = (stats.vram_total / 1024).toFixed(0)
  const powerPct  = stats.power_limit > 0 ? (stats.power_draw / stats.power_limit) * 100 : 0
  // Graceful fallback for fields added after initial deployment (old backend may omit them)
  const clockSm   = latest.clock_sm  ?? 0
  const clockMem  = latest.clock_mem ?? 0
  const fanSpeed  = stats.fan_speed  ?? 0

  return (
    <div className="hw-bar">

      {/* GPU UTIL */}
      <MetricCell
        label="GPU UTIL"
        value={`${latest.gpu_util.toFixed(0)}%`}
        color={threshold(latest.gpu_util, 70, 90)}
        data={history} dataKey="gpu_util"
        stroke={C.gpu.stroke}
        domain={[0, 100]} unit="%"
      />

      {/* VRAM */}
      <MetricCell
        label="VRAM"
        value={`${vramUsedG}G`}
        sub={`/ ${vramTotG}G  (${vramPct.toFixed(0)}%)`}
        color={threshold(vramPct, 70, 90)}
        data={history} dataKey="vram_pct"
        stroke={C.vram.stroke}
        domain={[0, 100]} unit="%"
      />

      {/* TEMP */}
      <MetricCell
        label="TEMP"
        value={`${latest.temp.toFixed(0)}°C`}
        color={threshold(latest.temp, 70, 85)}
        data={history} dataKey="temp"
        stroke={C.temp.stroke}
        domain={[20, 100]} unit="°C"
      />

      {/* POWER */}
      <MetricCell
        label="POWER"
        value={`${latest.power.toFixed(0)}W`}
        sub={`/ ${stats.power_limit.toFixed(0)}W  (${powerPct.toFixed(0)}%)`}
        color={threshold(powerPct, 78, 93)}
        data={history} dataKey="power"
        stroke={C.power.stroke}
        domain={[0, stats.power_limit ?? 450]} unit="W"
      />

      {/* SM CLOCK */}
      <MetricCell
        label="SM CLK"
        value={clockSm > 0 ? `${(clockSm / 1000).toFixed(2)}G` : '—'}
        sub="GHz"
        color="var(--cyan)"
        data={history} dataKey="clock_sm"
        stroke={C.clock_sm.stroke}
        domain={[0, 3000]} unit="MHz"
      />

      {/* MEM CLOCK */}
      <MetricCell
        label="MEM CLK"
        value={clockMem > 0 ? `${(clockMem / 1000).toFixed(1)}G` : '—'}
        sub="GHz"
        color="var(--cyan-dim)"
        data={history} dataKey="clock_mem"
        stroke={C.clock_mem.stroke}
        domain={[0, 12000]} unit="MHz"
      />

      {/* FAN */}
      <StaticCell
        label="FAN"
        value={fanSpeed > 0 ? `${fanSpeed.toFixed(0)}%` : '—'}
        color={fanSpeed > 80 ? 'var(--amber)' : 'var(--white-dim)'}
        barPct={fanSpeed}
        barColor={fanSpeed > 80 ? 'var(--amber)' : 'var(--cyan-dim)'}
      />

      {/* CPU */}
      <MetricCell
        label="CPU"
        value={`${latest.cpu_percent.toFixed(0)}%`}
        color={threshold(latest.cpu_percent, 70, 90)}
        data={history} dataKey="cpu_percent"
        stroke={C.cpu.stroke}
        domain={[0, 100]} unit="%"
      />

      {/* RAM */}
      <StaticCell
        label="RAM"
        value={`${stats.ram_used_gb}G`}
        sub={`/ ${stats.ram_total_gb}G  (${stats.ram_percent.toFixed(0)}%)`}
        color={threshold(stats.ram_percent, 70, 90)}
        barPct={stats.ram_percent}
        barColor={threshold(stats.ram_percent, 70, 90)}
      />

    </div>
  )
}
