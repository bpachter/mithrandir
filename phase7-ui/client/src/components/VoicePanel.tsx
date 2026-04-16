/**
 * VoicePanel.tsx — Push-to-talk voice interface for Enkidu
 *
 * Flow: record (Web Audio API, native sample rate, float32 mono)
 *    → WS /ws/voice (base64 PCM + actual sample rate)
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

// ── Audio device helpers ───────────────────────────────────────────────────

interface AudioDevice { deviceId: string; label: string }

async function listMicDevices(): Promise<AudioDevice[]> {
  try {
    // getUserMedia first to trigger permission prompt (needed to get labels)
    await navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => s.getTracks().forEach((t) => t.stop()))
    const devices = await navigator.mediaDevices.enumerateDevices()
    return devices
      .filter((d) => d.kind === 'audioinput')
      .map((d) => ({ deviceId: d.deviceId, label: d.label || `Microphone ${d.deviceId.slice(0, 6)}` }))
  } catch {
    return []
  }
}

// ── Audio capture ──────────────────────────────────────────────────────────

interface CaptureHandle {
  audioCtx: AudioContext
  stream:   MediaStream
  chunks:   Float32Array[]
  stop:     () => void
}

async function startCapture(deviceId?: string): Promise<CaptureHandle> {
  const constraints: MediaStreamConstraints = {
    audio: {
      deviceId:          deviceId ? { exact: deviceId } : undefined,
      channelCount:      1,
      echoCancellation:  true,
      noiseSuppression:  true,
      autoGainControl:   true,
    },
  }
  const stream = await navigator.mediaDevices.getUserMedia(constraints)

  // Do NOT force a sample rate — let the browser use the device's native rate.
  // We send the actual rate to the server so it can resample to 16 kHz for Whisper.
  const audioCtx  = new AudioContext()
  const source    = audioCtx.createMediaStreamSource(stream)
  const processor = audioCtx.createScriptProcessor(4096, 1, 1)
  const silencer  = audioCtx.createGain()
  silencer.gain.value = 0   // prevent speaker feedback

  const chunks: Float32Array[] = []
  processor.onaudioprocess = (e) => {
    chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
  }

  source.connect(processor)
  processor.connect(silencer)
  silencer.connect(audioCtx.destination)

  // AudioContext can start suspended on Windows — must resume or onaudioprocess never fires
  await audioCtx.resume()

  const stop = () => {
    processor.disconnect()
    silencer.disconnect()
    source.disconnect()
    stream.getTracks().forEach((t) => t.stop())
    audioCtx.close()
  }

  return { audioCtx, stream, chunks, stop }
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

// ── Component ─────────────────────────────────────────────────────────────

export default function VoicePanel() {
  const [voiceState,  setVoiceState]  = useState<VoiceState>('idle')
  const [transcript,  setTranscript]  = useState('')
  const [response,    setResponse]    = useState('')
  const [status,      setStatus]      = useState('')
  const [error,       setError]       = useState('')
  const [autoSpeak,   setAutoSpeak]   = useState(true)
  const [devices,     setDevices]     = useState<AudioDevice[]>([])
  const [selectedDev, setSelectedDev] = useState<string>('')
  const [debugInfo,   setDebugInfo]   = useState('')  // sample count feedback

  const wsRef       = useRef<WebSocket | null>(null)
  const captureRef  = useRef<CaptureHandle | null>(null)
  const responseRef = useRef('')

  // ── Load mic devices on mount ─────────────────────────────────────────

  useEffect(() => {
    listMicDevices().then((devs) => {
      setDevices(devs)
      // Auto-select first non-default device that looks like a headset
      const headset = devs.find((d) =>
        /headset|headphone|jabra|bose|sony|logitech|hyper/i.test(d.label)
      )
      if (headset) setSelectedDev(headset.deviceId)
      else if (devs.length > 0) setSelectedDev(devs[0].deviceId)
    })
  }, [])

  // ── WebSocket lifecycle ────────────────────────────────────────────────

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
        setDebugInfo('')
      } else if (msg.type === 'error') {
        setError(msg.content)
        setVoiceState('idle')
        setStatus('')
      }
    }

    ws.onclose = () => { wsRef.current = null }
    ws.onerror = () => { setError('WebSocket connection failed — is the server running?') }
    wsRef.current = ws
  }, [autoSpeak])

  useEffect(() => {
    connectVoiceWs()
    return () => { wsRef.current?.close(); wsRef.current = null }
  }, [])

  // ── Record toggle ─────────────────────────────────────────────────────

  const startRecording = useCallback(async () => {
    setError('')
    setTranscript('')
    setResponse('')
    setDebugInfo('')
    setStatus('Opening microphone…')

    try {
      const capture = await startCapture(selectedDev || undefined)
      captureRef.current = capture
      setVoiceState('recording')
      setStatus(`Listening… (${Math.round(capture.audioCtx.sampleRate / 1000)}kHz)`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(`Microphone error: ${msg}`)
      setStatus('')
    }
  }, [selectedDev])

  const stopRecording = useCallback(() => {
    const capture = captureRef.current
    if (!capture) return
    captureRef.current = null

    const actualRate = capture.audioCtx.sampleRate
    capture.stop()

    const { data, samples } = chunksToBase64(capture.chunks)
    const durationMs = Math.round((samples / actualRate) * 1000)

    if (samples < 800) {
      // ~50ms at 16kHz — almost certainly no real audio captured
      setError(`No audio captured (${samples} samples). Check that the correct mic is selected and try again.`)
      setVoiceState('idle')
      setStatus('')
      return
    }

    setDebugInfo(`${samples.toLocaleString()} samples · ${durationMs}ms · ${Math.round(actualRate / 1000)}kHz`)

    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      connectVoiceWs()
      setTimeout(() => wsRef.current?.send(JSON.stringify({ type: 'audio', data, rate: actualRate })), 300)
    } else {
      wsRef.current.send(JSON.stringify({ type: 'audio', data, rate: actualRate }))
    }

    setVoiceState('thinking')
    setStatus('Sending…')
  }, [connectVoiceWs])

  const handleMicClick = useCallback(() => {
    if (voiceState === 'recording') stopRecording()
    else if (voiceState === 'idle')  startRecording()
  }, [voiceState, startRecording, stopRecording])

  // ── Space bar PTT ─────────────────────────────────────────────────────

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

  return (
    <div className="panel" style={{ padding: 0, userSelect: 'none' }}>
      <div className="panel-title">VOICE TERMINAL</div>

      <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 14, alignItems: 'center' }}>

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
            animation: isRecording ? 'pulse-dot 0.8s ease-in-out infinite' : 'none',
          }} />
          {STATE_LABEL[voiceState]}
          {status && <span style={{ color: 'var(--amber-dim)', marginLeft: 8, fontSize: 10 }}>{status}</span>}
        </div>

        {/* Mic device selector */}
        {devices.length > 0 && (
          <div style={{ alignSelf: 'stretch' }}>
            <div style={{ fontSize: 10, color: 'var(--amber-dim)', letterSpacing: '0.12em', marginBottom: 4 }}>
              INPUT DEVICE
            </div>
            <select
              value={selectedDev}
              onChange={(e) => setSelectedDev(e.target.value)}
              disabled={isRecording || isBusy}
              style={{
                width: '100%', background: 'var(--bg-input)', color: 'var(--amber)',
                border: '1px solid var(--border)', padding: '4px 6px',
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

        {/* Mic button */}
        <button
          onClick={handleMicClick}
          disabled={isBusy}
          title={isRecording ? 'Click or release Space to send' : 'Click or hold Space to speak'}
          style={{
            width: 90, height: 90, borderRadius: '50%',
            background: isRecording ? 'rgba(255,26,64,0.15)' : 'var(--bg-input)',
            border: `2px solid ${isRecording ? 'var(--red)' : isBusy ? 'var(--amber-dim)' : 'var(--amber)'}`,
            color: isRecording ? 'var(--red)' : isBusy ? 'var(--amber-dim)' : 'var(--amber)',
            fontSize: 32, cursor: isBusy ? 'default' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: isRecording
              ? '0 0 0 0 rgba(255,26,64,0.5), 0 0 20px rgba(255,26,64,0.4)'
              : '0 0 12px var(--amber-glow)',
            transition: 'all 0.15s ease',
            animation: isRecording ? 'pulse-ring 1.2s ease-out infinite' : 'none',
          }}
        >
          {isRecording ? '⏹' : isBusy ? '⌛' : '🎤'}
        </button>

        <div style={{ fontSize: 10, color: 'var(--amber-dim)', letterSpacing: '0.12em' }}>
          {isRecording ? 'RELEASE TO SEND  ·  SPACE'
            : isBusy   ? ''
            : 'CLICK TO SPEAK  ·  SPACE'}
        </div>

        {/* Debug info (sample count) */}
        {debugInfo && (
          <div style={{ fontSize: 10, color: 'var(--cyan-dim)', letterSpacing: '0.1em' }}>
            {debugInfo}
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
              borderBottom: '1px solid var(--border)', paddingBottom: 4, marginBottom: 6,
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
              borderBottom: '1px solid var(--border)', paddingBottom: 4, marginBottom: 6,
            }}>ENKIDU</div>
            <div style={{ color: 'var(--amber)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
              {response}
            </div>
          </div>
        )}

        {/* Controls row */}
        <div style={{
          alignSelf: 'stretch', borderTop: '1px solid var(--border)',
          paddingTop: 8, display: 'flex', alignItems: 'center', gap: 12,
          fontSize: 11, color: 'var(--amber-dim)', marginTop: 'auto',
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
          <button
            onClick={() => listMicDevices().then(setDevices)}
            title="Refresh device list"
            style={{
              marginLeft: 'auto', padding: '2px 8px', fontSize: 10,
              background: 'transparent', border: '1px solid var(--border)',
              color: 'var(--amber-dim)', cursor: 'pointer',
            }}
          >
            ↺ DEVICES
          </button>
        </div>
      </div>

      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.3; }
        }
        @keyframes pulse-ring {
          0%   { box-shadow: 0 0 0 0 rgba(255,26,64,0.5), 0 0 20px rgba(255,26,64,0.4); }
          70%  { box-shadow: 0 0 0 10px rgba(255,26,64,0), 0 0 20px rgba(255,26,64,0.4); }
          100% { box-shadow: 0 0 0 0 rgba(255,26,64,0),   0 0 20px rgba(255,26,64,0.4); }
        }
      `}</style>
    </div>
  )
}
