/**
 * ChatPanel.tsx — unified chat + voice terminal
 *
 * Text input and voice input share the same message thread.
 * Voice flow: mic → VAD → /ws/voice → Whisper → agent → edge-tts → MP3 playback
 * Text flow:  input → /ws/chat → agent → streaming tokens
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { useStore } from '../store'
import { createChatSocket, API_BASE, wsBase } from '../api'

// ── Chat WebSocket (module-level singleton) ───────────────────────────────

let chatSocket: WebSocket | null = null
let pendingBotId: string | null = null
let tokenBuffer = ''
let rafPending  = false
let _onChatTtsError: ((msg: string) => void) | null = null
let _reconnectAttempts = 0
let _reconnectTimer: ReturnType<typeof setTimeout> | null = null

function flushTokenBuffer() {
  rafPending = false
  if (!tokenBuffer || !pendingBotId) { tokenBuffer = ''; return }
  const buf = tokenBuffer; tokenBuffer = ''
  const id  = pendingBotId
  useStore.setState((s) => ({
    messages: s.messages.map((m) =>
      m.id === id ? { ...m, content: (m.content || '') + buf } : m
    ),
  }))
}

function connectChatSocket(onTtsError?: (msg: string) => void) {
  if (onTtsError) _onChatTtsError = onTtsError
  if (chatSocket && chatSocket.readyState <= WebSocket.OPEN) return
  const { setBusy, appendStep } = useStore.getState()
  chatSocket = createChatSocket(
    (step)     => { if (pendingBotId) appendStep(pendingBotId, step) },
    (tok)      => { tokenBuffer += tok; if (!rafPending) { rafPending = true; requestAnimationFrame(flushTokenBuffer) } },
    (response) => {
      if (pendingBotId) useStore.setState((s) => ({
        messages: s.messages.map((m) => m.id === pendingBotId ? { ...m, content: response } : m),
      }))
    },
    ()         => { flushTokenBuffer(); setBusy(false); pendingBotId = null; _reconnectAttempts = 0 },
    (err)      => {
      flushTokenBuffer()
      if (pendingBotId) useStore.setState((s) => ({
        messages: s.messages.map((m) => m.id === pendingBotId ? { ...m, content: `ERROR: ${err}` } : m),
      }))
      setBusy(false); pendingBotId = null
    },
    (b64, fmt) => { enqueueAudio(b64, fmt) },
    (msg)      => { if (_onChatTtsError) _onChatTtsError(msg) },
  )
  // Auto-reconnect on unexpected server drop. wasClean=false means the server
  // closed without a normal WebSocket close handshake (crash / network drop).
  // Intentional closes (Escape reset) set chatSocket=null before reconnecting,
  // which guards against infinite loops here.
  chatSocket.addEventListener('close', (ev: CloseEvent) => {
    if (!ev.wasClean) {
      const delay = Math.min(1000 * Math.pow(2, _reconnectAttempts), 30_000)
      _reconnectAttempts++
      console.log(`[enkidu-ws] chat socket dropped — reconnecting in ${delay}ms (attempt ${_reconnectAttempts})`)
      _reconnectTimer = setTimeout(() => connectChatSocket(), delay)
    } else {
      _reconnectAttempts = 0
    }
  })
}

// ── VAD constants ─────────────────────────────────────────────────────────

const SPEECH_THRESHOLD    = 0.012
const SILENCE_THRESHOLD   = 0.008
const SILENCE_DURATION_MS = 900
const MIN_SPEECH_MS       = 400
const VAD_POLL_MS         = 80

// ── Audio helpers ─────────────────────────────────────────────────────────

interface AudioDevice { deviceId: string; label: string }

async function listMicDevices(): Promise<AudioDevice[]> {
  try {
    await navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => s.getTracks().forEach((t) => t.stop()))
    const devices = await navigator.mediaDevices.enumerateDevices()
    return devices.filter((d) => d.kind === 'audioinput')
      .map((d) => ({ deviceId: d.deviceId, label: d.label || `Mic ${d.deviceId.slice(0, 6)}` }))
  } catch { return [] }
}

interface CaptureHandle {
  audioCtx: AudioContext
  stream:   MediaStream
  chunks:   Float32Array[]
  analyser: AnalyserNode
  stop:     () => void
}

async function startCapture(deviceId?: string): Promise<CaptureHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { deviceId: deviceId ? { exact: deviceId } : undefined, channelCount: 1,
             echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  })
  const audioCtx  = new AudioContext()
  const source    = audioCtx.createMediaStreamSource(stream)
  const processor = audioCtx.createScriptProcessor(4096, 1, 1)
  const analyser  = audioCtx.createAnalyser()
  const silencer  = audioCtx.createGain()
  analyser.fftSize = 1024; silencer.gain.value = 0  // 1024 gives smoother oscilloscope waveform
  const chunks: Float32Array[] = []
  processor.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
  // Connect analyser INTO the silent output path so Chrome doesn't optimize
  // it out as a leaf node — without this, getFloatTimeDomainData returns zeros.
  source.connect(analyser); analyser.connect(silencer)
  source.connect(processor); processor.connect(silencer)
  silencer.connect(audioCtx.destination)
  await audioCtx.resume()
  const stop = () => { processor.disconnect(); silencer.disconnect(); source.disconnect(); stream.getTracks().forEach((t) => t.stop()); audioCtx.close() }
  return { audioCtx, stream, chunks, analyser, stop }
}

function getRms(analyser: AnalyserNode): number {
  const buf = new Float32Array(analyser.fftSize)
  analyser.getFloatTimeDomainData(buf)
  let sum = 0; for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
  return Math.sqrt(sum / buf.length)
}

function chunksToBase64(chunks: Float32Array[]): { data: string; samples: number } {
  const total = chunks.reduce((n, c) => n + c.length, 0)
  const combined = new Float32Array(total)
  let offset = 0; for (const c of chunks) { combined.set(c, offset); offset += c.length }
  const bytes = new Uint8Array(combined.buffer)
  let binary = ''; const STEP = 8192
  for (let i = 0; i < bytes.length; i += STEP) binary += String.fromCharCode(...bytes.subarray(i, i + STEP))
  return { data: btoa(binary), samples: total }
}

// Persistent AudioContext for TTS playback — survives across messages.
// Resumed on first user interaction (mic click), stays running so playback
// isn't blocked by the browser's autoplay policy even seconds later.
let _playCtx: AudioContext | null = null

function getPlayCtx(): AudioContext {
  if (!_playCtx || _playCtx.state === 'closed') _playCtx = new AudioContext()
  return _playCtx
}

function resumePlayCtx() {
  const ctx = getPlayCtx()
  if (ctx.state === 'suspended') ctx.resume()
}

async function playAudio(b64: string, _fmt: string = 'wav'): Promise<void> {
  const ctx = getPlayCtx()
  console.log(`[enkidu-audio] playAudio: ctx.state=${ctx.state}, bytes=${Math.round(b64.length * 0.75)}`)
  if (ctx.state === 'suspended') {
    console.log('[enkidu-audio] resuming suspended AudioContext…')
    await ctx.resume()
    console.log(`[enkidu-audio] AudioContext state after resume: ${ctx.state}`)
  }
  return new Promise((resolve) => {
    try {
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)).buffer
      ctx.decodeAudioData(bytes, (buf) => {
        console.log(`[enkidu-audio] decodeAudioData OK: ${buf.duration.toFixed(2)}s @ ${buf.sampleRate}Hz`)
        try {
          const src = ctx.createBufferSource()
          src.buffer = buf
          src.connect(ctx.destination)
          src.onended = () => { console.log('[enkidu-audio] playback ended'); resolve() }
          src.start(0)
          console.log('[enkidu-audio] src.start(0) called — audio should be playing')
        } catch (e) {
          console.error('[enkidu-audio] src.start error:', e)
          resolve()
        }
      }, (e) => {
        console.warn('[enkidu-audio] decodeAudioData failed, trying <audio> fallback:', e)
        const blob  = new Blob([Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))], { type: 'audio/wav' })
        const url   = URL.createObjectURL(blob)
        const audio = new Audio(url)
        audio.onended = () => { URL.revokeObjectURL(url); resolve() }
        audio.onerror = (err) => { console.error('[enkidu-audio] <audio> element error:', err); URL.revokeObjectURL(url); resolve() }
        audio.play()
          .then(() => console.log('[enkidu-audio] <audio>.play() started'))
          .catch((err) => { console.error('[enkidu-audio] <audio>.play() rejected (autoplay?):', err); resolve() })
      })
    } catch (e) {
      console.error('[enkidu-audio] playAudio outer error:', e)
      resolve()
    }
  })
}

// ── Audio queue — sequential chunk playback ───────────────────────────────
// Sentences arrive as tts_chunk messages with seq numbers. We queue them and
// play in order so sentence 1 starts while the server is synthesizing sentence 2.

interface AudioItem { b64: string; fmt: string }

const _audioQueue: AudioItem[] = []
let   _audioPlaying = false

async function _drainAudioQueue(): Promise<void> {
  if (_audioPlaying) return
  _audioPlaying = true
  while (_audioQueue.length > 0) {
    const item = _audioQueue.shift()!
    await playAudio(item.b64, item.fmt)
  }
  _audioPlaying = false
}

/** Push a chunk to the playback queue and start draining if idle. */
function enqueueAudio(b64: string, fmt: string): void {
  console.log(`[enkidu-audio] enqueueAudio: queueLen=${_audioQueue.length}, playing=${_audioPlaying}, bytes≈${Math.round(b64.length * 0.75)}`)
  _audioQueue.push({ b64, fmt })
  _drainAudioQueue()   // fire-and-forget — guards itself with _audioPlaying flag
}

