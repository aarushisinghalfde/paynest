import ApiStatus from '../ApiStatus.jsx'

// Phase 10 adds the review queue (sorted by SLA deadline) and approve / edit / reject.
export default function Review() {
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24 }}>
      <h1>Reviewer console</h1>
      <p>No tickets waiting for review.</p>
      <ApiStatus />
    </main>
  )
}
