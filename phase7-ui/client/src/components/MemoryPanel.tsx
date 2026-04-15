import { useEffect, useState } from 'react'
import { useStore } from '../store'
import { fetchMemory, rateMemory, deleteMemory } from '../api'

export default function MemoryPanel() {
  const memory      = useStore((s) => s.memory)
  const stats       = useStore((s) => s.memoryStats)
  const setMemory   = useStore((s) => s.setMemory)
  const updateRating = useStore((s) => s.updateMemoryRating)
  const removeEntry  = useStore((s) => s.removeMemoryEntry)
  const [expanded, setExpanded] = useState<string | null>(null)

  async function load() {
    try {
      const d = await fetchMemory()
      setMemory(d.entries ?? [], d.stats ?? { total: 0, rated: 0, avg_score: null })
    } catch {}
  }

  useEffect(() => { load() }, [])

  async function handleRate(id: string, r: number | null) {
    updateRating(id, r)
    await rateMemory(id, r).catch(() => {})
  }

  async function handleDelete(id: string) {
    removeEntry(id)
    await deleteMemory(id).catch(() => {})
  }

  return (
    <div className="panel" style={{ minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div className="panel-title" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span>MEMORY BANK</span>
        <button
          onClick={load}
          style={{
            background: 'none', border: 'none', color: 'var(--amber-dim)',
            fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer', padding: '0 4px',
          }}
        >
          ↺
        </button>
      </div>

      {/* Stats bar */}
      {stats && (
        <div style={{ display: 'flex', gap: 16, padding: '4px 12px 6px', fontSize: 10, borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          <span><span className="dim">TOTAL </span><span className="amber">{stats.total}</span></span>
          <span><span className="dim">RATED </span><span className="cyan">{stats.rated}</span></span>
          {stats.avg_score !== null && (
            <span><span className="dim">AVG SCORE </span><span className="green">{stats.avg_score}</span></span>
          )}
        </div>
      )}

      {/* Entry list */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {memory.length === 0 ? (
          <div className="dim" style={{ fontSize: 11, padding: '8px 12px' }}>no memory entries</div>
        ) : (
          memory.map((e) => (
            <div
              key={e.id}
              style={{
                borderBottom: '1px solid var(--border)',
                background: expanded === e.id ? '#0a0c14' : 'transparent',
              }}
            >
              <div
                style={{ display: 'flex', alignItems: 'flex-start', gap: 6, padding: '6px 10px', cursor: 'pointer' }}
                onClick={() => setExpanded(expanded === e.id ? null : e.id)}
              >
                {/* Score pill */}
                <span style={{
                  fontSize: 9, padding: '1px 4px', flexShrink: 0, marginTop: 1,
                  background: e.score !== null ? (e.score >= 7 ? 'var(--green-dim)' : e.score >= 4 ? '#3a2a00' : '#2a0008') : 'var(--border)',
                  color: e.score !== null ? (e.score >= 7 ? 'var(--green)' : e.score >= 4 ? 'var(--amber)' : 'var(--red)') : 'var(--white-dim)',
                }}>
                  {e.score !== null ? e.score.toFixed(1) : '—'}
                </span>

                <span style={{ fontSize: 11, color: 'var(--amber)', flex: 1, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                  {e.user}
                </span>

                {/* Rating buttons */}
                <span style={{ display: 'flex', gap: 2, flexShrink: 0 }} onClick={(ev) => ev.stopPropagation()}>
                  <button
                    onClick={() => handleRate(e.id, e.rating === 1 ? null : 1)}
                    style={{
                      background: 'none', border: 'none', cursor: 'pointer', fontSize: 11, padding: '0 2px',
                      color: e.rating === 1 ? 'var(--green)' : 'var(--white-dim)',
                    }}
                    title="Good response"
                  >▲</button>
                  <button
                    onClick={() => handleRate(e.id, e.rating === -1 ? null : -1)}
                    style={{
                      background: 'none', border: 'none', cursor: 'pointer', fontSize: 11, padding: '0 2px',
                      color: e.rating === -1 ? 'var(--red)' : 'var(--white-dim)',
                    }}
                    title="Poor response"
                  >▼</button>
                  <button
                    onClick={() => handleDelete(e.id)}
                    style={{
                      background: 'none', border: 'none', cursor: 'pointer', fontSize: 10, padding: '0 2px',
                      color: 'var(--white-dim)',
                    }}
                    title="Delete from memory"
                  >✕</button>
                </span>
              </div>

              {/* Expanded view */}
              {expanded === e.id && (
                <div style={{ padding: '0 10px 8px 10px', fontSize: 11 }}>
                  <div style={{ color: 'var(--cyan)', marginBottom: 4, fontSize: 10 }}>
                    {new Date(e.timestamp).toLocaleString('en-US', { hour12: false })}
                  </div>
                  <div style={{ color: 'var(--amber)', marginBottom: 6, lineHeight: 1.5 }}>{e.user}</div>
                  <div style={{ color: 'var(--white-dim)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{e.assistant}</div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
