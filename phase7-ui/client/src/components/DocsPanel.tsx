/**
 * DocsPanel.tsx — Searchable CUDA / RTX 4090 / Gemma4 reference panel.
 * Loaded from /api/docs (served by cuda_docs.py).
 * Category tabs filter entries; search filters by title/summary/tags.
 * "Ask Enkidu" injects a query into the chat input.
 */

import { useEffect, useState, useRef } from 'react'
import { fetchDocs } from '../api'

interface DocEntry {
  id:       string
  category: string
  title:    string
  summary:  string
  detail:   string
  specs:    [string, string][]
  example:  string | null
  tags:     string[]
}

const CAT_LABELS: Record<string, string> = {
  all:        'ALL',
  rtx4090:    'RTX 4090',
  memory:     'MEMORY',
  execution:  'EXECUTION',
  performance:'PERF',
  gemma4:     'GEMMA4',
  inference:  'INFERENCE',
}

const CAT_COLORS: Record<string, string> = {
  rtx4090:    'var(--cyan)',
  memory:     'var(--amber)',
  execution:  'var(--green)',
  performance:'#c084fc',
  gemma4:     '#818cf8',
  inference:  'var(--amber)',
}

// ── Single doc card ───────────────────────────────────────────────────────────

interface CardProps {
  entry: DocEntry
  onAskEnkidu: (query: string) => void
}

function DocCard({ entry, onAskEnkidu }: CardProps) {
  const [expanded, setExpanded] = useState(false)
  const accentColor = CAT_COLORS[entry.category] ?? 'var(--cyan)'

  return (
    <div
      className="doc-card"
      style={{ borderLeftColor: accentColor }}
    >
      <div
        className="doc-card-header"
        onClick={() => setExpanded((e) => !e)}
        style={{ cursor: 'pointer' }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="doc-card-title">{entry.title}</div>
          <div className="doc-card-summary">{entry.summary}</div>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', flexShrink: 0 }}>
          <span
            className="doc-cat-badge"
            style={{ background: accentColor + '20', color: accentColor, borderColor: accentColor + '40' }}
          >
            {CAT_LABELS[entry.category] ?? entry.category}
          </span>
          <span style={{ color: 'var(--white-dim)', fontSize: 11, paddingTop: 1 }}>
            {expanded ? '▲' : '▼'}
          </span>
        </div>
      </div>

      {expanded && (
        <div className="doc-card-body">
          {/* Detail prose */}
          <div className="doc-detail">{entry.detail}</div>

          {/* Specs table */}
          {entry.specs && entry.specs.length > 0 && (
            <table className="doc-specs-table">
              <tbody>
                {entry.specs.map(([label, val]) => (
                  <tr key={label}>
                    <td className="doc-spec-label">{label}</td>
                    <td className="doc-spec-val">{val}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Code example */}
          {entry.example && (
            <pre className="doc-example">{entry.example}</pre>
          )}

          {/* Tags + Ask Enkidu */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8, gap: 8, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {entry.tags.slice(0, 6).map((t) => (
                <span key={t} className="doc-tag">{t}</span>
              ))}
            </div>
            <button
              className="doc-ask-btn"
              onClick={(e) => {
                e.stopPropagation()
                onAskEnkidu(`Explain ${entry.title} in the context of my RTX 4090 setup`)
              }}
            >
              ASK ENKIDU ▸
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface DocsPanelProps {
  onAskEnkidu: (query: string) => void
}

export default function DocsPanel({ onAskEnkidu }: DocsPanelProps) {
  const [docs, setDocs]         = useState<DocEntry[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [activeTab, setActiveTab]   = useState('all')
  const [query, setQuery]           = useState('')
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setLoading(true)
    fetchDocs()
      .then((data) => {
        setDocs(data.docs ?? [])
        setCategories(['all', ...(data.categories ?? [])])
        setLoading(false)
      })
      .catch((e) => {
        setError(`Failed to load docs: ${e}`)
        setLoading(false)
      })
  }, [])

  const filtered = docs.filter((d) => {
    const inCat = activeTab === 'all' || d.category === activeTab
    if (!inCat) return false
    if (!query.trim()) return true
    const q = query.toLowerCase()
    return (
      d.title.toLowerCase().includes(q) ||
      d.summary.toLowerCase().includes(q) ||
      d.tags.some((t) => t.toLowerCase().includes(q))
    )
  })

  return (
    <div className="panel" style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div className="panel-title">CUDA REFERENCE</div>

      {/* Search bar */}
      <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <input
          ref={inputRef}
          className="doc-search"
          type="text"
          placeholder="search topics, specs, tags…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {/* Category tabs */}
      <div className="doc-cat-tabs" style={{ flexShrink: 0 }}>
        {categories.map((cat) => (
          <button
            key={cat}
            className={`doc-cat-tab${activeTab === cat ? ' active' : ''}`}
            onClick={() => setActiveTab(cat)}
            style={activeTab === cat ? { color: CAT_COLORS[cat] ?? 'var(--cyan)', borderBottomColor: CAT_COLORS[cat] ?? 'var(--cyan)' } : {}}
          >
            {CAT_LABELS[cat] ?? cat.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Card list */}
      <div className="doc-list">
        {loading && (
          <div style={{ padding: 16, color: 'var(--white-dim)', fontSize: 11 }}>
            ◈ LOADING REFERENCE DATA…
          </div>
        )}
        {error && (
          <div style={{ padding: 16, color: 'var(--red)', fontSize: 11 }}>{error}</div>
        )}
        {!loading && !error && filtered.length === 0 && (
          <div style={{ padding: 16, color: 'var(--white-dim)', fontSize: 11 }}>
            No entries match "{query}"
          </div>
        )}
        {filtered.map((entry) => (
          <DocCard key={entry.id} entry={entry} onAskEnkidu={onAskEnkidu} />
        ))}
      </div>
    </div>
  )
}
