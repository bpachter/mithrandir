# Phase 3 — Agentic Orchestration

**Status: ✅ Complete** (April 13, 2026)

Move Enkidu from a prompt-injection tool pipeline to a true agentic system: one that can reason, plan, call tools, observe results, and self-correct — all triggered from an iPhone via Telegram.

This phase was architected in collaboration with Gemma 4 (Enkidu itself), producing the strategic vision document that drives the build plan below.

---

## The Core Shift

**Phase 2:** User query → keyword detection → inject context → send to LLM → one response.

**Phase 3:** User query → agent reasons about what to do → calls tools → observes results → reasons again → calls more tools if needed → final answer. Multi-step. Self-correcting.

The pattern is **ReAct** (Reason → Act → Observe), introduced in the paper *ReAct: Synergizing Reasoning and Acting in Language Models* (Yao et al., 2022). It's the foundation of most modern agentic frameworks.

---

## Architecture

```
iPhone (Telegram app)
    ↓
Telegram Bot API (webhook or polling)
    ↓
enkidu_agent.py — ReAct loop
    ↓
Thought: what does the agent need to do?
    ↓
Action: choose a tool
    ├── edgar_screener   → EDGAR financials + QV portfolio
    ├── python_sandbox   → execute pandas/numpy/scipy code
    ├── system_info      → GPU/CPU/RAM stats
    ├── web_search       → (future) real-time data
    └── file_read        → local file access
    ↓
Observation: structured tool result (Pydantic-validated)
    ↓
Loop: reason over observation → next action OR final answer
    ↓
Response streamed back to Telegram
```

---

## Components

### 1. Telegram Interface

The chat channel. Replaces the terminal REPL from Phase 2.

- Python SDK: `python-telegram-bot`
- Mode: long-polling (no public server required — works on the home machine)
- Bot responds to messages from authorized users only (your Telegram user ID)
- Streaming: Telegram messages get edited in-place as the response builds (simulates streaming)
- Commands mirrored from Phase 2 REPL: `/local`, `/cloud`, `/stats`, `/refresh`

**Why Telegram over iMessage:** iMessage has no official API and requires a Mac relay server (BlueBubbles/AirMessage). Telegram has a first-class Bot API, works natively on iPhone, and is the standard for self-hosted bots.

Setup:
1. Create a bot via `@BotFather` on Telegram — get a bot token
2. Get your Telegram user ID via `@userinfobot`
3. Add both to `.env`

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ALLOWED_USER_ID=your_numeric_user_id
```

---

### 2. ReAct Agent Loop

The core of Phase 3. Instead of a single LLM call, the agent runs a loop:

```
while not done:
    thought = llm.reason(history + observations)
    if thought.is_final_answer:
        return thought.answer
    action = thought.chosen_tool
    observation = tools[action.name](**action.args)
    history.append((thought, action, observation))
```

The LLM is prompted to output structured JSON at each step:

```json
{
  "thought": "I need to look up NUE's EV/EBIT ratio before I can compare it.",
  "action": "edgar_screener",
  "action_input": {"ticker": "NUE"}
}
```

Or, when done:
```json
{
  "thought": "I have all the data I need.",
  "final_answer": "NUE trades at 6.2x EV/EBIT, ranking in the 8th percentile..."
}
```

---

### 3. Pydantic-Driven Validation

Every tool call and tool result is schema-validated. This is what makes the loop reliable.

```python
class ToolCall(BaseModel):
    thought: str
    action: str | None = None
    action_input: dict | None = None
    final_answer: str | None = None

    @validator("action")
    def action_must_be_known(cls, v):
        if v and v not in REGISTERED_TOOLS:
            raise ValueError(f"Unknown tool: {v}")
        return v
