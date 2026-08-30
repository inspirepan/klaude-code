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
    sourcemap: false, // klaude: keep the shipped bundle small (maps added ~6.6 MB to the wheel)
  },
  resolve: {
    dedupe: ['react', 'react-dom'],
  },
})
