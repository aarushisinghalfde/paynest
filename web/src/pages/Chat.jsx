import ApiStatus from '../ApiStatus.jsx'

// Phase 5 adds the message box and live replies over WebSockets.
export default function Chat() {
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24 }}>
      <h1>Customer chat</h1>
      <p>Messages will appear here.</p>
      <ApiStatus />
    </main>
  )
}
