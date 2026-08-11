import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy targets default to localhost for `npm run dev` on the host, but can be
// overridden via env vars so the dockerized dev server can reach sibling
// services by their compose service names (localhost inside a container points
// at the container itself, not the host).
const PRESETS_TARGET = process.env.VITE_PRESETS_TARGET || 'http://localhost:8005'
const CONFIG_TARGET = process.env.VITE_CONFIG_TARGET || 'http://localhost:8004'
const CONTROL_TARGET = process.env.VITE_CONTROL_TARGET || 'http://localhost:8003'
const QUEUESERVER_TARGET = process.env.VITE_QUEUESERVER_TARGET || 'http://localhost:60610'
const TILED_TARGET = process.env.VITE_TILED_TARGET || 'http://localhost:8000'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api/presets': {
        target: PRESETS_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/presets/, '/api/v1'),
      },
      '/api/config': {
        target: CONFIG_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/config/, '/api/v1'),
      },
      '/api/control': {
        target: CONTROL_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/control/, '/api/v1'),
      },
      '/api/queueserver': {
        target: QUEUESERVER_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/queueserver/, '/api'),
      },
      '/api/tiled': {
        target: TILED_TARGET,
        changeOrigin: true,
        rewrite: (path) => {
          // Fix Finch bug: TiledLookup sends sort=- without field name
          // Replace sort=- with sort=-time (sort by time descending)
          let newPath = path.replace(/^\/api\/tiled/, '/api/v1')
          newPath = newPath.replace(/sort=-(?=&|$)/, 'sort=-time')
          return newPath
        },
      },
    },
  },
})
