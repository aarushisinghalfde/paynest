import { useEffect, useState } from 'react'

// Reviewer console (minimal): tickets the router sent to review (statutory, P1, known issue)
// wait here. Approve sends the (optionally edited) reply to the customer's chat.
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
    setMsg(r.ok ? `${decision === 'approve' ? 'Approved and sent' : 'Rejected'}: ticket ${task.ticket_id.slice(0, 8)}` : `HTTP ${r.status}`)
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
          <div style={{ fontSize: 13, color: '#8a5a00' }}>Why here: {t.route_reason}</div>
          <p><b>Customer (masked):</b> {t.body}</p>
          <textarea rows={4} style={{ width: '100%' }} value={edits[t.id] ?? t.draft}
            onChange={(e) => setEdits({ ...edits, [t.id]: e.target.value })} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button onClick={() => decide(t, 'approve')}>Approve and send</button>
            <button onClick={() => decide(t, 'reject')}>Reject and take over</button>
          </div>
        </div>
      ))}
    </main>
  )
}
