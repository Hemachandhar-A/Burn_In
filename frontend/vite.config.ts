/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Relative asset URLs: the build works wherever api/main.py mounts it (routes live in the hash).
  base: './',
  server: { port: 5173, strictPort: true }, // must match the CORS origin in api/main.py
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
})
