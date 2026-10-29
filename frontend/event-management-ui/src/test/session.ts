import { vi } from 'vitest'
import type { User } from '../types'

/** Stubs a stored session whose token names the user, so fetch mocks can tell callers apart. */
export function signInAs(user: User) {
  const session = JSON.stringify({ accessToken: `${user.id} ${user.role}`, expiresAt: 4102444800, user })
  vi.stubGlobal('localStorage', { getItem: () => session, setItem: vi.fn(), removeItem: vi.fn() })
}

export const tokenOf = (init?: RequestInit) => ((init?.headers ?? {}) as Record<string, string>).Authorization ?? ''
