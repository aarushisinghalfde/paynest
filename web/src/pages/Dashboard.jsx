import { useEffect, useState } from 'react'

// Operations dashboard (admin token). What the agent did, from masked data only:
// classification (teams, confidence, which layer decided), merges (duplicates, incidents,
// Jira) and resolution (approved answers, cache, RAG, review, learning loop).
// "Q3 history" shows the client's export for comparison (customer pick vs final label).
const INK = '#16262E'
const MUTED = '#5f6f73'
const BAR = '#0E7C7B'
const SURFACE = '#F4F8F7'

function Tile({ value, label, sub }) {
  return (
    <div style={{ background: SURFACE, borderRadius: 10, padding: '12px 14px', minWidth: 150, flex: '1 1 150px' }}>
      <div style={{ fontSize: 28, fontWeight: 700, color: INK }}>{value ?? '–'}</div>
      <div style={{ fontSize: 13, color: INK }}>{label}</div>
      {sub && <div style={{ fontSize: 12, color: MUTED, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

// One series, one hue: horizontal bars sorted by size, value labels in text ink.
function Bars({ title, rows, unit = 'tickets' }) {
  if (!rows?.length) return null
  const max = Math.max(...rows.map((r) => r.n), 1)
  return (
    <section style={{ flex: '1 1 300px', minWidth: 280 }}>
      <h3 style={{ fontSize: 15, margin: '6px 0 8px', color: INK }}>{title}</h3>
      {rows.map((r) => (
        <div key={String(r.key)} title={`${r.key}: ${r.n} ${unit}`}
          style={{ display: 'grid', gridTemplateColumns: '140px 1fr 44px', alignItems: 'center', gap: 8, margin: '4px 0' }}>
          <span style={{ fontSize: 13, color: INK, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{String(r.key)}</span>
          <div style={{ height: 14, background: '#e6eeec', borderRadius: 4 }}>
            <div style={{ width: `${(100 * r.n) / max}%`, height: '100%', background: BAR, borderRadius: 4, minWidth: 2 }} />
          </div>
          <span style={{ fontSize: 13, color: MUTED, textAlign: 'right' }}>{r.n}</span>
        </div>
      ))}
    </section>
  )
}

function Table({ title, cols, rows }) {
  if (!rows?.length) return null
  return (
    <section style={{ marginTop: 18 }}>
      <h3 style={{ fontSize: 15, margin: '6px 0 8px', color: INK }}>{title}</h3>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
          <thead>
            <tr>{cols.map(([k, label]) => <th key={k} style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid #cfdcd9', color: MUTED }}>{label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>{cols.map(([k]) => <td key={k} dir="auto" style={{ padding: '6px 8px', borderBottom: '1px solid #edf2f1', color: INK, verticalAlign: 'top' }}>{r[k] ?? '–'}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

const pct = (x) => (x == null ? '–' : `${Math.round(100 * x)}%`)

export default function Dashboard() {
  const [token, setToken] = useState(sessionStorage.getItem('adminToken') || '')
  const [scope, setScope] = useState('live')
  const [days, setDays] = useState(7)
  const [d, setD] = useState(null)
  const [msg, setMsg] = useState('')

  async function load() {
    if (!token) return
    const r = await fetch(`/api/dashboard?scope=${scope}&days=${days}`, { headers: { 'X-Admin-Token': token } })
    if (!r.ok) { setMsg(`Cannot load: HTTP ${r.status}`); return }
    setMsg('')
    setD(await r.json())
  }

  useEffect(() => {
    sessionStorage.setItem('adminToken', token)
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [token, scope, days])

  const c = d?.classification || {}
  const m = d?.merges || {}
  const res = d?.resolution || {}

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24, maxWidth: 1100, margin: '0 auto', color: INK }}>
      <h1 style={{ marginBottom: 4 }}>Operations dashboard</h1>
      <p style={{ color: MUTED, marginTop: 0 }}>Classification, merges and resolution. Masked data only; refreshes every 10 s.</p>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', margin: '8px 0 16px' }}>
        <label>Admin token <input type="password" value={token} onChange={(e) => setToken(e.target.value)} /></label>
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="live">Live agent tickets</option>
          <option value="export">Q3 history (client export)</option>
        </select>
        {scope === 'live' && (
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 30, 90].map((n) => <option key={n} value={n}>Last {n} day{n > 1 ? 's' : ''}</option>)}
          </select>
        )}
      </div>
      {msg && <p style={{ color: 'crimson' }}>{msg}</p>}
      {!d && token && !msg && <p style={{ color: MUTED }}>Loading…</p>}

      {d && scope === 'live' && (
        <>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <Tile value={d.tickets} label="Tickets" />
            <Tile value={res.answered_automatically} label="Answered automatically" />
            <Tile value={pct(res.howto_automation_rate)} label="How-To answered by the agent"
              sub={`${res.howto_answered_by_agent ?? 0} of ${res.howto_tickets ?? 0}`} />
            <Tile value={res.waiting_for_review} label="Waiting for review" />
            <Tile value={res.with_a_team} label="With a team (queued)" />
            <Tile value={res.library_size} label="Approved How-To answers"
              sub={`${res.knowledge_tasks_open ?? 0} still to write`} />
          </div>

          <h2 style={{ fontSize: 18, marginTop: 24 }}>Classification</h2>
          <p style={{ color: MUTED, fontSize: 13, marginTop: 0 }}>
            Average confidence {c.avg_confidence ?? '–'} · {c.low_confidence ?? 0} below 0.5
          </p>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
            <Bars title="By team" rows={d.by_team} />
            <Bars title="Confidence branch" rows={c.branches} />
            <Bars title="Decided by" rows={c.decided_by} />
          </div>

          <h2 style={{ fontSize: 18, marginTop: 24 }}>Routing and resolution</h2>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
            <Bars title="By route" rows={d.by_route} />
            <Bars title="By rule" rows={d.by_rule} />
            <Bars title="Answer tier" rows={res.answer_tiers} />
          </div>

          <h2 style={{ fontSize: 18, marginTop: 24 }}>Merges</h2>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <Tile value={m.duplicates_linked} label="Duplicates linked" />
            <Tile value={m.incident_tickets} label="Tickets attached to incidents" />
            <Tile value={m.incidents?.length} label="Incidents" />
          </div>
          <Table title="Incidents" rows={m.incidents}
            cols={[['id', 'Incident'], ['tenant_id', 'Tenant'], ['team', 'Team'], ['tickets', 'Tickets'], ['opened_at', 'Opened (UTC)'], ['signature', 'First message (masked)']]} />
          <Bars title="Linked Jira issues" rows={m.jira_links} />

          <Table title="Recent tickets" rows={d.recent}
            cols={[['ref', 'Ticket'], ['created_at', 'Created (UTC)'], ['tenant_id', 'Tenant'], ['team', 'Team'], ['route', 'Route'], ['rule', 'Rule'], ['tier', 'Answered by'], ['confidence', 'Conf.'], ['reason', 'Reason']]} />
        </>
      )}

      {d && scope === 'export' && (
        <>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <Tile value={d.tickets} label="Q3 tickets" />
            <Tile value={c.customer_pick_wrong} label="Customer picked the wrong team" sub={`of ${c.customer_picks} picks`} />
            <Tile value={c.reassigned_more_than_once} label="Reassigned more than once" sub="includes shift handovers" />
            <Tile value={m.resubmits} label="Customer resubmits" />
          </div>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginTop: 16 }}>
            <Bars title="Final team" rows={d.by_team} />
            <Bars title="Language" rows={d.by_language} />
            <Bars title="KB articles agents used" rows={res.kb_articles_used} unit="uses" />
          </div>
          <Table title="Most common wrong picks (customer picked → final team)" rows={c.wrong_pairs}
            cols={[['picked', 'Customer picked'], ['final', 'Final team'], ['n', 'Tickets']]} />
          <Bars title="Linked Jira issues" rows={m.jira_links} />
          <Table title="Resubmits (ticket → original)" rows={m.resubmit_examples} cols={[['ref', 'Ticket'], ['of', 'Resubmit of']]} />
        </>
      )}
    </main>
  )
}
