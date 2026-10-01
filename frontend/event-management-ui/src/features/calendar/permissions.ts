/** Untrusted role text → DEV calendar visibility only, not authentication.
 * Separate from catalogue permissions: Technical Support also inspects availability. */
export function canViewCalendar(role: string): boolean {
  return [
    'Event Coordinator',
    'Venue Staff',
    'Technical Support',
    'Technical Support Staff',
  ].includes(role)
}
