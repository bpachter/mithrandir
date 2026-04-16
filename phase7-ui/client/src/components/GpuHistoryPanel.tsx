/**
 * GpuHistoryPanel.tsx — rolling sparkline graphs for GPU metrics
 * Inspired by iCUE's per-sensor history charts.
 * Reads from the gpuHistory ring-buffer in the Zustand store (120 pts = 60s at 2Hz).
 */

import {
  AreaChart, Area, YAxis, ResponsiveContainer, Tooltip,
} from 'recharts'
import { useStore } from '../store'
import type { GpuHistoryPoint } from '../store'

// ── Colours (match Blade Runner palette) ─────────────────────────────────

const COLORS = {
  gpu:   { stroke: '#00e5ff', fill: '#00e5ff18' },   // cyan  — GPU util
  vram:  { stroke: '#ff9500', fill: '#ff950018' },   // amber — VRAM
  temp:  { stroke: '#39d353', fill: '#39d35318' },   // green — temperature
  power: { stroke: '#ff1a40', fill: '#ff1a4018' },   // red   — power draw
  cpu:   { stroke: '#8899aa', fill: '#8899aa12' },   // dim   — CPU
}

// ── Custom tooltip ────────────────────────────────────────────────────────

function SparkTip({ active, payload, unit }: any) {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: '#0b0d14', border: '1px solid #1a2035',
      padding: '2px 7px', fontSize: 10, fontFamily: 'var(--font-mono)',
      color: payload[0]?.color ?? '#ff9500',
    }}>
      {typeof payload[0]?.value === 'number' ? payload[0].value.toFixed(1) : '—'}{unit}
    </div>
  )
}

// ── Single sparkline card ─────────────────────────────────────────────────

interface SparkCardProps {
  label:   string
  value:   string
  data:    GpuHistoryPoint[]
  dataKey: keyof GpuHistoryPoint
  color:   { stroke: string; fill: string }
  domain:  [number, number]
  unit:    string
  warn?:   number
  crit?:   number
}

function SparkCard({ label, value, data, dataKey, color, domain, unit, warn, crit }: SparkCardProps) {
  // Determine value color
  const numVal = data.length > 0 ? (data[data.length - 1][dataKey] as number) : 0
  const valColor = crit && numVal >= crit ? 'var(--red)'
    : warn && numVal >= warn ? 'var(--amber)'
    : color.stroke

  return (
    <div style={{
      background: '#07080d',
      border: `1px solid #1a2035`,
      padding: '6px 8px 4px',
      display: 'flex', flexDirection: 'column', gap: 3,
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 10, color: 'var(--white-dim)', letterSpacing: '0.12em' }}>
          {label}
        </span>
        <span style={{
          fontFamily: 'var(--font-display)', fontSize: 18, lineHeight: 1,
          color: valColor, textShadow: `0 0 8px ${valColor}50`,
        }}>
          {value}
        </span>
      </div>

      {/* Sparkline */}
      <div style={{ height: 48 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id={`grad-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={color.stroke} stopOpacity={0.25} />
                <stop offset="95%" stopColor={color.stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <YAxis domain={domain} hide />
            <Tooltip
              content={<SparkTip unit={unit} />}
              cursor={{ stroke: color.stroke, strokeWidth: 1, strokeOpacity: 0.4 }}
            />
            <Area
              type="monotone"
              dataKey={dataKey as string}
              stroke={color.stroke}
              strokeWidth={1.5}
              fill={`url(#grad-${dataKey})`}
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────

export default function GpuHistoryPanel() {
  const history = useStore((s) => s.gpuHistory)
  const stats   = useStore((s) => s.gpuStats)

  if (history.length === 0) {
    return (
      <div style={{ padding: '10px 12px', fontSize: 11, color: 'var(--white-dim)' }}>
        Collecting data…
      </div>
    )
  }

  const latest = history[history.length - 1]

  return (
    <div style={{
      padding: '8px 10px',
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 6,
      overflow: 'auto',
    }}>
      <SparkCard
        label="GPU UTIL"
        value={`${latest.gpu_util.toFixed(0)}%`}
        data={history}
        dataKey="gpu_util"
        color={COLORS.gpu}
        domain={[0, 100]}
        unit="%"
        warn={70} crit={90}
      />
      <SparkCard
        label="VRAM"
        value={`${latest.vram_pct.toFixed(0)}%`}
        data={history}
        dataKey="vram_pct"
        color={COLORS.vram}
        domain={[0, 100]}
        unit="%"
        warn={70} crit={90}
      />
      <SparkCard
        label="TEMP"
        value={`${latest.temp.toFixed(0)}°C`}
        data={history}
        dataKey="temp"
        color={COLORS.temp}
        domain={[20, 100]}
        unit="°C"
        warn={70} crit={85}
      />
      <SparkCard
        label="POWER"
        value={`${latest.power.toFixed(0)}W`}
        data={history}
        dataKey="power"
        color={COLORS.power}
        domain={[0, stats?.power_limit ?? 450]}
        unit="W"
        warn={350} crit={420}
      />
      <SparkCard
        label="CPU"
        value={`${latest.cpu_percent.toFixed(0)}%`}
        data={history}
        dataKey="cpu_percent"
        color={COLORS.cpu}
        domain={[0, 100]}
        unit="%"
        warn={70} crit={90}
      />
      <div style={{
        background: '#07080d', border: '1px solid #1a2035',
        padding: '6px 8px', display: 'flex', flexDirection: 'column',
        justifyContent: 'center', gap: 4,
      }}>
        <div style={{ fontSize: 10, color: 'var(--white-dim)', letterSpacing: '0.1em' }}>RAM</div>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 18, color: 'var(--cyan)' }}>
          {stats?.ram_used_gb ?? '—'}G
        </div>
        <div style={{ fontSize: 10, color: 'var(--white-dim)' }}>
          of {stats?.ram_total_gb ?? '—'}G ({stats?.ram_percent.toFixed(0) ?? '—'}%)
        </div>
        <div style={{ height: 3, background: '#1a2035', marginTop: 2 }}>
          <div style={{
            height: '100%',
            width: `${stats?.ram_percent ?? 0}%`,
            background: 'var(--cyan)',
            transition: 'width 400ms ease',
          }} />
        </div>
      </div>
    </div>
  )
}
