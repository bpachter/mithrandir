import { useEffect } from 'react'
import { useStore } from '../store'
import { fetchHistory, fetchHistoryItem } from '../api'

export default function HistoryPanel() {
  const history       = useStore((s) => s.history)
  const activeId      = useStore((s) => s.activeConversationId)
  const setHistory    = useStore((s) => s.setHistory)
  const addMessage    = useStore((s) => s.addMessage)
  const clearMessages = useStore((s) => s.clearMessages)
  const setActiveId   = useStore((s) => s.setActiveConversationId)

  useEffect(() => {
    fetchHistory().then(setHistory).catch(() => {})
  }, [])

  async function handleSelect(id: string, timestamp: string) {
    try {
      const full = await fetchHistoryItem(id)
      clearMessages()
      addMessage({
        id:      `hist-user-${id}`,
        role:    'user',
        content: full.user,
        ts:      new Date(timestamp).getTime(),
      })
      addMessage({
        id:      `hist-bot-${id}`,
        role:    'bot',
        content: full.assistant,
        ts:      new Date(timestamp).getTime() + 1,
      })
      setActiveId(id)
    } catch {
      // silently ignore fetch errors
    }
  }

  return (
    <div className="panel panel-bottom" style={{ minHeight: 0 }}>
      <div className="panel-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        CONVERSATION HISTORY
        {activeId && (
          <span style={{ fontSize: 10, color: 'var(--cyan)', marginLeft: 4 }}>
            · CONTINUING
          </span>
        )}
      </div>
      <div className="history-list">
        {history.length === 0 ? (
          <div className="dim" style={{ fontSize: 11, padding: '8px 0' }}>no history found</div>
        ) : (
          history.map((h) => (
            <div
              key={h.id}
              className={`history-item ${activeId === h.id ? 'active' : ''}`}
              onClick={() => handleSelect(h.id, h.timestamp)}
              title="Click to continue this conversation"
            >
              <div className="history-header">
                <span className="dim" style={{ fontSize: 10 }}>
                  {new Date(h.timestamp).toLocaleString('en-US', {
                    month: '2-digit', day: '2-digit',
                    hour: '2-digit', minute: '2-digit', hour12: false,
                  })}
                  {activeId === h.id && (
                    <span style={{ color: 'var(--cyan)', marginLeft: 6 }}>▶ active</span>
                  )}
                </span>
                <span className="history-preview">{h.user}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
