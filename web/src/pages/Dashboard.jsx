import { useEffect, useState } from 'react'
import { ConsoleEngineering, ConsoleOverview, ConsoleTickets, Drawers, INK, MUTED, NIGHT, Panel, StatStrip, SURFACE, Tile, Bars, Table, pct } from './Console.jsx'

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
  const [role, setRole] = useState(null)

  useEffect(() => {  // which console this token opens: the client's (lead) or the FDE's (admin)
    setRole(null)
    if (!token) return
    fetch('/api/console/whoami', { headers: { 'X-Admin-Token': token } })
      .then((r) => (r.ok ? r.json() : null)).then((j) => {
        setRole(j?.role || null)
        if (j?.role !== 'admin') setTab((t) => (t === 'engineering' ? 'overview' : t))
      }).catch(() => {})
  }, [token])

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

  const TABS = [['overview', 'Overview'], ['tickets', 'Tickets'], ['agent', 'Agent analytics'], ['export', 'Q3 history'],
    ...(role === 'admin' ? [['engineering', 'Engineering']] : [])]
  return (
    <div style={{ background: SURFACE, minHeight: '100vh' }}>
    <main style={{ padding: '0 24px 32px', maxWidth: 1320, margin: '0 auto', color: INK }}>
      <header style={{ background: NIGHT, color: '#fff', borderRadius: (tab === 'overview' || tab === 'engineering') && token ? 0 : '0 0 10px 10px', padding: '18px 20px 0' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600, fontFamily: "'IBM Plex Sans Condensed', 'IBM Plex Sans', sans-serif" }}>Support control room</h1>
            <p style={{ color: '#b9c6d6', margin: '4px 0 0', fontSize: 14 }}>{role === 'admin'
              ? 'Engineer view: the support picture plus step timings, failures, model calls and traces. Masked data only.'
              : 'What the agent did with each ticket, and why. Masked data only.'}</p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {tab !== 'export' && (
              <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Time window"
                style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid #3a5070', background: '#1d3150', color: '#fff' }}>
                {[1, 7, 30, 90].map((n) => <option key={n} value={n}>Last {n} day{n > 1 ? 's' : ''}</option>)}
              </select>
            )}
            <input type="password" placeholder="Lead or admin token" aria-label="Lead or admin token" value={token} onChange={(e) => setToken(e.target.value)}
              style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid #3a5070', background: '#1d3150', color: '#fff', width: 190 }} />
          </div>
        </div>
        <nav role="tablist" style={{ display: 'flex', gap: 22, marginTop: 14 }}>
          {TABS.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              style={{ padding: '8px 0 10px', border: 'none', background: 'none', cursor: 'pointer', fontSize: 14,
                color: tab === k ? '#fff' : '#b9c6d6', borderBottom: `3px solid ${tab === k ? '#3987e5' : 'transparent'}` }}>{label}</button>
          ))}
        </nav>
      </header>
      <div style={{ height: (tab === 'overview' || tab === 'engineering') && token ? 0 : 18 }} />
      {!token && <p style={{ color: MUTED }}>Enter your lead or admin token to load the control room.</p>}
      {token && tab === 'overview' && <ConsoleOverview token={token} days={days} onPick={(v) => { setView(v); setTab('tickets') }} />}
      {token && tab === 'engineering' && role === 'admin' && <ConsoleEngineering token={token} days={days} />}
      {token && tab === 'tickets' && <ConsoleTickets token={token} days={days} view={view} setView={setView} role={role} />}
      {msg && <p style={{ color: 'crimson' }}>{msg}</p>}
      {!d && token && !msg && (tab === 'agent' || tab === 'export') && <p style={{ color: MUTED }}>Loading…</p>}

      {d && tab === 'agent' && (
        <>
          <StatStrip>
            <Tile accent="#2a78d6" value={pct(res.howto_automation_rate)} label="How-To answered by the agent"
              sub={`${res.howto_answered_by_agent ?? 0} of ${res.howto_tickets ?? 0}`} />
            <Tile accent="#1baf7a" value={res.library_size} label="Approved How-To answers" sub={`${res.knowledge_tasks_open ?? 0} still to write`} />
            <Tile accent="#6250d6" value={c.avg_confidence ?? '–'} label="Average confidence" sub={`${c.low_confidence ?? 0} below 0.5`} />
            <Tile accent="#e87ba4" value={m.incidents?.length ?? 0} label="Incidents" sub={`${m.incident_tickets ?? 0} tickets attached, ${m.duplicates_linked ?? 0} duplicates`} />
          </StatStrip>
          <Drawers>
          <Panel title="Classification" accent="#6250d6" summary={`${(d.by_team || []).length} teams · top: ${(d.by_team || [])[0]?.key ?? '–'}`}>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <Bars title="By team" rows={d.by_team} />
              <Bars title="Confidence branch" rows={c.branches} />
              <Bars title="Decided by" rows={c.decided_by} />
            </div>
          </Panel>
          <Panel title="Routing rules" accent="#2a78d6" summary={`most used: ${(d.by_rule || [])[0]?.key ?? '–'} (${(d.by_rule || [])[0]?.n ?? 0})`}>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <Bars title="By route" rows={d.by_route} />
              <Bars title="By rule" rows={d.by_rule} />
            </div>
          </Panel>
          <Panel title="Incidents and known issues" accent="#e87ba4"
            summary={`${m.incidents?.length ?? 0} incidents · ${(m.jira_links || []).length} Jira issues linked`}>
            <Table rows={m.incidents}
              cols={[['id', 'Incident'], ['tenant_id', 'Tenant'], ['team', 'Team'], ['tickets', 'Tickets'], ['opened_at', 'Opened (UTC)'], ['signature', 'First message (masked)']]} />
            <Bars title="Linked Jira issues" rows={m.jira_links} />
          </Panel>
          </Drawers>
          <p style={{ fontSize: 12, color: MUTED }}>Individual tickets, with why each was handled that way, are in the Tickets tab.</p>
        </>
      )}

      {d && tab === 'export' && (
        <>
          <StatStrip>
            <Tile accent="#5b6b8c" value={d.tickets} label="Q3 tickets" />
            <Tile accent="#eda100" value={c.customer_pick_wrong} label="Customer picked the wrong team" sub={`of ${c.customer_picks} picks`} />
            <Tile accent="#6250d6" value={c.reassigned_more_than_once} label="Reassigned more than once" sub="includes shift handovers" />
            <Tile accent="#e87ba4" value={m.resubmits} label="Customer resubmits" />
          </StatStrip>
          <Drawers>
          <Panel title="Teams and languages" accent="#5b6b8c" summary={`${(d.by_team || []).length} teams · ${(d.by_language || []).length} languages`}>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <Bars title="Final team" rows={d.by_team} />
              <Bars title="Language" rows={d.by_language} />
            </div>
          </Panel>
          <Panel title="Wrong category picks" accent="#eda100" summary={`most common: ${(c.wrong_pairs || [])[0] ? `${c.wrong_pairs[0].picked} → ${c.wrong_pairs[0].final} (${c.wrong_pairs[0].n})` : '–'}`}>
            <Table rows={c.wrong_pairs} cols={[['picked', 'Customer picked'], ['final', 'Final team'], ['n', 'Tickets']]} />
          </Panel>
          <Panel title="Knowledge and known issues" accent="#1baf7a" summary={`${(res.kb_articles_used || []).length} KB articles used · ${(m.jira_links || []).length} Jira issues`}>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <Bars title="KB articles agents used" rows={res.kb_articles_used} unit="uses" />
              <Bars title="Linked Jira issues" rows={m.jira_links} />
            </div>
          </Panel>
          <Panel title="Resubmits" accent="#e87ba4" summary={`${m.resubmits ?? 0} tickets were a customer asking again`}>
            <Table rows={m.resubmit_examples} cols={[['ref', 'Ticket'], ['of', 'Resubmit of']]} />
          </Panel>
          </Drawers>
        </>
      )}
    </main>
    </div>
  )
}