/** Stop any in-flight audio and clear the queue (e.g., when user starts speaking). */
function clearAudioQueue(): void {
  _audioQueue.length = 0
}

// ── Waveform ─────────────────────────────────────────────────────────────

type WaveformMode = 'idle' | 'recording' | 'thinking' | 'speaking'

function Waveform({ analyser, mode }: { analyser: AnalyserNode | null; mode: WaveformMode }) {
  const canvasRef  = useRef<HTMLCanvasElement>(null)
  const rafRef     = useRef<number>(0)
  const phaseRef   = useRef<number>(0)  // idle breathing phase

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!

    const resize = () => {
      const w = canvas.offsetWidth  || 400
      const h = canvas.offsetHeight || 64
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width  = w
        canvas.height = h
      }
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)

    const draw = () => {
      rafRef.current = requestAnimationFrame(draw)
      const W = canvas.width, H = canvas.height
      ctx.clearRect(0, 0, W, H)

      if (mode === 'recording' && analyser) {
        // ── Oscilloscope waveform (time-domain, always visible) ───────────
        // getFloatTimeDomainData gives [-1..1] directly from the mic.
        // Amplify so even quiet mics look dramatic.
        const time = new Float32Array(analyser.fftSize)
        analyser.getFloatTimeDomainData(time)

        // Compute peak amplitude this frame for auto-gain display
        let peak = 0
        for (let i = 0; i < time.length; i++) if (Math.abs(time[i]) > peak) peak = Math.abs(time[i])
        // Amplify: boost quiet signal so it fills ~60% of canvas height,
        // cap at 1 so loud signals don't clip the canvas.
        const amp = peak > 0.001 ? Math.min(1, 0.6 / peak) : 40

        // Glow under-fill
        const fill = ctx.createLinearGradient(0, 0, 0, H)
        fill.addColorStop(0, '#ff1a4000')
        fill.addColorStop(0.5, '#ff1a4022')
        fill.addColorStop(1, '#ff1a4000')
        ctx.fillStyle = fill
        ctx.beginPath()
        ctx.moveTo(0, H / 2)
        for (let i = 0; i < time.length; i++) {
          const x = (i / (time.length - 1)) * W
          const y = H / 2 - time[i] * amp * H * 0.5
          ctx.lineTo(x, Math.max(0, Math.min(H, y)))
        }
        ctx.lineTo(W, H / 2)
        ctx.closePath()
        ctx.fill()

        // Main waveform line
        ctx.strokeStyle = '#ff1a40dd'
        ctx.lineWidth = 1.5
        ctx.shadowColor = '#ff1a40'
        ctx.shadowBlur = 6
        ctx.beginPath()
        for (let i = 0; i < time.length; i++) {
          const x = (i / (time.length - 1)) * W
          const y = H / 2 - time[i] * amp * H * 0.5
          i === 0 ? ctx.moveTo(x, Math.max(0, Math.min(H, y))) : ctx.lineTo(x, Math.max(0, Math.min(H, y)))
        }
        ctx.stroke()
        ctx.shadowBlur = 0

      } else if (mode === 'thinking') {
        // ── Scanning line ─────────────────────────────────────────────────
        phaseRef.current += 0.04
        const x = ((Math.sin(phaseRef.current) * 0.5 + 0.5)) * W
        const grad = ctx.createLinearGradient(0, 0, W, 0)
        grad.addColorStop(0, '#ff8c0000')
        grad.addColorStop(Math.max(0, x / W - 0.1), '#ff8c0000')
        grad.addColorStop(x / W, '#ffaa44ff')
        grad.addColorStop(Math.min(1, x / W + 0.1), '#ff8c0000')
        grad.addColorStop(1, '#ff8c0000')
        ctx.strokeStyle = grad
        ctx.lineWidth = 1.5
        ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke()
        // Glowing dot at scan position
        const glow = ctx.createRadialGradient(x, H / 2, 0, x, H / 2, 12)
        glow.addColorStop(0, '#ffaa44cc')
        glow.addColorStop(1, '#ffaa4400')
        ctx.fillStyle = glow
        ctx.beginPath(); ctx.arc(x, H / 2, 12, 0, Math.PI * 2); ctx.fill()

      } else if (mode === 'speaking') {
        // ── Animated sine wave ────────────────────────────────────────────
        phaseRef.current += 0.08
        ctx.strokeStyle = '#39d35388'
        ctx.lineWidth = 1.5
        ctx.beginPath()
        for (let x = 0; x < W; x++) {
          const y = H / 2 + Math.sin((x / W) * Math.PI * 6 + phaseRef.current) * (H * 0.3)
          x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
        }
        ctx.stroke()
        // Second layer, offset
        ctx.strokeStyle = '#39d35344'
        ctx.beginPath()
        for (let x = 0; x < W; x++) {
          const y = H / 2 + Math.sin((x / W) * Math.PI * 4 + phaseRef.current * 0.7) * (H * 0.18)
          x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
        }
        ctx.stroke()

      } else {
        // ── Idle: slow breathing flat line ────────────────────────────────
        phaseRef.current += 0.015
        const alpha = 0.12 + Math.abs(Math.sin(phaseRef.current)) * 0.18
        ctx.strokeStyle = `rgba(255, 26, 64, ${alpha})`
        ctx.lineWidth = 1
        ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke()
      }
    }
    draw()
    return () => { cancelAnimationFrame(rafRef.current); ro.disconnect() }
  }, [analyser, mode])

  return (
    <canvas
      ref={canvasRef}
      style={{ width: '100%', height: 64, display: 'block' }}
    />
  )
}

