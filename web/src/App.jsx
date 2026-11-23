import Chat from './pages/Chat.jsx'
import Review from './pages/Review.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Knowledge from './pages/Knowledge.jsx'
import ApiStatus from './ApiStatus.jsx'

// The control room is the landing page; customer chat, review and knowledge import sit in one top bar.
// Plain path matching keeps the app free of a router dependency.
const PAGES = [['/', 'Control room'], ['/chat', 'Customer chat'], ['/review', 'Review'], ['/knowledge', 'Knowledge']]

function Nav({ path }) {
  const active = (p) => (p === '/' ? path === '/' || path.startsWith('/dashboard') : path.startsWith(p))
  return (
    <nav style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '8px 24px', borderBottom: '1px solid #d6e2df',
      fontFamily: 'inherit', background: '#fff', position: 'sticky', top: 0, zIndex: 5 }}>
      <b style={{ marginRight: 16, color: '#16262E' }}>Payce Support Assist</b>
      {PAGES.map(([p, label]) => (
        <a key={p} href={p} style={{ padding: '6px 10px', borderRadius: 6, fontSize: 14, textDecoration: 'none',
          color: active(p) ? '#fff' : '#16262E', background: active(p) ? '#16262E' : 'transparent' }}>{label}</a>
      ))}
      <span style={{ marginLeft: 'auto', fontSize: 12 }}><ApiStatus /></span>
    </nav>
  )
}

export default function App() {
  const path = window.location.pathname
  let page = <Dashboard />
  if (path.startsWith('/chat')) page = <Chat />
  else if (path.startsWith('/review')) page = <Review />
  else if (path.startsWith('/knowledge')) page = <Knowledge />
  return (<><Nav path={path} />{page}</>)
}
