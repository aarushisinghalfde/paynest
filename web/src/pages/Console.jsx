import { useEffect, useState } from 'react'

// Support control room (phase G). Built for the support lead, on masked data only:
//   Overview   a one-line verdict, four outcome cards against the desk's own Q3 numbers, where every
//              ticket went (one flow strip), how answers were found (a path with counts), confidence
//              vs outcome, and which of the 12 checks stopped drafts.
//   Tickets    a workbench: queue (search, outcome chips, sorts) beside a decision trail for the
//              selected ticket, with English for Arabic/Hindi, the sources behind each citation,
//              "same question on another date" for statutory rules, and approve/edit/reject in place.
import { BAD, CONDENSED, INK, LINE, MUTED, NIGHT, OK, SURFACE, WARN, WARN_TEXT } from '../theme.jsx'

export { INK, MUTED, NIGHT, SURFACE }  // the dashboard imports these from here
// UI chrome (buttons, active tabs) stays ink so it never reads as a data colour
export const BAR = INK
const SERIES = '#2a78d6'  // single-series bars: categorical slot 1
// One hue per outcome in a fixed order, validated for colour-blind separation between neighbours
// (dataviz validator: worst adjacent CVD dE 9.1, normal-vision 22.9). "Conversation only" is neutral
// grey: it is not support work. Labels and counts always sit next to the colour.
const BUCKET = {
  resolved: { label: 'Resolved by the agent', short: 'Agent resolved', color: '#2a78d6' },
  approved: { label: 'Approved by a person', short: 'Approved', color: '#1baf7a' },
  approval: { label: 'Waiting for approval', short: 'Waiting', color: '#eda100' },
  human: { label: 'With a person', short: 'With a person', color: '#6250d6' },
  merged: { label: 'Merged', short: 'Merged', color: '#e87ba4' },
  chat: { label: 'Conversation only', short: 'Chat', color: '#b8b7b2' },
}
const ORDER = ['resolved', 'approved', 'approval', 'human', 'merged', 'chat']
const TIER = { library: 'Approved answer', cache: 'Answer cache', model: 'Sources + model', fallback: 'Sources (fixed wording)', template: 'Acknowledgement' }
const STEP = { pii_gate: 'Mask PII', normalise: 'Normalise', resolve_tenant: 'Tenant', classify: 'Classify', dedupe: 'Dedupe',
  route: 'Route', draft: 'Draft', output_guard: '12 checks', send: 'Send' }

