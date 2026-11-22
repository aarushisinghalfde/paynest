import { useEffect, useState } from 'react'
import { BAR, ConsoleOverview, ConsoleTickets, INK, MUTED, Tile, Bars, Table, pct } from './Console.jsx'

// Support-head console + operations dashboard (lead or admin token), masked data only.
//   Overview   what the agent resolved itself, what went to a person, trust signals, answer path
//   Tickets    queues by outcome, each with a step-by-step timeline (and English for ar/hi)
//   Agent      classification, routing and merge analytics (live)
//   Q3 history the client's export for comparison (customer pick vs final label)
export default function Dashboard() {
  const [token, setToken] = useState(sessionStorage.getItem('adminToken') || '')
  const [tab, setTab] = useState('overview')
  const [view, setView] = useState('all')
  const scope = tab === 'export' ? 'export' : 'live'
  const [days, setDays] = useState(7)
  const [d, setD] = useState(null)
  const [msg, setMsg] = useState('')

  async function load() {
    if (!token || (tab !== 'agent' && tab !== 'export')) return
    const r = await fetch(`/api/dashboard?scope=${scope}&days=${days}`, { headers: { 'X-Admin-Token': token } })
    if (!r.ok) { setMsg(`Cannot load: HTTP ${r.status}`); return }
    setMsg('')
    setD(await r.json())
  }

  useEffect(() => {
    sessionStorage.setItem('adminToken', token)
    setD(null)
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [token, tab, days])

  const c = d?.classification || {}
  const m = d?.merges || {}
  const res = d?.resolution || {}

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24, maxWidth: 1100, margin: '0 auto', color: INK }}>
      <h1 style={{ marginBottom: 4 }}>Support console</h1>
      <p style={{ color: MUTED, marginTop: 0 }}>What the agent did and why. Masked data only; English shown for Arabic and Hindi tickets.</p>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', margin: '8px 0 16px' }}>
        <label>Lead or admin token <input type="password" value={token} onChange={(e) => setToken(e.target.value)} /></label>
        {[['overview', 'Overview'], ['tickets', 'Tickets'], ['agent', 'Agent analytics'], ['export', 'Q3 history']].map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} style={{ padding: '6px 12px', borderRadius: 8, cursor: 'pointer',
            border: `1px solid ${BAR}`, background: tab === k ? BAR : '#fff', color: tab === k ? '#fff' : INK }}>{label}</button>
        ))}
        {tab !== 'export' && (
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 30, 90].map((n) => <option key={n} value={n}>Last {n} day{n > 1 ? 's' : ''}</option>)}
          </select>
        )}
      </div>
      {token && tab === 'overview' && <ConsoleOverview token={token} days={days} onPick={(v) => { setView(v); setTab('tickets') }} />}
      {token && tab === 'tickets' && <ConsoleTickets token={token} days={days} view={view} setView={setView} />}
      {msg && <p style={{ color: 'crimson' }}>{msg}</p>}
      {!d && token && !msg && (tab === 'agent' || tab === 'export') && <p style={{ color: MUTED }}>Loading…</p>}

      {d && tab === 'agent' && (
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

      {d && tab === 'export' && (
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
