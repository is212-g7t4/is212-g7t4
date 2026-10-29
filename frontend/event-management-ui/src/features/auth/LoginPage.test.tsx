/**
 * # SCRUM-8 — User Authentication: login form.
 * AC2: a successful attempt hands the session to the app.
 * AC3: an unsuccessful attempt shows why and keeps the user on the login page.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { LoginPage } from './LoginPage'
import { signIn } from './session'

vi.mock('./session', () => ({ signIn: vi.fn() }))
afterEach(() => vi.clearAllMocks())

async function submit(email: string, password: string) {
  await userEvent.type(screen.getByLabelText(/Email/), email)
  await userEvent.type(screen.getByLabelText(/Password/), password)
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

test('AC2: signing in passes the session on', async () => {
  const session = { accessToken: 't', expiresAt: 4102444800, user: { id: 'u1', username: 'Wei', email: '', organization: '', role: 'Attendee' as const } }
  vi.mocked(signIn).mockResolvedValue(session)
  const onSignedIn = vi.fn()
  render(<LoginPage onSignedIn={onSignedIn} />)

  await submit('w@x.com', 'secret')

  expect(signIn).toHaveBeenCalledWith('w@x.com', 'secret')
  expect(onSignedIn).toHaveBeenCalledWith(session)
})

test('AC3: a failed attempt shows the error and lets the user try again', async () => {
  vi.mocked(signIn).mockRejectedValue(new Error('Incorrect email or password.'))
  const onSignedIn = vi.fn()
  render(<LoginPage onSignedIn={onSignedIn} />)

  await submit('w@x.com', 'wrong')

  expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
  expect(onSignedIn).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled()
})
