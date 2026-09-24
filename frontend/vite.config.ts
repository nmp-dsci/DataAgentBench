import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Dev: Vite serves the SPA and proxies the API to FastAPI. In the image FastAPI
// serves the built SPA from the same origin, so the proxy does not exist there.
const API = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8091';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      // CodeMirror (the SQL editor and highlighter) in its own chunk, cached apart from the app
      output: { manualChunks: (id) => (/node_modules\/(@codemirror|@lezer|crelt|style-mod|w3c-keyname)\//.test(id) ? 'codemirror' : undefined) },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: API, changeOrigin: false },
      '/healthz': { target: API, changeOrigin: false },
    },
  },
});
