import type { User } from '../../types'
import { toUser, type ApiUser } from '../user/users'

// SCRUM-8: the signed-in user's Supabase access token and profile.
const SESSION_STORAGE_KEY = 'session'
export const SESSION_ENDED_EVENT = 'connectsphere:session-ended'

export interface Session {
  accessToken: string
  // Seconds since the epoch, as Supabase reports it.
  expiresAt: number
  user: User
}

const userServiceUrl = () => import.meta.env.VITE_USER_SERVICE_URL || 'http://localhost:5001'

export function loadSession(): Session | null {
  try {
    const session = JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY) ?? 'null') as Session | null
    return session && session.expiresAt * 1000 > Date.now() ? session : null
  } catch {
    return null
  }
}

export function endSession() {
  try {
    localStorage.removeItem(SESSION_STORAGE_KEY)
  } catch {
    // localStorage unavailable — there is no stored session to remove.
  }
  window.dispatchEvent(new Event(SESSION_ENDED_EVENT))
}

export async function signIn(email: string, password: string): Promise<Session> {
  const response = await fetch(`${userServiceUrl()}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to sign in.')
  const session: Session = { accessToken: body.accessToken, expiresAt: body.expiresAt, user: toUser(body.user as ApiUser) }
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session))
  } catch {
    // localStorage unavailable (e.g. private browsing) — the session lasts until reload.
  }
  return session
}

/** `fetch` that sends the signed-in user's token; a 401 means the session is over. */
export async function authFetch(...args: Parameters<typeof fetch>): Promise<Response> {
  const session = loadSession()
  if (session) {
    const [, init] = args
    args[1] = { ...init, headers: { ...(init?.headers as Record<string, string>), Authorization: 'Bearer ' + session.accessToken } }
  }
  const response = await fetch(...args)
  if (response.status === 401) endSession()
  return response
}