export const xray = (region, id) => `https://${region}.console.aws.amazon.com/cloudwatch/home?region=${region}#xray:traces/${id}`
export const pct = (x) => (x == null ? '–' : `${Math.round(100 * x)}%`)
const ago = (s) => (s == null ? '–' : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`)

// A ledger figure: coloured rule, condensed number, plain label. Groups of these sit in one white strip
// (StatStrip), never as separate floating cards.
export function Tile({ value, label, sub, accent = '#5b6b8c', onClick, dot }) {
  return (
    <div onClick={onClick} role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined}
      style={{ flex: '1 1 160px', minWidth: 150, padding: '14px 18px', borderLeft: `3px solid ${accent}`, cursor: onClick ? 'pointer' : 'default' }}>
      <div style={{ fontFamily: CONDENSED, fontSize: 30, fontWeight: 600, color: INK, lineHeight: 1 }}>{value ?? '–'}</div>
      <div style={{ fontSize: 13, color: INK, marginTop: 6 }}>{dot && <span style={{ color: dot, marginRight: 4 }}>●</span>}{label}</div>
      {sub && <div style={{ fontSize: 12, color: MUTED, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

export function StatStrip({ children }) {
  return <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 0', background: '#fff', borderRadius: 6, padding: '4px 0', margin: '0 0 14px' }}>{children}</div>
}

// A drawer in the ledger: the row states the answer, opening it shows the working.
export function Panel({ title, summary, accent = '#5b6b8c', children, open: initial = false }) {
  const [open, setOpen] = useState(initial)
  return (
    <section style={{ borderTop: `1px solid ${LINE}` }}>
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        style={{ width: '100%', display: 'grid', gridTemplateColumns: '14px 240px 1fr auto', alignItems: 'center', gap: 12, padding: '14px 18px',
          background: open ? '#f7f9fb' : 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left', color: INK }}>
        <span style={{ width: 10, height: 10, borderRadius: 2, background: accent }} />
        <span style={{ fontSize: 15, fontWeight: 600 }}>{title}</span>
        <span style={{ fontSize: 13, color: MUTED }}>{summary}</span>
        <span style={{ fontSize: 18, color: MUTED, transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>›</span>
      </button>
      {open && <div style={{ padding: '4px 18px 18px 44px', background: '#f7f9fb' }}>{children}</div>}
    </section>
  )
}

export function Drawers({ children }) {
  return <div style={{ background: '#fff', borderRadius: 6, overflow: 'hidden', borderBottom: `1px solid ${LINE}` }}>{children}</div>
}

export function Bars({ title, rows, unit = 'tickets' }) {
  if (!rows?.length) return null
  const max = Math.max(...rows.map((r) => r.n), 1)
  return (
    <section style={{ flex: '1 1 300px', minWidth: 260 }}>
      <h3 style={{ fontSize: 14, margin: '6px 0 8px', color: INK }}>{title}</h3>
      {rows.map((r) => (
        <div key={String(r.key)} title={`${r.label || r.key}: ${r.n} ${unit}`}
          style={{ display: 'grid', gridTemplateColumns: '150px 1fr 40px', alignItems: 'center', gap: 8, margin: '4px 0' }}>
          <span style={{ fontSize: 13, color: INK, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{String(r.label || r.key)}</span>
          <div style={{ height: 12, background: '#e6eeec', borderRadius: 4 }}>
            <div style={{ width: `${(100 * r.n) / max}%`, height: '100%', background: r.color || SERIES, borderRadius: 4, minWidth: r.n ? 2 : 0 }} />
          </div>
          <span style={{ fontSize: 13, color: MUTED, textAlign: 'right' }}>{r.n}</span>
        </div>
      ))}
    </section>
  )
}

export function Table({ title, cols, rows, onRow }) {
  if (!rows?.length) return null
  return (
    <section style={{ marginTop: 18 }}>
      {title && <h3 style={{ fontSize: 14, margin: '6px 0 8px', color: INK }}>{title}</h3>}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
          <thead><tr>{cols.map(([k, label]) => <th key={k} style={{ textAlign: 'left', padding: '6px 8px', borderBottom: `1px solid ${LINE}`, color: MUTED }}>{label}</th>)}</tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.id || i} onClick={onRow ? () => onRow(r) : undefined} style={{ cursor: onRow ? 'pointer' : 'default' }}>
                {cols.map(([k]) => <td key={k} dir="auto" style={{ padding: '6px 8px', borderBottom: '1px solid #edf2f1', color: INK, verticalAlign: 'top' }}>{r[k] ?? '–'}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function useApi(path, token, deps = []) {
  const [data, setData] = useState(null)
  const [msg, setMsg] = useState('')
  async function load() {
    if (!token || !path) return
    try {
      const r = await fetch(`/api${path}`, { headers: { 'X-Admin-Token': token } })
      if (!r.ok) { setMsg(r.status === 401 ? 'That token is not valid for the console.' : `Cannot load (HTTP ${r.status}).`); return }
      setMsg('')
      setData(await r.json())
    } catch { setMsg('The server did not answer. Is the demo running?') }
  }
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t) }, [token, path, ...deps])
  return [data, msg, load]
}

// ---------------------------------------------------------------- Overview

function AnswerPath({ ap }) {
  const steps = [['Approved library', ap.howto_from_library], ['Answer cache', ap.howto_from_cache], ['Guides + past fixes (RAG)', ap.howto_from_rag]]
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 6, flexWrap: 'wrap' }}>
        {steps.map(([label, n], i) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ border: `1px solid ${LINE}`, borderRadius: 10, padding: '8px 12px', minWidth: 130, background: '#fff' }}>
              <div style={{ fontSize: 12, color: MUTED }}>{i + 1}. {label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: INK }}>{n ?? 0}</div>
            </div>
            {i < steps.length - 1 && <span style={{ color: MUTED, fontSize: 18 }}>→</span>}
          </div>
        ))}
      </div>
      <p style={{ fontSize: 12, color: MUTED, margin: '8px 0 0' }}>
        {ap.howto_tickets ?? 0} How-To questions, tried in this order. Cache hit rate {pct(ap.cache_hit_rate)} (average match {ap.avg_cache_similarity ?? '–'});
        top guide relevance {ap.avg_top_rag_score ?? '–'} on average (a guide is offered from 3).
      </p>
    </div>
  )
}

// The ticket river: every ticket enters on the left, passes masking, classification and routing, and
// leaves by one of six outcomes. Branch width is the number of tickets; click a branch to open them.
// Drawn on the night band in the dark steps of the same validated outcome colours.
const NIGHT_COLOR = { resolved: '#3987e5', approved: '#199e70', approval: '#c98500', human: '#9085e9', merged: '#d55181', chat: '#8a8986' }

function River({ buckets, total, onPick }) {
  const W = 1000, H = 260, x0 = 30, xs = 420, xe = 700
  const n = (k) => buckets.find((b) => b.key === k)?.n || 0
  const scale = (v) => (total ? Math.max(2, (v / total) * 110) : 2)
  const trunk = scale(total)
  let yTop = 130 - trunk / 2
  const lanes = ORDER.map((k, i) => {
    const w = n(k) ? scale(n(k)) : 0
    const yIn = yTop + w / 2
    yTop += w
    return { k, w, yIn, yOut: 30 + i * 40, v: n(k) }
  })
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} role="img"
      aria-label={`Where ${total} tickets went: ${lanes.map((l) => `${BUCKET[l.k].label} ${l.v}`).join(', ')}`}>
      <rect x={x0} y={130 - trunk / 2} width={xs - x0} height={trunk} fill="#2a3d57" rx="2" />
      {[['Tickets in', x0 + 4], ['PII masked', 160], ['Classified', 260], ['Routed', 360]].map(([label, x], i) => (
        <g key={label}>
          {i > 0 && <line x1={x} x2={x} y1={130 - trunk / 2 - 6} y2={130 + trunk / 2 + 6} stroke="#8fa3bd" strokeWidth="1" strokeDasharray="2 3" />}
          <text x={x} y={130 - trunk / 2 - 12} fill="#b9c6d6" fontSize="12">{label}</text>
        </g>
      ))}
      <text x={x0 + 4} y={130 + trunk / 2 + 26} fill="#fff" fontSize="30" fontFamily={CONDENSED} fontWeight="600">{total}</text>
      {lanes.filter((l) => l.w).map((l) => (
        <path key={l.k} d={`M${xs},${l.yIn} C${xs + 140},${l.yIn} ${xe - 140},${l.yOut} ${xe},${l.yOut}`} fill="none"
          stroke={NIGHT_COLOR[l.k]} strokeWidth={l.w} strokeOpacity="0.9" style={{ cursor: 'pointer' }} onClick={() => onPick(l.k)}>
          <title>{`${BUCKET[l.k].label}: ${l.v} - open these tickets`}</title>
        </path>
      ))}
      {lanes.map((l) => (
        <g key={l.k} onClick={() => onPick(l.k)} style={{ cursor: 'pointer' }}>
          <rect x={xe} y={l.yOut - 15} width={W - xe} height={30} fill="transparent" />
          <rect x={xe + 6} y={l.yOut - 6} width={12} height={12} rx="2" fill={NIGHT_COLOR[l.k]} />
          <text x={xe + 30} y={l.yOut + 8} fill="#fff" fontSize="24" fontFamily={CONDENSED} fontWeight="600">{l.v}</text>
          <text x={xe + 82} y={l.yOut + 5} fill="#d5deea" fontSize="14">{BUCKET[l.k].label}</text>
        </g>
      ))}
    </svg>
  )
}

function Score({ value, children }) {
  return (
    <div style={{ flex: '1 1 220px', padding: '16px 20px', borderLeft: `1px solid ${LINE}` }}>
      <div style={{ fontFamily: CONDENSED, fontSize: 34, fontWeight: 600, color: INK, lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 13, color: MUTED, marginTop: 6, lineHeight: 1.4 }}>{children}</div>
    </div>
  )
}

export function ConsoleOverview({ token, days, onPick }) {
  const [s, msg] = useApi(`/console/summary?days=${days}`, token)
  if (msg) return <p style={{ color: BAD }}>{msg}</p>
  if (!s) return <p style={{ color: MUTED }}>Loading…</p>
  const im = s.impact || {}
  const base = im.baseline || {}
  const by = Object.fromEntries((s.buckets || []).map((b) => [b.key, b.n]))
  const a = s.approvals || {}
  const g = s.guard || {}
  const ap = s.answer_path || {}
  const total = s.tickets || 1
  const deskHours = base.median_first_response_hours
  const bands = s.confidence?.bands || []
  const low = bands.find((b) => b.band === 'below 0.5')?.tickets ?? 0
  return (
    <>
      <div style={{ background: NIGHT, borderRadius: '0 0 10px 10px', padding: '6px 20px 14px', margin: '0 0 18px' }}>
        <River buckets={s.buckets || []} total={s.tickets || 0} onPick={onPick} />
        <p style={{ color: '#b9c6d6', fontSize: 13, margin: '4px 0 0' }}>
          {pct(s.resolved_by_agent_rate)} of support tickets were resolved without a person. Click any outcome to open its tickets.
        </p>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', background: '#fff', borderRadius: 6, margin: '0 0 18px' }}>
        <Score value={ago(im.median_seconds_to_answer)}>to answer, at the median.{deskHours != null && <> The desk took {deskHours} h to first response in Q3.</>}</Score>
        <Score value={pct(im.answers_backed_by_a_source)}>of sent answers name the guide or rule they come from.</Score>
        <Score value={im.statutory_sent_without_a_person ?? 0}>statutory answers went out without a person. Figures always wait for approval.</Score>
        <Score value={im.cost_per_support_ticket != null ? `$${im.cost_per_support_ticket}` : '–'}>model cost per support ticket; USD {s.model_cost_usd ?? 0} over {s.days} day{s.days > 1 ? 's' : ''}.</Score>
      </div>
      {s.truncated && <p style={{ fontSize: 12, color: WARN_TEXT }}>Over 5,000 tickets in this window: figures cover the newest 5,000.</p>}

      <Drawers>
      <Panel title="How answers were found" accent={BUCKET.resolved.color}
        summary={`${ap.howto_tickets ?? 0} How-To: library ${ap.howto_from_library ?? 0} · cache ${ap.howto_from_cache ?? 0} · guides ${ap.howto_from_rag ?? 0}`}>
        <AnswerPath ap={ap} />
      </Panel>
      <Panel title="People in the loop" accent={BUCKET.approved.color}
        summary={`${a.waiting ?? 0} waiting · median ${a.median_minutes_to_decide ?? '–'} min to decide · ${a.rejected ?? 0} rejected · customers ${s.feedback?.solved ?? 0} solved / ${s.feedback?.not_solved ?? 0} not`}>
        <Bars rows={[
          { key: 'as_is', label: 'Approved as written', n: a.approved_as_is || 0, color: BUCKET.approved.color },
          { key: 'edited', label: 'Approved after an edit', n: a.edited || 0, color: '#8fd6bb' },
          { key: 'rejected', label: 'Rejected, taken over', n: a.rejected || 0, color: BUCKET.human.color },
          { key: 'waiting', label: 'Still waiting', n: a.waiting || 0, color: BUCKET.approval.color },
        ]} />
      </Panel>
      <Panel title="Confidence vs outcome" accent="#6250d6"
        summary={`average ${s.confidence?.average ?? '–'} · ${low} ticket${low === 1 ? '' : 's'} below 0.5 went to a person or the triage desk`}>
        <ConfidenceBands bands={bands} />
      </Panel>
      <Panel title="The 12 checks on drafts" accent={g.failed_checks?.length ? BAD : OK}
        summary={`${g.passed ?? 0} of ${g.drafts_checked ?? 0} passed · ${g.model_drafts_replaced ?? 0} model drafts replaced · ${im.out_of_date_rule_stopped ?? 0} out-of-date rules stopped`}>
        {(g.failed_checks || []).length
          ? <Bars rows={(g.failed_checks || []).map((f) => ({ ...f, label: f.key.replaceAll('_', ' '), color: BAD }))} unit="drafts stopped" />
          : <p style={{ fontSize: 13, color: MUTED }}><span style={{ color: OK }}>✓</span> No draft was stopped in this window.</p>}
      </Panel>
      <Panel title="Desk baseline (client's Q3 export)" accent="#7C8B8E"
        summary={`${base.tickets ?? '–'} tickets · ${pct(base.wrong_category_rate)} filed under the wrong category · CSAT ${base.csat_avg ?? '–'}`}>
        <p style={{ fontSize: 13, margin: 0 }}>Median time to first response {deskHours ?? '–'} h. Languages in this window: {(s.languages || []).map((l) => `${l.key} ${l.n}`).join(', ')}.
          The Q3 history tab has the full export view.</p>
      </Panel>
      </Drawers>
    </>
  )
}

function ConfidenceBands({ bands }) {
  if (!bands.length) return <p style={{ color: MUTED, fontSize: 13 }}>No classified tickets yet.</p>
  const max = Math.max(...bands.map((b) => b.tickets), 1)
  return (
    <div>
      {bands.map((b) => {
        // same colours as the ticket flow: resolved by the agent, approved by a person, taken over by a person
        const parts = [['resolved by the agent', b.resolved, BUCKET.resolved.color],
          ['approved by a person', (b.approved_as_is || 0) + (b.edited || 0), BUCKET.approved.color],
          ['rejected, a person took over', b.rejected, BUCKET.human.color]]
        const other = Math.max(b.tickets - parts.reduce((x, p) => x + p[1], 0), 0)
        return (
          <div key={b.band} style={{ display: 'grid', gridTemplateColumns: '80px 1fr 36px', gap: 8, alignItems: 'center', margin: '6px 0' }}>
            <span style={{ fontSize: 13, color: INK }}>{b.band}</span>
            <div style={{ display: 'flex', height: 14, width: `${(100 * b.tickets) / max}%`, gap: 2 }}
              title={`${b.tickets} tickets: ${parts.map(([l, n]) => `${l} ${n}`).join(', ')}, other ${other}`}>
              {[...parts, ['other', other, BUCKET.chat.color]].map(([l, n, c]) => n ? <div key={l} style={{ flex: n, background: c, borderRadius: 2 }} /> : null)}
            </div>
            <span style={{ fontSize: 13, color: MUTED, textAlign: 'right' }}>{b.tickets}</span>
          </div>
        )
      })}
      <p style={{ fontSize: 12, color: MUTED, margin: '4px 0 0' }}>
        Colours match the outcome cards: blue resolved by the agent, green approved by a person, violet rejected and taken over, grey everything else (queued, merged, chat). Low-confidence tickets should rarely be resolved on their own.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------- Workbench

const SORTS = {
  newest: 'Newest first', priority: 'Priority first', confidence: 'Least confident first',
  slowest: 'Slowest answer first', cost: 'Most model spend first',
}
const PAGE = 50

// The queue is filtered, searched and sorted on the server and comes 50 at a time, so it stays fast
// with thousands of tickets; the chips show counts for the whole window, not just the loaded page.
export function ConsoleTickets({ token, days, view, setView, role }) {
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('newest')
  const [open, setOpen] = useState(null)
  const [pages, setPages] = useState(1)
  useEffect(() => { const t = setTimeout(() => { setQuery(q.trim()); setPages(1) }, 300); return () => clearTimeout(t) }, [q])
  useEffect(() => { setPages(1) }, [view, sort, days])
  const path = `/console/tickets?view=${view}&days=${days}&sort=${sort}&limit=${PAGE * pages}${query ? `&q=${encodeURIComponent(query)}` : ''}`
  const [d, msg, reload] = useApi(path, token)
  const rows = d?.tickets || []
  const counts = d?.counts || {}
  useEffect(() => { if (rows.length && !rows.some((r) => r.id === open)) setOpen(rows[0].id) }, [d])
  return (
    <>
      <Simulate onDone={reload} />
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 360px) minmax(0, 1fr)', gap: 16, alignItems: 'start' }}>
        <aside style={{ borderRadius: 6, background: '#fff', overflow: 'hidden' }}>
          <div style={{ padding: 10, borderBottom: `1px solid ${LINE}` }}>
            <input placeholder="Search question, ticket, team, tenant…" value={q} onChange={(e) => setQ(e.target.value)}
              style={{ width: '100%', padding: 6, boxSizing: 'border-box' }} />
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
              {[['all', 'All'], ...ORDER.map((k) => [k, BUCKET[k].short])].map(([k, label]) => (
                <button key={k} onClick={() => setView(k)}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, padding: '3px 8px', borderRadius: 12, cursor: 'pointer',
                    border: `1px solid ${LINE}`, background: view === k ? INK : '#fff', color: view === k ? '#fff' : INK }}>
                  {k !== 'all' && <span style={{ width: 8, height: 8, borderRadius: 4, background: BUCKET[k].color }} />}
                  {label} {counts[k] ?? 0}
                </button>
              ))}
            </div>
            <select value={sort} onChange={(e) => setSort(e.target.value)} style={{ marginTop: 8, width: '100%' }}>
              {Object.entries(SORTS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
            {d?.truncated && <div style={{ fontSize: 11, color: WARN_TEXT, marginTop: 6 }}>Over 5,000 tickets in this window: showing the newest 5,000. Pick a shorter window.</div>}
          </div>
          {msg && <p style={{ color: BAD, padding: 10 }}>{msg}</p>}
          <div style={{ maxHeight: 640, overflowY: 'auto' }}>
            {!rows.length && <p style={{ color: MUTED, padding: 12, fontSize: 13 }}>{d ? 'No tickets here.' : 'Loading…'}</p>}
            {rows.map((t) => (
              <div key={t.id} onClick={() => setOpen(t.id)}
                style={{ padding: '9px 12px', borderBottom: '1px solid #eef3f2', cursor: 'pointer', background: open === t.id ? '#eef3f8' : '#fff',
                  borderLeft: `4px solid ${BUCKET[t.bucket]?.color || LINE}` }}>
                <div dir="auto" style={{ fontSize: 13, color: INK, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {t.priority && <b style={{ color: BAD }}>P1 </b>}{t.preview || '(empty)'}
                </div>
                <div style={{ fontSize: 11, color: MUTED, marginTop: 2 }}>
                  {(t.created_at || '').slice(5, 16).replace('T', ' ')} · {LANG[t.language] || t.language} · {t.team || 'no team'}{role === 'admin' ? ` · conf ${t.confidence == null ? '–' : t.confidence.toFixed(2)}` : ''}
                  {t.feedback && ` · customer: ${t.feedback === 'yes' ? 'solved' : 'not solved'}`}
                </div>
              </div>
            ))}
            {d && rows.length < d.count && (
              <button onClick={() => setPages(pages + 1)} style={{ width: '100%', padding: 10, border: 'none', background: SURFACE, cursor: 'pointer', color: INK }}>
                Load {Math.min(PAGE, d.count - rows.length)} more ({rows.length} of {d.count} shown)
              </button>
            )}
          </div>
        </aside>
        {open ? <Trail id={open} token={token} onChanged={reload} /> : <p style={{ color: MUTED }}>Pick a ticket.</p>}
      </div>
    </>
  )
}

function Simulate({ onDone }) {
  const [busy, setBusy] = useState('')
  const SAMPLES = {
    howto: [['C-1001', 'How do I download payslips for all employees?']],
    statutory: [['C-1001', 'What is the PF wage ceiling for our September 2026 payroll?']],
    arabic: [['C-1003', 'كيف يمكنني تحميل كشوف الرواتب لجميع الموظفين دفعة واحدة؟']],
    outage: Array.from({ length: 5 }, () => ['C-1004', 'Payslip PDF shows net pay 0 for everyone since this morning']),
  }
  async function send(kind) {
    setBusy(kind)
    for (const [tenant, body] of SAMPLES[kind]) {
      await fetch('/api/tickets', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ tenant_id: tenant, body, channel: 'chat', conversation_id: crypto.randomUUID() }) }).catch(() => {})
    }
    setTimeout(() => { setBusy(''); onDone() }, 6000)
  }
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', margin: '0 0 12px', fontSize: 13, color: MUTED }}>
      Try it live:
      {[['howto', 'How-To question'], ['statutory', 'Statutory question'], ['arabic', 'Arabic question'], ['outage', 'Outage burst (5 reports)']].map(([k, label]) => (
        <button key={k} disabled={!!busy} onClick={() => send(k)} style={{ fontSize: 12, padding: '4px 10px', borderRadius: 8, border: `1px solid ${BAR}`, background: '#fff', color: INK, cursor: 'pointer' }}>
          {busy === k ? 'Sending…' : label}
        </button>
      ))}
    </div>
  )
}

function Section({ title, children, tone, right }) {
  return (
    <section style={{ borderLeft: `3px solid ${tone || BAR}`, padding: '2px 0 2px 12px', margin: '14px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h4 style={{ margin: '0 0 4px', fontSize: 14, color: INK }}>{title}</h4>
        {right && <span style={{ fontSize: 11, color: MUTED }}>{right}</span>}
      </div>
      <div style={{ fontSize: 13, color: INK, lineHeight: 1.55 }}>{children}</div>
    </section>
  )
}

function Fold({ label, children }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ marginTop: 6 }}>
      <button onClick={() => setOpen(!open)} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: '#2a62a8', fontSize: 12 }}>
        {open ? '▲ ' : '▼ '}{label}
      </button>
      {open && <div style={{ marginTop: 6 }}>{children}</div>}
    </div>
  )
}

function ConfidenceMeter({ value }) {
  if (value == null) return null
  return (
    <div style={{ position: 'relative', height: 10, background: '#e6eeec', borderRadius: 5, margin: '6px 0', maxWidth: 360 }}
      title={`confidence ${value}; tickets at or above 0.5 are routed automatically`}>
      <div style={{ width: `${Math.round(value * 100)}%`, height: '100%', background: value >= 0.5 ? SERIES : WARN, borderRadius: 5 }} />
      <div style={{ position: 'absolute', left: '50%', top: -3, width: 2, height: 16, background: INK }} />
    </div>
  )
}

const LANG = { en: 'English', ar: 'Arabic', hi: 'Hindi', 'hi-Latn': 'Hinglish' }
// Plain names for the safety checks, for the client. The check ids stay in the FDE detail.
const CHECK = { empty: 'empty reply', too_long: 'too long', pii_leak: 'contained personal data', unknown_token: 'referred to data the customer did not give',
  bad_citation: 'cited a source that was not used', ungrounded_number: 'a number not found in the source', uncited_answer: 'a figure without a source',
  wrong_region: 'mixed India and UAE rules', superseded_source: 'used an out-of-date rule', instruction_leak: 'exposed internal instructions',
  promise: 'promised something we cannot guarantee', wrong_language: 'not in the customer\'s language',
  internal_detail: 'showed internal details (ids, scores)', not_specific: 'not specific: no clear steps' }
const band = (x) => (x == null ? { label: 'not scored', color: MUTED } : x >= 0.8 ? { label: 'High', color: OK }
  : x >= 0.5 ? { label: 'Medium', color: WARN_TEXT } : { label: 'Low', color: BAD })
const sourceTitles = (a) => {
  const src = a.sources || [], cites = a.citations || []
  const used = src.filter((h, i) => cites.includes(h.id) || (!cites.length && i === 0))
  return [...new Set(used.map((h) => h.title).filter(Boolean))]
}
function plainOutcome(t, d, task) {
  const a = d.answer || {}, m = d.merge || {}
  const by = { library: 'an answer our team approved', cache: 'an answer already given for the same question',
    model: 'the guide', fallback: 'the guide' }[a.tier]
  switch (t.bucket) {
    case 'resolved': return `Answered by the agent from ${by || 'approved sources'}.`
    case 'approved': return 'Answered after a person approved the agent\'s reply.'
    case 'approval':
      if (task && !task.final_draft) return 'No written steps existed yet: our team is writing the reply. The customer was told a person will answer.'
      return 'The agent prepared an answer; a person approves it before the customer sees it.'
    case 'merged': return m.incident_id ? `Part of an incident reported by ${m.incident_size} customers: they get one update.` : 'Same question as an earlier ticket: linked, not answered twice.'
    case 'chat': return 'Conversation (greeting, thanks or a follow-up), nothing to resolve.'
    default: return `With the ${t.team || 'support'} team.`
  }
}

function Trail({ id, token, onChanged }) {
  const [t, msg, reload] = useApi(`/console/tickets/${id}`, token, [id])
  const [english, setEnglish] = useState(true)
  const [edit, setEdit] = useState(null)
  const [cmp, setCmp] = useState(null)
  const [cmpDate, setCmpDate] = useState('2026-07-15')
  const [note, setNote] = useState('')
  useEffect(() => { setEdit(null); setCmp(null); setNote('') }, [id])
  if (msg) return <p style={{ color: BAD }}>{msg}</p>
  if (!t) return <p style={{ color: MUTED }}>Loading ticket…</p>
  const dcs = t.decision || {}
  const c = dcs.classification || {}
  const a = dcs.answer || {}
  const g = dcs.guard || {}
  const m = dcs.merge || {}
  const tr = t.translation || {}
  const timings = dcs.timings_ms || {}
  const totalMs = Object.values(timings).reduce((x, y) => x + y, 0)
  const task = (t.reviews || []).find((r) => r.id === t.open_task)
  const canDecide = task && t.role !== 'lead'
  const review = (t.reviews || []).filter((r) => r.kind === 'reply').slice(-1)[0]
  const showEn = english && tr.question?.ok
  const isStatutory = (a.facts || []).some((f) => f.tool === 'get_rate')

  async function decide(decision) {
    const r = await fetch(`/api/review/tasks/${encodeURIComponent(task.id)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Admin-Token': token },
      body: JSON.stringify({ decision, body: edit ?? task.final_draft, reviewer: 'console' }),
    })
    setNote(r.ok ? (decision === 'approve' ? 'Approved and sent.' : 'Rejected: a person takes over.') : `Not saved (HTTP ${r.status}).`)
    reload(); onChanged()
  }
  async function compare() {
    const r = await fetch(`/api/console/tickets/${id}/compare?date=${cmpDate}`, { headers: { 'X-Admin-Token': token } })
    setCmp(r.ok ? await r.json() : { error: `HTTP ${r.status}` })
  }

  return (
    <article style={{ borderRadius: 6, padding: '16px 18px', background: '#fff' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 12, color: MUTED }}>
            Ticket {t.ref}, {t.tenant_name || t.tenant_id} ({[t.tenant_tier || dcs.tier, t.region].filter(Boolean).join(', ') || t.tenant_id}), {LANG[t.language] || t.language}
            {t.role === 'admin' && `, model spend ${t.cost_usd ? `$${t.cost_usd.toFixed(5)}` : '$0'}`}
          </div>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 4, padding: '2px 10px', borderRadius: 12, fontSize: 12, color: INK, background: SURFACE }}>
            <span style={{ width: 10, height: 10, borderRadius: 5, background: BUCKET[t.bucket]?.color || MUTED }} />{BUCKET[t.bucket]?.label || t.bucket}
          </div>
        </div>
        {tr.question && tr.question.reason !== 'already English' && (
          <label style={{ fontSize: 12, color: MUTED }}><input type="checkbox" checked={english} onChange={(e) => setEnglish(e.target.checked)} /> Show English</label>
        )}
      </header>

      <Section title="The customer asked">
        <div dir="auto" style={{ fontSize: 15, whiteSpace: 'pre-wrap' }}>{t.masked_body}</div>
        {showEn && <div style={{ background: '#fff8e6', padding: 8, borderRadius: 6, marginTop: 6 }}><b>English</b> (machine translation, numbers checked): {tr.question.english}</div>}
        {english && tr.question && !tr.question.ok && tr.question.reason !== 'already English' && <div style={{ color: WARN_TEXT, fontSize: 12 }}>{tr.question.reason}</div>}
      </Section>

      <Section title="What happened">
        <div style={{ fontSize: 15 }}>{plainOutcome(t, dcs, task)}</div>
        <div style={{ marginTop: 6, color: INK }}>
          Category <b>{c.team || 'not decided'}</b>, confidence <b style={{ color: band(c.confidence).color }}>{band(c.confidence).label}</b>
          {c.injection && <span style={{ color: BAD }}>. Looked like an attempt to manipulate the assistant: only a person handles it.</span>}
          {c.priority_signal && <span style={{ color: WARN_TEXT }}>. Urgent: pay or a filing is at risk.</span>}
        </div>
        {sourceTitles(a).length > 0 && <div style={{ marginTop: 6 }}>Answer based on: {sourceTitles(a).map((x, i) => <span key={i}>{i ? ', ' : ''}\u201c{x}\u201d</span>)}{isStatutory && a.as_of ? `, rules in force on ${a.as_of}` : ''}</div>}
        {g.ok !== undefined && (
          <div style={{ marginTop: 6 }}>
            <span style={{ color: g.ok === false ? BAD : OK, fontWeight: 700 }}>{g.ok === false ? '✕' : '✓'}</span>{' '}
            {g.ok === false ? `Held back by our safety checks: ${(g.failed || []).map((k) => CHECK[k] || k.replaceAll('_', ' ')).join('; ')}` : 'Passed all safety checks before sending'}
          </div>
        )}
        {isStatutory && (
          <div style={{ marginTop: 8, padding: 8, background: SURFACE, borderRadius: 6 }}>
            Same question on another date:{' '}
            <input type="date" value={cmpDate} onChange={(e) => setCmpDate(e.target.value)} /> <button onClick={compare}>Compare</button>
            {cmp?.error && <span style={{ color: BAD }}> {cmp.error}</span>}
            {(cmp?.topics || []).map((x) => (
              <div key={x.topic} style={{ fontSize: 12, marginTop: 4 }}>
                {x.topic} ({x.region}): {x.asked_for.date || 'asked date'} → <b>{x.asked_for.value || '–'}</b>; {x.compared.date} → <b>{x.compared.value || 'no rule'}</b>
                {x.differs ? <span style={{ color: WARN_TEXT }}>, the rule changed in between</span> : <span style={{ color: MUTED }}>, same rule</span>}
              </div>
            ))}
          </div>
        )}
      </Section>

      {t.role === 'admin' && (
        <Fold label="Engineering detail (FDE only)">
      <Section title="What the agent decided" right={totalMs ? `${Math.round(totalMs)} ms in total` : null}>
        <div><b>{c.team || 'No team'}</b> · confidence {c.confidence ?? '–'} ({c.branch || '–'}) · {c.decided_by || '–'}</div>
        <ConfidenceMeter value={c.confidence} />
        <Fold label="How each layer voted">
          <div style={{ color: MUTED, fontSize: 12 }}>
            Keywords said {c.layers?.keywords || '–'}, similar past tickets said {c.layers?.similar || '–'}, model {c.layers?.model || 'not asked'}{c.second ? `; runner-up ${c.second}` : ''}.
          </div>
        </Fold>
        {c.injection && <div style={{ color: BAD }}>Prompt injection: no model saw this text.</div>}
        {c.priority_signal && <div style={{ color: WARN_TEXT }}>P1: pay or a filing is at risk.</div>}
        {(m.duplicate_of || m.incident_id || m.jira_key) && (
          <div style={{ marginTop: 4 }}>
            {m.duplicate_of && <div>Duplicate of {String(m.duplicate_of).slice(0, 8)} ({m.duplicate_reason})</div>}
            {m.incident_id && <div>Part of an incident with {m.incident_size} reports</div>}
            {m.jira_key && <div>Known issue {m.jira_key}</div>}
          </div>
        )}
        <div style={{ marginTop: 4 }}>Rule <b>{dcs.route?.rule || t.route_rule}</b>: {dcs.route?.reason || t.route_reason}</div>
        {t.role === 'admin' && (
          <div style={{ marginTop: 4, fontSize: 12, color: MUTED }}>
            Trace: {dcs.trace_id ? <a href={xray(t.aws_region, dcs.trace_id)} target="_blank" rel="noreferrer">{dcs.trace_id}</a>
              : <>none recorded. In X-Ray, filter <code>annotation.ticket_id = "{t.id}"</code></>}
          </div>
        )}
        {!!Object.keys(timings).length && (
          <Fold label="Time per step">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {Object.entries(timings).map(([k, ms]) => (
                <span key={k} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: SURFACE, color: INK }}>{STEP[k] || k} {Math.round(ms)} ms</span>
              ))}
            </div>
          </Fold>
        )}
      </Section>

      <Section title={`Answer: ${TIER[a.tier] || a.tier || '–'}`} right={a.as_of ? `rules as of ${a.as_of}` : null}>
        {a.library_similarity != null && <div>Matched an approved answer ({pct(a.library_similarity)} similar).</div>}
        {a.cache_similarity != null && <div>Matched an earlier answer in the cache ({pct(a.cache_similarity)} similar, same region, language and knowledge version).</div>}
        {(() => {
          const src = a.sources || []
          const row = (h, i) => (
            <div key={h.id} style={{ display: 'grid', gridTemplateColumns: '24px 1fr auto', gap: 6, fontSize: 12, margin: '3px 0' }}>
              <span style={{ background: (a.citations || []).includes(h.id) ? SERIES : '#c9d6d3', color: '#fff', borderRadius: 4, textAlign: 'center' }}>{i + 1}</span>
              <span>{h.title || h.id}{h.has_steps === false && <i style={{ color: WARN_TEXT }}> · title only</i>}{h.solved ? ` · solved ${h.solved} similar before` : ''}</span>
              <span style={{ color: MUTED }}>relevance {h.score ?? '–'}</span>
            </div>
          )
          const cited = src.filter((h, i) => (a.citations || []).includes(h.id) || (!(a.citations || []).length && i === 0))
          return (
            <>
              {cited.map((h) => row(h, src.indexOf(h)))}
              {src.length > cited.length && <Fold label={`All ${src.length} sources considered`}>{src.map(row)}</Fold>}
            </>
          )
        })()}
        {(a.facts || []).map((f, i) => <div key={i} style={{ fontSize: 12 }}>Fact · {f.tool} {f.source}: <b>{String(f.result ?? '–')}</b></div>)}
        {!!a.learn_kb?.length && <div style={{ color: WARN_TEXT, fontSize: 12 }}>Only a guide title existed, so support was asked to write the steps once ({a.learn_kb.join(', ')}).</div>}
      </Section>

      <Section title={`${(g.passed || []).length + (g.failed || []).length} checks on the draft`} tone={g.ok === false ? BAD : OK}>
        <div><span style={{ color: g.ok === false ? BAD : OK, fontWeight: 700 }}>{g.ok === false ? '✕' : '✓'}</span>{' '}
          {g.ok === false ? `Stopped by ${(g.failed || []).map((k) => k.replaceAll('_', ' ')).join(', ')}` : `All ${(g.passed || []).length} checks passed`}</div>
        {g.replaced_model_draft && <div style={{ fontSize: 12, marginTop: 4 }}>The model's draft failed ({g.replaced_model_draft.join(', ')}); the fixed wording from the same sources was used.</div>}
        <Fold label="Each check">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {[...(g.passed || []).map((k) => [k, true]), ...(g.failed || []).map((k) => [k, false])].map(([k, ok]) => (
              <span key={k} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, color: INK,
                background: ok ? '#eef6ee' : '#fdecec', border: `1px solid ${ok ? '#cfe6cf' : BAD}` }}>
                <span style={{ color: ok ? OK : BAD, fontWeight: 700 }}>{ok ? '✓' : '✕'}</span> {k.replaceAll('_', ' ')}
              </span>
            ))}
          </div>
        </Fold>
      </Section>

        </Fold>
      )}

      {task && (
        <Section title={canDecide ? 'Your decision' : 'Waiting for a reviewer'} tone={WARN} right={task.reason}>
          <textarea dir="auto" rows={5} style={{ width: '100%', boxSizing: 'border-box' }} disabled={!canDecide}
            value={edit ?? task.final_draft ?? ''} onChange={(e) => setEdit(e.target.value)} />
          {canDecide && (
            <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
              <button onClick={() => decide('approve')} style={{ background: BAR, color: '#fff', border: 'none', borderRadius: 6, padding: '6px 14px', cursor: 'pointer' }}>
                {edit != null && edit !== task.final_draft ? 'Approve my edit and send' : 'Approve and send'}
              </button>
              <button onClick={() => decide('reject')} style={{ borderRadius: 6, padding: '6px 14px', cursor: 'pointer' }}>Reject, a person takes over</button>
            </div>
          )}
          {!canDecide && <div style={{ fontSize: 12, color: MUTED }}>The lead view is read-only; reviewers decide in their own login.</div>}
        </Section>
      )}
      {note && <p style={{ color: INK }}><span style={{ color: OK }}>✓</span> {note}</p>}

      {review?.outcome === 'edited' && (
        <Section title="What the reviewer changed" tone={BUCKET.approved.color}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div><div style={{ fontSize: 11, color: MUTED }}>Agent proposed</div><div dir="auto" style={{ whiteSpace: 'pre-wrap', background: '#fdeceb', padding: 6, fontSize: 12 }}>{review.proposed_draft}</div></div>
            <div><div style={{ fontSize: 11, color: MUTED }}>Sent ({review.reviewer})</div><div dir="auto" style={{ whiteSpace: 'pre-wrap', background: '#e8f5ee', padding: 6, fontSize: 12 }}>{review.final_draft}</div></div>
          </div>
        </Section>
      )}

      <Section title="What the customer saw" tone={MUTED}>
        {(t.customer_saw || []).length ? t.customer_saw.map((r, i) => <div key={i} dir="auto" style={{ whiteSpace: 'pre-wrap', marginBottom: 6 }}>{r}</div>) : <i>Nothing sent yet</i>}
        {english && tr.reply?.ok && <div style={{ background: '#fff8e6', padding: 8, borderRadius: 6 }}><b>English:</b> {tr.reply.english}</div>}
        {t.feedback && <div>Customer said: <b style={{ color: t.feedback === 'yes' ? OK : BAD }}>{t.feedback === 'yes' ? 'solved' : 'not solved'}</b></div>}
      </Section>
    </article>
  )
}

