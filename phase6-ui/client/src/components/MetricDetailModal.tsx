/**
 * MetricDetailModal.tsx — click-to-expand detail panel for any hw-cell
 * Shows LIVE history chart, metric description, and alert state guide.
 * Anchored below the clicked cell with a dotted connector line.
 */

import { useEffect, useMemo, useRef } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip, ReferenceLine,
} from 'recharts'
import { X } from 'lucide-react'
import { useStore } from '../store'
import type { GpuHistoryPoint } from '../store'

/* ── Public types (re-exported for GpuHistoryPanel) ──────────────────── */

export interface StateGuide {
  level:   'safe' | 'warn' | 'crit'
  range:   string
  meaning: string
}

export interface MetricInfo {
  description:        string
  states:             StateGuide[]
  warnThreshold?:     number
  critThreshold?:     number
  invertedThreshold?: boolean   // lower = worse (e.g. thermal headroom)
}

interface SparkPoint { [key: string]: number }

export interface ModalState {
  label:     string
  value:     string
  color:     string
  dataKey:   string
  isDerived: boolean   // true = compute DerivedPoint series from live gpuHistory
  stroke:    string
  domain:    [number, number]
  unit:      string
  info:      MetricInfo
  cellRect:  DOMRect   // bounding rect of the clicked hw-cell for anchoring
}

/* ── Derived computation (mirrors GpuHistoryPanel) ────────────────────── */

function computeDerived(history: GpuHistoryPoint[]): SparkPoint[] {
  return history.map((curr, i) => {
    const prev = history[Math.max(0, i - 1)]
    const dt   = Math.max((curr.ts - prev.ts) / 1000, 0.25)
    return {
      ts:               curr.ts,
      gpu_delta:        i === 0 ? 0 : (curr.gpu_util  - prev.gpu_util)  / dt,
      vram_delta:       i === 0 ? 0 : (curr.vram_pct  - prev.vram_pct)  / dt,
      temp_rate:        i === 0 ? 0 : ((curr.temp     - prev.temp)      / dt) * 60,
      power_delta:      i === 0 ? 0 : (curr.power     - prev.power)     / dt,
      thermal_headroom: Math.max(0, 85 - curr.temp),
      perf_per_w:       curr.power > 1 ? curr.gpu_util / curr.power : 0,
      clock_eff:        curr.power > 1 ? curr.clock_sm / curr.power : 0,
      pressure:         Math.sqrt(Math.max(0, curr.gpu_util * curr.vram_pct)),
      cpu_gpu_ratio:    curr.gpu_util > 1 ? curr.cpu_percent / curr.gpu_util : 0,
    }
  })
}

/* ── Styling helpers ──────────────────────────────────────────────────── */

const LEVEL_COLOR: Record<string, string> = {
  safe: 'rgba(110,190,155,0.70)',
  warn: 'rgba(200,180,110,0.70)',
  crit: 'rgba(200,100,90,0.70)',
}
const LEVEL_BG: Record<string, string> = {
  safe: 'rgba(80,160,120,0.03)',
  warn: 'rgba(180,145,60,0.03)',
  crit: 'rgba(180,60,55,0.03)',
}

const MODAL_W = 840
const MODAL_GAP = 10   // px gap between cell bottom and modal top

