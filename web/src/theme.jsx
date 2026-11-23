// One design for every page: colours, type and the page frame (navy header band + grey canvas).
// Pages import from here; buttons, inputs and tables get their look from index.html.
export const INK = '#13233A'
export const NIGHT = '#13233A'      // header band
export const MUTED = '#5f6f73'
export const SURFACE = '#EEF2F5'    // page canvas
export const LINE = '#e3e8ee'
export const ACCENT = '#2a78d6'     // links, selected tab, primary series
export const OK = '#0ca30c'
export const WARN = '#fab219'
export const WARN_TEXT = '#8a5a00'
export const BAD = '#d03b3b'
export const CONDENSED = "'IBM Plex Sans Condensed', 'IBM Plex Sans', system-ui, sans-serif"
export const WIDTH = 1320

// The page frame. `tabs` sit at the bottom of the band; `flush` lets the first block (the control room's
// river) continue the band without a gap.
export function Page({ title, subtitle, controls, tabs, flush = false, narrow, children }) {
  return (
    <div style={{ background: SURFACE, minHeight: 'calc(100vh - 49px)' }}>
      <main style={{ padding: '0 24px 32px', maxWidth: WIDTH, margin: '0 auto', color: INK }}>
        <header style={{ background: NIGHT, color: '#fff', borderRadius: flush ? 0 : '0 0 10px 10px',
          padding: `18px 20px ${tabs ? 0 : 18}px` }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
            <div>
              <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600, fontFamily: CONDENSED }}>{title}</h1>
              {subtitle && <p style={{ color: '#b9c6d6', margin: '4px 0 0', fontSize: 14, maxWidth: 760 }}>{subtitle}</p>}
            </div>
            {controls && <div className="on-night" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>{controls}</div>}
          </div>
          {tabs}
        </header>
        {!flush && <div style={{ height: 18 }} />}
        <div style={narrow ? { maxWidth: narrow, margin: '0 auto' } : undefined}>{children}</div>
      </main>
    </div>
  )
}

export function Card({ children, style }) {
  return <section style={{ background: '#fff', borderRadius: 6, padding: '16px 18px', marginBottom: 14, ...style }}>{children}</section>
}

export function Note({ children, tone = 'info' }) {
  if (!children) return null
  const color = { info: INK, ok: OK, bad: BAD, warn: WARN_TEXT }[tone]
  return <p role={tone === 'bad' ? 'alert' : undefined} style={{ color, margin: '0 0 12px' }}>{children}</p>
}
