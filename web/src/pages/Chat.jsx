import { useEffect, useRef, useState } from 'react'
import ApiStatus from '../ApiStatus.jsx'

// Customer chat. Each message is posted once with its own Idempotency-Key (a double click or
// a network retry cannot create two tickets), then the page polls the ticket every 2 s until
// it has a final answer. API Gateway HTTP APIs have no WebSockets, so polling it is.
// Follow-ups are new messages in the same conversation; the agent links repeats itself.
const POLL_MS = 2000
const FINAL = new Set(['replied', 'taken_over', 'failed', 'pii_blocked'])

const STATUS = {
  received: 'Received, checking your message…',
  masked: 'Personal details hidden, reading your question…',
  running: 'Finding the answer…',
  waiting_review: 'A payroll specialist is checking the answer before it is sent.',
  taken_over: 'A specialist has taken this over and will reply to you directly.',
  failed: 'We could not answer automatically; a specialist will reply.',
  pii_blocked: 'Your message contained sensitive details we could not process safely; a specialist will reply.',
}

const EXAMPLES = [
  'What is the PF wage ceiling for September payroll?',
  'What was the PF wage ceiling for July 2026?',
  'How do I add a new employee?',
  'What is the status of payroll run PR-202609?',
]

function Bubble({ who, children, sub }) {
  const mine = who === 'you'
  return (
    <div style={{ display: 'flex', justifyContent: mine ? 'flex-end' : 'flex-start', margin: '8px 0' }}>
      <div style={{ maxWidth: '78%' }}>
        <div dir="auto" style={{
          background: mine ? '#1f5f8b' : '#eef3f1', color: mine ? '#fff' : '#1b1b1b',
          padding: '10px 12px', borderRadius: 12, whiteSpace: 'pre-wrap', lineHeight: 1.4,
        }}>{children}</div>
        {sub && <div style={{ fontSize: 12, color: '#6b6b6b', marginTop: 3, textAlign: mine ? 'right' : 'left' }}>{sub}</div>}
      </div>
    </div>
  )
}

export default function Chat() {
  const [tenant, setTenant] = useState('C-1001')
  const [text, setText] = useState('')
  const [messages, setMessages] = useState([])     // {text (as typed), body (as sent), ticketId}
  const [tickets, setTickets] = useState({})       // ticketId -> ticket view
  const [error, setError] = useState('')
  const sending = useRef(false)
  const bottom = useRef(null)

  async function send(e, preset) {
    e?.preventDefault()
    const typed = (preset ?? text).trim()
    if (!typed || sending.current) return
    // After a clarifying question, send the answer together with the first message,
    // so the agent reads the whole request.
    const last = messages[messages.length - 1]
    const body = last && tickets[last.ticketId]?.route === 'ask' ? `${last.body}\n${typed}` : typed
    sending.current = true
    setError('')
    try {
      const r = await fetch('/api/tickets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ tenant_id: tenant, body, channel: 'chat' }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const { ticket_id } = await r.json()
      setMessages((m) => [...m, { text: typed, body, ticketId: ticket_id }])
      setTickets((t) => ({ ...t, [ticket_id]: { status: 'received', replies: [] } }))
      setText('')
    } catch (err) {
      setError(`Could not send: ${err.message}`)
    } finally {
      sending.current = false
    }
  }

  useEffect(() => {
    const open = Object.entries(tickets).filter(([, t]) => !FINAL.has(t.status))
    if (!open.length) return
    const timer = setInterval(async () => {
      for (const [id] of open) {
        try {
          const r = await fetch(`/api/tickets/${id}`)
          if (!r.ok) continue
          const t = await r.json()
          const status = t.status === 'pii_blocked' ? 'pii_blocked' : t.agent_status || (t.status === 'masked' ? 'running' : t.status)
          setTickets((all) => ({ ...all, [id]: { ...t, status, replies: t.replies || [] } }))
        } catch { /* keep polling */ }
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [tickets])

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, tickets])

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24, maxWidth: 760, margin: '0 auto' }}>
      <h1 style={{ marginBottom: 4 }}>Payce Support</h1>
      <p style={{ color: '#555', marginTop: 0 }}>
        Ask a payroll question. Answers come from approved Payce sources; statutory answers are checked by a specialist first.
      </p>
      <label style={{ fontSize: 14 }}>
        Company (tenant id){' '}
        <input value={tenant} onChange={(e) => setTenant(e.target.value)} style={{ width: 110 }} />
        <span style={{ color: '#777' }}> e.g. C-1001 (India) · pick a UAE tenant for WPS questions</span>
      </label>

      <div style={{ border: '1px solid #d7dcdb', borderRadius: 12, padding: 14, margin: '12px 0', minHeight: 320,
        maxHeight: '60vh', overflowY: 'auto', background: '#fbfcfc' }}>
        <Bubble who="bot">Hi! I can help with payroll, statutory rules (PF, TDS, WPS, gratuity), payslips and payroll runs.</Bubble>
        {messages.map((m) => {
          const t = tickets[m.ticketId] || { status: 'received', replies: [] }
          const ref = t.ticket_ref || m.ticketId.slice(0, 8)
          return (
            <div key={m.ticketId}>
              <Bubble who="you" sub={`ticket ${ref}`}>{m.text}</Bubble>
              {t.replies.map((r) => (
                <Bubble key={r.draft_version} who="bot"
                  sub={[t.team && `team ${t.team}`, t.route_reason].filter(Boolean).join(' · ')}>{r.body}</Bubble>
              ))}
              {!t.replies.length && <Bubble who="bot"><i style={{ color: '#555' }}>{STATUS[t.status] || STATUS.running}</i></Bubble>}
              {!!t.replies.length && t.status === 'waiting_review' && <Bubble who="bot"><i>{STATUS.waiting_review}</i></Bubble>}
            </div>
          )
        })}
        <div ref={bottom} />
      </div>

      <form onSubmit={send} style={{ display: 'flex', gap: 8 }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type your message"
          style={{ flex: 1, padding: 10, borderRadius: 8, border: '1px solid #c8cfcd' }} />
        <button type="submit" style={{ padding: '10px 18px' }}>Send</button>
      </form>
      <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {EXAMPLES.map((q) => (
          <button key={q} onClick={(e) => send(e, q)} style={{ fontSize: 13, borderRadius: 16, padding: '4px 10px',
            border: '1px solid #c8cfcd', background: '#fff', cursor: 'pointer' }}>{q}</button>
        ))}
      </div>
      {error && <p style={{ color: 'crimson' }}>{error}</p>}
      <ApiStatus />
    </main>
  )
}
