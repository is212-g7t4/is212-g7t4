/** SCRUM-46 Attendee Registration and Update Notifications.
 * Story: As an Attendee, I want to receive notifications about my registration status, so that I can confirm my place and stay updated on event changes.
 * AC1 Given an Attendee successfully registers for an event, the system sends an in-app notification confirming their registration with the event name, date, time, venue, and registration reference number.
 * AC2 Given an Attendee successfully withdraws their registration, the system sends an in-app notification confirming the withdrawal with the event name.
 * AC3 Given an event cancellation takes effect, or a change to its date, time or venue is approved and applied, all currently registered Attendees receive an in-app notification with the event name and cancellation status or updated details, as applicable.
 * Coverage AC1/2: full reference remains visible after actions. AC3: cancelled-history targeted navigation.
 * Component/pure boundaries; APIs are doubled. Does not prove delivery or browser journeys.
 * AC = acceptance criterion; DR = supporting design rule.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { notificationPath } from '../features/notifications/notifications'
import { loadAttendeeRegistrations } from '../features/registration/attendeeRegistrations'
import { AttendeeRegistrationsPage } from './AttendeeRegistrationsPage'
import type { AttendeeRegistration } from '../features/registration/attendeeRegistrations'
vi.mock('../features/registration/attendeeRegistrations',()=>({loadAttendeeRegistrations:vi.fn(),withdrawRegistration:vi.fn()}))
const ref='33333333-3333-4333-8333-333333333333'
const user='22222222-2222-4222-8222-222222222222'
// Synthetic history deliberately separates Event Cancelled from Registration Confirmed.
// The component receives this through a doubled loader; no backend mutation occurs.
const registration: AttendeeRegistration={id:ref,attendeeId:user,registrationDate:null,withdrawnAt:null,status:'Confirmed',
 attendeeName:'Synthetic',attendeeEmail:'user@example.com',attendeeOrganization:'',venue:null,approvedVenueName:null,
 event:{id:'11111111-1111-4111-8111-111111111111',eventName:'Workshop',status:'Cancelled',
 description:'History',purpose:'',preferredStartDate:'2030-03-01T09:00:00+08:00',preferredEndDate:'2030-03-01T17:00:00+08:00',
 expectedAttendance:'20',venueRequirements:'',accessibilityNeeds:'',equipmentRequirements:'',registrationNeeds:'',
 submittedAt:null,coordinatorId:null,organiserId:null,decision:null,decisionHistory:[],actionDetails:'',actionHistory:[]}}

// AC1 / AC2 / AC3 ---- navigation shared by all attendee message types.
/** Boundary: give the real destination mapper a valid registration UUID and a path traversal value.
 * Only the UUID may produce /registrations?registration=..., never an internal Event link.
 * This guards notification navigation; it is a pure-function check, not access-control or delivery proof.
 */
test('AC1/2/3: attendee destinations target a UUID registration, not an internal event page',()=>{
 expect(notificationPath({kind:'attendee-registration',registrationId:ref})).toBe(`/registrations?registration=${ref}`)
 expect(notificationPath({kind:'attendee-registration',registrationId:'../../events'})).toBeNull()
})
// AC3 ---- a cancelled event remains a meaningful notification destination.
/** Normal: the mocked history loader returns an unrelated record before the targeted cancelled event.
 * Render the real page with that target and expect its full reference, Event Cancelled label,
 * unchanged Confirmed registration badge and no withdrawal button. Otherwise a cancellation
 * alert could open the wrong record or imply that cancellation withdrew the attendee.
 * React rendering/target selection run; APIs, notification delivery and browser navigation do not.
 */
test('AC3: notification opens the relevant cancelled registration and keeps its Confirmed status',async()=>{
 // Arrange: order is intentionally unrelated-first so picking the first row cannot pass.
 vi.mocked(loadAttendeeRegistrations).mockResolvedValue([{...registration,id:'44444444-4444-4444-8444-444444444444',event:{...registration.event,eventName:'Other event'}},registration])
 // Act: supply the notification registration target to the real component.
 render(<AttendeeRegistrationsPage role="Attendee" attendeeId={user} targetRegistrationId={ref} />)
 // Assert: cancellation is Event state, not a changed registration status.
 expect(await screen.findByRole('heading',{name:'Registration details'})).toBeInTheDocument()
 expect(screen.getByText(ref)).toBeInTheDocument()
 expect(screen.getByText('Event Cancelled')).toBeInTheDocument()
 expect(screen.getByText('Confirmed',{selector:'.status-badge'})).toBeInTheDocument()
 expect(screen.queryByRole('button',{name:'Withdraw registration'})).not.toBeInTheDocument()
})

// Supporting DR ---- changing the notification target resets already-open details.
/** Boundary: start with Workshop open, then supply a second target on the same component instance.
 * The real page must switch to Second workshop and its reference and remove the first reference.
 * This catches stale local detail state when a second notification is opened; only history loading
 * is mocked, and rerender is not a claim that a real browser click or inbox delivery ran.
 */
test('DR: a second notification target replaces an already open registration detail',async()=>{
 const second={...registration,id:'44444444-4444-4444-8444-444444444444',event:{...registration.event,eventName:'Second workshop'}}
 vi.mocked(loadAttendeeRegistrations).mockResolvedValue([registration,second])
 const view=render(<AttendeeRegistrationsPage role="Attendee" attendeeId={user} targetRegistrationId={ref} />)
 expect(await screen.findByRole('heading',{name:'Workshop',level:2})).toBeInTheDocument()
 // Act: reuse the mounted page, as opening another notification does.
 view.rerender(<AttendeeRegistrationsPage role="Attendee" attendeeId={user} targetRegistrationId={second.id} />)
 // Assert: both the displayed title and full reference belong to the second target.
 await waitFor(()=>expect(screen.getByRole('heading',{name:'Second workshop',level:2})).toBeInTheDocument())
 expect(screen.getByText(second.id)).toBeInTheDocument()
 expect(screen.queryByText(ref)).not.toBeInTheDocument()
})
