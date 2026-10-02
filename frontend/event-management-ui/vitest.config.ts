import { configDefaults, defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    exclude: [...configDefaults.exclude, 'e2e/**'],
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      include: [
        'src/features/calendar/**.{ts,tsx}',
        'src/pages/VenueCalendarPage.tsx',
        'src/features/venue/venueSearch.ts',
        'src/features/venue/permissions.ts',
        'src/pages/VenueSearchPage.tsx',
      ],
      exclude: ['**/*.test.*'],
    },
  },
})
