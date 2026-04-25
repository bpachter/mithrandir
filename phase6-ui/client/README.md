# Mithrandir UI — React Client

![Mithrandir UI hero shot](../../assets/phase6-ui-hero.png)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 6 / 7” -->

> **Plain English:** Open WebUI (from Phase 1) is great but generic. This phase replaces it with a custom dashboard styled like a Blade Runner terminal — chat on the left, live GPU/VRAM/temperature graphs on the right, market data, voice mic with a real-time waveform, and a memory viewer. Everything in one screen, all driven by the same local Gemma.

Custom Blade Runner terminal dashboard for the Mithrandir AI assistant. Replaces Open WebUI with a purpose-built interface.

## Tech Stack

- **React 18** + **Vite** + **TypeScript**
- **Recharts** — GPU/system sparkline history charts
- **Zustand** — global state (chat messages, GPU history ring buffer, model params, memory)
- **Web Audio API** — microphone capture, VAD, waveform visualization

## Dev Setup

```bash
npm install
npm run dev      # http://localhost:5173 (proxies /api and /ws to :8000)
```

Requires the FastAPI backend running: `python phase6-ui/server/main.py`

## Production Build

```bash
npm run build    # outputs to dist/
```

FastAPI serves `dist/` as a static SPA at `http://localhost:8000`.

## Layout

3-column CSS Grid:

```
┌──────────────────────────────────────────────────────────────────┐
│  MITHRANDIR  v8.0   VRAM 72%   62°C   285W        2026.04.16  ONLINE │
├──────────────┬───────────────────────────┬───────────────────────┤
│ VOICE        │ CHAT TERMINAL             │ MARKET                │
│ TERMINAL     │                           │ regime + QV picks     │
│              │ streaming responses       ├───────────────────────┤
│ mic button   │ with model indicator      │ PARAMS / MEMORY tabs  │
│ waveform     │                           ├───────────────────────┤
│ VAD toggles  ├───────────────────────────┤ ▸ GPU DETAIL          │
│              │ HISTORY (180px)           │   sparklines          │
├──────────────┴───────────────────────────┴───────────────────────┤
│  SYS: VRAM ████ 72%  GPU 68% 62°C  CPU 31%  RAM 55%             │
└──────────────────────────────────────────────────────────────────┘
```

## Components

| Component | Description |
|-----------|-------------|
| `App.tsx` | Layout shell; owns GPU WebSocket (always connected) |
| `ChatPanel.tsx` | Message thread; streaming tokens via `/ws/chat` |
| `VoicePanel.tsx` | Push-to-talk + VAD + frequency waveform + auto-conversation loop |
| `SystemMiniPanel.tsx` | Compact 112px strip — VRAM, GPU temp, CPU, RAM |
| `GpuHistoryPanel.tsx` | 6 iCUE-style sparklines: GPU util, VRAM, temp, power, CPU, RAM |
| `MarketPanel.tsx` | HMM regime badge + QV portfolio top picks |
| `ModelParamsPanel.tsx` | Gemma parameter sliders (temp, top_p, top_k, etc.) |
| `MemoryPanel.tsx` | Past conversation memory viewer |
| `HistoryPanel.tsx` | Session conversation history |
| `Header.tsx` | Title bar with live GPU stats inline |

![Streaming response + GPU sparklines](../../assets/phase6-streaming.gif)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 6 / 7” -->

## Voice System (Phase 7)

![Voice round-trip demo](../../assets/phase7-voice-roundtrip.mp4)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 6 / 7” — mp4 won’t inline-render on GitHub; falls back to a download link, which is fine -->

VoicePanel connects to `/ws/voice` which runs:

1. **Whisper STT** (faster-whisper `small.en`, CUDA float16) — first use auto-downloads ~244 MB
2. **Mithrandir agent** (`run_agent()`) — Gemma/Claude routing, tool use, streaming tokens
3. **edge-tts TTS** (`en-US-BrianNeural`) — MP3 streamed back and played

VAD toggles:
- **VAD** — auto-stop recording on 900ms of silence (no click needed to send)
- **SPEAK** — auto-play TTS response
- **LOOP** — after speaking, automatically start listening again (hands-free conversation)

## Design System

All colors are CSS variables in `index.css`:

```css
--bg-base:    #07080d   /* near-black background */
--amber:      #ff9500   /* primary text + UI */
--cyan:       #00e5ff   /* active / selected states */
--red:        #ff1a40   /* alerts + recording state */
--green:      #39d353   /* success + speaking state */
--white-dim:  #8899aa   /* secondary text */
```

Aesthetic: Blade Runner (1982) terminal — phosphor glow, CRT scanline overlay, monospace throughout.
