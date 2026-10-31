import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  envDir: process.env.E2E_ISOLATED === '1' ? false : undefined,
  server: {
    port: 5174,
    strictPort: true,
  },
})
