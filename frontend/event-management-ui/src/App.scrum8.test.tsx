/**
 * # SCRUM-8 — User Authentication
 * AC1: signed-out users see only the login page and no protected data is requested.
 * AC2: a successful sign-in opens the app as that user and requests carry their token.
 * AC3: a failed sign-in, an ended session or a rejected token leaves the user signed out.
 */
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import { authFetch, loadSession } from './features/auth/session'

const apiUser = { user_id: 'u1', username: 'Wei', email: 'w@x.com', role: 'Event Organiser', organization: 'O', contact_details: '' }
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
let stored: Record<string, string>
let http: ReturnType<typeof vi.fn>

beforeEach(() => {
  stored = {}
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => stored[key] ?? null,
    setItem: (key: string, value: string) => { stored[key] = value },
    removeItem: (key: string) => { delete stored[key] },
  })
  // Protected reads stay pending unless a test answers them.
  http = vi.fn((url: string) => url.endsWith('/auth/login')
    ? Promise.resolve(json({ accessToken: 'token', expiresAt: 4102444800, user: apiUser }))
    : new Promise(() => {}))
  vi.stubGlobal('fetch', http)
  window.history.replaceState({}, '', '/')
})
afterEach(() => vi.unstubAllGlobals())

async function signInThroughForm(password = 'secret') {
  await userEvent.type(screen.getByLabelText(/Email/), 'w@x.com')
  await userEvent.type(screen.getByLabelText(/Password/), password)
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

test('AC1: a signed-out visitor sees only the login page and nothing protected is requested', () => {
  render(<App />)

  expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument()
  expect(http).not.toHaveBeenCalled()
})

test('AC2: signing in opens the app as that user and protected requests carry their token', async () => {
  render(<App />)

  await signInThroughForm()

  expect(await screen.findByText('Signed in as Wei — Event Organiser')).toBeInTheDocument()
  expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()
  const protectedCalls = http.mock.calls.filter(([url]) => !String(url).endsWith('/auth/login'))
  expect(protectedCalls.length).toBeGreaterThan(0)
  expect(protectedCalls.every(([, init]) => init?.headers?.Authorization === 'Bearer token')).toBe(true)
})

test('AC3: a failed sign-in keeps the visitor on the login page', async () => {
  http.mockImplementation(() => Promise.resolve(json({ message: 'Incorrect email or password.' }, 401)))
  render(<App />)

  await signInThroughForm('wrong')

  expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
  expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument()
  expect(stored.session).toBeUndefined()
})

test('AC3: signing out returns to the login page and forgets the session', async () => {
  render(<App />)
  await signInThroughForm()

  await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))

  expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  expect(stored.session).toBeUndefined()
})

test('AC1: a token the services reject (401) ends the session', async () => {
  let reject!: () => void
  http.mockImplementation((url: string) => url.endsWith('/auth/login')
    ? Promise.resolve(json({ accessToken: 'token', expiresAt: 4102444800, user: apiUser }))
    : new Promise(resolve => { reject = () => resolve(json({ message: 'Your session is invalid or has expired. Sign in again.' }, 401)) }))
  render(<App />)
  await signInThroughForm()
  await screen.findByText('Signed in as Wei — Event Organiser')

  await act(async () => reject())

  expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  expect(stored.session).toBeUndefined()
})

const storeSession = (expiresAt: number) => {
  stored.session = JSON.stringify({ accessToken: 'token', expiresAt, user: { id: 'u1' } })
}

test('AC2: authFetch adds the bearer token alongside the caller\'s own headers', async () => {
  http.mockResolvedValue(json({}))
  storeSession(4102444800)

  await authFetch('http://service/x', { method: 'PUT', headers: { 'Content-Type': 'application/json' } })

  expect(http).toHaveBeenLastCalledWith('http://service/x', {
    method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer token' },
  })
})

test('AC1: without a session, or with an expired one, authFetch sends the request untouched with no token', async () => {
  http.mockResolvedValue(json({}))
  storeSession(Date.now() / 1000 - 1)

  expect(loadSession()).toBeNull()
  await authFetch('http://service/x')

  expect(http).toHaveBeenCalledWith('http://service/x')
})
