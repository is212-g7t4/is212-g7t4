/** Signed-in role → calendar visibility in the UI; services enforce access.
 * Separate from catalogue permissions: Technical Support also inspects availability. */
export function canViewCalendar(role: string): boolean {
  return [
    'Event Coordinator',
    'Event Coordinator Lead',
    'Venue Staff',
    'Technical Support',
    'Technical Support Staff',
  ].includes(role)
}
