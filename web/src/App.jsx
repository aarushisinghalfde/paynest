import Chat from './pages/Chat.jsx'
import Review from './pages/Review.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Knowledge from './pages/Knowledge.jsx'
import ApiStatus from './ApiStatus.jsx'

// Two windows only, as the build plan asks: /chat (customer) and /review (reviewer).
// Plain path matching keeps the skeleton free of a router dependency.
export default function App() {
  const path = window.location.pathname
  if (path.startsWith('/chat')) return <Chat />
  if (path.startsWith('/review')) return <Review />
  if (path.startsWith('/dashboard')) return <Dashboard />
  if (path.startsWith('/knowledge')) return <Knowledge />
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24 }}>
      <h1>Payce Support Assist</h1>
      <ul>
        <li><a href="/chat">Customer chat</a></li>
        <li><a href="/review">Reviewer console</a></li>
        <li><a href="/dashboard">Support console (lead)</a></li>
        <li><a href="/knowledge">Knowledge import</a></li>
      </ul>
      <ApiStatus />
    </main>
  )
}
