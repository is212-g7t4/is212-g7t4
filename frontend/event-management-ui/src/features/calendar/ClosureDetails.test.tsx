import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { InspectionCalendar } from './InspectionCalendar'
import type { CalendarClosure } from './api'
const closure: CalendarClosure = {kind:'closure', id:'closure:c1', eventId:null, venueId:'v1', requestedBy:null, reviewedBy:null, status:'Closed', blocksSelection:true, reason:'Roof repair <script>not HTML</script>', requestedStartTime:'2030-01-31T23:00:00.123456+08:00', requestedEndTime:'2030-02-02T02:00:00+08:00'}
test('SCRUM174 inspected closure has distinct label and expandable original details', async () => {
 const user=userEvent.setup()
 render(<InspectionCalendar start="2030-02-01T00:00:00+08:00" end="2030-02-01T01:00:00+08:00" rows={[closure]} summary="One closure" venueNames={{v1:'Hall'}} onBack={()=>{}} />)
 expect(screen.getByText(/Closed ·/)).toBeVisible()
 const summary=screen.getByText('Closure details')
 await user.click(summary) // Native summary keyboard behavior is verified in Chromium, not jsdom.
 expect(screen.getByText(closure.reason)).toBeVisible()
 expect(screen.getByText('2030-01-31 23:00:00.123456 SGT')).toBeVisible()
 expect(screen.getByText('2030-02-02 02:00:00 SGT')).toBeVisible()
 expect(screen.getByText(/Other bookings, holds and operating conditions still apply/)).toBeVisible()
})
