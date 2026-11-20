import { useEffect, useRef, useState } from 'react'
import ApiStatus from '../ApiStatus.jsx'

// Customer chat. Each message is posted once with its own Idempotency-Key (a double click or
// a network retry cannot create two tickets), then the page polls the ticket every 2 s for
// replies. (API Gateway HTTP APIs have no WebSockets; polling works through it today.)
const POLL_MS = 2000

export default function Chat() {
  const [tenant, setTenant] = useState('C-1001')
  const [text, setText] = useState('')
  const [messages, setMessages] = useState([])     // {who, text, ticketId?}
  const [tickets, setTickets] = useState({})       // ticketId -> {status, replies}
  const [error, setError] = useState('')
  const sending = useRef(false)

  async function send(e) {
    e.preventDefault()
    if (!text.trim() || sending.current) return
    sending.current = true
    setError('')
    try {
      const r = await fetch('/api/tickets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ tenant_id: tenant, body: text, channel: 'chat' }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const { ticket_id } = await r.json()
      setMessages((m) => [...m, { who: 'you', text, ticketId: ticket_id }])
      setTickets((t) => ({ ...t, [ticket_id]: { status: 'received', replies: [] } }))
      setText('')
    } catch (err) {
      setError(`Could not send: ${err.message}`)
    } finally {
      sending.current = false
    }
  }

  useEffect(() => {
    const open = Object.entries(tickets).filter(([, t]) => t.status !== 'replied')
    if (!open.length) return
    const timer = setInterval(async () => {
      for (const [id] of open) {
        const r = await fetch(`/api/tickets/${id}`)
        if (!r.ok) continue
        const t = await r.json()
        setTickets((all) => ({ ...all, [id]: { status: t.agent_status || t.status, replies: t.replies || [] } }))
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [tickets])

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24, maxWidth: 720 }}>
      <h1>Customer chat</h1>
      <label>
        Company (tenant){' '}
        <input value={tenant} onChange={(e) => setTenant(e.target.value)} style={{ width: 120 }} />
      </label>
      <div style={{ border: '1px solid #ccc', borderRadius: 8, padding: 12, margin: '12px 0', minHeight: 200 }}>
        {messages.map((m) => (
          <div key={m.ticketId} style={{ marginBottom: 12 }}>
            <div><b>You:</b> {m.text}</div>
            <div style={{ color: '#555', fontSize: 13 }}>
              Ticket {m.ticketId.slice(0, 8)} · {tickets[m.ticketId]?.status || 'received'}
            </div>
            {(tickets[m.ticketId]?.replies || []).map((r) => (
              <div key={r.draft_version} style={{ background: '#eef6f2', padding: 8, borderRadius: 6, marginTop: 4 }}>
                <b>Payce Support:</b> {r.body}
              </div>
            ))}
          </div>
        ))}
        {!messages.length && <p style={{ color: '#777' }}>Ask a payroll question to start.</p>}
      </div>
      <form onSubmit={send} style={{ display: 'flex', gap: 8 }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type your message"
          style={{ flex: 1, padding: 8 }} />
        <button type="submit">Send</button>
      </form>
      {error && <p style={{ color: 'crimson' }}>{error}</p>}
      <ApiStatus />
    </main>
  )
}
