import { useEffect, useRef, useState } from 'react'
import { ACCENT, Card, INK, MUTED, Note, Page, SURFACE } from '../theme.jsx'

// Customer chat. Each message is posted once with its own Idempotency-Key (a double click or
// a network retry cannot create two tickets), then the page polls the ticket every 2 s until
// it has a final answer. API Gateway HTTP APIs have no WebSockets, so polling it is.
// Every message carries this page's conversation_id, so a follow-up ("and for contractors?")
// is answered with the earlier turns in mind. How-To answers come from the answer cache first,
// then from the approved sources (RAG).
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

// Links in a reply are clickable. The guardrails only let through the link of a guide the reply used.
function Linked({ text }) {
  if (typeof text !== 'string') return text
  return text.split(/(https:\/\/[^\s<>"')\]]+)/g).map((part, i) => (
    /^https:\/\//.test(part)
      ? <a key={i} href={part.replace(/[.,;:!?]+$/, '')} target="_blank" rel="noopener noreferrer" style={{ color: ACCENT }}>{part}</a>
      : part))
}

function Bubble({ who, children, sub }) {
  const mine = who === 'you'
  return (
    <div style={{ display: 'flex', justifyContent: mine ? 'flex-end' : 'flex-start', margin: '8px 0' }}>
      <div style={{ maxWidth: '78%' }}>
        <div dir="auto" style={{
          background: mine ? INK : SURFACE, color: mine ? '#fff' : INK,
          padding: '10px 12px', borderRadius: 12, whiteSpace: 'pre-wrap', lineHeight: 1.4,
        }}><Linked text={children} /></div>
        {sub && <div style={{ fontSize: 12, color: MUTED, marginTop: 3, textAlign: mine ? 'right' : 'left' }}>{sub}</div>}
      </div>
    </div>
  )
}

export default function Chat() {
  const [tenant, setTenant] = useState('C-1001')
  const [text, setText] = useState('')
  const [messages, setMessages] = useState([])     // {text, ticketId}
  const [tickets, setTickets] = useState({})       // ticketId -> ticket view
  const [error, setError] = useState('')
  const sending = useRef(false)
  // One conversation per page visit: the agent reads follow-ups together with earlier turns.
  const [conversationId] = useState(() => crypto.randomUUID())
  const bottom = useRef(null)
  const [feedback, setFeedback] = useState({})   // ticketId -> true once answered

  // "Did this solve it?" goes to the support lead's console (a trust signal next to approvals).
  async function sendFeedback(ticketId, solved) {
    setFeedback((f) => ({ ...f, [ticketId]: true }))
    try {
      await fetch(`/api/tickets/${ticketId}/feedback`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ solved }),
      })
    } catch { /* best effort */ }
  }

  async function send(e, preset) {
    e?.preventDefault()
    const typed = (preset ?? text).trim()
    if (!typed || sending.current) return
    const body = typed
    sending.current = true
    setError('')
    try {
      const r = await fetch('/api/tickets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ tenant_id: tenant, body, channel: 'chat', conversation_id: conversationId }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const { ticket_id } = await r.json()
      setMessages((m) => [...m, { text: typed, ticketId: ticket_id }])
      setTickets((t) => ({ ...t, [ticket_id]: { status: 'received', replies: [] } }))
      setText('')
    } catch (err) {
      setError(`Could not send: ${err.message}`)
    } finally {
      sending.current = false
    }
  }

  useEffect(() => {
    // Keep checking every message of this conversation: a teammate's written steps or an approved
    // answer can arrive after the first reply. Finished tickets are checked every 10 s, open ones every 2 s.
    const ids = Object.keys(tickets)
    if (!ids.length) return
    let tick = 0
    const timer = setInterval(async () => {
      tick += 1
      const open = Object.entries(tickets).filter(([, t]) => !FINAL.has(t.status) || tick % 5 === 0)
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
    <Page narrow={760} title="Customer chat"
      subtitle="What a customer sees. Answers come from approved Payce sources; statutory answers are checked by a specialist first."
      controls={<label>Company <input value={tenant} onChange={(e) => setTenant(e.target.value)} aria-label="Company (tenant id)"
        style={{ width: 100 }} title="C-1001 is India; pick a UAE tenant for WPS questions" /></label>}>
      <Card style={{ minHeight: 320, maxHeight: '60vh', overflowY: 'auto' }}>
        <Bubble who="bot">Hi! I can help with payroll, statutory rules (PF, TDS, WPS, gratuity), payslips and payroll runs.</Bubble>
        {messages.map((m) => {
          const t = tickets[m.ticketId] || { status: 'received', replies: [] }
          const ref = t.ticket_ref || m.ticketId.slice(0, 8)
          return (
            <div key={m.ticketId}>
              <Bubble who="you" sub={`ticket ${ref}`}>{m.text}</Bubble>
              {t.replies.map((r) => (
                <Bubble key={r.draft_version} who="bot"
                  sub={null}>{r.body}</Bubble>
              ))}
              {!t.replies.length && <Bubble who="bot"><i style={{ color: MUTED }}>{STATUS[t.status] || STATUS.running}</i></Bubble>}
              {!!t.replies.length && t.status === 'waiting_review' && <Bubble who="bot"><i>{STATUS.waiting_review}</i></Bubble>}
              {!!t.replies.length && t.status === 'replied' && t.route === 'reply' && (
                <div style={{ fontSize: 13, color: MUTED, margin: '2px 0 10px' }}>
                  {feedback[m.ticketId] ? 'Thanks, noted.' : (
                    <>Did this solve it?{' '}
                      <button className="small" onClick={() => sendFeedback(m.ticketId, true)}>Yes</button>{' '}
                      <button className="small" onClick={() => sendFeedback(m.ticketId, false)}>No</button></>
                  )}
                </div>
              )}
            </div>
          )
        })}
        <div ref={bottom} />
      </Card>

      <form onSubmit={send} style={{ display: 'flex', gap: 8 }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type your message"
          aria-label="Your message" style={{ flex: 1, padding: 10 }} />
        <button type="submit" className="primary" style={{ padding: '10px 18px' }}>Send</button>
      </form>
      <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {EXAMPLES.map((q) => (
          <button key={q} onClick={(e) => send(e, q)} style={{ fontSize: 13, borderRadius: 16, padding: '4px 10px' }}>{q}</button>
        ))}
      </div>
      <div style={{ marginTop: 12 }}><Note tone="bad">{error}</Note></div>
    </Page>
  )
}
