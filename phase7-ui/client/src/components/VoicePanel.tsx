/**
 * VoicePanel.tsx — Push-to-talk voice interface for Enkidu
 *
 * Flow: record (Web Audio API, 16 kHz float32)
 *    → WS /ws/voice (base64 PCM)
 *    → server: Whisper STT → run_agent → edge-tts
 *    → transcript + streaming tokens + MP3 audio playback
 */

import { useEffect, useRef, useState, useCallback } from 'react'

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

// ── Audio capture helpers ──────────────────────────────────────────────────

const TARGET_RATE = 16000  // Whisper expects 16 kHz

async function startCapture(): Promise<{
  audioCtx: AudioContext
  stream: MediaStream
  chunks: Float32Array[]
  stop: () => void
}> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  })

  // Request 16 kHz — browser may resample internally if hardware doesn't support it
  const audioCtx = new AudioContext({ sampleRate: TARGET_RATE })
  const source   = audioCtx.createMediaStreamSource(stream)

  // ScriptProcessor to capture raw float32 PCM
  const processor = audioCtx.createScriptProcessor(4096, 1, 1)
  const silencer  = audioCtx.createGain()
  silencer.gain.value = 0   // prevent speaker echo

  const chunks: Float32Array[] = []
  processor.onaudioprocess = (e) => {
    chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
  }

  source.connect(processor)
  processor.connect(silencer)
  silencer.connect(audioCtx.destination)

  const stop = () => {
    processor.disconnect()
    silencer.disconnect()
    source.disconnect()
    stream.getTracks().forEach((t) => t.stop())
    audioCtx.close()
  }

  return { audioCtx, stream, chunks, stop }
}

function chunksToBase64(chunks: Float32Array[], actualRate: number): { data: string; rate: number } {
  const total    = chunks.reduce((n, c) => n + c.length, 0)
  const combined = new Float32Array(total)
  let offset = 0
  for (const c of chunks) { combined.set(c, offset); offset += c.length }

  const bytes  = new Uint8Array(combined.buffer)
  // btoa can't handle large arrays directly — use a chunked approach
  let binary = ''
  const CHUNK = 8192
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK))
  }
  return { data: btoa(binary), rate: actualRate }
}

function playMp3Base64(b64: string): Promise<void> {
  return new Promise((resolve) => {
    const bytes    = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
    const blob     = new Blob([bytes], { type: 'audio/mpeg' })
    const url      = URL.createObjectURL(blob)
    const audio    = new Audio(url)
    audio.onended  = () => { URL.revokeObjectURL(url); resolve() }
    audio.onerror  = () => { URL.revokeObjectURL(url); resolve() }
    audio.play().catch(() => resolve())
  })
}

// ── Component ─────────────────────────────────────────────────────────────

