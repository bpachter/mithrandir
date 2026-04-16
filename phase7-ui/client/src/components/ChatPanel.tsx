import { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import { createChatSocket } from '../api'

let chatSocket: WebSocket | null = null
let pendingBotId: string | null = null

// rAF-batched token buffer — accumulates tokens within one animation frame
// then flushes to the store in a single setState call (~60 updates/sec max)
let tokenBuffer = ''
let rafPending  = false

function flushTokenBuffer() {
  rafPending = false
  if (!tokenBuffer || !pendingBotId) { tokenBuffer = ''; return }
  const buf = tokenBuffer
  tokenBuffer = ''
  const id = pendingBotId
  useStore.setState((s) => ({
    messages: s.messages.map((m) =>
      m.id === id ? { ...m, content: (m.content || '') + buf } : m
    ),
  }))
}

function connectSocket() {
  if (chatSocket && chatSocket.readyState <= WebSocket.OPEN) return

  const { setBusy, appendStep } = useStore.getState()

  chatSocket = createChatSocket(
    // onStep
    (step) => {
      if (pendingBotId) appendStep(pendingBotId, step)
    },
    // onToken — batched via requestAnimationFrame
    (tok) => {
      tokenBuffer += tok
      if (!rafPending) {
        rafPending = true
        requestAnimationFrame(flushTokenBuffer)
      }
    },
    // onResponse — used only for Claude tool-use (no tokens streamed)
    (response) => {
      if (pendingBotId) {
        useStore.setState((s) => ({
          messages: s.messages.map((m) =>
            m.id === pendingBotId ? { ...m, content: response } : m
          ),
        }))
      }
    },
    // onDone
    () => {
      // Flush any remaining buffered tokens before marking done
      flushTokenBuffer()
      setBusy(false)
      pendingBotId = null
    },
    // onError
    (err) => {
      flushTokenBuffer()
      if (pendingBotId) {
        useStore.setState((s) => ({
          messages: s.messages.map((m) =>
            m.id === pendingBotId ? { ...m, content: `ERROR: ${err}` } : m
          ),
        }))
      }
      setBusy(false)
      pendingBotId = null
    },
  )
}

export default function ChatPanel() {
  const messages              = useStore((s) => s.messages)
  const busy                  = useStore((s) => s.busy)
  const addMessage            = useStore((s) => s.addMessage)
  const setBusy               = useStore((s) => s.setBusy)
  const clearMessages         = useStore((s) => s.clearMessages)
  const activeConversationId  = useStore((s) => s.activeConversationId)

  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    connectSocket()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function send() {
    const text = input.trim()
    if (!text || busy || !chatSocket) return
    if (chatSocket.readyState !== WebSocket.OPEN) {
      connectSocket()
      return
    }

    const userId = crypto.randomUUID()
    const botId  = crypto.randomUUID()
    pendingBotId = botId

    addMessage({ id: userId, role: 'user', content: text, ts: Date.now() })
    addMessage({ id: botId,  role: 'bot',  content: '',   ts: Date.now() })
    setBusy(true)
    setInput('')

    chatSocket.send(JSON.stringify({
      message: text,
      ...(activeConversationId ? { conversation_id: activeConversationId } : {}),
    }))
  }

  return (
    <div className="panel panel-chat" style={{ flex: 1, minHeight: 0 }}>
      <div className="panel-title" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span>
          CHAT TERMINAL
          {activeConversationId && (
            <span style={{ fontSize: 10, color: 'var(--cyan)', marginLeft: 8 }}>· CONTINUATION</span>
          )}
        </span>
        {messages.length > 0 && (
          <button
            onClick={() => clearMessages()}
            style={{
              background: 'none', border: '1px solid var(--border)', color: 'var(--white-dim)',
              fontFamily: 'var(--font-mono)', fontSize: 10, padding: '2px 8px', cursor: 'pointer',
              letterSpacing: '0.08em',
            }}
          >
            NEW
          </button>
        )}
      </div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="dim" style={{ alignSelf: 'center', marginTop: 40, textAlign: 'center', lineHeight: 2 }}>
            <div style={{ fontSize: 32, fontFamily: 'var(--font-display)', color: 'var(--amber)', opacity: 0.3 }}>
              ENKIDU ONLINE
            </div>
            <div style={{ fontSize: 11, opacity: 0.4 }}>AWAITING INPUT_</div>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            <span className="msg-label">
              {m.role === 'user' ? 'YOU' : 'ENKIDU'} ·{' '}
              {new Date(m.ts).toLocaleTimeString('en-US', { hour12: false })}
            </span>

            {m.steps && m.steps.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 4 }}>
                {m.steps.map((s, i) => (
                  <span key={i} className="msg-step">⟩ {s}</span>
                ))}
              </div>
            )}

            <div className="msg-bubble">
              {m.content || (m.role === 'bot' && busy && pendingBotId === m.id
                ? <span className="msg-typing">···</span>
                : m.content
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-row">
        <span className="chat-prefix">&gt;_</span>
        <input
          className="chat-input"
          placeholder="enter query..."
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
    </div>
  )
}
