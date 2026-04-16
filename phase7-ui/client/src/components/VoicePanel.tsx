/**
 * VoicePanel.tsx — Conversational voice interface for Enkidu
 *
 * Flow:
 *   VAD auto-stop (or push-to-talk fallback)
 *   → WS /ws/voice (base64 float32 PCM + sample rate)
 *   → server: Whisper STT → run_agent → edge-tts BrianNeural
 *   → transcript + streaming tokens + MP3 playback
 *   → [if auto-converse] immediately start listening again
 *
 * VAD algorithm:
 *   AnalyserNode (256-point FFT) → RMS every 80 ms
 *   Speech starts when RMS > SPEECH_THRESHOLD for 2+ consecutive frames
 *   Speech ends when RMS < SILENCE_THRESHOLD for SILENCE_DURATION_MS
 */

import { useEffect, useRef, useState, useCallback } from 'react'

// ── VAD constants ──────────────────────────────────────────────────────────

const SPEECH_THRESHOLD   = 0.012   // RMS level above which we consider it speech
const SILENCE_THRESHOLD  = 0.008   // RMS below this = silence
const SILENCE_DURATION_MS = 900    // how long silence must last before auto-stop
const MIN_SPEECH_MS       = 400    // minimum speech before we'll accept it
const VAD_POLL_MS         = 80     // how often to check the analyser

// ── Types ─────────────────────────────────────────────────────────────────

type VoiceState = 'idle' | 'recording' | 'thinking' | 'speaking'

const STATE_LABEL: Record<VoiceState, string> = {
  idle:      'READY',
  recording: 'LISTENING',
  thinking:  'PROCESSING',
  speaking:  'ENKIDU SPEAKING',
}

const STATE_COLOR: Record<VoiceState, string> = {
  idle:      'var(--amber-dim)',
  recording: 'var(--red)',
  thinking:  'var(--amber)',
  speaking:  'var(--green)',
}

// ── Device helpers ─────────────────────────────────────────────────────────

interface AudioDevice { deviceId: string; label: string }

async function listMicDevices(): Promise<AudioDevice[]> {
  try {
    await navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => s.getTracks().forEach((t) => t.stop()))
    const devices = await navigator.mediaDevices.enumerateDevices()
    return devices
      .filter((d) => d.kind === 'audioinput')
      .map((d) => ({ deviceId: d.deviceId, label: d.label || `Microphone ${d.deviceId.slice(0, 6)}` }))
  } catch {
    return []
  }
}

// ── Capture ────────────────────────────────────────────────────────────────

interface CaptureHandle {
  audioCtx: AudioContext
  stream:   MediaStream
  chunks:   Float32Array[]
  analyser: AnalyserNode
  stop:     () => void
}

async function startCapture(deviceId?: string): Promise<CaptureHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      deviceId:          deviceId ? { exact: deviceId } : undefined,
      channelCount:      1,
      echoCancellation:  true,
      noiseSuppression:  true,
      autoGainControl:   true,
    },
  })

  const audioCtx  = new AudioContext()
  const source    = audioCtx.createMediaStreamSource(stream)
  const processor = audioCtx.createScriptProcessor(4096, 1, 1)
  const analyser  = audioCtx.createAnalyser()
  const silencer  = audioCtx.createGain()

  analyser.fftSize = 256
  silencer.gain.value = 0

  const chunks: Float32Array[] = []
  processor.onaudioprocess = (e) => {
    chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
  }

  source.connect(analyser)
  source.connect(processor)
  processor.connect(silencer)
  silencer.connect(audioCtx.destination)

  await audioCtx.resume()

  const stop = () => {
    processor.disconnect()
    silencer.disconnect()
    source.disconnect()
    stream.getTracks().forEach((t) => t.stop())
    audioCtx.close()
  }

  return { audioCtx, stream, chunks, analyser, stop }
}

// ── Helpers ────────────────────────────────────────────────────────────────