// ---------------------------------------------------------------- Engineering (FDE, admin token only)
// The pipeline drawn the way a trace viewer draws one ticket: each graph step starts where the previous
// one's median ends, the bar is the median, the thin line runs on to the 95th percentile.
function Waterfall({ nodes, total }) {
  if (!nodes?.length) return <p style={{ color: '#b9c6d6', margin: 0, padding: '18px 0' }}>No step timings in this window yet. Send a ticket from Chat.</p>
  const W = 1000, ROW = 30, LEFT = 130, RIGHT = 170, H = nodes.length * ROW + 30
  const sum = nodes.reduce((x, n) => x + (n.p50 || 0), 0) || 1
  let at = 0
  const ends = nodes.map((n) => { const e = at + (n.p95 || n.p50 || 0); at += n.p50 || 0; return e })
  const raw = Math.max(sum, ...ends)
  const step = [50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000].find((s) => raw / s <= 5) || 20000
  const span = Math.ceil(raw / step) * step
  const x = (v) => LEFT + ((W - LEFT - RIGHT) * v) / span
  at = 0
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} role="img"
      aria-label={`Median time per step; end to end median ${total} ms`}>
      {Array.from({ length: span / step + 1 }, (_, i) => i * step).map((v) => (
        <g key={v}>
          <line x1={x(v)} x2={x(v)} y1={4} y2={H - 22} stroke="#2a3f5c" />
          <text x={x(v)} y={H - 6} fill="#8fa2b8" fontSize="12" textAnchor="middle">{v >= 1000 ? `${v / 1000} s` : `${v} ms`}</text>
        </g>
      ))}
      <text x={W - RIGHT + 24} y={H - 6} fill="#8fa2b8" fontSize="12">median, share of time</text>
      {nodes.map((n) => {
        const y = 8 + nodes.indexOf(n) * ROW, start = at, p50 = n.p50 || 0
        at += p50
        return (
          <g key={n.node}>
            <title>{`${STEP[n.node] || n.node}: median ${p50} ms, 95th ${n.p95} ms, max ${n.max} ms over ${n.n} tickets`}</title>
            <text x={0} y={y + 15} fill="#e6edf5" fontSize="14">{STEP[n.node] || n.node}</text>
            <line x1={x(start + p50)} x2={x(start + (n.p95 || p50))} y1={y + 10} y2={y + 10} stroke="#7fb0f0" strokeWidth="2" />
            <rect x={x(start)} y={y + 2} width={Math.max(3, x(start + p50) - x(start))} height={16} rx={4} fill="#3987e5" />
            <text x={W - RIGHT + 24} y={y + 15} fill="#e6edf5" fontSize="13">{Math.round(p50)} ms</text>
            <text x={W - 6} y={y + 15} fill="#b9c6d6" fontSize="13" textAnchor="end">{n.share >= 0.01 ? `${Math.round(100 * n.share)}%` : '<1%'}</text>
          </g>
        )
      })}
    </svg>
  )
}

