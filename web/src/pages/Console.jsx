import { useEffect, useState } from 'react'

// Support-head console (phase G): what the agent resolved itself, what went to a person and why,
// how confident it was, and how each answer was found (approved library, answer cache, RAG).
// Read-only with the lead token; masked text only, with English machine translation for
// Arabic / Hindi / Hinglish tickets (numbers and tokens are checked identical to the original).
export const INK = '#16262E'
export const MUTED = '#5f6f73'
export const BAR = '#0E7C7B'
export const SURFACE = '#F4F8F7'
const LINE = '#cfdcd9'
const OK = '#1f7a4d'
const WARN = '#a15c00'
const BAD = '#b42318'

export const pct = (x) => (x == null ? '–' : `${Math.round(100 * x)}%`)

export function Tile({ value, label, sub, onClick, active }) {
  return (
    <div onClick={onClick} role={onClick ? 'button' : undefined}
      style={{ background: active ? '#dceeea' : SURFACE, borderRadius: 10, padding: '12px 14px', minWidth: 130,
        flex: '1 1 130px', cursor: onClick ? 'pointer' : 'default', outline: active ? `2px solid ${BAR}` : 'none' }}>
      <div style={{ fontSize: 28, fontWeight: 700, color: INK }}>{value ?? '–'}</div>
      <div style={{ fontSize: 13, color: INK }}>{label}</div>
      {sub && <div style={{ fontSize: 12, color: MUTED, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

// One series, one hue: horizontal bars sorted by size, value labels in text ink.
export function Bars({ title, rows, unit = 'tickets' }) {
  if (!rows?.length) return null
  const max = Math.max(...rows.map((r) => r.n), 1)
  return (
    <section style={{ flex: '1 1 300px', minWidth: 280 }}>
      <h3 style={{ fontSize: 15, margin: '6px 0 8px', color: INK }}>{title}</h3>
      {rows.map((r) => (
        <div key={String(r.key)} title={`${r.key}: ${r.n} ${unit}`}
          style={{ display: 'grid', gridTemplateColumns: '150px 1fr 44px', alignItems: 'center', gap: 8, margin: '4px 0' }}>
          <span style={{ fontSize: 13, color: INK, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{String(r.label || r.key)}</span>
          <div style={{ height: 14, background: '#e6eeec', borderRadius: 4 }}>
            <div style={{ width: `${(100 * r.n) / max}%`, height: '100%', background: BAR, borderRadius: 4, minWidth: r.n ? 2 : 0 }} />
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
      {title && <h3 style={{ fontSize: 15, margin: '6px 0 8px', color: INK }}>{title}</h3>}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
          <thead>
            <tr>{cols.map(([k, label]) => <th key={k} style={{ textAlign: 'left', padding: '6px 8px', borderBottom: `1px solid ${LINE}`, color: MUTED }}>{label}</th>)}</tr>
          </thead>
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
    const r = await fetch(`/api${path}`, { headers: { 'X-Admin-Token': token } })
    if (!r.ok) { setMsg(`Cannot load: HTTP ${r.status}`); return }
    setMsg('')
    setData(await r.json())
  }
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t) }, [token, path, ...deps])
  return [data, msg]
}

const TIER = { library: 'Approved answer (library)', cache: 'Answer cache', model: 'RAG + model', fallback: 'RAG (fixed wording)', template: 'Template' }

export function ConsoleOverview({ token, days, onPick }) {
  const [s, msg] = useApi(`/console/summary?days=${days}`, token)
  if (msg) return <p style={{ color: BAD }}>{msg}</p>
  if (!s) return <p style={{ color: MUTED }}>Loading…</p>
  const ap = s.answer_path || {}
  const g = s.guard || {}
  const a = s.approvals || {}
  const by = Object.fromEntries((s.buckets || []).map((b) => [b.key, b.n]))
  return (
    <>
      <p style={{ color: MUTED, marginTop: 0 }}>
        {s.tickets} tickets in the last {s.days} day{s.days > 1 ? 's' : ''}, {s.support_tickets} needing support work.
        Every ticket is in exactly one box below; click a box to see its tickets.
      </p>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <Tile value={by.resolved} label="Resolved by the agent" sub={`${pct(s.resolved_by_agent_rate)} of support tickets`} onClick={() => onPick('resolved')} />
        <Tile value={by.approval} label="Waiting for approval" sub="statutory, P1, known issue, failed check" onClick={() => onPick('approval')} />
        <Tile value={by.approved} label="Approved by a person" sub={`${a.approved_as_is ?? 0} as is · ${a.edited ?? 0} edited`} onClick={() => onPick('approved')} />
        <Tile value={by.human} label="With a person" sub="team queue, blocked, rejected" onClick={() => onPick('human')} />
        <Tile value={by.merged} label="Merged" sub="incident or duplicate" onClick={() => onPick('merged')} />
        <Tile value={by.chat} label="Conversation only" sub="greetings, follow-ups" onClick={() => onPick('chat')} />
      </div>

      <h2 style={{ fontSize: 18, marginTop: 24 }}>Can we trust it?</h2>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <Tile value={s.confidence?.average ?? '–'} label="Average classification confidence" />
        <Tile value={a.rejected ?? 0} label="Drafts a person rejected" sub={`median ${a.median_minutes_to_decide ?? '–'} min to decide`} />
        <Tile value={`${s.feedback?.solved ?? 0} / ${s.feedback?.not_solved ?? 0}`} label="Customers: solved / not solved" />
        <Tile value={`${g.passed ?? 0} / ${g.drafts_checked ?? 0}`} label="Drafts passing all 12 checks"
          sub={`${g.model_drafts_replaced ?? 0} model drafts replaced by fixed wording`} />
      </div>
      <Table title="Confidence bands: how tickets in each band ended" rows={(s.confidence?.bands || []).map((b) => ({
        ...b, approved_rate: b.reviewed ? pct(b.approved_as_is / b.reviewed) : '–' }))}
        cols={[['band', 'Confidence'], ['tickets', 'Tickets'], ['resolved', 'Resolved by agent'], ['reviewed', 'Reviewed'],
          ['approved_as_is', 'Approved as is'], ['edited', 'Edited'], ['rejected', 'Rejected'], ['approved_rate', 'Approved unchanged'], ['said_not_solved', 'Customer: not solved']]} />

      <h2 style={{ fontSize: 18, marginTop: 24 }}>How answers were found</h2>
      <p style={{ color: MUTED, fontSize: 13, marginTop: 0 }}>
        How-To order: approved library → answer cache → RAG over guides and past resolutions. {ap.howto_tickets ?? 0} How-To tickets:
        {' '}{ap.howto_from_library ?? 0} from the library, {ap.howto_from_cache ?? 0} from the cache
        (hit rate {pct(ap.cache_hit_rate)}, average match {ap.avg_cache_similarity ?? '–'}), {ap.howto_from_rag ?? 0} from RAG
        (average relevance of the top guide {ap.avg_top_rag_score ?? '–'}; the agent needs at least 3 to offer a guide).
      </p>
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        <Bars title="Answered by" rows={(ap.tiers || []).map((t) => ({ ...t, label: TIER[t.key] || t.key }))} />
        <Bars title="Checks that stopped a draft" rows={g.failed_checks} unit="drafts" />
        <Bars title="Language" rows={s.languages} />
      </div>
      <p style={{ color: MUTED, fontSize: 12 }}>Model spend in this window: USD {s.model_cost_usd ?? 0}</p>
    </>
  )
}

const VIEWS = [['all', 'All'], ['resolved', 'Resolved by agent'], ['approval', 'Waiting approval'], ['approved', 'Approved'],
  ['human', 'With a person'], ['merged', 'Merged'], ['chat', 'Conversation']]

export function ConsoleTickets({ token, days, view, setView }) {
  const [language, setLanguage] = useState('')
  const [open, setOpen] = useState(null)
  const q = `/console/tickets?view=${view}&days=${days}${language ? `&language=${language}` : ''}`
  const [d, msg] = useApi(q, token)
  return (
    <>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        {VIEWS.map(([k, label]) => (
          <button key={k} onClick={() => { setView(k); setOpen(null) }}
            style={{ padding: '6px 10px', borderRadius: 16, border: `1px solid ${LINE}`, cursor: 'pointer',
              background: view === k ? BAR : '#fff', color: view === k ? '#fff' : INK }}>{label}</button>
        ))}
        <select value={language} onChange={(e) => setLanguage(e.target.value)} style={{ marginLeft: 8 }}>
          <option value="">All languages</option>
          {['en', 'hi-Latn', 'hi', 'ar'].map((l) => <option key={l} value={l}>{l}</option>)}
        </select>
      </div>
      {msg && <p style={{ color: BAD }}>{msg}</p>}
      <div style={{ display: 'grid', gridTemplateColumns: open ? 'minmax(0,1fr) minmax(0,1.2fr)' : '1fr', gap: 16 }}>
        <div>
          <p style={{ color: MUTED, fontSize: 13 }}>{d ? `${d.count} tickets` : 'Loading…'} · click a row for its timeline</p>
          <Table rows={(d?.tickets || []).map((t) => ({ ...t, confidence: t.confidence == null ? '–' : t.confidence.toFixed(2),
            created_at: (t.created_at || '').slice(5, 16).replace('T', ' '),
            answered_by: TIER[t.answered_by] || t.answered_by, preview: open ? `${(t.preview || '').slice(0, 48)}…` : t.preview }))}
            onRow={(r) => setOpen(r.id)}
            cols={open
              ? [['created_at', 'Created (UTC)'], ['language', 'Lang'], ['team', 'Team'], ['confidence', 'Conf.'], ['preview', 'Question']]
              : [['created_at', 'Created (UTC)'], ['ref', 'Ticket'], ['language', 'Lang'], ['team', 'Team'], ['confidence', 'Conf.'],
                ['rule', 'Rule'], ['answered_by', 'Answered by'], ['review_outcome', 'Review'], ['feedback', 'Customer'], ['preview', 'Question (masked)']]} />
        </div>
        {open && <TicketTimeline id={open} token={token} onClose={() => setOpen(null)} />}
      </div>
    </>
  )
}

function Step({ title, children, tone }) {
  return (
    <section style={{ borderLeft: `3px solid ${tone || BAR}`, padding: '4px 0 4px 12px', margin: '12px 0' }}>
      <h4 style={{ margin: '0 0 4px', fontSize: 14, color: INK }}>{title}</h4>
      <div style={{ fontSize: 13, color: INK, lineHeight: 1.5 }}>{children}</div>
    </section>
  )
}

function English({ part, label }) {
  if (!part) return null
  if (part.ok) return <div style={{ background: '#fff8e6', padding: 8, borderRadius: 6, marginTop: 4 }}><b>{label} (machine translation):</b> {part.english}</div>
  if (part.reason === 'already English' || part.reason === 'no reply') return null
  return <div style={{ color: WARN, marginTop: 4 }}>{label}: {part.reason}</div>
}

function TicketTimeline({ id, token, onClose }) {
  const [t, msg] = useApi(`/console/tickets/${id}`, token, [id])
  if (msg) return <p style={{ color: BAD }}>{msg}</p>
  if (!t) return <p style={{ color: MUTED }}>Loading ticket…</p>
  const d = t.decision || {}
  const c = d.classification || {}
  const a = d.answer || {}
  const g = d.guard || {}
  const m = d.merge || {}
  const tr = t.translation || {}
  const review = (t.reviews || []).filter((r) => r.kind === 'reply').slice(-1)[0]
  return (
    <aside style={{ border: `1px solid ${LINE}`, borderRadius: 10, padding: 14, background: '#fff', alignSelf: 'start' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <h3 style={{ margin: 0 }}>Ticket {t.ref}</h3>
        <button onClick={onClose}>Close</button>
      </div>
      <p style={{ color: MUTED, fontSize: 13, margin: '4px 0' }}>{t.tenant_id} · region {t.region || '–'} · {t.language} · {t.bucket}</p>

      <Step title="What the customer asked (masked)">
        <div dir="auto" style={{ whiteSpace: 'pre-wrap' }}>{t.masked_body}</div>
        <English part={tr.question} label="English" />
      </Step>
      <Step title="Classification">
        Team <b>{c.team || '–'}</b> with confidence <b>{c.confidence ?? '–'}</b> ({c.branch || '–'}); decided by {c.decided_by || '–'}.
        {' '}Layers: keywords {c.layers?.keywords || '–'}, similar past tickets {c.layers?.similar || '–'}, model {c.layers?.model || 'not asked'}.
        {c.second && <> Runner-up: {c.second}.</>}
        {c.injection && <div style={{ color: BAD }}>Prompt injection detected: no model was given this text.</div>}
        {c.priority_signal && <div style={{ color: WARN }}>P1 signal (pay or filing at risk).</div>}
      </Step>
      {(m.duplicate_of || m.incident_id || m.jira_key) && (
        <Step title="Merged">
          {m.duplicate_of && <div>Duplicate of {m.duplicate_of} ({m.duplicate_reason})</div>}
          {m.incident_id && <div>Part of incident {String(m.incident_id).slice(0, 8)} ({m.incident_size} tickets)</div>}
          {m.jira_key && <div>Linked to Jira {m.jira_key}</div>}
        </Step>
      )}
      <Step title="Routing rule">
        <b>{d.route?.rule || t.route_rule || '–'}</b> → {d.route?.route || t.route}: {d.route?.reason || t.route_reason}
      </Step>
      <Step title="How the answer was found">
        Answered by <b>{TIER[a.tier] || a.tier || '–'}</b>{a.as_of && <> · rules as of {a.as_of}</>}.
        {a.library_similarity != null && <div>Approved library match: {a.library_similarity}</div>}
        {a.cache_similarity != null && <div>Answer cache match: {a.cache_similarity} (same region, language and knowledge version)</div>}
        {!!a.sources?.length && (
          <table style={{ fontSize: 12, marginTop: 6, borderCollapse: 'collapse' }}>
            <thead><tr>{['Source', 'Relevance', 'Has steps', 'Solved before'].map((h) => <th key={h} align="left" style={{ padding: '2px 10px 2px 0', color: MUTED }}>{h}</th>)}</tr></thead>
            <tbody>{a.sources.map((h) => (
              <tr key={h.id}>{[h.title || h.id, h.score ?? '–', h.has_steps ? 'yes' : h.has_steps === false ? 'title only' : '–', h.solved ?? '–'].map((v, i) => <td key={i} style={{ padding: '2px 10px 2px 0' }}>{v}</td>)}</tr>
            ))}</tbody>
          </table>
        )}
        {!!a.facts?.length && <div>Facts used: {a.facts.map((f) => `${f.tool} ${f.source} = ${f.result}`).join('; ')}</div>}
        {!!a.learn_kb?.length && <div style={{ color: WARN }}>Only a guide title was found: support was asked to write the steps once ({a.learn_kb.join(', ')}).</div>}
      </Step>
      <Step title="Checks on the draft" tone={g.ok ? OK : BAD}>
        {g.ok ? <span style={{ color: OK }}>All checks passed</span> : <span style={{ color: BAD }}>Stopped by: {(g.failed || []).join(', ')}</span>}
        {g.replaced_model_draft && <div>The model's draft failed ({g.replaced_model_draft.join(', ')}); the fixed wording from the same sources was used.</div>}
        <div style={{ color: MUTED }}>{(g.passed || []).length} checks passed: {(g.passed || []).join(', ')}</div>
      </Step>
      {review && (
        <Step title="Person's review" tone={review.outcome === 'rejected' ? BAD : review.outcome ? OK : WARN}>
          {review.outcome ? <>Outcome: <b>{review.outcome.replaceAll('_', ' ')}</b>{review.reviewer && <> by {review.reviewer}</>}</> : 'Waiting for a decision'}
          {review.outcome === 'edited' && (
            <div style={{ marginTop: 6 }}>
              <div style={{ color: MUTED }}>Agent proposed:</div><div dir="auto" style={{ whiteSpace: 'pre-wrap', background: '#fdeceb', padding: 6 }}>{review.proposed_draft}</div>
              <div style={{ color: MUTED }}>Sent:</div><div dir="auto" style={{ whiteSpace: 'pre-wrap', background: '#e8f5ee', padding: 6 }}>{review.final_draft}</div>
            </div>
          )}
        </Step>
      )}
      <Step title="What the customer saw">
        {(t.customer_saw || []).length ? t.customer_saw.map((r, i) => <div key={i} dir="auto" style={{ whiteSpace: 'pre-wrap', marginBottom: 6 }}>{r}</div>) : <i>Nothing sent yet</i>}
        <English part={tr.reply} label="English" />
        {t.feedback && <div>Customer said: <b>{t.feedback === 'yes' ? 'solved' : 'not solved'}</b></div>}
      </Step>
    </aside>
  )
}
