import { useEffect, useState } from 'react'

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

  async function load() {
    if (!token) return
    const r = await fetch('/api/review/tasks', { headers: { 'X-Admin-Token': token } })
    if (!r.ok) { setMsg(`Cannot load tasks: HTTP ${r.status}`); return }
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

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24, maxWidth: 900 }}>
      <h1>Reviewer console</h1>
      <label>Admin token <input type="password" value={token} onChange={(e) => setToken(e.target.value)} /></label>
      {msg && <p>{msg}</p>}
      {!tasks.length && token && <p style={{ color: '#777' }}>No tickets waiting for review.</p>}
      {tasks.map((t) => (
        <div key={t.id} style={{ border: '1px solid #ccc', borderRadius: 8, padding: 12, margin: '12px 0' }}>
          <div style={{ fontSize: 13, color: '#555' }}>
            Ticket {t.ticket_id.slice(0, 8)} · tenant {t.tenant_id} · team {t.team || '?'} · {t.language}
          </div>
          {t.kind === 'knowledge' && (
            <div style={{ display: 'inline-block', background: '#e7f3ef', color: '#0e5e5d', borderRadius: 12,
              padding: '2px 10px', fontSize: 12, margin: '6px 0' }}>Knowledge: write the answer once, reused automatically</div>
          )}
          <div style={{ fontSize: 13, color: '#8a5a00' }}>Why here: {t.route_reason}</div>
          <p><b>Customer (masked):</b> {t.body}</p>
          <textarea rows={t.kind === 'knowledge' ? 6 : 4} style={{ width: '100%' }} value={edits[t.id] ?? t.draft}
            placeholder={t.kind === 'knowledge' ? 'Write the exact steps the customer should follow (no personal data)…' : ''}
            onChange={(e) => setEdits({ ...edits, [t.id]: e.target.value })} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button onClick={() => decide(t, 'approve')}
              disabled={t.kind === 'knowledge' && !(edits[t.id] || '').trim()}>
              {t.kind === 'knowledge' ? 'Save answer and send' : 'Approve and send'}
            </button>
            <button onClick={() => decide(t, 'reject')}>{t.kind === 'knowledge' ? 'Not needed' : 'Reject and take over'}</button>
          </div>
        </div>
      ))}
    </main>
  )
}
