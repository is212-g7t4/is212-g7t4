import { render, screen, fireEvent } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { VenueCalendarPage } from './VenueCalendarPage'
import { fetchCalendar } from '../features/calendar/api'
import { fetchVenues } from '../features/venue/venues'
vi.mock('../features/calendar/api',()=>({fetchCalendar:vi.fn()}))
vi.mock('../features/venue/venues',()=>({fetchVenues:vi.fn()}))
afterEach(()=>vi.clearAllMocks())
test('SCRUM174 month prioritises closed preview and day shows reason and active hold', async()=>{
 const id='00000000-0000-0000-0000-000000000001'
 vi.mocked(fetchVenues).mockResolvedValue([{id,name:'Hall'}] as Awaited<ReturnType<typeof fetchVenues>>)
 const row={id:'h1',eventId:null,venueId:id,requestedBy:null,reviewedBy:null,blocksSelection:true,requestedStartTime:'2030-01-31T10:00:00+08:00',requestedEndTime:'2030-01-31T12:00:00+08:00'}
 vi.mocked(fetchCalendar).mockResolvedValue([{...row,status:'On Hold'},{...row,id:'closure:c1',kind:'closure',status:'Closed',reason:'Air-conditioning maintenance'}])
 render(<VenueCalendarPage initialDate="2030-01-31" user={{id,role:'Event Coordinator'}} />)
 await screen.findByText(/Closed · 10:00/)
 fireEvent.click(screen.getByRole('button',{name:'Open 2030-01-31'}))
 await screen.findByText(/On hold ·/)
 fireEvent.click(screen.getByText('Closure details'))
 expect(screen.getByText('Air-conditioning maintenance')).toBeVisible()
})
