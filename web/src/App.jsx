import Chat from './pages/Chat.jsx'
import Review from './pages/Review.jsx'
import ApiStatus from './ApiStatus.jsx'

// Two windows only, as the build plan asks: /chat (customer) and /review (reviewer).
// Plain path matching keeps the skeleton free of a router dependency.
export default function App() {
  const path = window.location.pathname
  if (path.startsWith('/chat')) return <Chat />
  if (path.startsWith('/review')) return <Review />
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24 }}>
      <h1>Payce Support Assist</h1>
      <ul>
        <li><a href="/chat">Customer chat</a></li>
        <li><a href="/review">Reviewer console</a></li>
      </ul>
      <ApiStatus />
    </main>
  )
}
