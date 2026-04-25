import { useEffect, useRef, useState, useCallback } from 'react'
import { X, Play, CheckCircle, XCircle, Clock, FileCode, GitBranch, ChevronRight, ChevronDown, Send, Lock, GitCommit, GitPullRequest, RefreshCw, MessageSquare } from 'lucide-react'
import { Highlight, themes } from 'prism-react-renderer'
import { wsBase, API_BASE } from '../api'
import ChatPanel from './ChatPanel'

// Session-scoped dev password (cleared when tab closes)
const DEV_PW_KEY = 'mithrandir_dev_pw'
function getDevPw(): string { return sessionStorage.getItem(DEV_PW_KEY) ?? '' }
function setDevPw(pw: string) { sessionStorage.setItem(DEV_PW_KEY, pw) }
function clearDevPw() { sessionStorage.removeItem(DEV_PW_KEY) }

// Map file extension → prism language id
function langFor(rel: string): string {
  const ext = rel.toLowerCase().split('.').pop() ?? ''
  const name = rel.toLowerCase().split('/').pop() ?? ''
  if (name.startsWith('.env')) return 'bash'
  if (name === '.gitignore' || name === '.dockerignore') return 'bash'
  return ({
    py: 'python', ts: 'tsx', tsx: 'tsx', js: 'jsx', jsx: 'jsx',
    json: 'json', md: 'markdown', yml: 'yaml', yaml: 'yaml',
    toml: 'toml', sh: 'bash', ps1: 'powershell', css: 'css',
    html: 'markup', sql: 'sql', csv: 'csv', ini: 'ini', cfg: 'ini',
  } as Record<string, string>)[ext] ?? 'text'
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FilePatch {
  path: string
  original: string
  proposed: string
  status: 'pending' | 'accepted' | 'rejected'
}

interface DevEvent {
  kind: 'log' | 'patch_ready' | 'status' | 'error' | 'narration' | 'ping'
  ts: number
  message: string
  data?: FilePatch | null
  task_id?: string
}

interface DevTask {
  id: string
  goal: string
  project: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'needs_review'
  created_at: number
  updated_at: number
  events: DevEvent[]
  patches: FilePatch[]
  error: string
}

interface ProjectInfo {
  name: string
  exists: boolean
}

interface FileNode {
  name: string
  type: 'file' | 'dir'
  ext?: string
  sensitive?: boolean
  children?: FileNode[]
}

interface Props {
  onClose?: () => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<string, string> = {
  queued:       'text-amber-400',
  running:      'text-blue-400',
  done:         'text-green-400',
  failed:       'text-red-400',
  needs_review: 'text-cyan-400',
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
  queued:       <Clock className="inline h-3 w-3" />,
  running:      <Play className="inline h-3 w-3 animate-pulse" />,
  done:         <CheckCircle className="inline h-3 w-3" />,
  failed:       <XCircle className="inline h-3 w-3" />,
  needs_review: <FileCode className="inline h-3 w-3" />,
}

function ts(unix: number) {
  return new Date(unix * 1000).toLocaleTimeString()
}

async function apiGet<T>(path: string): Promise<T> {
  const base = API_BASE || ''
  const r = await fetch(`${base}${path}`, {
    headers: { 'X-Dev-Password': getDevPw() },
  })
  return r.json() as Promise<T>
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const base = API_BASE || ''
  const r = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Dev-Password': getDevPw() },
    body: JSON.stringify(body),
  })
  return r.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function FileTree({ nodes, onSelect }: { nodes: FileNode[]; onSelect: (name: string) => void }) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  function toggle(name: string) { setOpen(p => ({ ...p, [name]: !p[name] })) }

  return (
    <ul className="pl-3 text-[11px] font-mono">
      {nodes.map(n => (
        <li key={n.name}>
          {n.type === 'dir' ? (
            <div>
              <button
                onClick={() => toggle(n.name)}
                className="flex items-center gap-1 text-slate-400 hover:text-slate-200 py-0.5"
              >
                {open[n.name] ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                {n.name}/
              </button>
              {open[n.name] && n.children && (
                <FileTree nodes={n.children} onSelect={name => onSelect(`${n.name}/${name}`)} />
              )}
            </div>
          ) : (
            <button
              onClick={() => onSelect(n.name)}
              className="pl-4 text-slate-300 hover:text-cyan-300 py-0.5 flex items-center gap-1 w-full text-left"
            >
              {n.sensitive && <Lock className="h-2.5 w-2.5 text-amber-500 shrink-0" />}
              <span className="truncate">{n.name}</span>
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}

function DiffViewer({ original, proposed }: { original: string; proposed: string }) {
  const origLines = original.split('\n')
  const propLines = proposed.split('\n')
  // Simple unified display: show proposed with +/- markers by line comparison
  const maxLen = Math.max(origLines.length, propLines.length)
  const rows: { line: string; kind: 'add' | 'remove' | 'ctx' }[] = []

  for (let i = 0; i < maxLen; i++) {
    const o = origLines[i]
    const p = propLines[i]
    if (o === undefined) {
      rows.push({ line: `+ ${p}`, kind: 'add' })
    } else if (p === undefined) {
      rows.push({ line: `- ${o}`, kind: 'remove' })
    } else if (o !== p) {
      rows.push({ line: `- ${o}`, kind: 'remove' })
      rows.push({ line: `+ ${p}`, kind: 'add' })
    } else {
      rows.push({ line: `  ${o}`, kind: 'ctx' })
    }
  }

  return (
    <pre className="text-[10.5px] font-mono overflow-auto leading-relaxed max-h-[55vh]">
      {rows.map((r, i) => (
        <div
          key={i}
          className={
            r.kind === 'add' ? 'bg-green-950 text-green-300' :
            r.kind === 'remove' ? 'bg-red-950 text-red-300' :
            'text-slate-400'
          }
        >
          {r.line}
        </div>
      ))}
    </pre>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function DevPanel({ onClose }: Props) {
  // Full-panel password gate
  const [unlocked, setUnlocked] = useState<boolean>(!!getDevPw())
  const [gatePw, setGatePw]     = useState('')
  const [gateError, setGateError] = useState('')

  async function tryUnlock() {
    setDevPw(gatePw)
    try {
      const r = await fetch(`${API_BASE || ''}/api/dev/projects`, {
        headers: { 'X-Dev-Password': gatePw },
      })
      if (r.status === 401) {
        clearDevPw()
        setGateError('Incorrect password')
        return
      }
      setUnlocked(true)
      setGateError('')
    } catch {
      setGateError('Connection failed')
    }
  }

  function lockPanel() {
    clearDevPw()
    setUnlocked(false)
    setGatePw('')
    onClose?.()
  }

  if (!unlocked) {
    return (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center"
        style={{ background: '#070d1a', fontFamily: 'Roboto Mono, monospace' }}
      >
        <div className="bg-[#0f1729] border border-cyan-800 rounded-lg p-7 w-96 shadow-2xl">
          <div className="flex items-center gap-3 mb-4">
            <Lock className="h-5 w-5 text-amber-400" />
            <span className="text-[14px] font-semibold tracking-widest uppercase text-cyan-400">
              Mithrandir Dev
            </span>
          </div>
          <p className="text-[11px] text-slate-400 mb-4">
            This environment exposes source code and git operations across the entire portfolio.
            Enter the dev password to continue.
          </p>
          <input
            type="password"
            autoFocus
            value={gatePw}
            onChange={e => setGatePw(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && tryUnlock()}
            placeholder="Dev password…"
            className="w-full bg-[#070d1a] border border-[#1e2d4a] rounded px-3 py-2 text-[12px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-700 mb-2"
          />
          {gateError && (
            <p className="text-[10.5px] text-red-400 mb-2">{gateError}</p>
          )}
          <div className="flex gap-2 mt-3">
            <button
              onClick={tryUnlock}
              disabled={!gatePw}
              className="flex-1 px-3 py-2 rounded bg-cyan-800 text-cyan-200 text-[11px] font-semibold hover:bg-cyan-700 disabled:opacity-40"
            >
              Unlock
            </button>
            <button
              onClick={() => onClose?.()}
              className="px-3 py-2 rounded border border-slate-600 text-slate-400 text-[11px] hover:text-slate-200"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    )
  }

  // Project + tasks
  const [projects, setProjects]       = useState<ProjectInfo[]>([])
  const [activeProject, setActiveProject] = useState('mithrandir')
  const [tasks, setTasks]             = useState<DevTask[]>([])
  const [activeTask, setActiveTask]   = useState<DevTask | null>(null)

  // Task creation
  const [goal, setGoal]               = useState('')
  const [contextFiles, setContextFiles] = useState('')
  const [creating, setCreating]       = useState(false)

  // File tree
  const [fileTree, setFileTree]       = useState<FileNode[]>([])
  const [openedFile, setOpenedFile]   = useState<{ rel: string; contents: string } | null>(null)

  // Patch review
  const [reviewingPatch, setReviewingPatch] = useState<FilePatch | null>(null)

  // Password modal (for sensitive files)
  const [passwordPrompt, setPasswordPrompt] = useState(false)
  const [passwordInput, setPasswordInput] = useState('')
  const [pendingFile, setPendingFile] = useState<string | null>(null)
  const [passwordError, setPasswordError] = useState('')

  // Git panel
  const [gitBranch, setGitBranch] = useState('')
  const [gitStatus, setGitStatus] = useState('')
  const [commitMsg, setCommitMsg] = useState('')
  const [gitWorking, setGitWorking] = useState(false)
  const [gitOutput, setGitOutput] = useState('')

  // Log scroll
  const logRef = useRef<HTMLDivElement | null>(null)

  // WebSocket for live events
  const wsRef = useRef<WebSocket | null>(null)

  // -------------------------------------------------------------------------
  // Bootstrap
  // -------------------------------------------------------------------------

  useEffect(() => {
    apiGet<{ projects: ProjectInfo[] }>('/api/dev/projects')
      .then(d => setProjects(d.projects ?? []))
      .catch(() => {})
    loadTasks()
    connectWs()
    return () => wsRef.current?.close()
  }, [])

  useEffect(() => { loadTasks() }, [activeProject])
  useEffect(() => { loadFileTree() }, [activeProject])
  useEffect(() => { loadGitStatus() }, [activeProject])

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [activeTask?.events?.length])

  // -------------------------------------------------------------------------
  // API calls
  // -------------------------------------------------------------------------

  async function loadTasks() {
    try {
      const d = await apiGet<{ tasks: DevTask[] }>(`/api/dev/tasks?project=${activeProject}`)
      setTasks(d.tasks ?? [])
      if (!activeTask && d.tasks?.length) setActiveTask(d.tasks[0])
    } catch {}
  }

  async function loadFileTree() {
    try {
      const d = await apiGet<{ tree: FileNode[] }>(`/api/dev/files?project=${activeProject}`)
      setFileTree(d.tree ?? [])
    } catch {}
  }

  async function openFile(rel: string, password?: string) {
    try {
      let url = `/api/dev/file?project=${activeProject}&path=${encodeURIComponent(rel)}`
      if (password) url += `&password=${encodeURIComponent(password)}`
      const d = await apiGet<{ contents?: string; rel_path?: string; error?: string }>(url)
      if (d.error === 'password_required') {
        setPendingFile(rel)
        setPasswordInput('')
        setPasswordError('')
        setPasswordPrompt(true)
        return
      }
      if (d.contents !== undefined) setOpenedFile({ rel, contents: d.contents })
    } catch {}
  }

  async function submitPassword() {
    if (!pendingFile) return
    let url = `/api/dev/file?project=${activeProject}&path=${encodeURIComponent(pendingFile)}&password=${encodeURIComponent(passwordInput)}`
    try {
      const d = await apiGet<{ contents?: string; error?: string }>(url)
      if (d.error === 'password_required') {
        setPasswordError('Incorrect password')
        return
      }
      if (d.contents !== undefined) {
        setOpenedFile({ rel: pendingFile, contents: d.contents })
        setPasswordPrompt(false)
        setPasswordInput('')
        setPendingFile(null)
        setPasswordError('')
      }
    } catch { setPasswordError('Request failed') }
  }

  async function loadGitStatus() {
    try {
      const d = await apiGet<{ branch?: string; status?: string; error?: string }>(
        `/api/dev/git/status?project=${activeProject}`
      )
      if (!d.error) {
        setGitBranch(d.branch ?? '')
        setGitStatus(d.status ?? '')
      }
    } catch {}
  }

  async function gitCommitPush() {
    if (!commitMsg.trim()) return
    setGitWorking(true)
    setGitOutput('')
    try {
      const d = await apiPost<{ ok?: boolean; output?: string; error?: string }>(
        '/api/dev/git/commit-push',
        { project: activeProject, message: commitMsg.trim(), push: true }
      )
      setGitOutput(d.error ? `ERROR: ${d.error}` : (d.output ?? 'Done'))
      if (!d.error) { setCommitMsg(''); await loadGitStatus() }
    } catch { setGitOutput('Request failed') }
    finally { setGitWorking(false) }
  }

  async function gitPull() {
    setGitWorking(true)
    setGitOutput('')
    try {
      const d = await apiPost<{ ok?: boolean; output?: string; error?: string }>(
        '/api/dev/git/pull',
        { project: activeProject }
      )
      setGitOutput(d.error ? `ERROR: ${d.error}` : (d.output ?? 'Already up to date'))
      if (!d.error) { await loadGitStatus(); await loadFileTree() }
    } catch { setGitOutput('Request failed') }
    finally { setGitWorking(false) }
  }

  async function createTask() {
    if (!goal.trim()) return
    setCreating(true)
    try {
      const files = contextFiles.split(',').map(f => f.trim()).filter(Boolean)
      await apiPost('/api/dev/tasks', { goal: goal.trim(), project: activeProject, context_files: files })
      setGoal('')
      setContextFiles('')
      await loadTasks()
    } catch {
    } finally {
      setCreating(false)
    }
  }

  const applyPatch = useCallback(async (patch: FilePatch) => {
    if (!activeTask) return
    try {
      await apiPost('/api/dev/apply', {
        project: activeProject,
        path: patch.path,
        proposed: patch.proposed,
        task_id: activeTask.id,
      })
      // Refresh task to reflect accepted status
      const d = await apiGet<DevTask>(`/api/dev/tasks/${activeTask.id}`)
      setActiveTask(d)
      setReviewingPatch(null)
    } catch {}
  }, [activeTask, activeProject])

  const rejectPatch = useCallback((patch: FilePatch) => {
    // Mark locally without server call — rejection is ephemeral
    setActiveTask(prev => {
      if (!prev) return prev
      return {
        ...prev,
        patches: prev.patches.map(p => p.path === patch.path ? { ...p, status: 'rejected' } : p),
      }
    })
    setReviewingPatch(null)
  }, [])

  // -------------------------------------------------------------------------
  // WebSocket
  // -------------------------------------------------------------------------

  function connectWs() {
    const pw = encodeURIComponent(getDevPw())
    const url = `${wsBase()}/ws/dev?password=${pw}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onmessage = (e) => {
      try {
        const evt: DevEvent = JSON.parse(e.data)
        if (evt.kind === 'ping') return

        // Update or add the task this event belongs to
        const tid = evt.task_id
        if (!tid) return

        setTasks(prev => {
          const idx = prev.findIndex(t => t.id === tid)
          if (idx === -1) {
            // New task appeared — trigger a full refresh
            loadTasks()
            return prev
          }
          const updated = { ...prev[idx] }
          updated.events = [...(updated.events ?? []), evt]
          if (evt.kind === 'status') updated.status = evt.message.split(' ')[0] as DevTask['status']
          if (evt.kind === 'patch_ready' && evt.data) {
            updated.patches = [...(updated.patches ?? []), evt.data]
          }
          const next = [...prev]
          next[idx] = updated
          return next
        })

        // Mirror into activeTask if it matches
        setActiveTask(prev => {
          if (!prev || prev.id !== tid) return prev
          const updated = { ...prev }
          updated.events = [...(updated.events ?? []), evt]
          if (evt.kind === 'status') updated.status = evt.message.split(' ')[0] as DevTask['status']
          if (evt.kind === 'patch_ready' && evt.data) {
            updated.patches = [...(updated.patches ?? []), evt.data]
          }
          return updated
        })
      } catch {}
    }

    ws.onclose = () => {
      // Reconnect after 3s if closed unexpectedly
      setTimeout(() => connectWs(), 3000)
    }
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  const patchesPending = activeTask?.patches?.filter(p => p.status === 'pending') ?? []

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col"
      style={{ background: '#070d1a', fontFamily: 'Roboto Mono, monospace' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#1e2d4a] px-4 py-2 shrink-0">
        <div className="flex items-center gap-3">
          <FileCode className="h-4 w-4 text-cyan-400" />
          <span className="text-[13px] font-semibold tracking-widest uppercase text-cyan-400">
            Mithrandir Dev
          </span>
          <span className="text-[10px] text-slate-500">AI-driven code orchestration</span>
        </div>
        <div className="flex items-center gap-2">
          {/* Project tabs */}
          {projects.map(p => (
            <button
              key={p.name}
              onClick={() => setActiveProject(p.name)}
              className={`px-2 py-1 rounded text-[10.5px] uppercase tracking-wider font-semibold transition-colors ${
                activeProject === p.name
                  ? 'bg-cyan-900/40 text-cyan-300 border border-cyan-700'
                  : p.exists
                  ? 'text-slate-400 hover:text-slate-200 border border-transparent'
                  : 'text-slate-600 cursor-not-allowed border border-transparent'
              }`}
              disabled={!p.exists && p.name !== activeProject}
              title={p.exists ? p.name : `${p.name} — not on disk yet`}
            >
              {p.name}
            </button>
          ))}
          <button
            onClick={lockPanel}
            className="ml-3 p-1 rounded text-slate-400 hover:text-slate-200"
            title="Lock dev panel"
          >
            <Lock className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-slate-200"
            title="Close (stay unlocked this session)"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Body: 3-column layout */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* LEFT: File tree + Git panel */}
        <div className="w-52 shrink-0 border-r border-[#1e2d4a] flex flex-col overflow-hidden">
          <div className="px-3 py-2 text-[10px] uppercase tracking-widest text-slate-500 border-b border-[#1e2d4a] flex items-center justify-between">
            <span className="flex items-center gap-1">
              <GitBranch className="h-3 w-3" />
              {activeProject}
              {gitBranch && <span className="text-cyan-700 normal-case">:{gitBranch}</span>}
            </span>
            <button onClick={loadFileTree} className="text-slate-600 hover:text-slate-400" title="Refresh">
              <RefreshCw className="h-2.5 w-2.5" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto py-1 px-1">
            {fileTree.length > 0 ? (
              <FileTree
                nodes={fileTree}
                onSelect={(name) => openFile(name)}
              />
            ) : (
              <div className="text-[10px] text-slate-600 px-3 pt-2">
                {projects.find(p => p.name === activeProject)?.exists
                  ? 'Loading...'
                  : 'Project not on disk'}
              </div>
            )}
          </div>

          {/* Git panel */}
          <div className="border-t border-[#1e2d4a] p-2 shrink-0">
            <div className="text-[9px] uppercase tracking-widest text-slate-500 mb-1.5 flex items-center gap-1">
              <GitCommit className="h-3 w-3" /> Git
              {gitStatus && (
                <span className="ml-auto text-amber-600 font-mono normal-case">{gitStatus.split('\n').length} changed</span>
              )}
            </div>
            {gitStatus && (
              <pre className="text-[8.5px] font-mono text-slate-500 mb-1.5 max-h-16 overflow-auto whitespace-pre-wrap">{gitStatus}</pre>
            )}
            <input
              value={commitMsg}
              onChange={e => setCommitMsg(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && gitCommitPush()}
              placeholder="Commit message…"
              className="w-full bg-[#0f1729] border border-[#1e2d4a] rounded px-2 py-1 text-[10px] text-slate-300 placeholder-slate-600 focus:outline-none focus:border-cyan-800 mb-1"
            />
            <div className="flex gap-1">
              <button
                onClick={gitCommitPush}
                disabled={!commitMsg.trim() || gitWorking}
                className="flex-1 px-1.5 py-1 rounded bg-cyan-900/40 text-cyan-300 text-[9px] font-semibold hover:bg-cyan-900/60 disabled:opacity-40 border border-cyan-800 flex items-center justify-center gap-1"
              >
                <GitCommit className="h-2.5 w-2.5" />
                {gitWorking ? '…' : 'Commit+Push'}
              </button>
              <button
                onClick={gitPull}
                disabled={gitWorking}
                className="px-1.5 py-1 rounded bg-slate-800 text-slate-300 text-[9px] font-semibold hover:bg-slate-700 disabled:opacity-40 border border-slate-600 flex items-center gap-1"
              >
                <GitPullRequest className="h-2.5 w-2.5" /> Pull
              </button>
            </div>
            {gitOutput && (
              <pre className="mt-1.5 text-[8.5px] font-mono max-h-14 overflow-auto whitespace-pre-wrap text-slate-400 border border-[#1e2d4a] rounded p-1">{gitOutput}</pre>
            )}
          </div>
        </div>

        {/* CENTER: Task queue + event log + diff view */}
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">

          {/* Task list bar */}
          <div className="flex items-center gap-2 px-3 py-2 border-b border-[#1e2d4a] overflow-x-auto shrink-0">
            {tasks.length === 0 && (
              <span className="text-[10px] text-slate-600">No tasks yet — create one below</span>
            )}
            {tasks.map(t => (
              <button
                key={t.id}
                onClick={() => setActiveTask(t)}
                className={`shrink-0 flex items-center gap-1.5 px-2 py-1 rounded border text-[10.5px] transition-colors ${
                  activeTask?.id === t.id
                    ? 'border-cyan-700 bg-cyan-900/30 text-cyan-300'
                    : 'border-[#1e2d4a] text-slate-400 hover:text-slate-200'
                }`}
              >
                <span className={STATUS_COLORS[t.status]}>{STATUS_ICONS[t.status]}</span>
                <span className="max-w-[160px] truncate">{t.goal}</span>
              </button>
            ))}
          </div>

          {/* Active task detail */}
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            {activeTask ? (
              <>
                {/* Task header */}
                <div className="px-4 py-2 border-b border-[#1e2d4a] shrink-0 flex items-center justify-between">
                  <div>
                    <span className={`text-[11px] font-semibold ${STATUS_COLORS[activeTask.status]}`}>
                      {STATUS_ICONS[activeTask.status]}{' '}
                      {activeTask.status.toUpperCase()}
                    </span>
                    <span className="ml-3 text-[11px] text-slate-300">{activeTask.goal}</span>
                  </div>
                  <span className="text-[10px] text-slate-600">
                    #{activeTask.id} · {ts(activeTask.created_at)}
                  </span>
                </div>

                {/* Patches to review */}
                {patchesPending.length > 0 && (
                  <div className="px-4 py-2 border-b border-[#1e2d4a] shrink-0 flex items-center gap-2">
                    <span className="text-[10.5px] text-cyan-400 font-semibold">
                      {patchesPending.length} patch(es) ready for review:
                    </span>
                    {patchesPending.map(p => (
                      <button
                        key={p.path}
                        onClick={() => setReviewingPatch(p)}
                        className="text-[10px] px-2 py-0.5 rounded border border-cyan-700 text-cyan-300 hover:bg-cyan-900/30"
                      >
                        {p.path.split('/').pop()}
                      </button>
                    ))}
                  </div>
                )}

                {/* Event log or diff viewer */}
                {reviewingPatch ? (
                  <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                    <div className="px-4 py-2 border-b border-[#1e2d4a] shrink-0 flex items-center justify-between">
                      <span className="text-[11px] text-slate-300 font-mono">{reviewingPatch.path}</span>
                      <div className="flex gap-2">
                        <button
                          onClick={() => applyPatch(reviewingPatch)}
                          className="px-3 py-1 rounded bg-green-800 text-green-200 text-[10.5px] font-semibold hover:bg-green-700"
                        >
                          Apply
                        </button>
                        <button
                          onClick={() => rejectPatch(reviewingPatch)}
                          className="px-3 py-1 rounded bg-red-900 text-red-300 text-[10.5px] font-semibold hover:bg-red-800"
                        >
                          Reject
                        </button>
                        <button
                          onClick={() => setReviewingPatch(null)}
                          className="px-2 py-1 rounded border border-slate-600 text-slate-400 text-[10.5px] hover:text-slate-200"
                        >
                          Back
                        </button>
                      </div>
                    </div>
                    <div className="flex-1 overflow-auto p-3">
                      <DiffViewer original={reviewingPatch.original} proposed={reviewingPatch.proposed} />
                    </div>
                  </div>
                ) : (
                  <div ref={logRef} className="flex-1 overflow-y-auto p-3 space-y-1">
                    {activeTask.events.length === 0 && (
                      <div className="text-[10px] text-slate-600">Waiting for events...</div>
                    )}
                    {activeTask.events.map((ev, i) => (
                      <div key={i} className="flex gap-2 text-[10.5px] font-mono">
                        <span className="text-slate-600 shrink-0">{ts(ev.ts)}</span>
                        <span
                          className={
                            ev.kind === 'error' ? 'text-red-400' :
                            ev.kind === 'status' ? 'text-cyan-400 font-semibold' :
                            ev.kind === 'patch_ready' ? 'text-green-400' :
                            ev.kind === 'narration' ? 'text-slate-200 whitespace-pre-wrap' :
                            'text-slate-400'
                          }
                        >
                          {ev.kind === 'patch_ready' ? `[PATCH] ${ev.message}` : ev.message}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center text-[11px] text-slate-600">
                Select a task or create one below
              </div>
            )}
          </div>

          {/* Task creation form */}
          <div className="border-t border-[#1e2d4a] p-3 shrink-0">
            <div className="flex gap-2 mb-1.5">
              <input
                value={goal}
                onChange={e => setGoal(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && createTask()}
                placeholder={`Describe what to build in ${activeProject}…`}
                className="flex-1 bg-[#0f1729] border border-[#1e2d4a] rounded px-3 py-1.5 text-[11px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-700"
              />
              <button
                onClick={createTask}
                disabled={creating || !goal.trim()}
                className="px-3 py-1.5 rounded bg-cyan-800 text-cyan-200 text-[10.5px] font-semibold hover:bg-cyan-700 disabled:opacity-40 flex items-center gap-1.5"
              >
                <Send className="h-3 w-3" />
                {creating ? 'Creating…' : 'Run'}
              </button>
            </div>
            <input
              value={contextFiles}
              onChange={e => setContextFiles(e.target.value)}
              placeholder="Context files (comma-separated relative paths, optional)"
              className="w-full bg-[#0f1729] border border-[#1e2d4a] rounded px-3 py-1 text-[10.5px] text-slate-400 placeholder-slate-600 focus:outline-none focus:border-cyan-800"
            />
          </div>
        </div>

        {/* RIGHT: File viewer (top) + Chat (bottom) — equal width to center */}
        <div className="flex-1 border-l border-[#1e2d4a] flex flex-col overflow-hidden min-w-0">
          {/* File viewer — top half */}
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            <div className="px-3 py-2 text-[10px] uppercase tracking-widest text-slate-500 border-b border-[#1e2d4a] flex items-center gap-2">
              <FileCode className="h-3 w-3" />
              <span className="truncate normal-case font-mono text-slate-400">
                {openedFile ? openedFile.rel : 'File viewer'}
              </span>
            </div>
            <div className="flex-1 overflow-auto" style={{ background: '#0a0f1f' }}>
              {openedFile ? (
                <Highlight
                  theme={themes.vsDark}
                  code={openedFile.contents}
                  language={langFor(openedFile.rel)}
                >
                  {({ className, style, tokens, getLineProps, getTokenProps }) => (
                    <pre
                      className={className}
                      style={{ ...style, background: 'transparent', margin: 0, padding: '8px 10px', fontSize: '10.5px', lineHeight: 1.5 }}
                    >
                      {tokens.map((line, i) => (
                        <div key={i} {...getLineProps({ line })} style={{ display: 'flex' }}>
                          <span style={{ color: '#3b4a6b', userSelect: 'none', width: '2.5em', textAlign: 'right', paddingRight: '0.8em', flexShrink: 0 }}>
                            {i + 1}
                          </span>
                          <span style={{ flex: 1, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                            {line.map((token, key) => (
                              <span key={key} {...getTokenProps({ token })} />
                            ))}
                          </span>
                        </div>
                      ))}
                    </pre>
                  )}
                </Highlight>
              ) : (
                <div className="text-[10px] text-slate-600 pt-2 px-3">
                  Click a file in the tree to view it here — with syntax highlighting.
                </div>
              )}
            </div>
          </div>

          {/* Chat — bottom half (Mithrandir agent + voice) */}
          <div className="h-[42%] border-t border-[#1e2d4a] flex flex-col overflow-hidden">
            <div className="px-3 py-2 text-[10px] uppercase tracking-widest text-slate-500 border-b border-[#1e2d4a] flex items-center gap-2">
              <MessageSquare className="h-3 w-3" />
              Mithrandir — ask about code, memory, or delegate work
              <span className="ml-auto text-[9px] text-slate-600 normal-case">
                tip: "read orator/server/main.py" → uses dev_read_file tool
              </span>
            </div>
            <div className="flex-1 overflow-hidden">
              <ChatPanel />
            </div>
          </div>
        </div>
      </div>

      {/* Password modal */}
      {passwordPrompt && (
        <div className="absolute inset-0 z-60 flex items-center justify-center bg-black/70">
          <div className="bg-[#0f1729] border border-cyan-800 rounded-lg p-5 w-72 shadow-2xl">
            <div className="flex items-center gap-2 mb-3">
              <Lock className="h-4 w-4 text-amber-400" />
              <span className="text-[12px] font-semibold text-slate-200">Protected file</span>
            </div>
            <p className="text-[10.5px] text-slate-400 mb-3 font-mono">{pendingFile}</p>
            <input
              type="password"
              autoFocus
              value={passwordInput}
              onChange={e => setPasswordInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && submitPassword()}
              placeholder="Dev password…"
              className="w-full bg-[#070d1a] border border-[#1e2d4a] rounded px-3 py-1.5 text-[11px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-700 mb-1"
            />
            {passwordError && (
              <p className="text-[10px] text-red-400 mb-1">{passwordError}</p>
            )}
            <div className="flex gap-2 mt-2">
              <button
                onClick={submitPassword}
                className="flex-1 px-3 py-1.5 rounded bg-cyan-800 text-cyan-200 text-[10.5px] font-semibold hover:bg-cyan-700"
              >
                Unlock
              </button>
              <button
                onClick={() => { setPasswordPrompt(false); setPasswordInput(''); setPendingFile(null); setPasswordError('') }}
                className="px-3 py-1.5 rounded border border-slate-600 text-slate-400 text-[10.5px] hover:text-slate-200"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
