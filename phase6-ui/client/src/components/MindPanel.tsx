import { useEffect, useMemo, useState } from 'react'
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

function buildLiveContextBlock(args: {
  orator: ToolState<MacroSnapshotBrief>
  regime: ToolState<RegimePulse>
  siteScout: ToolState<SiteScoutResult[]>
  scoutQuery: string
  scoutArchetype: typeof ARCHETYPES[number]
}): string {
  const parts: string[] = []

  if (args.orator.status === 'ok') {
    const snapshot = args.orator.data
    const signals = snapshot.top_signals.slice(0, 4).map((signal) => `${signal.name}: ${signal.value} (${signal.state})`).join('; ')
    parts.push(
      [
        'Orator macro brief:',
        `- Recession: ${Math.round(snapshot.recession_composite * 100)}% (${snapshot.recession_label})`,
        `- Stagflation: ${Math.round(snapshot.stagflation_score * 100)}%`,
        `- VIX: ${snapshot.vix?.toFixed(1) ?? '—'} (${snapshot.vix_regime ?? 'unknown'})`,`
        `- Yield curve 2s10s: ${Math.round(snapshot.yield_curve_spread_2_10 * 100)} bps${snapshot.yield_curve_inverted ? ' inverted' : ''}`,
        `- Narrative: ${snapshot.narrative}`,
        signals ? `- Top signals: ${signals}` : '',
      ].filter(Boolean).join('\n'),
    )
  }

  if (args.regime.status === 'ok') {
    const regime = args.regime.data
    const signals = regime.signals.slice(0, 4).map((signal) => `${signal.name}: ${signal.value}${signal.direction !== '—' ? ` (${signal.direction})` : ''}`).join('; ')
    parts.push(
      [
        'Regime pulse:',
        `- Regime: ${regime.regime}`,
        `- Confidence: ${Math.round(regime.confidence * 100)}%`,
        signals ? `- Drivers: ${signals}` : '',
      ].filter(Boolean).join('\n'),
    )
  }

  if (args.siteScout.status === 'ok' && args.siteScout.data.length > 0) {
    const topSites = args.siteScout.data.slice(0, 3)
      .map((site) => `${site.name}, ${site.state} (${Math.round(site.composite * 100)})`)
      .join('; ')
    parts.push(
      [
        'Avalon site scout:',
        `- Query: ${args.scoutQuery || 'default'} / archetype ${args.scoutArchetype}`,
        `- Best matches: ${topSites}`,
      ].join('\n'),
    )
  }

  return parts.length > 0 ? `\n\nLive system context:\n${parts.join('\n\n')}` : ''
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

const ARCHETYPES = ['mixed', 'training', 'inference'] as const

export default function MindPanel() {
  const [data, setData] = useState<MindData | null>(null)
  const [expandedInsight, setExpandedInsight] = useState<string | null>(null)
  const [expandedReflection, setExpandedReflection] = useState<string | null>(null)
  const [pulse, setPulse] = useState(false)
  const [reflecting, setReflecting] = useState(false)
  const [localReflections, setLocalReflections] = useState<ReflectionEntry[]>([])
  const [statusText, setStatusText] = useState('hover the star to surface actions')
  const [activeTool, setActiveTool] = useState<'reflect' | 'orator' | 'avalon' | 'regime'>('reflect')
  const [oratorState, setOratorState] = useState<ToolState<MacroSnapshotBrief>>({ status: 'idle' })
  const [siteScoutState, setSiteScoutState] = useState<ToolState<SiteScoutResult[]>>({ status: 'idle' })
  const [regimeState, setRegimeState] = useState<ToolState<RegimePulse>>({ status: 'idle' })
  const [scoutQuery, setScoutQuery] = useState('texas')
  const [scoutArchetype, setScoutArchetype] = useState<typeof ARCHETYPES[number]>('mixed')

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
    void loadOratorSnapshot()
    void loadRegimePulse()
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

  async function loadOratorSnapshot() {
    setOratorState({ status: 'loading' })
    setActiveTool('orator')
    setStatusText('drawing Orator macro brief into active awareness')
    try {
      const result = await fetchOratorSnapshot()
      setOratorState({ status: 'ok', data: result })
      setStatusText('Orator macro brief aligned with reflection layer')
      pulsePanel()
      return result
    } catch (e) {
      setOratorState({ status: 'error', msg: e instanceof Error ? e.message : String(e) })
      setStatusText('Orator brief unavailable')
      return null
    }
  }

  async function loadRegimePulse() {
    setRegimeState({ status: 'loading' })
    setActiveTool('regime')
    setStatusText('reading regime pulse from live market state')
    try {
      const result = await fetchRegimePulse()
      setRegimeState({ status: 'ok', data: result })
      setStatusText('regime pulse is now feeding the star')
      pulsePanel()
      return result
    } catch (e) {
      setRegimeState({ status: 'error', msg: e instanceof Error ? e.message : String(e) })
      setStatusText('regime pulse unavailable')
      return null
    }
  }

  async function runSiteScout(nextQuery = scoutQuery, nextArchetype = scoutArchetype) {
    setSiteScoutState({ status: 'loading' })
    setActiveTool('avalon')
    setStatusText('scouting Avalon sites into the reflection stream')
    try {
      const result = await fetchSiteScout(nextQuery, nextArchetype)
      setSiteScoutState({ status: 'ok', data: result.results })
      setStatusText(`Avalon scout resolved ${result.results.length} candidate sites`)
      pulsePanel()
      return result.results
    } catch (e) {
      setSiteScoutState({ status: 'error', msg: e instanceof Error ? e.message : String(e) })
      setStatusText('Avalon scout unavailable')
      return null
    }
  }

  async function handleReflect() {
    if (!data || reflecting) return
    setReflecting(true)
    setActiveTool('reflect')
    setStatusText('mithrandir is reflecting over recent memory')
    try {
      let parsed: Omit<ReflectionEntry, 'id' | 'timestamp' | 'source'>
      try {
        const oratorData = oratorState.status === 'ok' ? oratorState.data : await loadOratorSnapshot()
        const regimeData = regimeState.status === 'ok' ? regimeState.data : await loadRegimePulse()
        const raw = await generateMindReflection(
          `${buildReflectionPrompt(data)}${buildLiveContextBlock({
            orator: oratorData ? { status: 'ok', data: oratorData } : oratorState,
            regime: regimeData ? { status: 'ok', data: regimeData } : regimeState,
            siteScout: siteScoutState,
            scoutQuery,
            scoutArchetype,
          })}`,
        )
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
            onMouseLeave={() => setStatusText(reflecting ? 'mithrandir is reflecting over recent memory' : 'hover the star to surface actions')}
          >
            <div className="mind-neural-ambient" aria-hidden="true" />
            <svg viewBox="0 0 280 220" className="mind-neural-svg" aria-hidden="true">
              <defs>
                <radialGradient id="starSphereA" cx="50%" cy="48%" r="58%">
                  <stop offset="0%" stopColor="rgba(246,252,255,1)" />
                  <stop offset="34%" stopColor="rgba(186,228,255,0.95)" />
                  <stop offset="74%" stopColor="rgba(114,172,235,0.84)" />
                  <stop offset="100%" stopColor="rgba(72,130,205,0.74)" />
                </radialGradient>
                <radialGradient id="starHaloA" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="rgba(174,228,255,0.48)" />
                  <stop offset="62%" stopColor="rgba(132,186,248,0.18)" />
                  <stop offset="100%" stopColor="rgba(100,160,240,0)" />
                </radialGradient>
                <filter id="starGlowA">
                  <feGaussianBlur stdDeviation="3.2" result="blur"/>
                  <feMerge>
                    <feMergeNode in="blur"/>
                    <feMergeNode in="SourceGraphic"/>
                  </feMerge>
                </filter>
                <filter id="starCoreA">
                  <feGaussianBlur stdDeviation="2.4" result="blur"/>
                  <feMerge>
                    <feMergeNode in="blur"/>
                    <feMergeNode in="SourceGraphic"/>
                  </feMerge>
                </filter>
              </defs>

              <ellipse cx="140" cy="112" rx="124" ry="94" className="mind-star-halo" filter="url(#starGlowA)" />
              <ellipse cx="140" cy="112" rx="138" ry="104" className="mind-star-halo-outer" filter="url(#starGlowA)" />

              <g className="mind-star-rings">
                <ellipse cx="140" cy="112" rx="98" ry="62" className="mind-ring mind-ring-a" />
                <ellipse cx="140" cy="112" rx="66" ry="100" className="mind-ring mind-ring-b" />
                <ellipse cx="140" cy="112" rx="84" ry="84" className="mind-ring mind-ring-c" />
              </g>

              <g className="mind-star-rayfield">
                <line x1="140" y1="20" x2="140" y2="55" className="mind-star-ray ray-n" />
                <line x1="140" y1="204" x2="140" y2="169" className="mind-star-ray ray-s" />
                <line x1="40" y1="112" x2="74" y2="112" className="mind-star-ray ray-w" />
                <line x1="240" y1="112" x2="206" y2="112" className="mind-star-ray ray-e" />
                <line x1="72" y1="44" x2="95" y2="67" className="mind-star-ray ray-nw" />
                <line x1="208" y1="44" x2="185" y2="67" className="mind-star-ray ray-ne" />
                <line x1="72" y1="180" x2="95" y2="157" className="mind-star-ray ray-sw" />
                <line x1="208" y1="180" x2="185" y2="157" className="mind-star-ray ray-se" />
              </g>

              <circle cx="140" cy="112" r="56" className="mind-star-sphere" fill="url(#starSphereA)" />
              <ellipse cx="140" cy="98" rx="42" ry="20" className="mind-star-highlight" />

              {/* Ethereal wisps (less geometric, more angelic) */}
              <path d="M 90 108 C 112 88, 168 86, 194 106" className="mind-star-wisp" />
              <path d="M 90 118 C 116 132, 166 134, 194 118" className="mind-star-wisp" />
              <path d="M 104 78 C 120 108, 121 132, 106 154" className="mind-star-wisp" />
              <path d="M 176 78 C 160 108, 159 132, 174 154" className="mind-star-wisp" />

              {/* Long slow streaks emitted from center */}
              <g className="mind-star-streaks">
                <line x1="140" y1="112" x2="140" y2="10" className="mind-star-streak s1" />
                <line x1="140" y1="112" x2="182" y2="16" className="mind-star-streak s2" />
                <line x1="140" y1="112" x2="222" y2="44" className="mind-star-streak s3" />
                <line x1="140" y1="112" x2="264" y2="92" className="mind-star-streak s4" />
                <line x1="140" y1="112" x2="264" y2="132" className="mind-star-streak s5" />
                <line x1="140" y1="112" x2="228" y2="186" className="mind-star-streak s6" />
                <line x1="140" y1="112" x2="184" y2="210" className="mind-star-streak s7" />
                <line x1="140" y1="112" x2="140" y2="220" className="mind-star-streak s8" />
                <line x1="140" y1="112" x2="96" y2="210" className="mind-star-streak s9" />
                <line x1="140" y1="112" x2="52" y2="186" className="mind-star-streak s10" />
                <line x1="140" y1="112" x2="16" y2="132" className="mind-star-streak s11" />
                <line x1="140" y1="112" x2="16" y2="92" className="mind-star-streak s12" />
                <line x1="140" y1="112" x2="58" y2="44" className="mind-star-streak s13" />
                <line x1="140" y1="112" x2="98" y2="16" className="mind-star-streak s14" />
              </g>

              <g className="mind-star-burst">
                <path d="M 140 70 L 146 104 L 180 112 L 146 120 L 140 154 L 134 120 L 100 112 L 134 104 Z" className="mind-star-burst-main" />
                <path d="M 140 82 L 143 102 L 163 112 L 143 122 L 140 142 L 137 122 L 117 112 L 137 102 Z" className="mind-star-burst-inner" />
              </g>

              {/* Slow drifting light particles */}
              <g className="mind-star-particles">
                <circle cx="140" cy="16"  r="1.4" className="mind-star-particle p1" />
                <circle cx="178" cy="22"  r="1.2" className="mind-star-particle p2" />
                <circle cx="216" cy="42"  r="1.6" className="mind-star-particle p3" />
                <circle cx="250" cy="78"  r="1.3" className="mind-star-particle p4" />
                <circle cx="266" cy="114" r="1.5" className="mind-star-particle p5" />
                <circle cx="248" cy="148" r="1.2" className="mind-star-particle p6" />
                <circle cx="220" cy="184" r="1.5" className="mind-star-particle p7" />
                <circle cx="184" cy="206" r="1.2" className="mind-star-particle p8" />
                <circle cx="140" cy="216" r="1.6" className="mind-star-particle p9" />
                <circle cx="98"  cy="206" r="1.3" className="mind-star-particle p10" />
                <circle cx="60"  cy="184" r="1.4" className="mind-star-particle p11" />
                <circle cx="32"  cy="148" r="1.2" className="mind-star-particle p12" />
                <circle cx="14"  cy="114" r="1.5" className="mind-star-particle p13" />
                <circle cx="30"  cy="78"  r="1.2" className="mind-star-particle p14" />
                <circle cx="64"  cy="42"  r="1.6" className="mind-star-particle p15" />
                <circle cx="102" cy="22"  r="1.3" className="mind-star-particle p16" />
                <circle cx="196" cy="112" r="1.1" className="mind-star-particle p17" />
                <circle cx="84"  cy="112" r="1.1" className="mind-star-particle p18" />
                <circle cx="232" cy="64"  r="1.1" className="mind-star-particle p19" />
                <circle cx="246" cy="102" r="1.0" className="mind-star-particle p20" />
                <circle cx="236" cy="160" r="1.2" className="mind-star-particle p21" />
                <circle cx="204" cy="194" r="1.0" className="mind-star-particle p22" />
                <circle cx="166" cy="212" r="1.1" className="mind-star-particle p23" />
                <circle cx="116" cy="212" r="1.0" className="mind-star-particle p24" />
                <circle cx="76"  cy="196" r="1.2" className="mind-star-particle p25" />
                <circle cx="44"  cy="162" r="1.0" className="mind-star-particle p26" />
                <circle cx="34"  cy="102" r="1.2" className="mind-star-particle p27" />
                <circle cx="48"  cy="64"  r="1.0" className="mind-star-particle p28" />
                <circle cx="78"  cy="30"  r="1.1" className="mind-star-particle p29" />
                <circle cx="116" cy="12"  r="1.0" className="mind-star-particle p30" />
                <circle cx="166" cy="12"  r="1.0" className="mind-star-particle p31" />
                <circle cx="204" cy="30"  r="1.1" className="mind-star-particle p32" />
              </g>

              {/* Ambient filaments + moving pulses */}
              <line x1="102" y1="78" x2="52" y2="54" className="mind-syn" />
              <line x1="88" y1="146" x2="40" y2="172" className="mind-syn" />
              <line x1="178" y1="78" x2="228" y2="54" className="mind-syn" />
              <line x1="192" y1="146" x2="240" y2="172" className="mind-syn" />
              <line x1="140" y1="170" x2="140" y2="214" className="mind-syn" />

              <path d="M 102 78 L 52 54" className="mind-pulse pulse-1" />
              <path d="M 88 146 L 40 172" className="mind-pulse pulse-2" />
              <path d="M 178 78 L 228 54" className="mind-pulse pulse-4" />
              <path d="M 192 146 L 240 172" className="mind-pulse pulse-5" />
              <path d="M 140 170 L 140 214" className="mind-pulse pulse-7" />

              <circle cx="52" cy="54" r="2.2" className="mind-nc node-1" />
              <circle cx="40" cy="172" r="2.2" className="mind-nc node-2" />
              <circle cx="228" cy="54" r="2.2" className="mind-nc node-4" />
              <circle cx="240" cy="172" r="2.2" className="mind-nc node-5" />
              <circle cx="140" cy="214" r="2.2" className="mind-nc node-7" />

              <circle cx="140" cy="112" r="6" className="mind-star-core" filter="url(#starCoreA)" />
            </svg>
            <div className="mind-neural-chips">
              <button
                className={`mind-neural-chip ${activeTool === 'reflect' ? 'is-active' : ''}`}
                onClick={handleReflect}
                disabled={reflecting || !data}
              >
                <Sparkles className="h-3 w-3" strokeWidth={2.2} />
                {reflecting ? 'Reflecting…' : 'Reflect'}
              </button>
              <button
                className={`mind-neural-chip ${activeTool === 'orator' ? 'is-active' : ''}`}
                onClick={() => void loadOratorSnapshot()}
                disabled={oratorState.status === 'loading'}
              >
                <Zap className="h-3 w-3" strokeWidth={2.2} />
                {oratorState.status === 'loading' ? 'Syncing…' : 'Orator'}
              </button>
              <button
                className={`mind-neural-chip ${activeTool === 'avalon' ? 'is-active' : ''}`}
                onClick={() => void runSiteScout()}
                disabled={siteScoutState.status === 'loading'}
              >
                <MapPin className="h-3 w-3" strokeWidth={2.2} />
                {siteScoutState.status === 'loading' ? 'Scouting…' : 'Avalon'}
              </button>
              <button
                className={`mind-neural-chip ${activeTool === 'regime' ? 'is-active' : ''}`}
                onClick={() => void loadRegimePulse()}
                disabled={regimeState.status === 'loading'}
              >
                <Activity className="h-3 w-3" strokeWidth={2.2} />
                {regimeState.status === 'loading' ? 'Reading…' : 'Regime'}
              </button>
              <button className="mind-neural-chip" onClick={() => void load()}>
                <RefreshCcw className="h-3 w-3" strokeWidth={2.2} />
                Refresh
              </button>
            </div>
            <div className={`mind-tool-orbit mind-tool-orbit--${activeTool}`}>
              <div className="mind-tool-orbit-glow" aria-hidden="true" />
              <div className="mind-tool-orbit-panel">
                {activeTool === 'reflect' && (
                  <div className="mind-orbit-feed">
                    <div className="mind-orbit-head">
                      <span className="mind-orbit-kicker">reflection input</span>
                      <span className="mind-orbit-badge">live synthesis</span>
                    </div>
                    <div className="mind-orbit-copy">
                      Reflection now blends memory patterns with Orator macro context and any active Avalon scout results before generating a new thought.
                    </div>
                    <div className="mind-orbit-stats">
                      <div className="mind-orbit-stat">
                        <span className="mind-orbit-stat-key">orator</span>
                        <span className={`mind-orbit-stat-val state-${oratorState.status}`}>{oratorState.status}</span>
                      </div>
                      <div className="mind-orbit-stat">
                        <span className="mind-orbit-stat-key">avalon</span>
                        <span className={`mind-orbit-stat-val state-${siteScoutState.status}`}>{siteScoutState.status}</span>
                      </div>
                      <div className="mind-orbit-stat">
                        <span className="mind-orbit-stat-key">regime</span>
                        <span className={`mind-orbit-stat-val state-${regimeState.status}`}>{regimeState.status}</span>
                      </div>
                    </div>
                  </div>
                )}

                {activeTool === 'orator' && (
                  <div className="mind-orbit-feed">
                    <div className="mind-orbit-head">
                      <span className="mind-orbit-kicker">Orator stream</span>
                      {oratorState.status === 'ok' && <span className="mind-orbit-badge">{oratorState.data.recession_label}</span>}
                    </div>
                    {oratorState.status === 'error' && <div className="mind-orbit-copy mind-orbit-copy--error">{oratorState.msg}</div>}
                    {oratorState.status === 'loading' && <div className="mind-orbit-copy">Pulling macro pulse, term structure, volatility, and signal stack.</div>}
                    {oratorState.status === 'ok' && (
                      <>
                        <div className="mind-orbit-grid">
                          <div className="mind-orbit-grid-cell"><span>recession</span><strong>{Math.round(oratorState.data.recession_composite * 100)}%</strong></div>
                          <div className="mind-orbit-grid-cell"><span>stagflation</span><strong>{Math.round(oratorState.data.stagflation_score * 100)}%</strong></div>
                          <div className="mind-orbit-grid-cell"><span>vix</span><strong>{oratorState.data.vix?.toFixed(1) ?? '—'}</strong></div>
                          <div className="mind-orbit-grid-cell"><span>2s10s</span><strong>{Math.round(oratorState.data.yield_curve_spread_2_10 * 100)} bps</strong></div>
                        </div>
                        <div className="mind-orbit-copy">{oratorState.data.narrative}</div>
                        <div className="mind-orbit-pill-row">
                          {oratorState.data.top_signals.slice(0, 4).map((signal) => (
                            <span key={signal.name} className={`mind-orbit-pill state-${signal.state.toLowerCase()}`}>{signal.name}: {signal.value}</span>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}

                {activeTool === 'avalon' && (
                  <div className="mind-orbit-feed">
                    <div className="mind-orbit-head">
                      <span className="mind-orbit-kicker">Avalon scout</span>
                      <span className="mind-orbit-badge">interactive</span>
                    </div>
                    <div className="mind-orbit-controls">
                      <input
                        className="mind-orbit-input"
                        value={scoutQuery}
                        placeholder="state, region, or keyword"
                        onChange={(event) => setScoutQuery(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') void runSiteScout()
                        }}
                      />
                      <select
                        className="mind-orbit-select"
                        value={scoutArchetype}
                        onChange={(event) => setScoutArchetype(event.target.value as typeof ARCHETYPES[number])}
                      >
                        {ARCHETYPES.map((archetype) => (
                          <option key={archetype} value={archetype}>{archetype}</option>
                        ))}
                      </select>
                      <button className="mind-orbit-run" onClick={() => void runSiteScout()} disabled={siteScoutState.status === 'loading'}>
                        scan
                      </button>
                    </div>
                    {siteScoutState.status === 'error' && <div className="mind-orbit-copy mind-orbit-copy--error">{siteScoutState.msg}</div>}
                    {siteScoutState.status === 'loading' && <div className="mind-orbit-copy">Scoring candidate sites and pushing the best matches into the reflection layer.</div>}
                    {siteScoutState.status === 'ok' && (
                      <div className="mind-orbit-list">
                        {siteScoutState.data.slice(0, 4).map((site, index) => (
                          <div key={site.site_id} className="mind-orbit-list-row">
                            <span className="mind-orbit-rank">#{index + 1}</span>
                            <span className="mind-orbit-name">{site.name}</span>
                            <span className="mind-orbit-meta">{site.state}</span>
                            <span className="mind-orbit-score">{Math.round(site.composite * 100)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {activeTool === 'regime' && (
                  <div className="mind-orbit-feed">
                    <div className="mind-orbit-head">
                      <span className="mind-orbit-kicker">regime pulse</span>
                      {regimeState.status === 'ok' && <span className="mind-orbit-badge">{Math.round(regimeState.data.confidence * 100)}%</span>}
                    </div>
                    {regimeState.status === 'error' && <div className="mind-orbit-copy mind-orbit-copy--error">{regimeState.msg}</div>}
                    {regimeState.status === 'loading' && <div className="mind-orbit-copy">Reading live HMM classification and confidence drivers.</div>}
                    {regimeState.status === 'ok' && (
                      <>
                        <div className="mind-orbit-regime">{regimeState.data.regime}</div>
                        <div className="mind-orbit-bar"><span style={{ width: `${Math.round(regimeState.data.confidence * 100)}%` }} /></div>
                        <div className="mind-orbit-list">
                          {regimeState.data.signals.slice(0, 4).map((signal) => (
                            <div key={signal.name} className="mind-orbit-list-row">
                              <span className="mind-orbit-name">{signal.name}</span>
                              <span className="mind-orbit-meta">{signal.direction}</span>
                              <span className="mind-orbit-score">{signal.value}</span>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
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

        <div className="mind-section">
          <div className="mind-section-head">
            <div className="mind-section-label">LIVE CONTEXT</div>
            <div className="mind-section-meta">orator, avalon, regime</div>
          </div>
          <div className="mind-live-context-grid">
            <button
              className={`mind-live-context-card ${activeTool === 'orator' ? 'is-active' : ''}`}
              onClick={() => void loadOratorSnapshot()}
              disabled={oratorState.status === 'loading'}
            >
              <div className="mind-live-context-head">
                <span className="mind-live-context-kicker">orator</span>
                <span className={`mind-live-context-state state-${oratorState.status}`}>{oratorState.status}</span>
              </div>
              {oratorState.status === 'ok' && (
                <>
                  <div className="mind-live-context-title">{oratorState.data.recession_label} recession pulse</div>
                  <div className="mind-live-context-copy">VIX {oratorState.data.vix?.toFixed(1) ?? '—'} with {Math.round((oratorState.data.stagflation_score ?? 0) * 100)}% stagflation risk.</div>
                </>
              )}
              {oratorState.status === 'loading' && <div className="mind-live-context-copy">Pulling macro brief and top signal stack.</div>}
              {oratorState.status === 'error' && <div className="mind-live-context-copy mind-live-context-copy--error">{oratorState.msg}</div>}
              {oratorState.status === 'idle' && <div className="mind-live-context-copy">Sync the latest Orator macro brief into awareness.</div>}
            </button>

            <button
              className={`mind-live-context-card ${activeTool === 'avalon' ? 'is-active' : ''}`}
              onClick={() => {
                setActiveTool('avalon')
                if (siteScoutState.status === 'idle') void runSiteScout()
              }}
              disabled={siteScoutState.status === 'loading'}
            >
              <div className="mind-live-context-head">
                <span className="mind-live-context-kicker">avalon</span>
                <span className={`mind-live-context-state state-${siteScoutState.status}`}>{siteScoutState.status}</span>
              </div>
              {siteScoutState.status === 'ok' && siteScoutState.data[0] && (
                <>
                  <div className="mind-live-context-title">{siteScoutState.data[0].name}</div>
                  <div className="mind-live-context-copy">Top {scoutArchetype} match for "{scoutQuery}" in {siteScoutState.data[0].state}.</div>
                </>
              )}
              {siteScoutState.status === 'loading' && <div className="mind-live-context-copy">Scoring candidate sites and staging them for reflection.</div>}
              {siteScoutState.status === 'error' && <div className="mind-live-context-copy mind-live-context-copy--error">{siteScoutState.msg}</div>}
              {(siteScoutState.status === 'idle' || (siteScoutState.status === 'ok' && !siteScoutState.data[0])) && (
                <div className="mind-live-context-copy">Open the Avalon scout panel to search and rank sites.</div>
              )}
            </button>

            <button
              className={`mind-live-context-card ${activeTool === 'regime' ? 'is-active' : ''}`}
              onClick={() => void loadRegimePulse()}
              disabled={regimeState.status === 'loading'}
            >
              <div className="mind-live-context-head">
                <span className="mind-live-context-kicker">regime</span>
                <span className={`mind-live-context-state state-${regimeState.status}`}>{regimeState.status}</span>
              </div>
              {regimeState.status === 'ok' && (
                <>
                  <div className="mind-live-context-title">{regimeState.data.regime}</div>
                  <div className="mind-live-context-copy">Confidence {Math.round(regimeState.data.confidence * 100)}% with live driver readout.</div>
                </>
              )}
              {regimeState.status === 'loading' && <div className="mind-live-context-copy">Reading HMM regime classification and signal drivers.</div>}
              {regimeState.status === 'error' && <div className="mind-live-context-copy mind-live-context-copy--error">{regimeState.msg}</div>}
              {regimeState.status === 'idle' && <div className="mind-live-context-copy">Pull the current regime pulse into the live context layer.</div>}
            </button>
          </div>
        </div>

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
