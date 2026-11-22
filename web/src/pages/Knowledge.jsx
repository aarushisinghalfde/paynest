import { useEffect, useState } from 'react'

// Knowledge import (admin token). Upload support articles (Markdown, HTML or text, e.g. a
// Confluence export) and a CSV of approved How-To answers. The API masks everything before
// it is stored in the database; the agent uses it within a minute. Statutory articles
// (PF, WPS, TDS, gratuity) are only used for drafts a specialist reviews.
const INK = '#16262E'
const MUTED = '#5f6f73'

function readAll(files) {
  return Promise.all([...files].map((f) => f.text().then((text) => ({ filename: f.name, text }))))
}

export default function Knowledge() {
  const [token, setToken] = useState(sessionStorage.getItem('adminToken') || '')
  const [articles, setArticles] = useState([])
  const [csv, setCsv] = useState(null)
  const [result, setResult] = useState(null)
  const [list, setList] = useState(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    if (!token) return
    const r = await fetch('/api/knowledge', { headers: { 'X-Admin-Token': token } })
    if (r.ok) setList(await r.json())
    else setMsg(`Cannot load: HTTP ${r.status}`)
  }

  useEffect(() => { sessionStorage.setItem('adminToken', token); load() }, [token])

  async function upload() {
    setBusy(true); setMsg(''); setResult(null)
    try {
      const r = await fetch('/api/knowledge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Admin-Token': token },
        body: JSON.stringify({ articles, answers_csv: csv?.text ?? null, imported_by: 'support' }),
      })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) { setMsg(`Not imported: ${body.detail ?? `HTTP ${r.status}`}`); return }
      setResult(body); setArticles([]); setCsv(null); load()
    } finally { setBusy(false) }
  }

  async function withdraw(kbId) {
    const r = await fetch(`/api/knowledge/${encodeURIComponent(kbId)}`, { method: 'DELETE', headers: { 'X-Admin-Token': token } })
    setMsg(r.ok ? `Withdrawn: ${kbId}` : `HTTP ${r.status}`); load()
  }

  const cell = { padding: '6px 8px', borderBottom: '1px solid #edf2f1', textAlign: 'left', verticalAlign: 'top' }

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24, maxWidth: 980, margin: '0 auto', color: INK }}>
      <h1 style={{ marginBottom: 4 }}>Knowledge import</h1>
      <p style={{ color: MUTED, marginTop: 0 }}>
        Articles and approved answers go into the database the agent answers How-To questions from.
        Personal data is masked before storing. Statutory articles are used only for drafts a specialist reviews.
      </p>
      <label>Admin token <input type="password" value={token} onChange={(e) => setToken(e.target.value)} /></label>

      <section style={{ background: '#F4F8F7', borderRadius: 10, padding: 16, marginTop: 16 }}>
        <h2 style={{ fontSize: 17, marginTop: 0 }}>1. Articles</h2>
        <p style={{ fontSize: 13, color: MUTED }}>
          .md, .txt or .html. Put the id in the file name (<code>KB-0105 Downloading payslips.md</code>) or start the file with
          front matter: <code>---</code> / <code>id: KB-0105</code> / <code>title: …</code> / <code>region: ALL</code> / <code>language: en</code> / <code>---</code>.
          Re-uploading an id replaces its text.
        </p>
        <input type="file" multiple accept=".md,.txt,.html,.htm" onChange={async (e) => setArticles(await readAll(e.target.files))} />
        {!!articles.length && <p style={{ fontSize: 13 }}>{articles.length} file(s): {articles.map((a) => a.filename).join(', ')}</p>}

        <h2 style={{ fontSize: 17 }}>2. Approved answers (optional)</h2>
        <p style={{ fontSize: 13, color: MUTED }}>CSV with columns <code>question, answer</code> and optionally <code>language, region, kb_ids</code> (ids separated by ;).</p>
        <input type="file" accept=".csv" onChange={async (e) => setCsv(e.target.files[0] ? (await readAll([e.target.files[0]]))[0] : null)} />

        <div style={{ marginTop: 14 }}>
          <button disabled={busy || !token || (!articles.length && !csv)} onClick={upload}>
            {busy ? 'Importing…' : 'Import into the database'}
          </button>
        </div>
      </section>

      {msg && <p style={{ color: msg.startsWith('Withdrawn') ? INK : 'crimson' }}>{msg}</p>}
      {result && (
        <section style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 17 }}>Imported</h2>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
            <thead><tr>{['Article', 'Title', 'Parts', 'Use', 'Values masked'].map((h) => <th key={h} style={{ ...cell, color: MUTED }}>{h}</th>)}</tr></thead>
            <tbody>
              {result.articles.map((a) => (
                <tr key={a.kb_id}><td style={cell}>{a.kb_id}</td><td style={cell}>{a.title}</td><td style={cell}>{a.chunks}</td>
                  <td style={cell}>{a.topic.startsWith('statutory') ? 'Reviewed drafts only (statutory)' : 'How-To answers'}</td><td style={cell}>{a.masked}</td></tr>
              ))}
            </tbody>
          </table>
          {!!result.answers_imported && <p style={{ fontSize: 13 }}>{result.answers_imported} approved answer(s) added to the library ({result.answers_masked_values} values masked).</p>}
          <p style={{ fontSize: 13, color: MUTED }}>The agent starts using this within a minute.</p>
        </section>
      )}

      {list && (
        <section style={{ marginTop: 20 }}>
          <h2 style={{ fontSize: 17 }}>In the database</h2>
          <p style={{ fontSize: 13, color: MUTED }}>
            Approved answers in the library: {Object.entries(list.library || {}).map(([k, v]) => `${v} ${k.replace('_', ' ')}`).join(', ') || 'none yet'}
          </p>
          {!list.articles?.length ? <p style={{ fontSize: 13 }}>No imported articles yet.</p> : (
            <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
              <thead><tr>{['Article', 'Title', 'Region', 'Parts', 'Use', ''].map((h) => <th key={h} style={{ ...cell, color: MUTED }}>{h}</th>)}</tr></thead>
              <tbody>
                {list.articles.map((a) => (
                  <tr key={a.kb_id}><td style={cell}>{a.kb_id}</td><td style={cell}>{a.title}</td><td style={cell}>{a.region}</td><td style={cell}>{a.chunks}</td>
                    <td style={cell}>{String(a.topic).startsWith('statutory') ? 'Reviewed only' : 'How-To'}</td>
                    <td style={cell}><button onClick={() => withdraw(a.kb_id)}>Withdraw</button></td></tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </main>
  )
}
