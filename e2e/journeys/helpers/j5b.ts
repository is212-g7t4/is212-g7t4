import type { APIRequestContext } from '@playwright/test'
import {
  TABLE_ID, approveAllEquipment, createUnderReviewEvent, randomWindow, requestEquipment,
} from './stack'

/** Event A holds 40 of 50 tables; event B (same window) has a pending request for 20, so only 10 remain. */
export async function seedJ5b(api: APIRequestContext, runId: string) {
  const window = randomWindow()
  const eventA = `J5b Event A ${runId}`
  const eventB = `J5b Event B ${runId}`
  const eventAId = await createUnderReviewEvent(api, eventA, window)
  const eventBId = await createUnderReviewEvent(api, eventB, window)
  await requestEquipment(api, eventAId, TABLE_ID, 40)
  await approveAllEquipment(api, eventAId)
  await requestEquipment(api, eventBId, TABLE_ID, 20)
  return { eventA, eventB, eventAId, eventBId, window }
}
