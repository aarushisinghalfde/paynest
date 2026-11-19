import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `npm run dev` on the laptop: /api/* goes to the API on port 8000.
// In Docker, nginx does the same proxying (see nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', rewrite: (p) => p.replace(/^\/api/, '') },
    },
  },
})
