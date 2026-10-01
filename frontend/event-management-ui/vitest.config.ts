import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      include: [
        'src/features/calendar/**.{ts,tsx}',
        'src/pages/VenueCalendarPage.tsx',
      ],
      exclude: ['**/*.test.*'],
    },
  },
})