function CustomTip({ active, payload, label: ts, unit }: any) {
  if (!active || !payload?.length) return null
  const v = payload[0]?.value
  const d = new Date(ts)
  const time = `${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
  return (
    <div style={{
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border-strong)',
      padding: '4px 9px', borderRadius: 4,
      fontFamily: 'var(--font-mono)', fontSize: 11,
      color: payload[0]?.stroke ?? 'var(--fg)',
    }}>
      <div style={{ fontSize: 9, color: 'var(--white-dim)', marginBottom: 2 }}>{time}</div>
      {typeof v === 'number' ? v.toFixed(2) : '—'}{unit}
    </div>
  )
}

/* ── Component ─────────────────────────────────────────────────────────── */

interface Props extends ModalState {
  onClose: () => void
}

export default function MetricDetailModal({
  onClose, label, value, color, dataKey, isDerived, stroke, domain, unit, info, cellRect,
}: Props) {
  const overlayRef = useRef<HTMLDivElement>(null)

  // ── Live data subscription ─────────────────────────────────────────────
  const rawHistory = useStore((s) => s.gpuHistory)
  const liveData: SparkPoint[] = useMemo(
    () => isDerived ? computeDerived(rawHistory) : (rawHistory as unknown as SparkPoint[]),
    [rawHistory, isDerived],
  )

  // ── Positioning: anchor below the clicked cell ─────────────────────────
  const vw       = window.innerWidth
  const rawLeft  = cellRect.left + cellRect.width / 2 - MODAL_W / 2
  const modalLeft    = Math.max(12, Math.min(rawLeft, vw - MODAL_W - 12))
  const connectorLeft = (cellRect.left + cellRect.width / 2) - modalLeft

  // ── body attribute: suppress pane hover states while open ──────────────
  useEffect(() => {
    document.body.setAttribute('data-modal-open', '')
    return () => document.body.removeAttribute('data-modal-open')
  }, [])

  // ── Escape key ─────────────────────────────────────────────────────────
  useEffect(() => {
    const fn = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', fn)
    return () => window.removeEventListener('keydown', fn)
  }, [onClose])

  return (
    <>
      {/* Full-screen dimmer — click outside to close */}
      <div
        ref={overlayRef}
        className="metric-modal-overlay"
        onClick={(e) => { if (e.target === overlayRef.current) onClose() }}
      />

      {/* Dotted vertical connector stem from cell bottom to modal top */}
      <div
        className="metric-modal-stem"
        style={{
          left:   cellRect.left + cellRect.width / 2 - 1,
          top:    cellRect.bottom,
          height: MODAL_GAP,
        }}
      />

      {/* Modal anchored below the cell */}
      <div
        className="metric-modal"
        role="dialog" aria-modal="true" aria-label={label}
        style={{
          left:  modalLeft,
          top:   cellRect.bottom + MODAL_GAP,
          width: MODAL_W,
        }}
      >
        {/* Small notch triangle at top pointing up toward cell */}
        <div className="metric-modal-notch" style={{ left: connectorLeft }} />

        {/* ── Header ── */}
        <div className="metric-modal-header">
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
            <span className="metric-modal-label">{label}</span>
            <span
              className="metric-modal-val"
              style={{ color, textShadow: `0 0 18px ${color}80` }}
            >
              {value}
            </span>
            <span className="metric-modal-unit">{unit}</span>
          </div>
          <button className="metric-modal-close" onClick={onClose} aria-label="Close">
            <X size={14} strokeWidth={2.2} />
          </button>
        </div>

        {/* ── Description ── */}
        <p className="metric-modal-desc">{info.description}</p>

        {/* ── Live history chart ── */}
        {liveData.length > 0 ? (
          <div className="metric-modal-chart">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={liveData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="mdl-grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={stroke} stopOpacity={0.30} />
                    <stop offset="95%" stopColor={stroke} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="ts"
                  tickFormatter={(v) => {
                    const d = new Date(v)
                    return `${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
                  }}
                  tick={{ fontSize: 9, fill: 'var(--white-dim)', fontFamily: 'var(--font-mono)' }}
                  axisLine={false} tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={domain}
                  tick={{ fontSize: 9, fill: 'var(--white-dim)', fontFamily: 'var(--font-mono)' }}
                  axisLine={false} tickLine={false} width={38}
                />
                <Tooltip content={<CustomTip unit={unit} />} />
                {info.warnThreshold !== undefined && (
                  <ReferenceLine
                    y={info.warnThreshold}
                    stroke="rgba(220,195,120,0.45)"
                    strokeDasharray="4 3"
                  />
                )}
                {info.critThreshold !== undefined && (
                  <ReferenceLine
                    y={info.critThreshold}
                    stroke="rgba(215,110,100,0.45)"
                    strokeDasharray="4 3"
                  />
                )}
                <Area
                  type="monotone"
                  dataKey={dataKey}
                  stroke={stroke}
                  strokeWidth={1.8}
                  fill="url(#mdl-grad)"
                  dot={false}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="metric-modal-no-history">No stored history for this metric</div>
        )}

        {/* ── State guide ── */}
        <div className="metric-modal-states">
          {info.states.map((s, i) => (
            <div
              key={i}
              className="metric-modal-state"
              style={{ background: LEVEL_BG[s.level], borderColor: 'var(--border)', borderLeftColor: LEVEL_COLOR[s.level], borderLeftWidth: 2 }}
            >
              <div className="metric-modal-state-hdr">
                <span className="metric-modal-state-dot" style={{ background: LEVEL_COLOR[s.level] }} />
                <span style={{
                  color: LEVEL_COLOR[s.level],
                  fontFamily: 'var(--font-display)',
                  fontSize: 9, fontWeight: 600, letterSpacing: '0.14em',
                  opacity: 0.80,
                }}>
                  {s.level.toUpperCase()}
                </span>
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10,
                  color: 'var(--white-dim)', marginLeft: 'auto',
                }}>
                  {s.range}
                </span>
              </div>
              <p className="metric-modal-state-text">{s.meaning}</p>
            </div>
          ))}
        </div>

      </div>
    </>
  )
}
