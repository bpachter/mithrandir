/**
 * DemoPanel.tsx — Prebuilt demo launcher
 *
 * Shows 4 scripted demos (local speed, EDGAR analysis, voice, system monitoring).
 * Each demo has a list of prompts the user can fire one at a time into ChatPanel.
 * Voice-only steps show a tip to click the mic instead of injecting text.
 */

import { useEffect, useState } from 'react'
import { useStore } from '../store'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

interface DemoStep {
  label: string
  prompt: string
  voice_only?: boolean
  tip?: string
  expected_keywords?: string[]
}

interface Demo {
  id: string
  title: string
  description: string
  category: string
  step_count: number
  intro: string
  steps?: DemoStep[]
  tags?: string[]
}

const CATEGORY_ICONS: Record<string, string> = {
  local:   '⚡',
  finance: '📊',
  voice:   '🎙',
  system:  '🖥',
}

const CATEGORY_COLORS: Record<string, string> = {
  local:   'var(--amber)',
  finance: 'var(--cyan)',
  voice:   'var(--red)',
  system:  'var(--green)',
}

export default function DemoPanel({ onAskEnkidu }: { onAskEnkidu: (q: string) => void }) {
  const [demos,        setDemos]        = useState<Demo[]>([])
  const [activeDemo,   setActiveDemo]   = useState<Demo | null>(null)
  const [currentStep,  setCurrentStep]  = useState(0)
  const [loading,      setLoading]      = useState(false)
  const [error,        setError]        = useState('')
  const busy = useStore((s) => s.busy)

  useEffect(() => {
    fetch(`${API_BASE}/api/demos`)
      .then((r) => r.json())
      .then((d) => setDemos(d.demos || []))
      .catch(() => setError('Backend not reachable'))
  }, [])

  async function startDemo(demo: Demo) {
    setLoading(true)
    try {
      const r = await fetch(`${API_BASE}/api/demos/${demo.id}`)
      const full: Demo = await r.json()
      setActiveDemo(full)
      setCurrentStep(0)
    } catch {
      setError('Failed to load demo')
    } finally {
      setLoading(false)
    }
  }

  function runStep(step: DemoStep) {
    if (step.voice_only) return  // voice-only: user must use mic
    onAskEnkidu(step.prompt)
    setCurrentStep((n) => Math.min(n + 1, (activeDemo?.steps?.length ?? 1) - 1))
  }

  function nextStep() {
    if (!activeDemo?.steps) return
    const step = activeDemo.steps[currentStep]
    if (step && !step.voice_only) {
      runStep(step)
    } else {
      // Voice-only step — just advance
      setCurrentStep((n) => Math.min(n + 1, activeDemo.steps!.length - 1))
    }
  }

  if (activeDemo) {
    const steps = activeDemo.steps ?? []
    const catColor = CATEGORY_COLORS[activeDemo.category] || 'var(--amber)'

    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '10px', gap: 10, overflowY: 'auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={() => setActiveDemo(null)}
            style={{ background: 'none', border: '1px solid var(--border)', color: 'var(--amber-dim)', fontSize: 10, padding: '2px 8px', cursor: 'pointer', letterSpacing: '0.08em' }}
          >
            ← DEMOS
          </button>
          <span style={{ fontSize: 11, color: catColor, letterSpacing: '0.12em', fontWeight: 600 }}>
            {CATEGORY_ICONS[activeDemo.category]} {activeDemo.title.toUpperCase()}
          </span>
        </div>

        {/* Intro */}
        <div style={{ fontSize: 11, color: 'var(--white-dim)', lineHeight: 1.6, padding: '8px', background: 'rgba(255,180,0,0.04)', border: `1px solid ${catColor}33`, borderRadius: 4 }}>
          {activeDemo.intro}
        </div>

        {/* Progress */}
        <div style={{ fontSize: 10, color: 'var(--amber-dim)', letterSpacing: '0.1em' }}>
          STEP {currentStep + 1} / {steps.length}
          <div style={{ marginTop: 4, height: 2, background: 'var(--border)', borderRadius: 1 }}>
            <div style={{ height: '100%', width: `${((currentStep + 1) / steps.length) * 100}%`, background: catColor, borderRadius: 1, transition: 'width 0.3s' }} />
          </div>
        </div>

        {/* Steps list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {steps.map((s, i) => {
            const isActive = i === currentStep
            const isDone = i < currentStep
            return (
              <div
                key={i}
                style={{
                  padding: '8px 10px',
                  border: `1px solid ${isActive ? catColor : isDone ? 'var(--green)33' : 'var(--border)'}`,
                  background: isActive ? `${catColor}0d` : isDone ? 'rgba(57,211,83,0.03)' : 'transparent',
                  borderRadius: 4,
                  opacity: i > currentStep ? 0.45 : 1,
                  transition: 'all 0.15s',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ fontSize: 11, color: isActive ? catColor : isDone ? 'var(--green)' : 'var(--amber-dim)', letterSpacing: '0.08em' }}>
                    {isDone ? '✓' : isActive ? '▶' : `${i + 1}.`} {s.label}
                  </span>
                  {isActive && (
                    s.voice_only ? (
                      <span style={{ fontSize: 10, color: 'var(--red)', letterSpacing: '0.08em' }}>🎤 USE MIC</span>
                    ) : (
                      <button
                        onClick={() => runStep(s)}
                        disabled={busy}
                        style={{
                          padding: '2px 10px', fontSize: 10, letterSpacing: '0.1em',
                          background: busy ? 'transparent' : `${catColor}22`,
                          border: `1px solid ${catColor}`,
                          color: catColor, cursor: busy ? 'default' : 'pointer',
                        }}
                      >
                        RUN
                      </button>
                    )
                  )}
                </div>

                {isActive && s.voice_only && s.tip && (
                  <div style={{ marginTop: 6, fontSize: 10, color: 'var(--red)', lineHeight: 1.5 }}>
                    → {s.tip}
                  </div>
                )}
                {isActive && !s.voice_only && (
                  <div style={{ marginTop: 6, fontSize: 10, color: 'var(--white-dim)', opacity: 0.7, lineHeight: 1.5 }}>
                    {s.prompt.length > 120 ? s.prompt.slice(0, 120) + '…' : s.prompt}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Next/Done */}
        {currentStep < steps.length - 1 ? (
          <button
            onClick={nextStep}
            disabled={busy}
            style={{
              padding: '6px 0', fontSize: 11, letterSpacing: '0.12em',
              background: busy ? 'transparent' : `${catColor}1a`,
              border: `1px solid ${catColor}`,
              color: busy ? 'var(--border)' : catColor,
              cursor: busy ? 'default' : 'pointer',
              marginTop: 4,
            }}
          >
            NEXT STEP →
          </button>
        ) : (
          <div style={{ textAlign: 'center', padding: '10px 0', color: 'var(--green)', fontSize: 11, letterSpacing: '0.12em' }}>
            ✓ DEMO COMPLETE
            <div style={{ marginTop: 8 }}>
              <button
                onClick={() => setActiveDemo(null)}
                style={{ padding: '4px 14px', fontSize: 10, background: 'rgba(57,211,83,0.1)', border: '1px solid var(--green)', color: 'var(--green)', cursor: 'pointer', letterSpacing: '0.08em' }}
              >
                ← BACK TO DEMOS
              </button>
            </div>
          </div>
        )}
      </div>
    )
  }

  // Demo list
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflowY: 'auto', padding: '10px', gap: 8 }}>
      <div style={{ fontSize: 10, color: 'var(--amber-dim)', letterSpacing: '0.12em', marginBottom: 4 }}>
        SELECT DEMO MODE
      </div>

      {error && (
        <div style={{ fontSize: 10, color: 'var(--red)', padding: '6px 8px', border: '1px solid var(--red)', marginBottom: 4 }}>
          {error}
        </div>
      )}

      {loading && (
        <div style={{ fontSize: 10, color: 'var(--amber-dim)', padding: '10px 0', textAlign: 'center', letterSpacing: '0.1em' }}>
          LOADING…
        </div>
      )}

      {demos.map((demo) => {
        const catColor = CATEGORY_COLORS[demo.category] || 'var(--amber)'
        const icon = CATEGORY_ICONS[demo.category] || '▷'
        return (
          <div
            key={demo.id}
            style={{
              border: '1px solid var(--border)',
              borderRadius: 4,
              overflow: 'hidden',
              cursor: 'pointer',
              transition: 'border-color 0.15s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = catColor)}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--border)')}
          >
            <div style={{ padding: '8px 10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 12, color: catColor, letterSpacing: '0.08em', fontWeight: 600 }}>
                  {icon} {demo.title}
                </span>
                <span style={{ fontSize: 9, color: 'var(--border)', letterSpacing: '0.1em' }}>
                  {demo.step_count} STEPS
                </span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--white-dim)', lineHeight: 1.5, marginBottom: 8 }}>
                {demo.description}
              </div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
                {(demo.tags ?? []).slice(0, 4).map((tag: string) => (
                  <span key={tag} style={{ fontSize: 9, padding: '1px 5px', border: `1px solid ${catColor}44`, color: catColor, letterSpacing: '0.08em', opacity: 0.7 }}>
                    {tag}
                  </span>
                ))}
              </div>
              <button
                onClick={() => startDemo(demo)}
                style={{
                  width: '100%', padding: '5px 0', fontSize: 10, letterSpacing: '0.12em',
                  background: `${catColor}1a`, border: `1px solid ${catColor}`,
                  color: catColor, cursor: 'pointer', transition: 'background 0.12s',
                }}
              >
                ▶ RUN DEMO
              </button>
            </div>
          </div>
        )
      })}

      {!loading && demos.length === 0 && !error && (
        <div style={{ fontSize: 10, color: 'var(--border)', textAlign: 'center', padding: '20px 0' }}>
          No demos loaded — is the backend running?
        </div>
      )}
    </div>
  )
}
