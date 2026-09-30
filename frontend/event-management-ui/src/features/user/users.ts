import type { Role, User } from '../../types'

interface ApiUser {
  user_id: string
  username: string
  email: string
  role: string
  organization: string
  manager_id: string | null
}

function toUser(apiUser: ApiUser): User {
  return {
    id: apiUser.user_id,
    username: apiUser.username,
    email: apiUser.email,
    role: apiUser.role as Role,
    organization: apiUser.organization,
    managerId: apiUser.manager_id,
  }
}

export async function fetchUsers(): Promise<User[]> {
  const response = await fetch(`${import.meta.env.VITE_USER_SERVICE_URL || 'http://localhost:5001'}/users`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load users.')
  return (body.users as ApiUser[]).map(toUser)
}
