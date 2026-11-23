import { useEffect, useState } from 'react'
import { BAD, Card, INK, MUTED, Note, Page, SURFACE, WARN_TEXT } from '../theme.jsx'

// Reviewer console. Two kinds of task:
//  - reply: a draft the router sent to review (statutory, P1, known issue, failed guard). Approve sends
//    the (optionally edited) reply to the customer's chat.
//  - knowledge: a How-To question the agent could only answer with a guide. Write the steps once:
//    the customer receives them, and every similar question is answered automatically from then on.
export default function Review() {
  const [token, setToken] = useState(sessionStorage.getItem('adminToken') || '')
  const [tasks, setTasks] = useState([])
  const [edits, setEdits] = useState({})
  const [msg, setMsg] = useState('')
  const [why, setWhy] = useState({})   // ticket_id -> console detail (English + decision record)

  // The same timeline the support lead sees: English for Arabic/Hindi, confidence, rule, sources.
  async function explain(ticketId) {
    setWhy((w) => ({ ...w, [ticketId]: 'loading' }))
    const r = await fetch(`/api/console/tickets/${ticketId}`, { headers: { 'X-Admin-Token': token } })
    setWhy((w) => ({ ...w, [ticketId]: r.ok ? null : `HTTP ${r.status}` }))
    if (r.ok) { const d = await r.json(); setWhy((w) => ({ ...w, [ticketId]: d })) }
  }

  async function load() {
    if (!token) return
    const r = await fetch('/api/review/tasks', { headers: { 'X-Admin-Token': token } })
    if (!r.ok) {
      setMsg(r.status === 401
        ? 'This token cannot review. Use the admin token or a named reviewer token (the support lead token is read-only: it opens the control room).'
        : `Cannot load tasks: HTTP ${r.status}`)
      return
    }
    setMsg('')
    setTasks(await r.json())
  }

  async function decide(task, decision) {
    const r = await fetch(`/api/review/tasks/${encodeURIComponent(task.id)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Admin-Token': token },
      body: JSON.stringify({ decision, body: edits[task.id] ?? task.draft, reviewer: 'reviewer' }),
    })
    const done = task.kind === 'knowledge' ? 'Saved to the How-To library and sent' : 'Approved and sent'
    setMsg(r.ok ? `${decision === 'approve' ? done : 'Rejected'}: ticket ${task.ticket_id.slice(0, 8)}` : `HTTP ${r.status}`)
    load()
  }

  useEffect(() => {
    sessionStorage.setItem('adminToken', token)
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [token])

  const ok = msg.startsWith('Approved') || msg.startsWith('Saved') || msg.startsWith('Rejected')
  return (
    <Page title="Review" subtitle="Answers waiting for a person: approve, edit or take over. Knowledge tasks: write the steps once and every similar question is answered automatically."
      controls={<input type="password" placeholder="Reviewer or admin token" aria-label="Reviewer or admin token" value={token}
        onChange={(e) => setToken(e.target.value)} style={{ width: 210 }} />}>
      <Note tone={ok ? 'ok' : 'bad'}>{msg}</Note>
      {!token && <Note>Enter a reviewer or admin token to see the tickets waiting for you.</Note>}
      {!tasks.length && token && !msg && <Card><span style={{ color: MUTED }}>Nothing is waiting for review.</span></Card>}
      {tasks.map((t) => (
        <Card key={t.id} style={{ borderLeft: `3px solid ${t.kind === 'knowledge' ? '#1baf7a' : '#eda100'}` }}>
          <div style={{ fontSize: 13, color: MUTED }}>
            Ticket {t.ticket_id.slice(0, 8)}, {t.tenant_id}, {t.team || 'no team'}, {LANG[t.language] || t.language}
            {t.kind === 'knowledge' && <b style={{ color: INK }}>. Knowledge task: write the steps once</b>}
          </div>
          <div style={{ fontSize: 13, color: WARN_TEXT, marginTop: 4 }}>Why it is here: {t.route_reason}</div>
          <p dir="auto" style={{ fontSize: 15 }}>{t.body}</p>
          <button className="small" onClick={() => explain(t.ticket_id)}>
            {t.language && t.language !== 'en' ? 'Show English and why' : 'Show why'}
          </button>
          <Why d={why[t.ticket_id]} />
          <textarea rows={t.kind === 'knowledge' ? 6 : 4} style={{ width: '100%', marginTop: 8 }} value={edits[t.id] ?? t.draft} dir="auto"
            placeholder={t.kind === 'knowledge' ? 'Write the exact steps the customer should follow (no personal data)' : ''}
            onChange={(e) => setEdits({ ...edits, [t.id]: e.target.value })} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="primary" onClick={() => decide(t, 'approve')}
              disabled={t.kind === 'knowledge' && !(edits[t.id] || '').trim()}>
              {t.kind === 'knowledge' ? 'Save answer and send' : 'Approve and send'}
            </button>
            <button onClick={() => decide(t, 'reject')}>{t.kind === 'knowledge' ? 'Not needed' : 'Reject and take over'}</button>
          </div>
        </Card>
      ))}
    </Page>
  )
}

const LANG = { en: 'English', ar: 'Arabic', hi: 'Hindi', 'hi-Latn': 'Hinglish' }

function Why({ d }) {
  if (!d) return null
  if (typeof d === 'string') return <p style={{ fontSize: 13, color: MUTED }}>{d === 'loading' ? 'Loading…' : d}</p>
  const c = d.decision?.classification || {}
  const a = d.decision?.answer || {}
  const q = d.translation?.question
  return (
    <div style={{ background: SURFACE, borderRadius: 6, padding: 8, margin: '6px 0', fontSize: 13 }}>
      {q?.ok && <div><b>English (machine translation):</b> {q.english}</div>}
      {q && !q.ok && q.reason !== 'already English' && <div style={{ color: WARN_TEXT }}>{q.reason}</div>}
      <div>Category {c.team || '–'}, confidence {c.confidence ?? '–'}, rule {d.decision?.route?.rule || d.route_rule}</div>
      {!!a.sources?.length && <div>Sources: {a.sources.slice(0, 3).map((h) => h.title || h.id).join('; ')}</div>}
      {!!a.facts?.length && <div>Facts: {a.facts.map((f) => `${f.tool} = ${f.result}`).join('; ')}</div>}
      {d.decision?.guard && !d.decision.guard.ok && <div style={{ color: BAD }}>Checks failed: {d.decision.guard.failed.join(', ')}</div>}
    </div>
  )
}
