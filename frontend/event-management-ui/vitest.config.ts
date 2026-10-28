import { configDefaults, defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    exclude: [...configDefaults.exclude, 'e2e/**', 'e2e-real/**'],
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      // Machine-readable totals accompany the visible report; no paths are hidden.
      reporter: ['text', 'json', 'json-summary'],
      include: [
        // SCRUM-48: retain the existing whitelist and expose whole changed modules,
        // including App's legacy gaps; a feature-only percentage is not a module gate.
        'src/App.tsx',
        'src/features/notifications/notifications.ts',
        'src/pages/EquipmentRequestsPage.tsx',
        'src/features/calendar/**.{ts,tsx}',
        'src/pages/VenueCalendarPage.tsx',
        'src/features/venue/venueSearch.ts',
        'src/features/venue/venueClosures.ts',
        'src/features/venue/VenueClosuresPanel.tsx',
        'src/features/venue/permissions.ts',
        'src/pages/VenueSearchPage.tsx',
      ],
      exclude: ['**/*.test.*'],
    },
  },
})
