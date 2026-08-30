import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The built page is served by the klaude server from
// src/klaude_code/server/web/ and mounted at the site root. CSS modules ride
// Vite's defaults, exactly as they do upstream.
export default defineConfig({
  base: '/',
  plugins: [react()],
  build: {
    target: 'es2022',
    outDir: '../src/klaude_code/server/web',
    emptyOutDir: true,
    sourcemap: true,
  },
  resolve: {
    dedupe: ['react', 'react-dom'],
  },
})
