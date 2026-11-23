import { useEffect, useState } from 'react'
import { Card, MUTED, Note, Page } from '../theme.jsx'

// Knowledge import (admin token). Upload support articles (Markdown, HTML or text, e.g. a
// Confluence export) and a CSV of approved How-To answers. The API masks everything before
// it is stored in the database; the agent uses it within a minute. Statutory articles
// (PF, WPS, TDS, gratuity) are only used for drafts a specialist reviews.

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

  return (
    <Page title="Knowledge" subtitle="Articles and approved answers the agent answers How-To questions from. Personal data is masked before storing; statutory articles are used only for drafts a specialist reviews."
      controls={<input type="password" placeholder="Admin token" aria-label="Admin token" value={token}
        onChange={(e) => setToken(e.target.value)} style={{ width: 190 }} />}>
      <Card>
        <h2 style={{ fontSize: 16, marginTop: 0 }}>1. Articles</h2>
        <p style={{ fontSize: 13, color: MUTED, overflowWrap: 'anywhere' }}>
          .md, .txt or .html. Put the id in the file name (<code>KB-0105 Downloading payslips.md</code>) or start the file with
          front matter: <code>---</code> / <code>id: KB-0105</code> / <code>title: …</code> / <code>region: ALL</code> / <code>language: en</code> / <code>url: https://…</code> (optional link to the guide) / <code>---</code>.
          Re-uploading an id replaces its text.
        </p>
        <input type="file" multiple accept=".md,.txt,.html,.htm" onChange={async (e) => setArticles(await readAll(e.target.files))} />
        {!!articles.length && <p style={{ fontSize: 13 }}>{articles.length} file(s): {articles.map((a) => a.filename).join(', ')}</p>}

        <h2 style={{ fontSize: 16 }}>2. Approved answers (optional)</h2>
        <p style={{ fontSize: 13, color: MUTED }}>CSV with columns <code>question, answer</code> and optionally <code>language, region, kb_ids</code> (ids separated by ;).</p>
        <input type="file" accept=".csv" onChange={async (e) => setCsv(e.target.files[0] ? (await readAll([e.target.files[0]]))[0] : null)} />

        <div style={{ marginTop: 14 }}>
          <button className="primary" disabled={busy || !token || (!articles.length && !csv)} onClick={upload}>
            {busy ? 'Importing…' : 'Import into the database'}
          </button>
        </div>
      </Card>

      <Note tone={msg.startsWith('Withdrawn') ? 'ok' : 'bad'}>{msg}</Note>
      {result && (
        <Card>
          <h2 style={{ fontSize: 16, marginTop: 0 }}>Imported</h2>
          <table>
            <thead><tr>{['Article', 'Title', 'Parts', 'Use', 'Values masked'].map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>
              {result.articles.map((a) => (
                <tr key={a.kb_id}><td>{a.kb_id}</td><td>{a.title}</td><td>{a.chunks}</td>
                  <td>{a.topic.startsWith('statutory') ? 'Reviewed drafts only (statutory)' : 'How-To answers'}</td><td>{a.masked}</td></tr>
              ))}
            </tbody>
          </table>
          {!!result.answers_imported && <p style={{ fontSize: 13 }}>{result.answers_imported} approved answer(s) added to the library ({result.answers_masked_values} values masked).</p>}
          <p style={{ fontSize: 13, color: MUTED }}>The agent starts using this within a minute.</p>
        </Card>
      )}

      {list && (
        <Card>
          <h2 style={{ fontSize: 16, marginTop: 0 }}>In the database</h2>
          <p style={{ fontSize: 13, color: MUTED }}>
            Approved answers in the library: {Object.entries(list.library || {}).map(([k, v]) => `${v} ${k.replace('_', ' ')}`).join(', ') || 'none yet'}
          </p>
          {!list.articles?.length ? <p style={{ fontSize: 13 }}>No imported articles yet.</p> : (
            <table>
              <thead><tr>{['Article', 'Title', 'Region', 'Parts', 'Use', ''].map((h) => <th key={h}>{h}</th>)}</tr></thead>
              <tbody>
                {list.articles.map((a) => (
                  <tr key={a.kb_id}><td>{a.kb_id}</td><td>{a.title}</td><td>{a.region}</td><td>{a.chunks}</td>
                    <td>{String(a.topic).startsWith('statutory') ? 'Reviewed only' : 'How-To'}{a.imported_by === 'demo-guides' && <span style={{ color: MUTED }}> (demo guide, replace with the real article)</span>}</td>
                    <td><button className="small" onClick={() => withdraw(a.kb_id)}>Withdraw</button></td></tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </Page>
  )
}
