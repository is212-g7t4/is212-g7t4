import { afterEach, expect, test, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { VenueSearchPage } from './VenueSearchPage'
import * as venues from '../features/venue/venues'
import * as search from '../features/venue/venueSearch'
afterEach(()=>{vi.restoreAllMocks(); window.history.replaceState({},'', '/venue-search')})
test('SCRUM174 overnight search submits distinct dates and restores them from URL', async()=>{
 window.history.replaceState({},'', '/venue-search')
 vi.spyOn(venues,'fetchVenues').mockResolvedValue([])
 const fetch=vi.spyOn(search,'searchVenues').mockResolvedValue([])
 const view=render(<VenueSearchPage role="Event Coordinator" onViewVenue={()=>{}} />)
 for(const [label,value] of [['Start date','2030-01-31'],['Start time','23:00'],['End date','2030-02-02'],['End time','02:00'],['Expected attendance','10']]) fireEvent.change(screen.getByLabelText(new RegExp(`^${label}`)),{target:{value}})
 fireEvent.click(screen.getByRole('button',{name:/Search/}))
 await waitFor(()=>expect(fetch).toHaveBeenCalled())
 expect(new URLSearchParams(window.location.search).get('end')).toBe('2030-02-02T02:00:00')
 expect(fetch.mock.calls[0][0]).toMatchObject({date:'2030-01-31',endDate:'2030-02-02'})
 view.unmount()
 render(<VenueSearchPage role="Event Coordinator" onViewVenue={()=>{}} />)
 expect(screen.getByLabelText(/^End date/)).toHaveValue('2030-02-02')
 await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2))
})