```

When the LLM outputs malformed JSON or an invalid tool name, the `ValidationError` is caught and fed back into the context:

```
"Your last output was invalid: action 'edgar_search' is not a registered tool.
Available tools: edgar_screener, python_sandbox, system_info.
Try again."
```

This **self-correction loop** means the agent doesn't need to be perfect — it gets multiple attempts before escalating to the user.

---

### 4. Python Sandbox

The most important new tool. Solves LLMs' arithmetic weakness by letting the agent write and run Python itself.

```
User: "What's the CAGR of NUE's revenue over the last 5 years?"
Agent thought: "I need to compute CAGR. I'll use the Python sandbox."
Agent action: python_sandbox
Agent input: "import numpy as np; ..."
Agent observation: "CAGR = 12.4%"
```

Implementation: `subprocess` running in a restricted environment (no network, no file writes outside a temp dir). The agent gets stdout/stderr as the observation.

This enables: compound growth calculations, ratio analysis, portfolio statistics, anything requiring actual arithmetic on real numbers.

---

### 5. HMM Regime Detection *(Advanced — later in phase)*

Hidden Markov Models to identify unobservable market regimes from observable signals.

**Observable inputs:** price momentum, volatility, breadth, sector rotation, credit spreads

**Hidden states inferred:** Expansion, Contraction, Crisis, Recovery

**How it plugs into Enkidu:**
- `regime_detector` tool called at session start
- Current regime injected into system prompt: *"Current market regime: Contraction (78% confidence)"*
- QV screening criteria adjust automatically: tighter quality threshold in Crisis, normal thresholds in Expansion

Implementation: `hmmlearn` library, trained on historical market data, retrained quarterly.

---

### 6. RL Strategy Optimization *(Research-grade — end of phase)*

Treat the QV screening process as a reinforcement learning environment.

- **State:** current market regime + macro indicators
- **Action:** screening parameter set (quality threshold, value threshold, number of positions)
- **Reward:** backtested portfolio return over subsequent quarter

An RL agent (PPO or DQN) learns which parameter combinations produce the best risk-adjusted returns in each regime. The result: screening parameters that adapt to market conditions rather than being fixed by human judgment.

Implementation: `stable-baselines3` + custom gym environment wrapping the QV pipeline.

---

## Build Order

| Step | Component | Deliverable |
|------|-----------|-------------|
| 3.1 | Telegram bot skeleton | Messages route to Enkidu; responses come back |
| 3.2 | ReAct loop (basic) | Agent calls one tool per query, returns answer |
| 3.3 | Pydantic validation + self-correction | Agent retries on malformed output |
| 3.4 | Python sandbox tool | Agent can execute pandas/numpy code |
| 3.5 | Multi-step tool chains | Agent calls 2+ tools in sequence |
| 3.6 | Conversation memory | Agent remembers earlier messages in the session |
| 3.7 | HMM regime detection | Regime-aware screening |
| 3.8 | RL strategy optimization | Self-optimizing parameter discovery |

---

## Files (planned)

```
phase3-agents/
├── README.md                    # This file
├── requirements.txt             # python-telegram-bot, pydantic, stable-baselines3, hmmlearn
├── enkidu_agent.py              # ReAct loop — replaces enkidu.py
├── telegram_interface.py        # Bot polling + message routing
├── tools/
│   ├── registry.py              # Tool registration + dispatch
│   ├── python_sandbox.py        # Secure subprocess code execution
│   └── regime_detector.py       # HMM market regime inference
└── rl/
    ├── screening_env.py         # Gym environment wrapping QV pipeline
    └── train_agent.py           # PPO/DQN training loop
```

---

## What Enkidu Will Be Able to Do After Phase 3

```
You (iPhone Telegram): "Compare NUE and CLF on EV/EBIT and FCF yield, 
                        then calculate which is cheaper on a blended basis."

Enkidu: [calls edgar_screener for NUE]
        [calls edgar_screener for CLF]
        [calls python_sandbox to compute blended metric]
        "NUE trades at 6.2x EV/EBIT and 8.1% FCF yield.
         CLF trades at 5.8x EV/EBIT and 6.4% FCF yield.
         On a blended 50/50 basis: CLF scores 0.42, NUE scores 0.38.
         CLF is marginally cheaper. However, NUE's FCF yield advantage
         suggests stronger cash generation..."
```

The LLM provides the reasoning. The tools provide the math. The loop makes it reliable.

---

## Key Papers and References

- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) — Yao et al., 2022
- [Toolformer: Language Models Can Teach Themselves to Use Tools](https://arxiv.org/abs/2302.04761) — Schick et al., 2023
- *Quantitative Value* — Wesley Gray & Tobias Carlisle (QV methodology, Phase 2 basis)
- `hmmlearn` documentation — HMM implementation
- `stable-baselines3` documentation — RL implementation

---

See [JOURNEY.md](../JOURNEY.md) for updates as this phase progresses.
