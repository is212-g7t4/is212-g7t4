import type { APIRequestContext, Browser, Page } from '@playwright/test'
import { expect } from '@playwright/test'

// Load local journey credentials when the runner is launched without exported
// shell variables. The file is git-ignored; callers may still supply env vars.
try {
  process.loadEnvFile('.env')
} catch {
  // `.env` is optional when credentials are provided by the invoking shell.
}

// Seeded users (database/supabase/seed.sql). SCRUM-8: each signs in through User Service with
// the shared E2E_PASSWORD, so journeys need that env var and the real Supabase accounts.
export const users = {
  lead: { id: 'e7334aa9-eb3a-4c45-84b5-280501b6c109', role: 'Event Coordinator Lead', email: 'alice.tan@connectsphere.example' },
  coordinator: { id: '7912075d-46f5-405b-9af3-05502f42f173', role: 'Event Coordinator', email: 'marcus.lim@connectsphere.example' },
  organiser: { id: '3d89d4d2-3502-4bd9-ade8-c9887f2bee45', role: 'Event Organiser', email: 'michaellee@connect.com' },
  safetyOfficer: { id: '5af3e7c1-2b4d-4e8a-9f60-7d1c3b5a9e21', role: 'Safety Officer', email: 'nurul.huda@connectsphere.example' },
  attendee: { id: '207cd4a6-9aa3-481c-882c-e14311f5b7cf', role: 'Attendee', email: 'attendee@example.com' },
  techSupport: { id: 'ad3d6da3-7220-4f80-9157-2ee4abc0455c', role: 'Technical Support', email: 'wei.chen@connectsphere.example' },
  venueStaff: { id: 'd9e4002b-db91-4939-b87e-50f9cceb5e0a', role: 'Venue Staff', email: 'siti.aminah@connectsphere.example' },
} as const
export type Actor = (typeof users)[keyof typeof users]

const passwordEnv: Record<string, string> = {
  // Set one shared E2E_PASSWORD when the seeded accounts share a password,
  // or these per-role values when they do not. Never commit either form.
  [users.lead.id]: 'E2E_PASSWORD_LEAD',
  [users.coordinator.id]: 'E2E_PASSWORD_COORDINATOR',
  [users.organiser.id]: 'E2E_PASSWORD_ORGANISER',
  [users.techSupport.id]: 'E2E_PASSWORD_TECH_SUPPORT',
  [users.venueStaff.id]: 'E2E_PASSWORD_VENUE_STAFF',
  [users.safetyOfficer.id]: 'E2E_PASSWORD_SAFETY_OFFICER',
  [users.attendee.id]: 'E2E_PASSWORD_ATTENDEE',
}

const ports = { user: 5001, event: 5003, assignment: 5004, reservation: 5010, venue: 5006, venueBooking: 5007, safety: 5012 }
const url = (service: keyof typeof ports, path: string) => `http://localhost:${ports[service]}${path}`

type Login = { accessToken: string; expiresAt: number; user: Record<string, string> }
const logins = new Map<string, Promise<Login>>()

/** Signs `actor` in once per run through User Service's POST /auth/login. */
function signIn(actor: Actor): Promise<Login> {
  if (!logins.has(actor.id)) {
    logins.set(actor.id, (async () => {
      const password = process.env[passwordEnv[actor.id]] || process.env.E2E_PASSWORD
      if (!password) {
        throw new Error(
          `Set ${passwordEnv[actor.id]} or the shared E2E_PASSWORD to sign in as ${actor.role}.`,
        )
      }
      const response = await fetch(url('user', '/auth/login'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: actor.email, password }),
      })
      if (!response.ok) throw new Error(`sign in ${actor.email}: ${response.status} ${await response.text()}`)
      return response.json() as Promise<Login>
    })())
  }
  return logins.get(actor.id)!
}

export const authHeaders = async (actor: Actor) => ({ Authorization: `Bearer ${(await signIn(actor)).accessToken}` })
export const serviceUrl = (service: keyof typeof ports, path: string) => url(service, path)

/** A fresh browser context signed in as `actor`, so several roles can act in one test. */
export async function openAs(browser: Browser, actor: Actor): Promise<Page> {
  const { accessToken, expiresAt, user } = await signIn(actor)
  const session = { accessToken, expiresAt, user: {
    id: user.user_id, username: user.username, email: user.email, role: user.role,
    organization: user.organization, contactDetails: user.contact_details,
  } }
  const context = await browser.newContext()
  const origin = new URL(process.env.FRONTEND_URL ?? 'http://localhost:5174').origin
  await context.addInitScript(({ origin, value }) => {
    if (window.location.origin === origin) localStorage.setItem('session', value)
  }, { origin, value: JSON.stringify(session) })
  return context.newPage()
}

/** A far-future window that is unlikely to collide with seeded events or earlier runs. */
export function randomWindow() {
  const day = new Date(Date.UTC(2031, 0, 1) + Math.floor(Math.random() * 3000) * 86_400_000)
  const date = day.toISOString().slice(0, 10)
  return { start: `${date}T09:00`, end: `${date}T17:00` }
}

async function ok(response: { ok(): boolean; status(): number; text(): Promise<string> }, what: string) {
  expect(response.ok(), `${what}: ${response.status()} ${await response.text()}`).toBe(true)
}

/** Creates an event the coordinator can request equipment for (status "Under Review"). */
export async function createUnderReviewEvent(api: APIRequestContext, name: string, window: { start: string; end: string }) {
  const created = await api.post(url('event', '/events'), {
    headers: await authHeaders(users.organiser),
    data: {
      eventName: name, description: 'E2E journey fixture', purpose: 'E2E journey',
      preferredStartDate: window.start, preferredEndDate: window.end, expectedAttendance: '50',
    },
  })
  await ok(created, 'create event')
  const eventId = (await created.json()).id as string

  await ok(await api.post(url('assignment', `/events/${eventId}/assign-coordinator/${users.coordinator.id}`), {
    headers: await authHeaders(users.lead),
  }), 'assign coordinator')

  await ok(await api.patch(url('event', `/events/${eventId}/progress`), {
    headers: await authHeaders(users.coordinator),
    data: { status: 'Under Review', actionDetails: 'E2E journey fixture' },
  }), 'move to Under Review')
  return eventId
}

export async function requestEquipment(api: APIRequestContext, eventId: string, equipmentId: string, quantity: number) {
  await ok(await api.post(url('reservation', `/equipment-reservations/events/${eventId}/requests`), {
    headers: await authHeaders(users.coordinator),
    data: { items: [{ equipmentId, quantityRequested: quantity, technicalRequirements: '' }] },
  }), 'request equipment')
}

export async function approveAllEquipment(api: APIRequestContext, eventId: string) {
  await ok(await api.patch(url('reservation', `/equipment-reservations/events/${eventId}`), {
    headers: await authHeaders(users.techSupport),
    data: { status: 'Approved' },
  }), 'approve equipment')
}
