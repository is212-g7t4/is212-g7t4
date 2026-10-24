import type { APIRequestContext, Browser, Page } from '@playwright/test'
import { expect } from '@playwright/test'

// Seeded users (database/supabase/seed.sql). The UI "logs in" by reading activeUserId from localStorage.
export const users = {
  lead: { id: 'e7334aa9-eb3a-4c45-84b5-280501b6c109', role: 'Event Coordinator Lead' },
  coordinator: { id: '7912075d-46f5-405b-9af3-05502f42f173', role: 'Event Coordinator' },
  organiser: { id: '3d89d4d2-3502-4bd9-ade8-c9887f2bee45', role: 'Event Organiser' },
  techSupport: { id: 'ad3d6da3-7220-4f80-9157-2ee4abc0455c', role: 'Technical Support' },
  venueStaff: { id: 'd9e4002b-db91-4939-b87e-50f9cceb5e0a', role: 'Venue Staff' },
} as const
export type Actor = (typeof users)[keyof typeof users]

export const TABLE_ID = '2ebcd2d3-636b-48e7-8784-ddef1d2d550c' // "6-foot folding table", stock 50
export const TABLE_STOCK = 50

const ports = { event: 5003, assignment: 5004, reservation: 5010 }
const url = (service: keyof typeof ports, path: string) => `http://localhost:${ports[service]}${path}`
const devHeaders = (actor: Actor) => ({ 'X-Dev-User-Id': actor.id, 'X-Dev-Role': actor.role })

/** A fresh browser context logged in as `actor`, so several roles can act in one test. */
export async function openAs(browser: Browser, actor: Actor): Promise<Page> {
  const context = await browser.newContext()
  await context.addInitScript((id) => localStorage.setItem('activeUserId', id), actor.id)
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
    data: {
      eventName: name, description: 'E2E journey fixture', purpose: 'E2E journey',
      preferredStartDate: window.start, preferredEndDate: window.end, expectedAttendance: '50',
      organiserId: users.organiser.id,
    },
  })
  await ok(created, 'create event')
  const eventId = (await created.json()).id as string

  await ok(await api.post(url('assignment', `/events/${eventId}/assign-coordinator/${users.coordinator.id}`), {
    data: { actingUserId: users.lead.id },
  }), 'assign coordinator')

  await ok(await api.patch(url('event', `/events/${eventId}/progress`), {
    data: { coordinatorId: users.coordinator.id, status: 'Under Review', actionDetails: 'E2E journey fixture' },
  }), 'move to Under Review')
  return eventId
}

export async function requestEquipment(api: APIRequestContext, eventId: string, equipmentId: string, quantity: number) {
  await ok(await api.post(url('reservation', `/equipment-reservations/events/${eventId}/requests`), {
    headers: devHeaders(users.coordinator),
    data: { items: [{ equipmentId, quantityRequested: quantity, technicalRequirements: '' }] },
  }), 'request equipment')
}

export async function approveAllEquipment(api: APIRequestContext, eventId: string) {
  await ok(await api.patch(url('reservation', `/equipment-reservations/events/${eventId}`), {
    headers: devHeaders(users.techSupport),
    data: { status: 'Approved' },
  }), 'approve equipment')
}