function getRms(analyser: AnalyserNode): number {
  const buf = new Float32Array(analyser.fftSize)
  analyser.getFloatTimeDomainData(buf)
  let sum = 0
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
  return Math.sqrt(sum / buf.length)
}

function chunksToBase64(chunks: Float32Array[]): { data: string; samples: number } {
  const total    = chunks.reduce((n, c) => n + c.length, 0)
  const combined = new Float32Array(total)
  let offset = 0
  for (const c of chunks) { combined.set(c, offset); offset += c.length }
  const bytes = new Uint8Array(combined.buffer)
  let binary  = ''
  const STEP  = 8192
  for (let i = 0; i < bytes.length; i += STEP) {
    binary += String.fromCharCode(...bytes.subarray(i, i + STEP))
  }
  return { data: btoa(binary), samples: total }
}

function playMp3Base64(b64: string): Promise<void> {
  return new Promise((resolve) => {
    const bytes   = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
    const blob    = new Blob([bytes], { type: 'audio/mpeg' })
    const url     = URL.createObjectURL(blob)
    const audio   = new Audio(url)
    audio.onended = () => { URL.revokeObjectURL(url); resolve() }
    audio.onerror = () => { URL.revokeObjectURL(url); resolve() }
    audio.play().catch(() => resolve())
  })
}

// ── Waveform canvas ────────────────────────────────────────────────────────

interface WaveformProps {
  analyser: AnalyserNode | null
  color:    string
  active:   boolean
}

function Waveform({ analyser, color, active }: WaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef    = useRef<number>(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const W   = canvas.width
    const H   = canvas.height

    const draw = () => {
      rafRef.current = requestAnimationFrame(draw)
      ctx.clearRect(0, 0, W, H)

      if (!analyser || !active) {
        // Flat idle line
        ctx.strokeStyle = color + '40'
        ctx.lineWidth   = 1
        ctx.beginPath()
        ctx.moveTo(0, H / 2)
        ctx.lineTo(W, H / 2)
        ctx.stroke()
        return
      }

      const freqBuf = new Uint8Array(analyser.frequencyBinCount)
      analyser.getByteFrequencyData(freqBuf)

      const barW   = W / freqBuf.length
      const half   = freqBuf.length / 2   // only use lower half of spectrum (voice range)

      ctx.fillStyle = color
      for (let i = 0; i < half; i++) {
        const x  = i * barW * 2
        const h  = (freqBuf[i] / 255) * H
        const y  = H - h

        // Gradient bar
        const grad = ctx.createLinearGradient(x, y, x, H)
        grad.addColorStop(0, color + 'ff')
        grad.addColorStop(1, color + '22')
        ctx.fillStyle = grad
        ctx.fillRect(x, y, Math.max(1, barW * 2 - 1), h)
      }

      // Scan line
      ctx.strokeStyle = color + '30'
      ctx.lineWidth   = 1
      ctx.beginPath()
      ctx.moveTo(0, H / 2)
      ctx.lineTo(W, H / 2)
      ctx.stroke()
    }

    draw()
    return () => cancelAnimationFrame(rafRef.current)
  }, [analyser, color, active])

  return (
    <canvas
      ref={canvasRef}
      width={200}
      height={56}
      style={{ width: '100%', height: 56, display: 'block' }}
    />
  )
}

// ── Component ─────────────────────────────────────────────────────────────

