import { useEffect, useState } from 'react'

// Shows whether the page can reach the API through the /api proxy.
export default function ApiStatus() {
  const [status, setStatus] = useState('checking…')
  useEffect(() => {
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((body) => setStatus(`● live · ${body.version || 'dev'} · ${body.aws_region}`))
      .catch((err) => setStatus(`API unreachable (${err})`))
  }, [])
  return <span data-testid="api-status" style={{ color: '#5f6f73' }}>{status}</span>
}
