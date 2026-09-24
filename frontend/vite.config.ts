import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Nothing unusual here - a stock Vite + React config. The interesting
// part of this app (how it finds the backend) lives in src/api.ts and
// the Dockerfile, not here.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
  },
})
