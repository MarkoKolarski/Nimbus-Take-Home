import { type KeyboardEvent, useState } from 'react'
import { ApiError, postChatMessage, type Citation } from '../api'

interface Message {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSend() {
    const text = input.trim()
    if (!text || sending) return
    setError(null)
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setSending(true)
    try {
      const reply = await postChatMessage(text)
      setMessages((prev) => [...prev, { role: 'assistant', content: reply.answer, citations: reply.citations }])
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : 'chat request failed')
    } finally {
      setSending(false)
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') void handleSend()
  }

  return (
    <div className="panel chat">
      <h2>Chat</h2>
      <div className="messages">
        {messages.length === 0 && <p className="empty">Ask a question about your indexed documents.</p>}
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.role}`}>
            <div className="content">{m.content}</div>
            {m.citations && m.citations.length > 0 && (
              <ul className="citations">
                {m.citations.map((c) => (
                  <li key={c.number}>
                    [{c.number}] {c.filenames.join(', ')}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      {error && <div className="error">{error}</div>}
      <div className="chat-input">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about your documents…"
          disabled={sending}
        />
        <button onClick={handleSend} disabled={sending || !input.trim()}>
          {sending ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  )
}
