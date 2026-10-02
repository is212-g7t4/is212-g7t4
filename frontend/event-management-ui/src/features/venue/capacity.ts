import type { Venue } from './venues'

export function venueCapacityMessage(venue: Venue, expectedAttendance: number) {
  if (venue.capacity === null) {
    return `Capacity could not be determined for ${venue.name} because it has no registered capacity.`
  }
  if (expectedAttendance <= venue.capacity) {
    return `${venue.name} is suitable: its maximum capacity is ${venue.capacity} and the expected attendance is ${expectedAttendance}.`
  }
  return `Capacity warning: ${venue.name}'s maximum capacity is ${venue.capacity}, but the expected attendance is ${expectedAttendance}.`
}
