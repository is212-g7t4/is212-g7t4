import type { APIRequestContext } from '@playwright/test'
import { createUnderReviewEvent, randomWindow } from '../../../../helpers/stack'

/** Two separately reviewable requests created by the seeded organiser. */
export async function seedJ6a(api: APIRequestContext, runId: string) {
  const window = randomWindow()
  const approveName = `J6a Event approve ${runId}`
  const rejectName = `J6a Event reject ${runId}`
  const approveId = await createUnderReviewEvent(api, approveName, window)
  const rejectId = await createUnderReviewEvent(api, rejectName, window)
  return { approveName, rejectName, approveId, rejectId }
}