// ── Component ─────────────────────────────────────────────────────────────

type VoiceState = 'idle' | 'recording' | 'thinking' | 'speaking'

export default function ChatPanel() {
  const messages             = useStore((s) => s.messages)
  const busy                 = useStore((s) => s.busy)
  const addMessage           = useStore((s) => s.addMessage)
  const setBusy              = useStore((s) => s.setBusy)
  const clearMessages        = useStore((s) => s.clearMessages)
  const activeConversationId = useStore((s) => s.activeConversationId)
  const pendingChatInput     = useStore((s) => s.pendingChatInput)
  const setPendingChatInput  = useStore((s) => s.setPendingChatInput)

  const [input,        setInput]        = useState('')
  const [voiceState,   setVoiceState]   = useState<VoiceState>('idle')
  const [vadEnabled,   setVadEnabled]   = useState(true)
  const [loopEnabled,  setLoopEnabled]  = useState(false)
  const [ttsStatus,    setTtsStatus]    = useState('')   // 'speaking' | 'tts_error' | ''
  const [micError,     setMicError]     = useState('')
  const [devices,      setDevices]      = useState<AudioDevice[]>([])
  const [selectedDev,  setSelectedDev]  = useState('')
  const [showDevSel,   setShowDevSel]   = useState(false)
  const [voiceProfiles,  setVoiceProfiles]  = useState<string[]>(['default'])
  const [selectedVoice,  setSelectedVoice]  = useState('default')
  const [activeAnalyser, setActiveAnalyser] = useState<AnalyserNode | null>(null)

  const bottomRef       = useRef<HTMLDivElement>(null)
  const voiceWsRef      = useRef<WebSocket | null>(null)
  const captureRef      = useRef<CaptureHandle | null>(null)
  const analyserRef     = useRef<AnalyserNode | null>(null)
  const vadTimerRef     = useRef<ReturnType<typeof setInterval> | null>(null)
  const speechStartRef  = useRef<number | null>(null)
  const silenceStartRef = useRef<number | null>(null)
  const voiceBotIdRef   = useRef<string | null>(null)
  const voiceStateRef   = useRef<VoiceState>('idle')
  const loopRef         = useRef(false)

  useEffect(() => { voiceStateRef.current = voiceState }, [voiceState])
  useEffect(() => { loopRef.current = loopEnabled }, [loopEnabled])

  // ── Pending input from DocsPanel "Ask Enkidu" button ─────────────────
  useEffect(() => {
    if (pendingChatInput) {
      setInput(pendingChatInput)
      setPendingChatInput(null)
    }
  }, [pendingChatInput])

  // ── Chat socket ──────────────────────────────────────────────────────

  useEffect(() => {
    connectChatSocket((msg) => {
      setTtsStatus(`TTS: ${msg}`)
      setTimeout(() => setTtsStatus(''), 4000)
    })
  }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // Emergency reset: Escape key clears busy state and reconnects sockets if
  // the UI ever gets stuck (e.g. after a server hiccup mid-TTS).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'Escape') return
      setBusy(false)
      pendingBotId = null
      voiceBotIdRef.current = null
      setVoiceState('idle')
      setTtsStatus('')
      clearAudioQueue()
      setMicError('')
      // Cancel any pending auto-reconnect before closing so we don't loop.
      if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null }
      _reconnectAttempts = 0
      try { chatSocket?.close() } catch {}
      try { voiceWsRef.current?.close() } catch {}
      chatSocket = null
      voiceWsRef.current = null
      setTimeout(() => {
        connectChatSocket((m) => { setTtsStatus(`TTS: ${m}`); setTimeout(() => setTtsStatus(''), 4000) })
        connectVoiceWs()
      }, 200)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setBusy])

  // ── Mic devices ──────────────────────────────────────────────────────

  useEffect(() => {
    listMicDevices().then((devs) => {
      setDevices(devs)
      const headset = devs.find((d) => /headset|headphone|jabra|bose|sony|logitech|hyper|blue|yeti|rode/i.test(d.label))
      setSelectedDev(headset?.deviceId ?? devs[0]?.deviceId ?? '')
    })
  }, [])

  // ── Voice profiles ────────────────────────────────────────────────────

  useEffect(() => {
    fetch(`${API_BASE}/api/voices`)
      .then((r) => r.json())
      .then((d) => {
        if (d.voices?.length) setVoiceProfiles(d.voices)
        if (d.active) setSelectedVoice(d.active)
      })
      .catch(() => {/* server may not be up yet */})
  }, [])

  const handleVoiceChange = (profile: string) => {
    setSelectedVoice(profile)
    fetch(`${API_BASE}/api/voice`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile }),
    }).catch(() => {/* non-critical */})
  }

  // ── Voice WebSocket ──────────────────────────────────────────────────

  const connectVoiceWs = useCallback(() => {
    if (voiceWsRef.current && voiceWsRef.current.readyState <= WebSocket.OPEN) return
    const ws = new WebSocket(`${wsBase()}/ws/voice`)

    ws.onopen = () => setMicError('')   // clear any stale error from a previous disconnect

    ws.onmessage = async (ev) => {
      const msg = JSON.parse(ev.data)

      if (msg.type === 'transcript') {
        // Add user message from transcript
        const userId = crypto.randomUUID()
        const botId  = crypto.randomUUID()
        voiceBotIdRef.current = botId
        pendingBotId = botId
        addMessage({ id: userId, role: 'user',  content: `🎤 ${msg.text}`, ts: Date.now() })
        addMessage({ id: botId,  role: 'bot',   content: '', ts: Date.now() })
        setBusy(true)
        setVoiceState('thinking')

      } else if (msg.type === 'step') {
        if (voiceBotIdRef.current) useStore.getState().appendStep(voiceBotIdRef.current, msg.content)

      } else if (msg.type === 'token') {
        tokenBuffer += msg.content
        if (!rafPending) { rafPending = true; requestAnimationFrame(flushTokenBuffer) }

      } else if (msg.type === 'response') {
        if (voiceBotIdRef.current) useStore.setState((s) => ({
          messages: s.messages.map((m) => m.id === voiceBotIdRef.current ? { ...m, content: msg.content } : m),
        }))

      } else if (msg.type === 'tts_chunk' || msg.type === 'tts_audio') {
        // First chunk: transition to speaking state
        if (voiceStateRef.current !== 'speaking') {
          setVoiceState('speaking')
          setTtsStatus('speaking')
        }
        enqueueAudio(msg.data, msg.format ?? 'wav')

      } else if (msg.type === 'tts_error') {
        setTtsStatus(`TTS: ${msg.content}`)
        setTimeout(() => setTtsStatus(''), 3000)

      } else if (msg.type === 'done') {
        flushTokenBuffer()
        setBusy(false)
        pendingBotId = null
        voiceBotIdRef.current = null
        // Wait for audio queue to finish before going idle, so loop-mode
        // doesn't start recording while Enkidu is still speaking.
        const waitAndReset = async () => {
          while (_audioPlaying || _audioQueue.length > 0) {
            await new Promise<void>((r) => setTimeout(r, 80))
          }
          setVoiceState('idle')
          setTtsStatus('')
          if (loopRef.current) setTimeout(() => startRecording(), 300)
        }
        waitAndReset()

      } else if (msg.type === 'error') {
        setMicError(msg.content)
        setBusy(false); pendingBotId = null; voiceBotIdRef.current = null
        setVoiceState('idle')
      }
    }
    ws.onclose = () => {
      voiceWsRef.current = null
      // If the socket drops while Enkidu was still responding, force-release
      // the UI so buttons become clickable again. Without this reset the panel
      // would stay locked on busy + speaking forever.
      if (voiceStateRef.current !== 'idle' || pendingBotId) {
        flushTokenBuffer()
        clearAudioQueue()
        setBusy(false)
        pendingBotId = null
        voiceBotIdRef.current = null
        setVoiceState('idle')
        setTtsStatus('')
      }
      // Auto-reconnect after a short delay so the next mic/send works.
      setTimeout(() => { try { connectVoiceWs() } catch {} }, 400)
    }
    ws.onerror = () => {
      setMicError('Voice WS error — is the server running?')
      if (voiceStateRef.current !== 'idle' || pendingBotId) {
        flushTokenBuffer()
        clearAudioQueue()
        setBusy(false)
        pendingBotId = null
        voiceBotIdRef.current = null
        setVoiceState('idle')
        setTtsStatus('')
      }
    }
    voiceWsRef.current = ws
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addMessage, setBusy])

  useEffect(() => {
    connectVoiceWs()
    return () => { voiceWsRef.current?.close(); voiceWsRef.current = null }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── VAD ──────────────────────────────────────────────────────────────

  const stopVad = useCallback(() => {
    if (vadTimerRef.current) { clearInterval(vadTimerRef.current); vadTimerRef.current = null }
    speechStartRef.current = null; silenceStartRef.current = null
  }, [])

  const sendAudio = useCallback((capture: CaptureHandle) => {
    captureRef.current = null; analyserRef.current = null; setActiveAnalyser(null)
    const actualRate = capture.audioCtx.sampleRate
    capture.stop()
    const { data, samples } = chunksToBase64(capture.chunks)
    if (samples < 800) {
      setMicError(`No audio captured (${samples} samples). Check mic.`)
      setVoiceState('idle'); return
    }
    const payload = JSON.stringify({ type: 'audio', data, rate: actualRate, voice_profile: selectedVoice })
    if (voiceWsRef.current?.readyState === WebSocket.OPEN) {
      voiceWsRef.current.send(payload)
    } else {
      // WS is not open — (re)connect and wait for the open event before sending.
      // Using addEventListener('open', ...) avoids the race condition where a fixed
      // setTimeout fires while the socket is still in CONNECTING state.
      connectVoiceWs()
      const ws = voiceWsRef.current
      if (ws) {
        ws.addEventListener('open', () => ws.send(payload), { once: true })
      } else {
        setMicError('Voice connection unavailable — please try again.')
        setVoiceState('idle'); return
      }
    }
    setVoiceState('thinking')
  }, [connectVoiceWs, selectedVoice, setActiveAnalyser])

  const startRecording = useCallback(async () => {
    if (voiceStateRef.current !== 'idle') return
    setMicError(''); setTtsStatus('')
    clearAudioQueue()  // stop any in-progress TTS before recording
    resumePlayCtx()    // warm up AudioContext while we still have the user gesture
    try {
      const capture = await startCapture(selectedDev || undefined)
      captureRef.current = capture; analyserRef.current = capture.analyser
      setActiveAnalyser(capture.analyser)
      setVoiceState('recording')

      if (vadEnabled) {
        speechStartRef.current = null; silenceStartRef.current = null
        vadTimerRef.current = setInterval(() => {
          if (voiceStateRef.current !== 'recording') { stopVad(); return }
          const rms = getRms(capture.analyser)
          const now = Date.now()
          if (rms > SPEECH_THRESHOLD) { if (!speechStartRef.current) speechStartRef.current = now; silenceStartRef.current = null }
          else if (rms < SILENCE_THRESHOLD && speechStartRef.current) {
            if (!silenceStartRef.current) silenceStartRef.current = now
            const silenceDur = now - silenceStartRef.current
            const speechDur  = silenceStartRef.current - speechStartRef.current
            if (silenceDur >= SILENCE_DURATION_MS && speechDur >= MIN_SPEECH_MS) { stopVad(); sendAudio(capture) }
          }
        }, VAD_POLL_MS)
      }
    } catch (e: unknown) {
      setMicError(`Mic error: ${e instanceof Error ? e.message : String(e)}`)
    }
  }, [selectedDev, vadEnabled, stopVad, sendAudio])

  const stopRecording = useCallback(() => {
    stopVad()
    const capture = captureRef.current
    if (!capture) return
    sendAudio(capture)
  }, [stopVad, sendAudio])

  const handleMicClick = useCallback(() => {
    if (voiceState === 'recording') stopRecording()
    else if (voiceState === 'idle' && !busy) startRecording()
  }, [voiceState, busy, startRecording, stopRecording])

  // Space bar PTT
  useEffect(() => {
    const onDown = (e: KeyboardEvent) => { if (e.code === 'Space' && e.target === document.body && voiceState === 'idle' && !busy) { e.preventDefault(); startRecording() } }
    const onUp   = (e: KeyboardEvent) => { if (e.code === 'Space' && voiceState === 'recording') { e.preventDefault(); stopRecording() } }
    window.addEventListener('keydown', onDown); window.addEventListener('keyup', onUp)
    return () => { window.removeEventListener('keydown', onDown); window.removeEventListener('keyup', onUp) }
  }, [voiceState, busy, startRecording, stopRecording])

  // ── Text send ────────────────────────────────────────────────────────

  function send() {
    const text = input.trim()
    if (!text || busy || !chatSocket) return
    resumePlayCtx()
    if (chatSocket.readyState !== WebSocket.OPEN) { connectChatSocket(); return }
    const userId = crypto.randomUUID(); const botId = crypto.randomUUID()
    pendingBotId = botId
    addMessage({ id: userId, role: 'user', content: text, ts: Date.now() })
    addMessage({ id: botId,  role: 'bot',  content: '',   ts: Date.now() })
    setBusy(true); setInput('')
    chatSocket.send(JSON.stringify({ message: text, voice_profile: selectedVoice, ...(activeConversationId ? { conversation_id: activeConversationId } : {}) }))
  }

  // ── Render ───────────────────────────────────────────────────────────

  const isRecording = voiceState === 'recording'
  const isSpeaking  = voiceState === 'speaking'
  const micColor    = isRecording ? 'var(--red)' : isSpeaking ? 'var(--green)' : busy ? 'var(--amber-dim)' : 'var(--amber)'

  return (
    <div className="panel panel-chat" style={{ flex: 1, minHeight: 0 }}>
      <div className="panel-title" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span>
          CHAT TERMINAL
          {activeConversationId && <span style={{ fontSize: 10, color: 'var(--cyan)', marginLeft: 8 }}>· CONTINUATION</span>}
          {isRecording && <span style={{ fontSize: 10, color: 'var(--red)', marginLeft: 8, animation: 'pulse-text 0.8s infinite' }}>· LISTENING</span>}
          {isSpeaking  && <span style={{ fontSize: 10, color: 'var(--green)', marginLeft: 8 }}>· SPEAKING</span>}
          {voiceState === 'thinking' && <span style={{ fontSize: 10, color: 'var(--amber)', marginLeft: 8 }}>· PROCESSING</span>}
        </span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {ttsStatus && (
            <span style={{ fontSize: 10, color: ttsStatus.startsWith('TTS:') ? 'var(--red)' : 'var(--green)', letterSpacing: '0.1em' }}>
              {ttsStatus.startsWith('TTS:') ? ttsStatus : '♪'}
            </span>
          )}
          {messages.length > 0 && (
            <button onClick={() => clearMessages()} style={{ background: 'none', border: '1px solid var(--border)', color: 'var(--white-dim)', fontFamily: 'var(--font-mono)', fontSize: 10, padding: '2px 8px', cursor: 'pointer', letterSpacing: '0.08em' }}>
              NEW
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="dim" style={{ alignSelf: 'center', marginTop: 40, textAlign: 'center', lineHeight: 2 }}>
            <div style={{ fontSize: 32, fontFamily: 'var(--font-display)', color: 'var(--amber)', opacity: 0.3 }}>ENKIDU ONLINE</div>
            <div style={{ fontSize: 11, opacity: 0.4 }}>TYPE OR SPEAK TO BEGIN_</div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            <span className="msg-label">
              {m.role === 'user' ? 'YOU' : 'ENKIDU'} · {new Date(m.ts).toLocaleTimeString('en-US', { hour12: false })}
            </span>
            {m.steps && m.steps.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 4 }}>
                {m.steps.map((s, i) => <span key={i} className="msg-step">⟩ {s}</span>)}
              </div>
            )}
            <div className="msg-bubble">
              {m.content || (m.role === 'bot' && busy && pendingBotId === m.id
                ? <span className="msg-typing">···</span>
                : m.content)}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Waveform — always visible, mode-driven animation */}
      <div style={{ flexShrink: 0, background: '#06070c', borderTop: '1px solid var(--border)' }}>
        <Waveform analyser={activeAnalyser} mode={voiceState} />
      </div>

      {/* Mic error */}
      {micError && (
        <div style={{ flexShrink: 0, padding: '4px 12px', fontSize: 11, color: 'var(--red)', background: 'rgba(255,26,64,0.07)', borderTop: '1px solid var(--red)' }}>
          {micError}
          <button onClick={() => setMicError('')} style={{ marginLeft: 8, background: 'none', border: 'none', color: 'var(--red)', cursor: 'pointer', fontSize: 11 }}>✕</button>
        </div>
      )}

      {/* Input row */}
      <div className="chat-input-row" style={{ gap: 6 }}>
        {/* Mic button */}
        <button
          onClick={handleMicClick}
          disabled={busy && !isRecording}
          title={isRecording ? 'Stop / Space' : 'Speak / Space'}
          style={{
            flexShrink: 0, width: 34, height: 34, borderRadius: '50%',
            background: isRecording ? 'rgba(255,26,64,0.15)' : 'var(--bg-input)',
            border: `1.5px solid ${micColor}`,
            color: micColor, fontSize: 16,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: (busy && !isRecording) ? 'default' : 'pointer',
            boxShadow: isRecording ? '0 0 10px rgba(255,26,64,0.4)' : isSpeaking ? '0 0 8px rgba(57,211,83,0.3)' : 'none',
            transition: 'all 0.15s',
            animation: isRecording ? 'pulse-ring-sm 1.2s ease-out infinite' : 'none',
            padding: 0,
          }}
        >
          {isRecording ? '⏹' : isSpeaking ? '🔊' : '🎤'}
        </button>

        <span className="chat-prefix">&gt;_</span>
        <input
          className="chat-input"
          placeholder={isRecording ? 'listening…' : 'enter query or speak…'}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && send()}
          disabled={busy}
          autoFocus
        />
        <button className="chat-send" onClick={send} disabled={busy || !input.trim()}>
          SEND
        </button>
      </div>

      {/* Voice controls strip */}
      <div style={{
        flexShrink: 0, display: 'flex', alignItems: 'center', gap: 6,
        padding: '4px 10px', borderTop: '1px solid var(--border)',
        background: '#060810',
      }}>
        <VoiceToggle label="VAD"  on={vadEnabled}  onClick={() => setVadEnabled(v => !v)}  title="Auto-stop on silence" />
        <VoiceToggle label="LOOP" on={loopEnabled} onClick={() => setLoopEnabled(v => !v)} title="Auto-listen after response" />

        {/* Voice profile selector */}
        <select
          value={selectedVoice}
          onChange={(e) => handleVoiceChange(e.target.value)}
          disabled={isRecording || busy}
          title="TTS voice profile"
          style={{
            marginLeft: 4, fontSize: 10, padding: '1px 4px',
            background: selectedVoice !== 'default' ? 'rgba(0,200,255,0.08)' : 'var(--bg-input)',
            border: `1px solid ${selectedVoice !== 'default' ? 'var(--cyan)' : 'var(--border)'}`,
            color: selectedVoice !== 'default' ? 'var(--cyan)' : 'var(--amber-dim)',
            fontFamily: 'var(--font-mono)', cursor: 'pointer', outline: 'none',
            maxWidth: 100,
          }}
        >
          {voiceProfiles.map((v) => (
            <option key={v} value={v}>{v.toUpperCase()}</option>
          ))}
        </select>

        {/* Device selector toggle */}
        <button
          onClick={() => setShowDevSel(v => !v)}
          title="Microphone settings"
          style={{ marginLeft: 4, padding: '1px 6px', fontSize: 10, background: 'transparent', border: '1px solid var(--border)', color: 'var(--amber-dim)', cursor: 'pointer' }}
        >
          🎤 {showDevSel ? '▲' : '▼'}
        </button>

        <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--amber-dim)', letterSpacing: '0.08em' }}>
          {isRecording ? vadEnabled ? 'AUTO-STOP · SPACE TO SEND' : 'SPACE TO SEND'
            : isSpeaking ? '♪ SPEAKING'
            : 'SPACE TO SPEAK'}
        </span>
      </div>

      {/* Device selector (collapsible) */}
      {showDevSel && devices.length > 0 && (
        <div style={{ flexShrink: 0, padding: '6px 10px', borderTop: '1px solid var(--border)', background: '#06070c' }}>
          <div style={{ fontSize: 10, color: 'var(--amber-dim)', marginBottom: 4, letterSpacing: '0.1em' }}>INPUT DEVICE</div>
          <select
            value={selectedDev}
            onChange={(e) => setSelectedDev(e.target.value)}
            disabled={isRecording || busy}
            style={{ width: '100%', background: 'var(--bg-input)', color: 'var(--amber)', border: '1px solid var(--border)', padding: '3px 6px', fontSize: 11, fontFamily: 'var(--font-mono)', outline: 'none', cursor: 'pointer' }}
          >
            {devices.map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label}</option>)}
          </select>
        </div>
      )}

      <style>{`
        @keyframes pulse-ring-sm {
          0%   { box-shadow: 0 0 0 0 rgba(255,26,64,0.5); }
          70%  { box-shadow: 0 0 0 6px rgba(255,26,64,0); }
          100% { box-shadow: 0 0 0 0 rgba(255,26,64,0); }
        }
        @keyframes pulse-text {
          0%, 100% { opacity: 1; } 50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  )
}

function VoiceToggle({ label, on, onClick, title }: { label: string; on: boolean; onClick: () => void; title?: string }) {
  return (
    <button onClick={onClick} title={title} style={{
      padding: '1px 7px', fontSize: 10, letterSpacing: '0.1em',
      background: on ? 'rgba(57,211,83,0.1)' : 'transparent',
      border: `1px solid ${on ? 'var(--green)' : 'var(--border)'}`,
      color: on ? 'var(--green)' : 'var(--amber-dim)',
      cursor: 'pointer', transition: 'all 0.12s',
    }}>{label}</button>
  )
}
