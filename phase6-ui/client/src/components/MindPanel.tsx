import { useEffect, useMemo, useRef, useState } from 'react'
import { RefreshCcw, Sparkles, Zap, MapPin, Activity } from 'lucide-react'
import {
  fetchHistory, fetchMemory, fetchMind, generateMindReflection,
  fetchOratorSnapshot, fetchSiteScout, fetchRegimePulse,
  type MacroSnapshotBrief, type SiteScoutResult, type RegimePulse,
} from '../api'

interface MindStats {
  total: number
  rated: number
  thumbs_up: number
  first_exchange: string | null
}

interface Insight {
  id: string
  timestamp: string
  user: string
  assistant: string
  rating: number | null
  score: string | null
}

interface RecentTopic {
  msg: string
  timestamp: string
}

interface TopicEntry {
  term: string
  count: number
  pct: number
}

interface ReflectionEntry {
  id: string
  timestamp: string
  title: string
  reflection: string
  implication: string
  tags: string[]
  source: 'local' | 'mithrandir'
}

interface MindData {
  stats: MindStats
  insights: Insight[]
  recent_topics: RecentTopic[]
  topic_map: TopicEntry[]
  reflections?: ReflectionEntry[]
}

interface MemoryEntry {
  id: string
  timestamp: string
  user: string
  assistant: string
  rating: number | null
  score: string | null
}

interface HistoryEntry {
  id: string
  timestamp: string
  user: string
  assistant: string
}

const STOPWORDS = new Set([
  'the','a','an','is','are','was','were','be','been','being','have','has',
  'had','do','does','did','will','would','could','should','may','might',
  'shall','can','of','to','in','for','on','with','at','by','from','as',
  'into','through','during','before','after','above','below','up','down',
  'out','off','over','under','again','then','once','here','there','when',
  'where','why','how','all','both','each','few','more','most','other',
  'some','such','no','nor','not','only','own','same','so','than','too',
  'very','just','but','and','or','if','i','you','he','she','it','we',
  'they','me','him','her','us','them','my','your','his','its','our',
  'their','this','that','these','those','what','which','who','whom',
  'about','get','got','also','please','let','make','use','using','used',
  'need','want','help','know','think','see','tell','give','look','going',
  'gone','come','take','show','keep','say','said','does','much','many',
  'any','like','well','okay','yeah','sure','right','good','great','true',
])

const REFLECTIONS_KEY = 'mithrandir.mind.reflections.v1'

function buildTopicMap(texts: string[]): TopicEntry[] {
  const counts = new Map<string, number>()
  for (const text of texts) {
    const words = text.toLowerCase().match(/\b[a-z]{4,}\b/g) ?? []
    for (const word of words) {
      if (STOPWORDS.has(word)) continue
      counts.set(word, (counts.get(word) ?? 0) + 1)
    }
  }
  const ranked = [...counts.entries()].sort((left, right) => right[1] - left[1]).slice(0, 20)
  const maxCount = ranked[0]?.[1] ?? 1
  return ranked.map(([term, count]) => ({
    term,
    count,
    pct: Math.round((count / maxCount) * 100),
  }))
}

function buildFallbackMindData(memoryEntries: MemoryEntry[], historyEntries: HistoryEntry[]): MindData {
  const total = memoryEntries.length
  const rated = memoryEntries.filter((entry) => entry.rating !== null).length
  const thumbsUp = memoryEntries.filter((entry) => entry.rating === 1).length
  const oldest = [...memoryEntries].sort((left, right) => left.timestamp.localeCompare(right.timestamp))[0]?.timestamp ?? null
  const insights = [...memoryEntries]
    .sort((left, right) => {
      if ((left.rating === 1) !== (right.rating === 1)) return left.rating === 1 ? -1 : 1
      return Number(right.score ?? 0) - Number(left.score ?? 0)
    })
    .slice(0, 10)
  const recentTopics = historyEntries.slice(0, 25).map((entry) => ({
    msg: entry.user,
    timestamp: entry.timestamp,
  }))
  const topicMap = buildTopicMap(memoryEntries.map((entry) => entry.user))

  return {
    stats: {
      total,
      rated,
      thumbs_up: thumbsUp,
      first_exchange: oldest,
    },
    insights,
    recent_topics: recentTopics,
    topic_map: topicMap,
    reflections: [],
  }
}

