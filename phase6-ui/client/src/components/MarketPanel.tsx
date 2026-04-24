import { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { useStore } from '../store'
import { fetchRegime, fetchPortfolio } from '../api'

type View = 'table' | 'quality' | 'value'

const AMBER  = '#00ff41'
const CYAN   = '#00ffcc'
const GREEN  = '#00ff41'
const RED    = '#ff4444'
const DIM    = '#0a2a0a'

function scoreColor(s: number) {
  return s >= 70 ? GREEN : s >= 50 ? AMBER : RED
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div
      style={{
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border-strong)',
        padding: '5px 9px',
        fontSize: 11,
        fontFamily: 'var(--font-mono)',
        fontVariantNumeric: 'tabular-nums',
        borderRadius: 3,
        boxShadow: '0 6px 16px -6px rgba(0,0,0,0.6)',
      }}
    >
      <div style={{ color: CYAN, marginBottom: 2, fontWeight: 600 }}>{label}</div>
      {payload.map((p: any) => (
        <div key={p.name} style={{ color: p.color ?? AMBER }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(1) : p.value}
        </div>
      ))}
    </div>
  )
}

export default function MarketPanel() {
  const regime       = useStore((s) => s.regime)
  const portfolio    = useStore((s) => s.portfolio)
  const setRegime    = useStore((s) => s.setRegime)
  const setPortfolio = useStore((s) => s.setPortfolio)
  const [view, setView] = useState<View>('table')

  useEffect(() => {
    fetchRegime().then(setRegime).catch(() => {})
    fetchPortfolio().then(setPortfolio).catch(() => {})
  }, [])

  const regimeColor =
    regime?.regime === 'BULL'   ? 'green' :
    regime?.regime === 'BEAR'   ? 'red'   :
    regime?.regime === 'CRISIS' ? 'red'   : 'amber'

  const top10 = portfolio.slice(0, 10)

  const qualityData = top10
    .filter((p) => p.quality_score != null)
    .map((p) => ({ ticker: p.ticker, score: +(p.quality_score!.toFixed(1)) }))

  const valueData = top10
    .filter((p) => p.value_composite != null)
    .map((p) => ({
      ticker: p.ticker,
      // value_composite is a percentile rank (0–1); display as 0–100
      rank: +(( p.value_composite! * 100).toFixed(1)),
    }))

  return (
    <div className="panel" style={{ minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div className="panel-title">MARKET INTELLIGENCE</div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 0 8px' }}>

        {/* ── Regime ── */}
        <div style={{ padding: '6px 12px 10px', borderBottom: '1px solid var(--border)' }}>
          {regime ? (
            <>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 3 }}>
                <span className={`metric-value ${regimeColor}`} style={{ fontSize: 18 }}>
                  {regime.regime}
                </span>
                <span className="dim" style={{ fontSize: 11 }}>
                  {Math.round(regime.confidence * 100)}% conf
                </span>
                {regime.as_of && (
                  <span className="dim" style={{ fontSize: 10, marginLeft: 'auto' }}>
                    {regime.as_of}
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', gap: 16, fontSize: 11 }}>
                {regime.weekly_return != null && (
                  <span>
                    <span className="dim">WK RET </span>
                    <span className={regime.weekly_return >= 0 ? 'green' : 'red'}>
                      {(regime.weekly_return * 100).toFixed(2)}%
                    </span>
                  </span>
                )}
                {regime.volatility_30d != null && (
                  <span>
                    <span className="dim">VOL30 </span>
                    <span className="amber">{(regime.volatility_30d * 100).toFixed(2)}%</span>
                  </span>
                )}
              </div>
            </>
          ) : (
            <div className="dim" style={{ fontSize: 11 }}>loading regime...</div>
          )}
        </div>

        {/* ── View toggle ── */}
        {portfolio.length > 0 && (
          <>
            <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
              {(['table', 'quality', 'value'] as View[]).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  style={{
                    flex: 1, background: 'none', border: 'none',
                    borderBottom: view === v ? `2px solid ${AMBER}` : '2px solid transparent',
                    color: view === v ? AMBER : 'var(--white-dim)',
                    fontFamily: 'var(--font-mono)', fontSize: 9,
                    letterSpacing: '0.08em', padding: '5px 0', cursor: 'pointer',
                    textTransform: 'uppercase',
                  }}
                >
                  {v === 'table' ? 'TABLE' : v === 'quality' ? 'QUALITY' : 'VALUE'}
                </button>
              ))}
            </div>

            {/* TABLE */}
            {view === 'table' && (
              <table className="ticker-table" style={{ margin: '0' }}>
                <thead>
                  <tr>
                    <th>TICKER</th>
                    <th>EV/EBIT</th>
                    <th>VAL%</th>
                    <th>QUAL</th>
                    <th>F</th>
                  </tr>
                </thead>
                <tbody>
                  {top10.map((p) => (
                    <tr key={p.ticker}>
                      <td className="cyan">{p.ticker}</td>
                      <td>{p.ev_ebit != null ? (p.ev_ebit * 100).toFixed(0) : '—'}</td>
                      <td>{p.value_composite != null ? (p.value_composite * 100).toFixed(0) : '—'}</td>
                      <td style={{ color: p.quality_score != null ? scoreColor(p.quality_score) : 'inherit' }}>
                        {p.quality_score?.toFixed(0) ?? '—'}
                      </td>
                      <td>{p.f_score ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {/* QUALITY SCORE CHART */}
            {view === 'quality' && qualityData.length > 0 && (
              <div style={{ padding: '8px 4px 0' }}>
                <div style={{ fontSize: 10, color: 'var(--white-dim)', padding: '0 8px 6px', letterSpacing: '0.1em' }}>
                  QUALITY SCORE (0–100)
                </div>
                <ResponsiveContainer width="100%" height={qualityData.length * 26 + 20}>
                  <BarChart data={qualityData} layout="vertical" margin={{ left: 4, right: 16, top: 0, bottom: 0 }}>
                    <XAxis type="number" domain={[0, 100]} tick={{ fill: '#556677', fontSize: 9 }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="ticker" tick={{ fill: CYAN, fontSize: 10, fontFamily: 'monospace' }} axisLine={false} tickLine={false} width={36} />
                    <Tooltip content={<CustomTooltip />} cursor={{ fill: DIM }} />
                    <Bar dataKey="score" radius={[0, 2, 2, 0]}>
                      {qualityData.map((d) => (
                        <Cell key={d.ticker} fill={scoreColor(d.score)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* VALUE RANK CHART */}
            {view === 'value' && valueData.length > 0 && (
              <div style={{ padding: '8px 4px 0' }}>
                <div style={{ fontSize: 10, color: 'var(--white-dim)', padding: '0 8px 6px', letterSpacing: '0.1em' }}>
                  VALUE COMPOSITE RANK (higher = cheaper)
                </div>
                <ResponsiveContainer width="100%" height={valueData.length * 26 + 20}>
                  <BarChart data={valueData} layout="vertical" margin={{ left: 4, right: 16, top: 0, bottom: 0 }}>
                    <XAxis type="number" domain={[0, 100]} tick={{ fill: '#556677', fontSize: 9 }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="ticker" tick={{ fill: CYAN, fontSize: 10, fontFamily: 'monospace' }} axisLine={false} tickLine={false} width={36} />
                    <Tooltip content={<CustomTooltip />} cursor={{ fill: DIM }} />
                    <Bar dataKey="rank" fill={AMBER} radius={[0, 2, 2, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </>
        )}

        {portfolio.length === 0 && (
          <div className="dim" style={{ fontSize: 11, padding: '8px 12px' }}>no picks loaded</div>
        )}
      </div>
    </div>
  )
}
