import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // 5173 is Vite's default and is already taken on this machine by another
    // project, so this app claims its own port and refuses to drift off it —
    // a moving port silently breaks bookmarks and the API proxy origin.
    port: 5180,
    strictPort: true,
    host: '127.0.0.1',
    proxy: {
      // Keeps the browser on one origin in development, so no CORS round trip.
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
})
