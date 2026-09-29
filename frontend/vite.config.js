import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],

  // Vitest runs against the same config, so a component under test resolves
  // its imports exactly as it does in the app.
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    // The built bundle is not source; linting and testing it is noise.
    exclude: ['node_modules/**', 'dist/**'],
  },
  server: {
    port: 5173,
    strictPort: false,

    // Listen on all interfaces so the workbench is reachable from a phone
    // or a teammate's laptop on the same network.
    host: true,

    // Proxy the API through the dev server so the browser only ever talks to
    // one origin. That matters for network access: a device loading
    // http://<lan-ip>:5173 would resolve "localhost:8000" to *itself*, not to
    // this machine. Going through the proxy also means no CORS configuration
    // and no LAN address baked into the bundle.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
