import { useEffect } from 'react'
import { useStore } from '../store'
import { fetchParams, saveParams } from '../api'
import { useState } from 'react'

// ── Per-parameter documentation ───────────────────────────────────────────
// Each entry maps to a slider. desc is shown on hover below the slider.

const PARAM_META: Record<string, { label: string; min: number; max: number; step: number; desc: string; format?: 'int' | 'float2' | 'float1' }> = {
  temperature: {
    label: 'TEMPERATURE',
    min: 0, max: 2, step: 0.05,
    format: 'float2',
    desc: 'Controls randomness. 0 = fully deterministic (same output every time). Higher values increase creativity and variation but reduce factual precision. Sweet spot for balanced chat: 0.6–0.9.',
  },
  top_p: {
    label: 'TOP-P  (nucleus)',
    min: 0, max: 1, step: 0.05,
    format: 'float2',
    desc: 'Nucleus sampling: only consider tokens whose cumulative probability sums to ≤ p. Lower = more focused; 1.0 = all tokens considered. Works alongside temperature — lower both for more conservative output.',
  },
  top_k: {
    label: 'TOP-K',
    min: 1, max: 200, step: 1,
    format: 'int',
    desc: 'Limit sampling pool to the K most likely next tokens. Lower = more conservative and predictable. 40 is a common default. 0 = disabled (use only top-p). Combine with top-p for fine control.',
  },
  min_p: {
    label: 'MIN-P',
    min: 0, max: 0.2, step: 0.01,
    format: 'float2',
    desc: 'Minimum probability filter relative to the top token. Tokens with probability < min_p × P(top) are discarded. More aggressive than top-k at cutting improbable noise. 0 = disabled; 0.05–0.1 = recommended.',
  },
  repeat_penalty: {
    label: 'REPEAT PEN.',
    min: 1, max: 2, step: 0.05,
    format: 'float2',
    desc: 'Penalises recently-generated tokens to reduce repetition. 1.0 = no penalty. 1.1–1.3 = good range for chat. Too high (>1.5) causes incoherent output as the model avoids useful words.',
  },
  num_ctx: {
    label: 'CONTEXT (tokens)',
    min: 2048, max: 131072, step: 2048,
    format: 'int',
    desc: 'Context window size in tokens (~¾ of a word each). Gemma 4 supports up to 128K. Larger = remembers more of the conversation but uses more VRAM and is slower. 8192 covers ~6K words.',
  },
  num_predict: {
    label: 'MAX OUTPUT',
    min: 256, max: 8192, step: 256,
    format: 'int',
    desc: 'Maximum tokens to generate per response. Higher = longer replies allowed but slower worst-case. 2048 ≈ 1500 words. Use 4096+ for detailed analysis. Does not guarantee long output — model stops when done.',
  },
  seed: {
    label: 'SEED',
    min: -1, max: 9999, step: 1,
    format: 'int',
    desc: 'Random seed for reproducibility. -1 = new random seed each time (default). Set a specific value to get identical output for identical inputs — useful for debugging or consistent demos.',
  },
}

// ── Slider row ─────────────────────────────────────────────────────────────

interface SliderRowProps {
  paramKey: string
  value: number
  onChange: (v: number) => void
}

function SliderRow({ paramKey, value, onChange }: SliderRowProps) {
  const meta = PARAM_META[paramKey]
  if (!meta) return null
  const { label, min, max, step, desc, format } = meta

  const display = format === 'int'    ? Math.round(value).toString()
                : format === 'float1' ? value.toFixed(1)
                : value.toFixed(2)

  return (
    <div className="param-row-wrap">
      <div className="param-row">
        <span className="param-label">{label}</span>
        <input
          type="range"
          className="param-slider"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
        />
        <span className="param-value">{display}</span>
      </div>
      <div className="param-desc">{desc}</div>
    </div>
  )
}

// ── Panel ──────────────────────────────────────────────────────────────────

export default function ModelParamsPanel() {
  const params    = useStore((s) => s.params)
  const setParams = useStore((s) => s.setParams)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetchParams().then((p) => setParams(p)).catch(() => {})
  }, [])

  async function handleSave() {
    await saveParams(params)
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  const keys: Array<keyof typeof params> = [
    'temperature', 'top_p', 'top_k', 'min_p',
    'repeat_penalty', 'num_ctx', 'num_predict', 'seed',
  ]

  return (
    <div className="panel" style={{ minHeight: 0, overflow: 'auto' }}>
      <div className="panel-title">MODEL PARAMS</div>
      <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>

        <div style={{ fontSize: 9, color: 'var(--white-dim)', marginBottom: 4, lineHeight: 1.5 }}>
          Hover any row to see what each parameter does.
          Parameters are forwarded directly to Gemma 4 via Ollama.
        </div>

        {keys.map((k) => (
          <SliderRow
            key={k}
            paramKey={k}
            value={params[k]}
            onChange={(v) => setParams({ [k]: v })}
          />
        ))}

        <button
          className="save-btn"
          onClick={handleSave}
          style={{ marginTop: 8 }}
        >
          {saved ? 'SAVED ✓' : 'SAVE PARAMS'}
        </button>
      </div>
    </div>
  )
}
