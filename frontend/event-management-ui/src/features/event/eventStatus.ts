import type { EventStatus } from './submission'

// Mirrors ALLOWED_TRANSITIONS / SAFETY_BLOCK_MESSAGES in
// services/event-service/app/models.py. The backend is the authority — this
// copy only lets the UI offer the right options and explain what's needed next
// (SCRUM-152 AC1). Keep the two in step.

export const ALLOWED_TRANSITIONS: Record<EventStatus, EventStatus[]> = {
  Submitted: ['Submitted', 'Under Review'],
  'Under Review': ['Under Review', 'Approved', 'Rejected'],
  // A coordinator can't confirm an event; the safety workflow does that, so
  // 'Approved' offers only itself. The next step is submit-for-safety-check.
  Approved: ['Approved'],
  Rejected: ['Rejected'],
  'Pending Safety Check': ['Pending Safety Check'],
  // 'Confirmed' is the preparation stage — there is nothing after it today.
  Confirmed: ['Confirmed'],
  'Safety Changes Requested': ['Safety Changes Requested'],
  Cancelled: ['Cancelled'],
}

// 'Confirmed' means the event passed its Operational Safety Check, so it is
// the stage that counts as "in preparation". Kept as a literal type so the
// message map below can exclude it and still be checked for exhaustiveness.
export const PREPARATION_STATUS = 'Confirmed' as const

// Every status except 'Confirmed' — a 'Confirmed' event is already there, so
// there is nothing to explain. Typing it this way means adding a status to the
// lifecycle is a compile error here until its message is written.
const SAFETY_BLOCK_MESSAGES: Record<Exclude<EventStatus, typeof PREPARATION_STATUS>, string> = {
  Submitted: 'This event must be approved and pass its Operational Safety Check before it can progress to Confirmed.',
  'Under Review': 'This event must be approved and pass its Operational Safety Check before it can progress to Confirmed.',
  Approved: 'Submit this event for safety check for it to progress to Confirmed.',
  Rejected: "This event was rejected, so it can't progress to Confirmed.",
  'Pending Safety Check': "This event is waiting for the Safety Officer's decision.",
  'Safety Changes Requested': 'The Safety Officer has requested changes that must be made and resubmitted.',
  Cancelled: "This event was cancelled after its safety check, so it can't progress to Confirmed.",
}

/** Why an event at `status` can't progress to 'Confirmed' yet (SCRUM-152 AC1). */
export function safetyBlockMessage(status: EventStatus) {
  // Nothing blocks an already-'Confirmed' event; showsSafetyHint() keeps this
  // out of the UI, so the text is a safety net rather than something shown.
  if (status === PREPARATION_STATUS) return 'This event has passed its Operational Safety Check.'
  return SAFETY_BLOCK_MESSAGES[status]
}

// Where the hint is worth showing. 'Confirmed' has already progressed, and on
// 'Submitted'/'Under Review'/'Rejected' the safety check is not yet the
// coordinator's next concern, so the line would only be noise. The API still
// blocks a crafted call from any of them.
const SHOWS_SAFETY_HINT: EventStatus[] = [
  'Approved', 'Pending Safety Check', 'Safety Changes Requested',
]

export function showsSafetyHint(status: EventStatus) {
  return SHOWS_SAFETY_HINT.includes(status)
}