export default function VoicePanel() {
  const [voiceState,  setVoiceState]  = useState<VoiceState>('idle')
  const [transcript,  setTranscript]  = useState('')
  const [response,    setResponse]    = useState('')
  const [status,      setStatus]      = useState('')
  const [error,       setError]       = useState('')
  const [autoSpeak,   setAutoSpeak]   = useState(true)
  const [micGranted,  setMicGranted]  = useState<boolean | null>(null)

  const wsRef       = useRef<WebSocket | null>(null)
  const captureRef  = useRef<Awaited<ReturnType<typeof startCapture>> | null>(null)
  const responseRef = useRef('')   // accumulate tokens

  // ── WebSocket lifecycle ────────────────────────────────────────────────

  const connectVoiceWs = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) return

    const ws = new WebSocket('ws://localhost:8000/ws/voice')

    ws.onmessage = async (ev) => {
      const msg = JSON.parse(ev.data)

      if (msg.type === 'status') {
        setStatus(msg.content)
      }
      else if (msg.type === 'transcript') {
        setTranscript(msg.text)
        setVoiceState('thinking')
        responseRef.current = ''
        setResponse('')
      }
      else if (msg.type === 'step') {
        setStatus(msg.content)
      }
      else if (msg.type === 'token') {
        responseRef.current += msg.content
        setResponse(responseRef.current)
      }
      else if (msg.type === 'response') {
        responseRef.current = msg.content
        setResponse(msg.content)
      }
      else if (msg.type === 'tts_audio') {
        if (autoSpeak) {
          setVoiceState('speaking')
          setStatus('Enkidu speaking…')
          await playMp3Base64(msg.data)
        }
      }
      else if (msg.type === 'done') {
        setVoiceState('idle')
        setStatus('')
      }
      else if (msg.type === 'error') {
        setError(msg.content)
        setVoiceState('idle')
        setStatus('')
      }
    }

    ws.onclose = () => { wsRef.current = null }
    wsRef.current = ws
  }, [autoSpeak])

  useEffect(() => {
    connectVoiceWs()
    // Check mic permission
    navigator.permissions
      .query({ name: 'microphone' as PermissionName })
      .then((p) => setMicGranted(p.state === 'granted'))
      .catch(() => setMicGranted(null))

    return () => { wsRef.current?.close(); wsRef.current = null }
  }, [])  // only on mount — connectVoiceWs reconnects on demand

  // ── Record toggle ─────────────────────────────────────────────────────

  const startRecording = useCallback(async () => {
    setError('')
    setTranscript('')
    setResponse('')
    setStatus('Opening microphone…')

    try {
      const capture = await startCapture()
      captureRef.current = capture
      setVoiceState('recording')
      setStatus('Listening…')
      setMicGranted(true)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(`Microphone error: ${msg}`)
      setStatus('')
      setMicGranted(false)
    }
  }, [])

  const stopRecording = useCallback(() => {
    const capture = captureRef.current
    if (!capture) return
    captureRef.current = null

    capture.stop()
    const { data, rate } = chunksToBase64(capture.chunks, capture.audioCtx.sampleRate)

    if (!data) { setVoiceState('idle'); return }

    // Ensure WS is open
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      connectVoiceWs()
      // Give WS a moment to open, then send
      setTimeout(() => {
        wsRef.current?.send(JSON.stringify({ type: 'audio', data, rate }))
      }, 300)
    } else {
      wsRef.current.send(JSON.stringify({ type: 'audio', data, rate }))
    }

    setVoiceState('thinking')
    setStatus('Sending audio…')
  }, [connectVoiceWs])

  const handleMicClick = useCallback(() => {
    if (voiceState === 'recording') {
      stopRecording()
    } else if (voiceState === 'idle') {
      startRecording()
    }
  }, [voiceState, startRecording, stopRecording])

  // ── Keyboard shortcut: Space bar = PTT ───────────────────────────────

  useEffect(() => {
    const onDown = (e: KeyboardEvent) => {
      if (e.code === 'Space' && e.target === document.body && voiceState === 'idle') {
        e.preventDefault()
        startRecording()
      }
    }
    const onUp = (e: KeyboardEvent) => {
      if (e.code === 'Space' && voiceState === 'recording') {
        e.preventDefault()
        stopRecording()
      }
    }
    window.addEventListener('keydown', onDown)
    window.addEventListener('keyup',   onUp)
    return () => { window.removeEventListener('keydown', onDown); window.removeEventListener('keyup', onUp) }
  }, [voiceState, startRecording, stopRecording])

  // ── Render ─────────────────────────────────────────────────────────────

  const isRecording = voiceState === 'recording'
  const isbusy      = voiceState !== 'idle' && voiceState !== 'recording'

  return (
    <div className="panel" style={{ padding: 0, userSelect: 'none' }}>
      <div className="panel-title">VOICE TERMINAL</div>

      <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'center' }}>

        {/* State badge */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          fontSize: 11, letterSpacing: '0.2em', color: STATE_COLOR[voiceState],
          textShadow: `0 0 8px ${STATE_COLOR[voiceState]}`,
          alignSelf: 'stretch',
        }}>
          <span style={{
            display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
            background: STATE_COLOR[voiceState],
            boxShadow: `0 0 6px ${STATE_COLOR[voiceState]}`,
            animation: isRecording ? 'pulse-red 0.8s ease-in-out infinite' : 'none',
          }} />
          {STATE_LABEL[voiceState]}
          {status && <span style={{ color: 'var(--amber-dim)', marginLeft: 8 }}>{status}</span>}
        </div>

        {/* Mic button */}
        <button
          onClick={handleMicClick}
          disabled={isbusy}
          title={isRecording ? 'Click or release Space to send' : 'Click or hold Space to speak'}
          style={{
            width: 100, height: 100, borderRadius: '50%',
            background: isRecording ? 'var(--red)' : '#0b0d14',
            border: `2px solid ${isRecording ? 'var(--red)' : isbusy ? 'var(--amber-dim)' : 'var(--amber)'}`,
            color: isRecording ? '#fff' : isbusy ? 'var(--amber-dim)' : 'var(--amber)',
            fontSize: 36, cursor: isbusy ? 'default' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: isRecording
              ? '0 0 24px var(--red), 0 0 48px rgba(255,26,64,0.3)'
              : isbusy
                ? '0 0 8px var(--amber-glow)'
                : '0 0 16px var(--amber-glow)',
            transition: 'all 0.15s ease',
            animation: isRecording ? 'pulse-ring 1s ease-out infinite' : 'none',
          }}
        >
          {isRecording ? '⏹' : isbusy ? '⌛' : '🎤'}
        </button>

        <div style={{ fontSize: 10, color: 'var(--amber-dim)', letterSpacing: '0.15em' }}>
          {isRecording ? 'RELEASE TO SEND  ·  SPACE' : isbusy ? '' : 'CLICK TO SPEAK  ·  SPACE'}
        </div>

        {/* Mic permission warning */}
        {micGranted === false && (
          <div style={{ color: 'var(--red)', fontSize: 11, textAlign: 'center' }}>
            Microphone access denied. Check browser permissions.
          </div>
        )}

        {/* Error */}
        {error && (
          <div style={{
            color: 'var(--red)', fontSize: 11, textAlign: 'center',
            border: '1px solid var(--red)', padding: '4px 8px',
            background: 'rgba(255,26,64,0.08)', alignSelf: 'stretch',
          }}>
            {error}
          </div>
        )}

        {/* Transcript */}
        {transcript && (
          <div style={{ alignSelf: 'stretch' }}>
            <div style={{
              fontSize: 10, color: 'var(--cyan)', letterSpacing: '0.15em',
              borderBottom: '1px solid var(--border)', paddingBottom: 4, marginBottom: 6,
            }}>
              YOU SAID
            </div>
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
              borderBottom: '1px solid var(--border)', paddingBottom: 4, marginBottom: 6,
            }}>
              ENKIDU
            </div>
            <div style={{ color: 'var(--amber)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
              {response}
            </div>
          </div>
        )}

        {/* Controls */}
        <div style={{
          alignSelf: 'stretch', borderTop: '1px solid var(--border)',
          paddingTop: 8, display: 'flex', alignItems: 'center', gap: 12,
          fontSize: 11, color: 'var(--amber-dim)',
        }}>
          <span>AUTO-SPEAK</span>
          <button
            onClick={() => setAutoSpeak((v) => !v)}
            style={{
              padding: '2px 10px', fontSize: 10, letterSpacing: '0.1em',
              background: autoSpeak ? 'var(--green-dim)' : 'transparent',
              border: `1px solid ${autoSpeak ? 'var(--green)' : 'var(--amber-dim)'}`,
              color: autoSpeak ? 'var(--green)' : 'var(--amber-dim)',
              cursor: 'pointer',
              boxShadow: autoSpeak ? '0 0 6px var(--green-dim)' : 'none',
            }}
          >
            {autoSpeak ? 'ON' : 'OFF'}
          </button>
          <span style={{ marginLeft: 'auto', color: 'var(--amber-dim)', fontSize: 10 }}>
            GUY·NEURAL
          </span>
        </div>
      </div>

      <style>{`
        @keyframes pulse-red {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.4; }
        }
        @keyframes pulse-ring {
          0%   { box-shadow: 0 0 0 0 rgba(255,26,64,0.6), 0 0 24px var(--red); }
          70%  { box-shadow: 0 0 0 12px rgba(255,26,64,0), 0 0 24px var(--red); }
          100% { box-shadow: 0 0 0 0 rgba(255,26,64,0), 0 0 24px var(--red); }
        }
      `}</style>
    </div>
  )
}