const ms = (v) => (v == null ? '–' : v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(1)} s`)

export function ConsoleEngineering({ token, days, onOpen }) {
  const [e, msg] = useApi(`/console/engineering?days=${days}`, token, [days])
  if (msg) return <p style={{ color: BAD, padding: 18 }}>{msg}</p>
  if (!e) return <p style={{ color: MUTED, padding: 18 }}>Loading…</p>
  const rt = e.runtime || {}
  const link = (r) => (r.trace_id
    ? <a href={xray(rt.aws_region, r.trace_id)} target="_blank" rel="noreferrer" onClick={(ev) => ev.stopPropagation()}>Open trace</a>
    : <span style={{ color: MUTED }}>no trace</span>)
  const rows = (list) => list.map((r) => ({ ...r, step: STEP[r.slowest_node] || r.slowest_node, time: ms(r.ms), trace: link(r), tier: TIER[r.tier] || r.tier }))
  const g = e.guard || {}
  return (
    <>
      <div style={{ background: NIGHT, color: '#fff', padding: '6px 20px 18px', borderRadius: '0 0 10px 10px', marginBottom: 14 }}>
        <p style={{ color: '#b9c6d6', fontSize: 14, margin: '8px 0 12px' }}>
          One ticket through the graph at the median of {e.with_timings} tickets: each bar starts where the step before it ends, the thin line runs to the 95th percentile. End to end {ms(e.end_to_end_ms?.p50)}, 95th percentile {ms(e.end_to_end_ms?.p95)}.
        </p>
        <Waterfall nodes={e.nodes} total={e.end_to_end_ms?.p50} />
      </div>
      <StatStrip>
        <Tile accent={e.failed?.n ? BAD : OK} value={e.failed?.n ?? 0} label="Graph runs failed" sub={`of ${e.tickets} tickets`} />
        <Tile accent={g.blocked ? WARN : OK} value={g.blocked ?? 0} label="Drafts the guard stopped" sub={`${g.replaced ?? 0} swapped for fixed wording`} />
        <Tile accent="#6250d6" value={e.model_calls} label="Model calls" sub={`$${(e.model_cost_usd ?? 0).toFixed(2)}, ${e.escalations} escalated a rung`} />
        <Tile accent="#2a78d6" value={pct(e.tickets ? e.traced / e.tickets : null)} label="Tickets with a trace" sub={rt.tracing ? 'X-Ray export on' : 'Tracing is off on this host'} />
      </StatStrip>
      <Drawers>
        <Panel title="Slowest tickets" accent="#2a78d6" summary={e.slowest?.length ? `slowest ${ms(e.slowest[0].ms)}, mostly in ${STEP[e.slowest[0].slowest_node] || e.slowest[0].slowest_node}` : 'none yet'}>
          <Table rows={rows(e.slowest || [])} onRow={onOpen ? (r) => onOpen(r.id) : undefined}
            cols={[['ref', 'Ticket'], ['time', 'Total'], ['step', 'Slowest step'], ['route', 'Route'], ['tier', 'Answer'], ['trace', 'Trace']]} />
        </Panel>
        <Panel title="Failures and guard stops" accent={BAD} summary={`${e.failed?.n ?? 0} failed runs, ${g.blocked ?? 0} guard stops, ${e.injection} injection attempt${e.injection === 1 ? '' : 's'}`}>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
            <Bars title="Guard check that failed" rows={(g.by_check || []).map((r) => ({ ...r, color: WARN }))} unit="drafts" />
          </div>
          <Table title="Failed runs" rows={rows(e.failed?.rows || [])} onRow={onOpen ? (r) => onOpen(r.id) : undefined}
            cols={[['ref', 'Ticket'], ['step', 'Last slow step'], ['route', 'Route'], ['trace', 'Trace']]} />
          {!e.failed?.n && !g.blocked && <p style={{ color: MUTED, fontSize: 13 }}>Nothing failed in this window.</p>}
        </Panel>
        <Panel title="Model calls" accent="#6250d6" summary={`${e.model_calls} calls, classifier asked the model on ${pct(e.classifier_model_rate)} of tickets, ${e.fallback} fixed-wording answers`}>
          <Table rows={(e.models || []).map((r) => ({ ...r, cost: `$${r.cost_usd.toFixed(4)}`, tok: `${r.tokens_in} in, ${r.tokens_out} out` }))}
            cols={[['purpose', 'Step'], ['model', 'Model'], ['rung', 'Rung'], ['calls', 'Calls'], ['tok', 'Tokens'], ['cost', 'Cost']]} />
          {!e.models?.length && <p style={{ color: MUTED, fontSize: 13 }}>No model calls logged in this window.</p>}
        </Panel>
        <Panel title="Runtime" accent="#5b6b8c" summary={`${rt.version} in ${rt.aws_region}, models via ${rt.model_provider}`}>
          <Table rows={[{ k: 'Release', v: rt.version }, { k: 'Region', v: `${rt.region} (${rt.aws_region})` }, { k: 'Model provider', v: rt.model_provider },
            { k: 'Tracing', v: rt.tracing ? 'OpenTelemetry to X-Ray, ticket_id and route indexed' : 'off' },
            { k: 'First reply', v: `median ${ago(e.first_reply_s?.p50)}, 95th ${ago(e.first_reply_s?.p95)}` }]}
            cols={[['k', ''], ['v', '']]} />
        </Panel>
      </Drawers>
    </>
  )
}
