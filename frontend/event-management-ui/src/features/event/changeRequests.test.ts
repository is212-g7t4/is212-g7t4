import { beforeEach, expect, test, vi } from 'vitest'
import { decideChangeRequest, fetchPendingChangeRequests } from './changeRequests'

const fetcher = vi.fn()

beforeEach(() => {
  vi.stubGlobal('fetch', fetcher)
  fetcher.mockReset()
})

test('AC1 loads the coordinator pending queue from Event Workflow Service', async () => {
  fetcher.mockResolvedValue(new Response(JSON.stringify({ changeRequests: [{ id: 'change-1' }] })))

  expect(await fetchPendingChangeRequests('coordinator-1')).toEqual([{ id: 'change-1' }])
  expect(String(fetcher.mock.calls[0][0])).toBe('http://localhost:5014/change-requests?coordinatorId=coordinator-1')
})

test('AC3 approval sends the decision without browser-supplied proposed values', async () => {
  fetcher.mockResolvedValue(new Response(JSON.stringify({ id: 'change-1', status: 'Approved' })))

  await decideChangeRequest('change-1', 'coordinator-1', 'Approved')

  expect(fetcher).toHaveBeenCalledWith('http://localhost:5014/change-requests/change-1', expect.objectContaining({
    method: 'PATCH',
    body: JSON.stringify({ coordinatorId: 'coordinator-1', decision: 'Approved' }),
  }))
})

test('AC4 rejection sends its required reason', async () => {
  fetcher.mockResolvedValue(new Response(JSON.stringify({ id: 'change-1', status: 'Rejected' })))
  await decideChangeRequest('change-1', 'coordinator-1', 'Rejected', 'Venue unavailable.')
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
    coordinatorId: 'coordinator-1', decision: 'Rejected', reason: 'Venue unavailable.',
  })
})

test('impact conflicts remain structured for the review UI', async () => {
  fetcher.mockResolvedValue(new Response(JSON.stringify({
    code: 'CHANGE_CONTRADICTS_ARRANGEMENTS',
    message: 'Cannot approve.',
    conflicts: [{ field: 'expectedAttendance', area: 'venue', message: 'Venue too small.' }],
  }), { status: 409 }))

  await expect(decideChangeRequest('change-1', 'coordinator-1', 'Approved')).rejects.toMatchObject({
    code: 'CHANGE_CONTRADICTS_ARRANGEMENTS',
    conflicts: [{ field: 'expectedAttendance', area: 'venue', message: 'Venue too small.' }],
  })
})