function readStoredReflections(): ReflectionEntry[] {
  try {
    const raw = window.localStorage.getItem(REFLECTIONS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeStoredReflections(reflections: ReflectionEntry[]) {
  try {
    window.localStorage.setItem(REFLECTIONS_KEY, JSON.stringify(reflections.slice(0, 18)))
  } catch {
    // Ignore storage failures.
  }
}

function mergeReflections(serverReflections: ReflectionEntry[] | undefined, localReflections: ReflectionEntry[]) {
  const seen = new Set<string>()
  return [...(serverReflections ?? []), ...localReflections]
    .filter((entry) => {
      if (seen.has(entry.id)) return false
      seen.add(entry.id)
      return true
    })
    .sort((left, right) => right.timestamp.localeCompare(left.timestamp))
    .slice(0, 18)
}

function formatRelative(ts: string | null): string {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    const diff = Date.now() - d.getTime()
    const mins = Math.floor(diff / 60_000)
    if (mins < 2) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    if (days < 7) return `${days}d ago`
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  } catch {
    return '—'
  }
}

function formatBorn(ts: string | null): string {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleDateString('en-US', {
      year: 'numeric', month: 'long', day: 'numeric',
    })
  } catch {
    return '—'
  }
}

function parseReflection(raw: string): Omit<ReflectionEntry, 'id' | 'timestamp' | 'source'> {
  const titleMatch = raw.match(/TITLE:\s*(.+)/i)
  const reflectionMatch = raw.match(/REFLECTION:\s*([\s\S]*?)(?:\nIMPLICATION:|$)/i)
  const implicationMatch = raw.match(/IMPLICATION:\s*([\s\S]*?)(?:\nTAGS:|$)/i)
  const tagsMatch = raw.match(/TAGS:\s*(.+)/i)

  return {
    title: titleMatch?.[1]?.trim() || 'Emergent reflection',
    reflection: reflectionMatch?.[1]?.trim() || raw.trim(),
    implication: implicationMatch?.[1]?.trim() || 'No immediate implication surfaced.',
    tags: (tagsMatch?.[1] ?? 'memory, pattern, reflection')
      .split(',')
      .map((tag) => tag.trim().toLowerCase())
      .filter(Boolean)
      .slice(0, 4),
  }
}

function buildReflectionPrompt(data: MindData) {
  const recent = data.recent_topics.slice(0, 8).map((entry) => `- ${entry.msg}`).join('\n')
  const insights = data.insights.slice(0, 5).map((entry) => `- User: ${entry.user}\n  Mithrandir: ${entry.assistant}`).join('\n')
  const map = data.topic_map.slice(0, 8).map((entry) => `${entry.term} (${entry.count})`).join(', ')
  return [
    'You are Mithrandir writing a short internal reflection for your own Mind panel.',
    'Study the recent history below and infer one compact, insightful note about what you are learning, noticing, or repeatedly being asked to do.',
    'Be concrete. Do not flatter. Do not narrate your limitations. Aim for one strong observation.',
    'Return exactly this format:',
    'TITLE: <6 words max>',
    'REFLECTION: <2-4 sentences>',
    'IMPLICATION: <1 sentence about what Mithrandir should improve, remember, or surface>',
    'TAGS: <comma-separated lower-case tags>',
    '',
    `Memory depth: ${data.stats.total} exchanges; valued: ${data.stats.thumbs_up}; rated: ${data.stats.rated}.`,
    `Top themes: ${map || 'none yet'}`,
    '',
    'Recent prompts:',
    recent || '- none yet',
    '',
    'Notable exchanges:',
    insights || '- none yet',
  ].join('\n')
}

function buildLocalReflection(data: MindData): Omit<ReflectionEntry, 'id' | 'timestamp' | 'source'> {
  const dominant = data.topic_map.slice(0, 3).map((entry) => entry.term)
  const latest = data.recent_topics[0]?.msg ?? 'recent conversation'
  return {
    title: dominant[0] ? `${dominant[0]} keeps recurring` : 'Patterns are forming',
    reflection: dominant.length > 0
      ? `Recent history clusters around ${dominant.join(', ')}. The latest prompt still sits near the same thematic neighborhood: ${latest}.`
      : `There is not yet enough repeated history to surface a strong durable pattern, but the current line of inquiry still centers on ${latest}.`,
    implication: dominant[0]
      ? `Mithrandir should preserve context around ${dominant[0]} and surface prior answers before recomputing nearby requests.`
      : 'Mithrandir should keep accumulating examples until a clearer pattern emerges.',
    tags: dominant.length > 0 ? dominant.slice(0, 3) : ['pattern', 'memory', 'reflection'],
  }
}

// ---------------------------------------------------------------------------
// Live tool widgets
// ---------------------------------------------------------------------------

type ToolState<T> = { status: 'idle' } | { status: 'loading' } | { status: 'ok'; data: T } | { status: 'error'; msg: string }

function recessionColor(label: string): string {
  if (label === 'High') return '#c76f5d'
  if (label === 'Elevated') return '#b7834c'
  if (label === 'Moderate') return '#cfa75a'
  return '#6aa58d'
}

function signalDotColor(state: string): string {
  if (state === 'critical') return '#c76f5d'
  if (state === 'warning') return '#b7834c'
  if (state === 'watch') return '#cfa75a'
  return '#6aa58d'
}

function regimeColor(regime: string): string {
  const r = regime.toLowerCase()
  if (r.includes('bear') || r.includes('crisis') || r.includes('contraction')) return '#c76f5d'
  if (r.includes('transition') || r.includes('volatile') || r.includes('risk')) return '#cfa75a'
  return '#6aa58d'
}

// ── Tool 1: Orator Macro Brief ──────────────────────────────────────────────

function OratorSnapshotTool() {
  const [state, setState] = useState<ToolState<MacroSnapshotBrief>>({ status: 'idle' })

  async function run() {
    setState({ status: 'loading' })
    try {
      const data = await fetchOratorSnapshot()
      setState({ status: 'ok', data })
    } catch (e) {
      setState({ status: 'error', msg: e instanceof Error ? e.message : String(e) })
    }
  }

  const data = state.status === 'ok' ? state.data : null

  return (
    <div className="mind-tool-card">
      <div className="mind-tool-header">
        <Zap className="h-3 w-3" strokeWidth={2.2} />
        <span className="mind-tool-title">macro brief</span>
        <button
          className="mind-tool-run"
          onClick={run}
          disabled={state.status === 'loading'}
        >
          {state.status === 'loading' ? '…' : <RefreshCcw className="h-2.5 w-2.5" strokeWidth={2.5} />}
        </button>
      </div>

      {state.status === 'idle' && (
        <div className="mind-tool-idle">pull live macro snapshot from orator</div>
      )}
      {state.status === 'error' && (
        <div className="mind-tool-error">{state.msg}</div>
      )}
      {data && (
        <div className="mind-tool-body">
          <div className="mind-tool-row">
            <span className="mind-tool-key">date</span>
            <span className="mind-tool-val">{data.date}</span>
          </div>
          <div className="mind-tool-row">
            <span className="mind-tool-key">recession risk</span>
            <span className="mind-tool-val" style={{ color: recessionColor(data.recession_label) }}>
              {Math.round(data.recession_composite * 100)}% — {data.recession_label}
            </span>
          </div>
          <div className="mind-tool-row">
            <span className="mind-tool-key">stagflation</span>
            <span className="mind-tool-val">{Math.round(data.stagflation_score * 100)}%</span>
          </div>
          <div className="mind-tool-row">
            <span className="mind-tool-key">2s10s spread</span>
            <span className="mind-tool-val" style={{ color: data.yield_curve_inverted ? '#c76f5d' : '#6aa58d' }}>
              {data.yield_curve_inverted ? '⚠ ' : ''}{Math.round(data.yield_curve_spread_2_10 * 100)} bps
            </span>
          </div>
          <div className="mind-tool-row">
            <span className="mind-tool-key">vix</span>
            <span className="mind-tool-val">{data.vix.toFixed(1)} ({data.vix_regime})</span>
          </div>
          <div className="mind-tool-row">
            <span className="mind-tool-key">hy spread</span>
            <span className="mind-tool-val">{Math.round(data.hy_spread)} bps</span>
          </div>
          <div className="mind-tool-row">
            <span className="mind-tool-key">unemployment</span>
            <span className="mind-tool-val">{data.unemployment.toFixed(1)}%</span>
          </div>
          <div className="mind-tool-row">
            <span className="mind-tool-key">cpi yoy</span>
            <span className="mind-tool-val">{data.cpi_yoy.toFixed(1)}%</span>
          </div>
          <div className="mind-tool-row">
            <span className="mind-tool-key">fed funds</span>
            <span className="mind-tool-val">{data.fed_funds_rate.toFixed(2)}%</span>
          </div>
          {data.top_signals.length > 0 && (
            <div className="mind-tool-signals">
              {data.top_signals.map((s, i) => (
                <div key={i} className="mind-tool-signal-row">
                  <span className="mind-tool-signal-dot" style={{ background: signalDotColor(s.state) }} />
                  <span className="mind-tool-signal-name">{s.name}</span>
                  <span className="mind-tool-signal-val">{s.value}</span>
                </div>
              ))}
            </div>
          )}
          {data.narrative && (
            <div className="mind-tool-narrative">{data.narrative}</div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Tool 2: Avalon Site Scout ───────────────────────────────────────────────

const ARCHETYPES = ['mixed', 'training', 'inference'] as const

function SiteScoutTool() {
  const [query, setQuery] = useState('')
  const [archetype, setArchetype] = useState<typeof ARCHETYPES[number]>('mixed')
  const [state, setState] = useState<ToolState<SiteScoutResult[]>>({ status: 'idle' })
  const inputRef = useRef<HTMLInputElement>(null)

  async function run() {
    setState({ status: 'loading' })
    try {
      const res = await fetchSiteScout(query, archetype)
      setState({ status: 'ok', data: res.results })
    } catch (e) {
      setState({ status: 'error', msg: e instanceof Error ? e.message : String(e) })
    }
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter') void run()
  }

  const results = state.status === 'ok' ? state.data : []
  const maxScore = results.length > 0 ? Math.max(...results.map((r) => r.composite)) : 1

  return (
    <div className="mind-tool-card">
      <div className="mind-tool-header">
        <MapPin className="h-3 w-3" strokeWidth={2.2} />
        <span className="mind-tool-title">site scout</span>
      </div>
      <div className="mind-tool-controls">
        <input
          ref={inputRef}
          className="mind-tool-input"
          placeholder="state, region, or keyword…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKey}
        />
        <select
          className="mind-tool-select"
          value={archetype}
          onChange={(e) => setArchetype(e.target.value as typeof ARCHETYPES[number])}
        >
          {ARCHETYPES.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        <button
          className="mind-tool-run-btn"
          onClick={run}
          disabled={state.status === 'loading'}
        >
          {state.status === 'loading' ? '…' : 'scout'}
        </button>
      </div>

      {state.status === 'idle' && (
        <div className="mind-tool-idle">filter + rank avalon sample sites by archetype</div>
      )}
      {state.status === 'error' && (
        <div className="mind-tool-error">{state.msg}</div>
      )}
      {results.length > 0 && (
        <div className="mind-tool-site-list">
          {results.map((r, i) => (
            <div key={r.site_id} className="mind-tool-site-row">
              <span className="mind-tool-site-rank">#{i + 1}</span>
              <div className="mind-tool-site-info">
                <span className="mind-tool-site-name">{r.name}</span>
                <span className="mind-tool-site-state">{r.state}</span>
              </div>
              <div className="mind-tool-site-score-wrap">
                <div
                  className="mind-tool-site-bar"
                  style={{ width: `${Math.round((r.composite / maxScore) * 100)}%` }}
                />
                <span className="mind-tool-site-score">{(r.composite * 100).toFixed(0)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Tool 3: Regime Pulse ────────────────────────────────────────────────────

function RegimePulseTool() {
  const [state, setState] = useState<ToolState<RegimePulse>>({ status: 'idle' })

  async function run() {
    setState({ status: 'loading' })
    try {
      const data = await fetchRegimePulse()
      setState({ status: 'ok', data })
    } catch (e) {
      setState({ status: 'error', msg: e instanceof Error ? e.message : String(e) })
    }
  }

  const data = state.status === 'ok' ? state.data : null
  const pct = data ? Math.round(data.confidence * 100) : 0

  return (
    <div className="mind-tool-card">
      <div className="mind-tool-header">
        <Activity className="h-3 w-3" strokeWidth={2.2} />
        <span className="mind-tool-title">regime pulse</span>
        <button
          className="mind-tool-run"
          onClick={run}
          disabled={state.status === 'loading'}
        >
          {state.status === 'loading' ? '…' : <RefreshCcw className="h-2.5 w-2.5" strokeWidth={2.5} />}
        </button>
      </div>

      {state.status === 'idle' && (
        <div className="mind-tool-idle">read current hmm market regime classification</div>
      )}
      {state.status === 'error' && (
        <div className="mind-tool-error">{state.msg}</div>
      )}
      {data && (
        <div className="mind-tool-body">
          <div className="mind-tool-regime-hero">
            <span className="mind-tool-regime-label" style={{ color: regimeColor(data.regime) }}>
              {data.regime}
            </span>
            <div className="mind-tool-confidence-bar-wrap">
              <div
                className="mind-tool-confidence-bar"
                style={{
                  width: `${pct}%`,
                  background: regimeColor(data.regime),
                }}
              />
            </div>
            <span className="mind-tool-confidence-pct">{pct}% confidence</span>
          </div>
          {data.signals.length > 0 && (
            <div className="mind-tool-regime-signals">
              {data.signals.map((s, i) => (
                <div key={i} className="mind-tool-row">
                  <span className="mind-tool-key">{s.name}</span>
                  <span className="mind-tool-val">{s.value} {s.direction !== '—' ? `(${s.direction})` : ''}</span>
                </div>
              ))}
            </div>
          )}
          {data.updated && (
            <div className="mind-tool-updated">updated {data.updated.slice(0, 10)}</div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Container section ───────────────────────────────────────────────────────

function LiveToolsSection() {
  return (
    <div className="mind-section">
      <div className="mind-section-head">
        <div className="mind-section-label">LIVE TOOLS</div>
        <div className="mind-section-meta">interact directly</div>
      </div>
      <div className="mind-tools-grid">
        <OratorSnapshotTool />
        <SiteScoutTool />
        <RegimePulseTool />
      </div>
    </div>
  )
}

export default function MindPanel() {
  const [data, setData] = useState<MindData | null>(null)
  const [expandedInsight, setExpandedInsight] = useState<string | null>(null)
  const [expandedReflection, setExpandedReflection] = useState<string | null>(null)
  const [pulse, setPulse] = useState(false)
  const [reflecting, setReflecting] = useState(false)
  const [localReflections, setLocalReflections] = useState<ReflectionEntry[]>([])
  const [statusText, setStatusText] = useState('hover the cortex to surface actions')

  function pulsePanel() {
    setPulse(true)
    setTimeout(() => setPulse(false), 600)
  }

  async function load() {
    try {
      const d = await fetchMind()
      setData(d)
      pulsePanel()
      return
    } catch {
      try {
        const [memoryData, historyData] = await Promise.all([
          fetchMemory(),
          fetchHistory(),
        ])
        const fallback = buildFallbackMindData(
          (memoryData.entries ?? []) as MemoryEntry[],
          (historyData ?? []) as HistoryEntry[],
        )
        setData(fallback)
        pulsePanel()
      } catch {
        setData(null)
      }
    }
  }

  useEffect(() => {
    setLocalReflections(readStoredReflections())
    void load()
    const intervalId = setInterval(() => {
      void load()
    }, 12_000)
    return () => clearInterval(intervalId)
  }, [])

  const reflections = useMemo(() => mergeReflections(data?.reflections, localReflections), [data?.reflections, localReflections])
  const stats = data?.stats
  const insights = data?.insights ?? []
  const topics = data?.recent_topics ?? []
  const topicMap = data?.topic_map ?? []

  async function handleReflect() {
    if (!data || reflecting) return
    setReflecting(true)
    setStatusText('mithrandir is reflecting over recent memory')
    try {
      let parsed: Omit<ReflectionEntry, 'id' | 'timestamp' | 'source'>
      try {
        const raw = await generateMindReflection(buildReflectionPrompt(data))
        parsed = parseReflection(raw)
      } catch {
        parsed = buildLocalReflection(data)
      }

      const entry: ReflectionEntry = {
        id: `reflection-${Date.now()}`,
        timestamp: new Date().toISOString(),
        source: 'mithrandir',
        ...parsed,
      }

      const next = [entry, ...localReflections].slice(0, 18)
      setLocalReflections(next)
      writeStoredReflections(next)
      setExpandedReflection(entry.id)
      setStatusText('new reflection stored in local mind cache')
      pulsePanel()
    } finally {
      setReflecting(false)
    }
  }

  return (
    <div className="mind-panel">
      <div className="mind-header">
        <span className={`mind-pulse-dot ${pulse ? 'mind-pulse-active' : ''}`} />
        <span className="mind-header-title">AWARENESS</span>
        {stats && <span className="mind-depth-badge">{stats.total} exchanges</span>}
      </div>

      <div className="mind-body">
        <div className="mind-section mind-hero-section">
          <div
            className={`mind-neural-stage ${reflecting ? 'is-reflecting' : ''}`}
            onMouseEnter={() => setStatusText('inspect, refresh, or trigger reflection')}
            onMouseLeave={() => setStatusText(reflecting ? 'mithrandir is reflecting over recent memory' : 'hover the cortex to surface actions')}
          >
            <div className="mind-neural-ambient" aria-hidden="true" />
            <svg viewBox="0 0 280 220" className="mind-neural-svg" aria-hidden="true">
              {/* Top-down (dorsal) anatomical brain view */}

              <defs>
                <filter id="brainGlowA">
                  <feGaussianBlur stdDeviation="3" result="blur"/>
                  <feMerge>
                    <feMergeNode in="blur"/>
                    <feMergeNode in="SourceGraphic"/>
                  </feMerge>
                </filter>
                <filter id="coreGlowA">
                  <feGaussianBlur stdDeviation="2" result="blur"/>
                  <feMerge>
                    <feMergeNode in="blur"/>
                    <feMergeNode in="SourceGraphic"/>
                  </feMerge>
                </filter>
              </defs>

              {/* Ambient field glow */}
              <ellipse cx="140" cy="112" rx="96" ry="76" fill="rgba(80,140,220,0.07)" filter="url(#brainGlowA)" />

              {/* ── Right cerebral hemisphere ── */}
              <path
                d="M 140 28 C 175 24, 222 46, 245 84 C 258 110, 252 148, 230 172 C 210 190, 176 198, 148 197 L 140 196 Z"
                className="mind-hemi" filter="url(#brainGlowA)"
              />

              {/* ── Left cerebral hemisphere ── */}
              <path
                d="M 140 28 C 105 24, 58 46, 35 84 C 22 110, 28 148, 50 172 C 70 190, 104 198, 132 197 L 140 196 Z"
                className="mind-hemi" filter="url(#brainGlowA)"
              />

              {/* ── Right hemisphere sulci (grooves between gyri) ── */}
              {/* Medial sulcus R — just right of midline */}
              <path d="M 146 32 C 150 68, 150 105, 148 138 C 146 163, 142 183, 140 196" className="mind-fold-major" />
              {/* Superior frontal sulcus R */}
              <path d="M 160 30 C 168 60, 170 95, 167 130 C 163 158, 155 180, 149 195" className="mind-fold" />
              {/* Intraparietal sulcus R */}
              <path d="M 185 36 C 200 63, 206 94, 201 126 C 195 154, 180 172, 166 186" className="mind-fold-major" />
              {/* Lateral groove R */}
              <path d="M 218 56 C 234 80, 240 108, 231 136 C 221 160, 200 175, 183 185" className="mind-fold" />
              {/* Central sulcus R — transverse landmark separating frontal from parietal */}
              <path d="M 148 74 C 166 69, 190 67, 213 70 C 228 73, 240 79, 245 88" className="mind-fold-major" />
              {/* Post-central sulcus R */}
              <path d="M 148 92 C 164 88, 185 87, 206 90 C 222 93, 234 99, 241 108" className="mind-fold" />
              {/* Parieto-occipital sulcus R */}
              <path d="M 148 154 C 165 151, 186 147, 205 142 C 222 137, 234 131, 241 122" className="mind-fold" />

              {/* ── Left hemisphere sulci (mirror) ── */}
              {/* Medial sulcus L */}
              <path d="M 134 32 C 130 68, 130 105, 132 138 C 134 163, 138 183, 140 196" className="mind-fold-major" />
              {/* Superior frontal sulcus L */}
              <path d="M 120 30 C 112 60, 110 95, 113 130 C 117 158, 125 180, 131 195" className="mind-fold" />
              {/* Intraparietal sulcus L */}
              <path d="M 95 36 C 80 63, 74 94, 79 126 C 85 154, 100 172, 114 186" className="mind-fold-major" />
              {/* Lateral groove L */}
              <path d="M 62 56 C 46 80, 40 108, 49 136 C 59 160, 80 175, 97 185" className="mind-fold" />
              {/* Central sulcus L */}
              <path d="M 132 74 C 114 69, 90 67, 67 70 C 52 73, 40 79, 35 88" className="mind-fold-major" />
              {/* Post-central sulcus L */}
              <path d="M 132 92 C 116 88, 95 87, 74 90 C 58 93, 46 99, 39 108" className="mind-fold" />
              {/* Parieto-occipital sulcus L */}
              <path d="M 132 154 C 115 151, 94 147, 75 142 C 58 137, 46 131, 39 122" className="mind-fold" />

              {/* ── Gyral ridge highlights — bright ridge crests ── */}
              {/* Right crests */}
              <path d="M 153 31 C 158 64, 159 100, 157 134 C 155 160, 151 180, 148 195" className="mind-gyrus-ridge" />
              <path d="M 172 33 C 182 61, 187 94, 183 127 C 179 156, 167 176, 157 190" className="mind-gyrus-ridge" />
              <path d="M 200 44 C 217 70, 222 100, 215 130 C 207 158, 190 173, 174 184" className="mind-gyrus-ridge" />
              {/* Left crests (mirror) */}
              <path d="M 127 31 C 122 64, 121 100, 123 134 C 125 160, 129 180, 132 195" className="mind-gyrus-ridge" />
              <path d="M 108 33 C 98 61, 93 94, 97 127 C 101 156, 113 176, 123 190" className="mind-gyrus-ridge" />
              <path d="M 80 44 C 63 70, 58 100, 65 130 C 73 158, 90 173, 106 184" className="mind-gyrus-ridge" />

              {/* Interhemispheric fissure — midline groove */}
              <line x1="140" y1="28" x2="140" y2="196" className="mind-sulcus" />
              {/* Frontal notch where fissure meets frontal pole */}
              <path d="M 133 28 C 136 22, 144 22, 147 28" className="mind-fold-major" />

              {/* ── Neural pathways radiating outward ── */}
              <line x1="84"  y1="56"  x2="30"  y2="28"  className="mind-syn" />
              <line x1="40"  y1="112" x2="10"  y2="120" className="mind-syn" />
              <line x1="68"  y1="178" x2="28"  y2="210" className="mind-syn" />
              <line x1="196" y1="56"  x2="250" y2="28"  className="mind-syn" />
              <line x1="240" y1="112" x2="270" y2="120" className="mind-syn" />
              <line x1="212" y1="178" x2="252" y2="210" className="mind-syn" />
              <line x1="140" y1="197" x2="140" y2="218" className="mind-syn" />

              {/* Traveling synaptic pulses */}
              <path d="M 84 56 L 30 28"   className="mind-pulse pulse-1" />
              <path d="M 40 112 L 10 120"  className="mind-pulse pulse-2" />
              <path d="M 68 178 L 28 210"  className="mind-pulse pulse-3" />
              <path d="M 196 56 L 250 28"  className="mind-pulse pulse-4" />
              <path d="M 240 112 L 270 120" className="mind-pulse pulse-5" />
              <path d="M 212 178 L 252 210" className="mind-pulse pulse-6" />
              <path d="M 140 197 L 140 218" className="mind-pulse pulse-7" />

              {/* Neural endpoint nodes */}
              <circle cx="30"  cy="28"  r="2.2" className="mind-nc node-1" />
              <circle cx="10"  cy="120" r="2.2" className="mind-nc node-2" />
              <circle cx="28"  cy="210" r="2.2" className="mind-nc node-3" />
              <circle cx="250" cy="28"  r="2.2" className="mind-nc node-4" />
              <circle cx="270" cy="120" r="2.2" className="mind-nc node-5" />
              <circle cx="252" cy="210" r="2.2" className="mind-nc node-6" />
              <circle cx="140" cy="218" r="2.2" className="mind-nc node-7" />

              {/* Corpus callosum core glow */}
              <circle cx="140" cy="112" r="5.5" className="mind-nc mind-nc-core" filter="url(#coreGlowA)" />
            </svg>
            <div className="mind-neural-chips">
              <button
                className="mind-neural-chip"
                onClick={handleReflect}
                disabled={reflecting || !data}
              >
                <Sparkles className="h-3 w-3" strokeWidth={2.2} />
                {reflecting ? 'Reflecting…' : 'Reflect'}
              </button>
              <button className="mind-neural-chip" onClick={() => void load()}>
                <RefreshCcw className="h-3 w-3" strokeWidth={2.2} />
                Refresh
              </button>
            </div>
            <div className="mind-neural-status">{statusText}</div>
          </div>
        </div>

        {stats && (
          <div className="mind-section">
            <div className="mind-section-label">DEPTH</div>
            <div className="mind-depth-grid">
              <div className="mind-stat-cell">
                <span className="mind-stat-val">{stats.total}</span>
                <span className="mind-stat-key">total</span>
              </div>
              <div className="mind-stat-cell">
                <span className="mind-stat-val">{stats.thumbs_up}</span>
                <span className="mind-stat-key">valued</span>
              </div>
              <div className="mind-stat-cell">
                <span className="mind-stat-val">{stats.rated}</span>
                <span className="mind-stat-key">rated</span>
              </div>
            </div>
            {stats.first_exchange && <div className="mind-born">awakened {formatBorn(stats.first_exchange)}</div>}
          </div>
        )}

        {reflections.length > 0 && (
          <div className="mind-section">
            <div className="mind-section-head">
              <div className="mind-section-label">REFLECTIONS</div>
              <div className="mind-section-meta">stored thoughts</div>
            </div>
            <div className="mind-reflections-list">
              {reflections.map((reflection) => (
                <div
                  key={reflection.id}
                  className={`mind-reflection-card ${expandedReflection === reflection.id ? 'expanded' : ''}`}
                  onClick={() => setExpandedReflection(expandedReflection === reflection.id ? null : reflection.id)}
                >
                  <div className="mind-reflection-head">
                    <div>
                      <div className="mind-reflection-title">{reflection.title}</div>
                      <div className="mind-reflection-meta">
                        <span>{formatRelative(reflection.timestamp)}</span>
                        <span>{reflection.source === 'mithrandir' ? 'synthetic' : 'local'}</span>
                      </div>
                    </div>
                    <div className="mind-reflection-tags">
                      {reflection.tags.slice(0, 3).map((tag) => (
                        <span key={tag} className="mind-reflection-tag">{tag}</span>
                      ))}
                    </div>
                  </div>
                  {expandedReflection === reflection.id && (
                    <div className="mind-reflection-body">
                      <p>{reflection.reflection}</p>
                      <p className="mind-reflection-implication">{reflection.implication}</p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {topicMap.length > 0 && (
          <div className="mind-section">
            <div className="mind-section-label">KNOWLEDGE MAP</div>
            <div className="mind-topic-map">
              {topicMap.map((topic) => (
                <div key={topic.term} className="mind-topic-row">
                  <span className="mind-topic-term">{topic.term}</span>
                  <div className="mind-topic-bar-wrap">
                    <div className="mind-topic-bar" style={{ width: `${topic.pct}%` }} />
                  </div>
                  <span className="mind-topic-count">{topic.count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {insights.length > 0 && (
          <div className="mind-section">
            <div className="mind-section-head">
              <div className="mind-section-label">INSIGHTS</div>
              <div className="mind-section-meta">valued exchanges</div>
            </div>
            <div className="mind-insights-list">
              {insights.map((insight) => (
                <div
                  key={insight.id}
                  className={`mind-insight-card ${expandedInsight === insight.id ? 'expanded' : ''}`}
                  onClick={() => setExpandedInsight(expandedInsight === insight.id ? null : insight.id)}
                >
                  <div className="mind-insight-header">
                    {insight.rating === 1 && <span className="mind-insight-star" title="Valued exchange">★</span>}
                    <span className="mind-insight-q">{insight.user}</span>
                    <span className="mind-insight-age">{formatRelative(insight.timestamp)}</span>
                  </div>
                  {expandedInsight === insight.id && <div className="mind-insight-body">{insight.assistant}</div>}
                </div>
              ))}
            </div>
          </div>
        )}

        {topics.length > 0 && (
          <div className="mind-section">
            <div className="mind-section-head">
              <div className="mind-section-label">RECENT STREAM</div>
              <div className="mind-section-meta">active memory</div>
            </div>
            <div className="mind-stream">
              {topics.map((topic, index) => (
                <div key={`${topic.timestamp}-${index}`} className="mind-stream-row">
                  <span className="mind-stream-age">{formatRelative(topic.timestamp)}</span>
                  <span className="mind-stream-msg">{topic.msg}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {!data && <div className="mind-offline">Mithrandir backend offline — memory unavailable</div>}

        <LiveToolsSection />
      </div>
    </div>
  )
}