export default function VoicePanel() {
  const [voiceState,    setVoiceState]    = useState<VoiceState>('idle')
  const [transcript,    setTranscript]    = useState('')
  const [response,      setResponse]      = useState('')
  const [status,        setStatus]        = useState('')
  const [error,         setError]         = useState('')
  const [autoSpeak,     setAutoSpeak]     = useState(true)
  const [autoConverse,  setAutoConverse]  = useState(false)  // full hands-free loop
  const [vadMode,       setVadMode]       = useState(true)   // auto-stop on silence
  const [devices,       setDevices]       = useState<AudioDevice[]>([])
  const [selectedDev,   setSelectedDev]   = useState<string>('')
  const [levelPct,      setLevelPct]      = useState(0)       // 0–100 for the level bar

  const wsRef          = useRef<WebSocket | null>(null)
  const captureRef     = useRef<CaptureHandle | null>(null)
  const responseRef    = useRef('')
  const voiceStateRef  = useRef<VoiceState>('idle')
  const vadTimerRef    = useRef<ReturnType<typeof setInterval> | null>(null)
  const speechStartRef = useRef<number | null>(null)   // ms timestamp when speech began
  const silenceStartRef = useRef<number | null>(null)  // ms timestamp when silence began
  const analyserRef    = useRef<AnalyserNode | null>(null)

  // Keep ref in sync so VAD callbacks can read current state
  useEffect(() => { voiceStateRef.current = voiceState }, [voiceState])

  // ── Device list ───────────────────────────────────────────────────────

  useEffect(() => {
    listMicDevices().then((devs) => {
      setDevices(devs)
      const headset = devs.find((d) =>
        /headset|headphone|jabra|bose|sony|logitech|hyper|blue|yeti|rode|samson/i.test(d.label)
      )
      if (headset) setSelectedDev(headset.deviceId)
      else if (devs.length > 0) setSelectedDev(devs[0].deviceId)
    })
  }, [])

  // ── WebSocket ──────────────────────────────────────────────────────────

  const connectVoiceWs = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) return

    const ws = new WebSocket('ws://localhost:8000/ws/voice')

    ws.onmessage = async (ev) => {
      const msg = JSON.parse(ev.data)

      if (msg.type === 'status') {
        setStatus(msg.content)
      } else if (msg.type === 'transcript') {
        setTranscript(msg.text)
        setVoiceState('thinking')
        responseRef.current = ''
        setResponse('')
      } else if (msg.type === 'step') {
        setStatus(msg.content)
      } else if (msg.type === 'token') {
        responseRef.current += msg.content
        setResponse(responseRef.current)
      } else if (msg.type === 'response') {
        responseRef.current = msg.content
        setResponse(msg.content)
      } else if (msg.type === 'tts_audio') {
        if (autoSpeak) {
          setVoiceState('speaking')
          setStatus('Enkidu speaking…')
          await playMp3Base64(msg.data)
        }
      } else if (msg.type === 'done') {
        setVoiceState('idle')
        setStatus('')
        setLevelPct(0)
        // Auto-converse: immediately start listening again
        if (autoConverse) {
          setTimeout(() => startRecording(), 300)
        }
      } else if (msg.type === 'error') {
        setError(msg.content)
        setVoiceState('idle')
        setStatus('')
        setLevelPct(0)
      }
    }

    ws.onclose = () => { wsRef.current = null }
    ws.onerror = () => { setError('WebSocket error — is the server running?') }
    wsRef.current = ws
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSpeak, autoConverse])

  useEffect(() => {
    connectVoiceWs()
    return () => { wsRef.current?.close(); wsRef.current = null }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── VAD loop ───────────────────────────────────────────────────────────

  const stopVad = useCallback(() => {
    if (vadTimerRef.current) {
      clearInterval(vadTimerRef.current)
      vadTimerRef.current = null
    }
    speechStartRef.current  = null
    silenceStartRef.current = null
  }, [])

  const startVad = useCallback((capture: CaptureHandle, sendFn: () => void) => {
    speechStartRef.current  = null
    silenceStartRef.current = null

    vadTimerRef.current = setInterval(() => {
      if (voiceStateRef.current !== 'recording') { stopVad(); return }

      const rms = getRms(capture.analyser)
      setLevelPct(Math.min(100, (rms / SPEECH_THRESHOLD) * 60))

      const now = Date.now()

      if (rms > SPEECH_THRESHOLD) {
        if (!speechStartRef.current) speechStartRef.current = now
        silenceStartRef.current = null   // reset silence timer
      } else if (rms < SILENCE_THRESHOLD) {
        if (speechStartRef.current) {
          // We had speech — now track silence
          if (!silenceStartRef.current) silenceStartRef.current = now
          const silenceDuration = now - silenceStartRef.current
          const speechDuration  = silenceStartRef.current - speechStartRef.current

          if (silenceDuration >= SILENCE_DURATION_MS && speechDuration >= MIN_SPEECH_MS) {
            stopVad()
            sendFn()
          }
        }
      }
    }, VAD_POLL_MS)
  }, [stopVad])

  // ── Record / send ──────────────────────────────────────────────────────

  const sendAudio = useCallback((capture: CaptureHandle) => {
    captureRef.current = null
    analyserRef.current = null

    const actualRate = capture.audioCtx.sampleRate
    capture.stop()

    const { data, samples } = chunksToBase64(capture.chunks)

    if (samples < 800) {
      setError(`No audio captured (${samples} samples). Check mic selection.`)
      setVoiceState('idle')
      setStatus('')
      setLevelPct(0)
      return
    }

    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      connectVoiceWs()
      setTimeout(() => wsRef.current?.send(JSON.stringify({ type: 'audio', data, rate: actualRate })), 300)
    } else {
      wsRef.current.send(JSON.stringify({ type: 'audio', data, rate: actualRate }))
    }

    setVoiceState('thinking')
    setStatus('Sending…')
  }, [connectVoiceWs])

  const startRecording = useCallback(async () => {
    setError('')
    setTranscript('')
    setResponse('')
    setStatus('Opening microphone…')
    setLevelPct(0)

    try {
      const capture = await startCapture(selectedDev || undefined)
      captureRef.current  = capture
      analyserRef.current = capture.analyser
      setVoiceState('recording')
      setStatus(vadMode ? 'Listening — speak now' : `Recording · ${Math.round(capture.audioCtx.sampleRate / 1000)}kHz`)

      if (vadMode) {
        startVad(capture, () => sendAudio(capture))
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(`Microphone error: ${msg}`)
      setStatus('')
    }
  }, [selectedDev, vadMode, startVad, sendAudio])

  const stopRecording = useCallback(() => {
    stopVad()
    const capture = captureRef.current
    if (!capture) return
    sendAudio(capture)
  }, [stopVad, sendAudio])

  const handleMicClick = useCallback(() => {
    if (voiceState === 'recording') stopRecording()
    else if (voiceState === 'idle')  startRecording()
  }, [voiceState, startRecording, stopRecording])

  // ── Space bar PTT ──────────────────────────────────────────────────────

  useEffect(() => {
    const onDown = (e: KeyboardEvent) => {
      if (e.code === 'Space' && e.target === document.body && voiceState === 'idle') {
        e.preventDefault(); startRecording()
      }
    }
    const onUp = (e: KeyboardEvent) => {
      if (e.code === 'Space' && voiceState === 'recording') {
        e.preventDefault(); stopRecording()
      }
    }
    window.addEventListener('keydown', onDown)
    window.addEventListener('keyup',   onUp)
    return () => { window.removeEventListener('keydown', onDown); window.removeEventListener('keyup', onUp) }
  }, [voiceState, startRecording, stopRecording])

  // ── Render ─────────────────────────────────────────────────────────────

  const isRecording = voiceState === 'recording'
  const isBusy      = voiceState === 'thinking' || voiceState === 'speaking'
  const stateColor  = STATE_COLOR[voiceState]

  return (
    <div className="panel" style={{ padding: 0, userSelect: 'none', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div className="panel-title">VOICE TERMINAL</div>

      <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 10, overflow: 'auto' }}>

        {/* State badge */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          fontSize: 11, letterSpacing: '0.2em', color: stateColor,
          textShadow: `0 0 8px ${stateColor}`,
          alignSelf: 'stretch',
        }}>
          <span style={{
            display: 'inline-block', width: 7, height: 7, borderRadius: '50%',
            background: stateColor,
            boxShadow: `0 0 6px ${stateColor}`,
            animation: isRecording ? 'pulse-dot 0.8s ease-in-out infinite' : 'none',
            flexShrink: 0,
          }} />
          {STATE_LABEL[voiceState]}
          {status && <span style={{ color: 'var(--amber-dim)', marginLeft: 4, fontSize: 10, fontWeight: 400 }}>{status}</span>}
        </div>

        {/* Waveform + mic button row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* Mic button */}
          <button
            onClick={handleMicClick}
            disabled={isBusy}
            title={isRecording
              ? vadMode ? 'Stop early / Space' : 'Click or release Space to send'
              : 'Click or hold Space to speak'}
            style={{
              width: 64, height: 64, borderRadius: '50%', flexShrink: 0,
              background: isRecording ? 'rgba(255,26,64,0.15)' : 'var(--bg-input)',
              border: `2px solid ${isRecording ? 'var(--red)' : isBusy ? 'var(--amber-dim)' : 'var(--amber)'}`,
              color: isRecording ? 'var(--red)' : isBusy ? 'var(--amber-dim)' : 'var(--amber)',
              fontSize: 24, cursor: isBusy ? 'default' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: isRecording
                ? '0 0 0 0 rgba(255,26,64,0.5), 0 0 18px rgba(255,26,64,0.4)'
                : '0 0 10px var(--amber-glow)',
              transition: 'all 0.15s ease',
              animation: isRecording ? 'pulse-ring 1.2s ease-out infinite' : 'none',
            }}
          >
            {isRecording ? '⏹' : isBusy ? '⌛' : '🎤'}
          </button>

          {/* Waveform */}
          <div style={{
            flex: 1, background: '#07080d',
            border: `1px solid ${isRecording ? 'var(--red)' : '#1a2035'}`,
            borderRadius: 2, overflow: 'hidden',
            transition: 'border-color 0.2s',
          }}>
            <Waveform
              analyser={analyserRef.current}
              color={isRecording ? '#ff1a40' : voiceState === 'speaking' ? '#39d353' : '#00e5ff'}
              active={isRecording}
            />
          </div>
        </div>

        {/* Level bar (VAD mode) */}
        {isRecording && vadMode && (
          <div style={{ height: 3, background: '#1a2035', borderRadius: 2 }}>
            <div style={{
              height: '100%',
              width: `${levelPct}%`,
              background: levelPct > 70 ? 'var(--green)' : levelPct > 30 ? 'var(--amber)' : 'var(--red)',
              transition: 'width 80ms linear, background 200ms',
              borderRadius: 2,
            }} />
          </div>
        )}

        {/* Hint text */}
        <div style={{ fontSize: 10, color: 'var(--amber-dim)', letterSpacing: '0.1em', textAlign: 'center' }}>
          {isRecording
            ? vadMode ? 'AUTO-STOP ON SILENCE  ·  SPACE TO SEND NOW' : 'RELEASE TO SEND  ·  SPACE'
            : isBusy ? ''
            : 'CLICK TO SPEAK  ·  SPACE'}
        </div>

        {/* Device selector */}
        {devices.length > 0 && (
          <div style={{ alignSelf: 'stretch' }}>
            <div style={{ fontSize: 10, color: 'var(--amber-dim)', letterSpacing: '0.12em', marginBottom: 3 }}>
              INPUT DEVICE
            </div>
            <select
              value={selectedDev}
              onChange={(e) => setSelectedDev(e.target.value)}
              disabled={isRecording || isBusy}
              style={{
                width: '100%', background: 'var(--bg-input)', color: 'var(--amber)',
                border: '1px solid var(--border)', padding: '3px 6px',
                fontSize: 11, fontFamily: 'var(--font-mono)',
                cursor: 'pointer', outline: 'none',
              }}
            >
              {devices.map((d) => (
                <option key={d.deviceId} value={d.deviceId}>{d.label}</option>
              ))}
            </select>
          </div>
        )}

        {/* Error */}
        {error && (
          <div style={{
            color: 'var(--red)', fontSize: 11, textAlign: 'center',
            border: '1px solid var(--red)', padding: '5px 8px',
            background: 'rgba(255,26,64,0.07)', alignSelf: 'stretch',
          }}>
            {error}
          </div>
        )}

        {/* Transcript */}
        {transcript && (
          <div style={{ alignSelf: 'stretch' }}>
            <div style={{
              fontSize: 10, color: 'var(--cyan)', letterSpacing: '0.15em',
              borderBottom: '1px solid var(--border)', paddingBottom: 3, marginBottom: 5,
            }}>YOU SAID</div>
            <div style={{ color: 'var(--white-dim)', fontSize: 12, lineHeight: 1.5 }}>
              {transcript}
            </div>
          </div>
        )}

        {/* Response */}
        {response && (
          <div style={{ alignSelf: 'stretch', flex: 1, overflow: 'auto' }}>
            <div style={{
              fontSize: 10, color: 'var(--green)', letterSpacing: '0.15em',
              borderBottom: '1px solid var(--border)', paddingBottom: 3, marginBottom: 5,
            }}>ENKIDU</div>
            <div style={{ color: 'var(--amber)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
              {response}
            </div>
          </div>
        )}

        {/* Controls row */}
        <div style={{
          alignSelf: 'stretch', borderTop: '1px solid var(--border)',
          paddingTop: 8, display: 'flex', alignItems: 'center', gap: 8,
          fontSize: 10, color: 'var(--amber-dim)', marginTop: 'auto', flexWrap: 'wrap',
        }}>

          <ToggleBtn label="VAD"     on={vadMode}      onClick={() => setVadMode(v => !v)} />
          <ToggleBtn label="SPEAK"   on={autoSpeak}    onClick={() => setAutoSpeak(v => !v)} />
          <ToggleBtn label="LOOP"    on={autoConverse} onClick={() => setAutoConverse(v => !v)}
            title="Auto-listen after each response" />

          <button
            onClick={() => listMicDevices().then(setDevices)}
            title="Refresh device list"
            style={{
              marginLeft: 'auto', padding: '2px 8px', fontSize: 10,
              background: 'transparent', border: '1px solid var(--border)',
              color: 'var(--amber-dim)', cursor: 'pointer',
            }}
          >↺</button>
        </div>
      </div>

      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.3; }
        }
        @keyframes pulse-ring {
          0%   { box-shadow: 0 0 0 0 rgba(255,26,64,0.5), 0 0 18px rgba(255,26,64,0.4); }
          70%  { box-shadow: 0 0 0 8px rgba(255,26,64,0), 0 0 18px rgba(255,26,64,0.4); }
          100% { box-shadow: 0 0 0 0 rgba(255,26,64,0),  0 0 18px rgba(255,26,64,0.4); }
        }
      `}</style>
    </div>
  )
}

// ── Small reusable toggle ──────────────────────────────────────────────────

function ToggleBtn({ label, on, onClick, title }: { label: string; on: boolean; onClick: () => void; title?: string }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        padding: '2px 7px', fontSize: 10, letterSpacing: '0.1em',
        background: on ? 'rgba(57,211,83,0.12)' : 'transparent',
        border: `1px solid ${on ? 'var(--green)' : 'var(--border)'}`,
        color: on ? 'var(--green)' : 'var(--amber-dim)',
        cursor: 'pointer',
        boxShadow: on ? '0 0 5px rgba(57,211,83,0.2)' : 'none',
        transition: 'all 0.15s',
      }}
    >
      {label}
    </button>
  )
}
