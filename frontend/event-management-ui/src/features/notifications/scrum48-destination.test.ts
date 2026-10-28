/**
 * SCRUM-48 — AC1/AC2/AC3 shared equipment notification destination contract.
 * Supporting validation rules, not extra business ACs. Public notificationPath
 * seam only: these retrospective cases prove safe structured URL construction,
 * not access enforcement or delivery. Literals come from the destination contract.
 * AC1=submission, AC2=approval, AC3=rejection; this pure-function suite
 * protects their shared destination but proves none of their business triggers.
 * No browser, HTTP call, database or broker is used.
 */
import { describe, expect, it } from 'vitest'
import { notificationPath } from './notifications'

const eventId = 'ABCDEF00-1234-5678-9ABC-DEF012345678'
const first = '40000000-0000-0000-0000-000000000001'
const second = '40000000-0000-0000-0000-000000000002'
const destination = (requestIds: unknown, event: unknown = eventId) => ({ kind: 'equipment-requests', eventId: event, requestIds })

describe('SCRUM-48 supporting structured destination boundaries', () => {
  it('one request keeps a valid uppercase event UUID without rewriting identity', () => {
    // Arrange / Act / Assert: valid UUID case is accepted and preserved literally.
    expect(notificationPath(destination([first]))).toBe('/equipment-requests?event=ABCDEF00-1234-5678-9ABC-DEF012345678&request=40000000-0000-0000-0000-000000000001')
  })
  it('multi-item and repeated request IDs preserve producer order rather than broadening the query', () => {
    // Arrange: reversed order and a repeat; Act: build through the public seam.
    const path = notificationPath(destination([second, first, second]))
    // Assert: exact allowlisted route, stable order, no inferred targets.
    expect(path).toBe('/equipment-requests?event=ABCDEF00-1234-5678-9ABC-DEF012345678&request=40000000-0000-0000-0000-000000000002&request=40000000-0000-0000-0000-000000000001&request=40000000-0000-0000-0000-000000000002')
  })
  it('accepts the maximum 50 request IDs without silently dropping a target', () => {
    // Arrange: distinct valid contract IDs at the inclusive maximum.
    const ids = Array.from({ length: 50 }, (_, i) => `40000000-0000-0000-0000-${String(i + 1).padStart(12, '0')}`)
    const path = notificationPath(destination(ids))!
    // Assert: maximum boundary is navigable and every target survives in order.
    expect(path.startsWith('/equipment-requests?event=')).toBe(true)
    expect(new URL(path, 'http://localhost').searchParams.getAll('request')).toEqual(ids)
    expect(new URL(path, 'http://localhost').searchParams.getAll('request')).toHaveLength(50)
  })
  /** Supporting request-ID validation. Cases cover empty/51-ID size boundaries,
   * missing/null/scalar/object values, invalid members, mixed valid/invalid IDs,
   * query injection and whitespace. Each must return null, never an unscoped list.
   */
  it.each([
    [], Array(51).fill(first), undefined, null, first, {}, [null], [false], [1], [{}], [''],
    ['not-a-uuid'], [first, 'bad'], [`${first}&event=evil`], [` ${first}`], [`${first}\n`],
  ])('rejects invalid/empty/oversized request targets instead of returning an untargeted page: %j', requestIds => {
    // Arrange / Act / Assert: malformed producer values must have no navigation path.
    expect(notificationPath(destination(requestIds))).toBeNull()
  })
  it.each([undefined, null, 1, {}, '', 'not-a-uuid', '//evil.test', `${eventId}?request=${first}`, ` ${eventId}`])('rejects invalid event identity %j', event => {
    // Given malformed event identity, when building a path, then refuse the whole
    // destination: a valid request ID cannot make an invalid event safe.
    expect(notificationPath({ kind: 'equipment-requests', eventId: event, requestIds: [first] })).toBeNull()
  })
  it.each([undefined, null, false, 3, '', 'https://evil.test', [], { kind: 'unknown' }])('rejects absent or arbitrary unstructured destination %j', value => {
    // Given no supported structured destination, return no link rather than trusting
    // an arbitrary URL. This is URL validation, not authorization enforcement.
    expect(notificationPath(value)).toBeNull()
  })
})
