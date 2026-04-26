import { useEffect, useMemo, useState } from 'react'
import { RefreshCcw, Sparkles } from 'lucide-react'
import { fetchHistory, fetchMemory, fetchMind, generateMindReflection } from '../api'

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
            <svg viewBox="0 0 200 150" className="mind-neural-svg" aria-hidden="true">
              {/* Orbit rings — 3 planes give 3-D orbital feel */}
              <ellipse cx="100" cy="75" rx="86" ry="24" className="mind-ring mind-ring-a" />
              <ellipse cx="100" cy="75" rx="24" ry="72" className="mind-ring mind-ring-b" />
              <ellipse cx="100" cy="75" rx="72" ry="20" className="mind-ring mind-ring-c" />
              {/* Left hemisphere — 3 gyri bumps on outer edge */}
              <path d="M 100 20 C 90 15,76 13,62 18 C 50 23,42 30,38 37 C 34 37,28 39,26 47 C 24 55,28 58,28 63 C 24 68,20 72,20 78 C 20 84,24 88,26 94 C 24 100,26 105,28 110 C 32 116,42 122,56 126 C 70 130,86 130,100 128" className="mind-hemi" />
              {/* Right hemisphere — mirror */}
              <path d="M 100 20 C 110 15,124 13,138 18 C 150 23,158 30,162 37 C 166 37,172 39,174 47 C 176 55,172 58,172 63 C 176 68,180 72,180 78 C 180 84,176 88,174 94 C 176 100,174 105,172 110 C 168 116,158 122,144 126 C 130 130,114 130,100 128" className="mind-hemi" />
              {/* Longitudinal fissure — slightly wavy center line */}
              <path d="M 100 20 C 99 55,101 90,100 128" className="mind-sulcus" />
              {/* Left sulci — major gyral boundaries */}
              <path d="M 85 28 C 70 36,58 48,54 62 C 52 70,54 80,56 90" className="mind-fold" />
              <path d="M 74 70 C 64 70,54 66,46 58" className="mind-fold" />
              <path d="M 82 100 C 70 104,58 110,52 120" className="mind-fold" />
              {/* Right sulci — mirror */}
              <path d="M 115 28 C 130 36,142 48,146 62 C 148 70,146 80,144 90" className="mind-fold" />
              <path d="M 126 70 C 136 70,146 66,154 58" className="mind-fold" />
              <path d="M 118 100 C 130 104,142 110,148 120" className="mind-fold" />
              {/* Synaptic base connections */}
              <line x1="100" y1="72" x2="100" y2="46" className="mind-syn" />
              <line x1="100" y1="72" x2="74" y2="56" className="mind-syn" />
              <line x1="100" y1="72" x2="126" y2="56" className="mind-syn" />
              <line x1="100" y1="72" x2="58" y2="80" className="mind-syn" />
              <line x1="100" y1="72" x2="142" y2="80" className="mind-syn" />
              <line x1="100" y1="72" x2="74" y2="104" className="mind-syn" />
              <line x1="100" y1="72" x2="126" y2="104" className="mind-syn" />
              {/* Traveling synaptic pulses */}
              <path d="M100 72 L100 46" className="mind-pulse pulse-1" />
              <path d="M100 72 L74 56"  className="mind-pulse pulse-2" />
              <path d="M100 72 L126 56" className="mind-pulse pulse-3" />
              <path d="M100 72 L58 80"  className="mind-pulse pulse-4" />
              <path d="M100 72 L142 80" className="mind-pulse pulse-5" />
              <path d="M100 72 L74 104" className="mind-pulse pulse-6" />
              <path d="M100 72 L126 104" className="mind-pulse pulse-7" />
              {/* Peripheral nodes */}
              <circle cx="100" cy="46"  r="3"   className="mind-nc node-top" />
              <circle cx="74"  cy="56"  r="3.5" className="mind-nc node-1" />
              <circle cx="126" cy="56"  r="3.5" className="mind-nc node-2" />
              <circle cx="58"  cy="80"  r="3"   className="mind-nc node-3" />
              <circle cx="142" cy="80"  r="3"   className="mind-nc node-4" />
              <circle cx="74"  cy="104" r="3"   className="mind-nc node-5" />
              <circle cx="126" cy="104" r="3"   className="mind-nc node-6" />
              {/* Core — always rendered last so it's on top */}
              <circle cx="100" cy="72"  r="7"   className="mind-nc mind-nc-core" />
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
      </div>
    </div>
  )
}
