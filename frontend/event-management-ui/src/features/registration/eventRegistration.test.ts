import { expect, test } from 'vitest'
import { validateRegistrationForm } from './eventRegistration'

test('registration form requires a full name and email', () => {
  expect(validateRegistrationForm({ fullName: '', email: '' })).toEqual({
    fullName: 'Full name is required.',
    email: 'Email address is required.',
  })
})

test('registration form rejects an invalid email', () => {
  expect(validateRegistrationForm({ fullName: 'Adam Yeo', email: 'invalid' })).toEqual({
    email: 'Enter a valid email address.',
  })
})

test('registration form accepts valid required fields', () => {
  expect(validateRegistrationForm({ fullName: 'Adam Yeo', email: 'adam@example.com' })).toEqual({})
})
