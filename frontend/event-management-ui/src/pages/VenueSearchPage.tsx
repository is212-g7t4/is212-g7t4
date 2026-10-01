import { useCallback, useEffect, useRef, useState } from 'react'
import type { Role } from '../types'
import { fetchVenues } from '../features/venue/venues'
import type { Venue } from '../features/venue/venues'
import {
  ACCESSIBILITY_OPTIONS,
  EMPTY_CRITERIA,
  missingRequiredFields,
  searchVenues,
  toQuery,
} from '../features/venue/venueSearch'
import type { VenueSearchCriteria, VenueSearchResult } from '../features/venue/venueSearch'
import { VENUE_SEARCH_NOTICE, canSearchVenues } from '../features/venue/permissions'
import { ArrowRightIcon, SearchIcon } from '../components/Icon'
import { Field, RoleWarning } from '../components/FormControls'
import { InlineLoading, VenueCardGridSkeleton } from '../components/Loading'

const PENDING_HINT = 'Free at this time, but another coordinator has a request waiting for review.'

function badgeClass(availability: string): string {
  return availability.toLowerCase().replace(/\s+/g, '-')
}

/** The catalogue's distinct layouts/facilities, so a facility added under
 *  SCRUM-22 appears in the form without a code change. */
function distinct(venues: Venue[], pick: (venue: Venue) => string[]): string[] {
  return [...new Set(venues.flatMap(pick))].sort()
}

/** Re-create the criteria a search was run with, so browser Back from a venue
 *  detail page returns to that same search instead of an empty form. */
function criteriaFromUrl(): VenueSearchCriteria | null {
  const query = new URLSearchParams(window.location.search)
  const start = query.get('start')
  const end = query.get('end')
  if (!start || !end) return null
  return {
    ...EMPTY_CRITERIA,
    date: start.slice(0, 10),
    startTime: start.slice(11, 16),
    endTime: end.slice(11, 16),
    expectedAttendance: query.get('expectedAttendance') || '',
    minCapacity: query.get('minCapacity') || '',
    location: query.get('location') || '',
    layout: query.get('layout') || '',
    facilities: query.getAll('facility'),
    accessibility: query.getAll('accessibility'),
  }
}

export function VenueSearchPage({ role, onViewVenue }: { role: Role; onViewVenue: (venueId: string) => void }) {
  const [criteria, setCriteria] = useState<VenueSearchCriteria>(() => criteriaFromUrl() ?? EMPTY_CRITERIA)
  const [options, setOptions] = useState<{ locations: string[]; layouts: string[]; facilities: string[] }>({
    locations: [], layouts: [], facilities: [],
  })
  const [optionsError, setOptionsError] = useState('')
  const [results, setResults] = useState<VenueSearchResult[] | null>(null)
  const [message, setMessage] = useState('')
  // A search carried in the URL is re-run on mount, so the first render
  // already shows the loading state rather than an empty result.
  const [searching, setSearching] = useState(() => criteriaFromUrl() !== null)
  // Each search gets a token so a slow earlier response can't overwrite a
  // newer one (or land after Clear all).
  const latestSearch = useRef(0)

  const allowed = canSearchVenues(role)

  useEffect(() => {
    if (!allowed) return
    let active = true
    fetchVenues().then((venues) => {
      if (!active) return
      setOptions({
        locations: distinct(venues, (venue) => (venue.location ? [venue.location] : [])),
        layouts: distinct(venues, (venue) => venue.supportedLayouts),
        facilities: distinct(venues, (venue) => venue.facilities),
      })
    }).catch(() => {
      // The required fields still work — only the suggestions are missing.
      if (active) setOptionsError('Filter options could not be loaded. You can still search by date, time and attendance.')
    })
    return () => { active = false }
  }, [allowed])

  /** Send the search and mirror it into the URL. Caller owns the loading state. */
  const performSearch = useCallback((next: VenueSearchCriteria) => {
    const token = ++latestSearch.current
    window.history.replaceState({}, '', `/venue-search?${toQuery(next)}`)
    searchVenues(next).then((venues) => {
      if (token === latestSearch.current) setResults(venues)
    }).catch((cause: Error) => {
      if (token !== latestSearch.current) return
      setMessage(cause.message)
      setResults(null)
    }).finally(() => {
      if (token === latestSearch.current) setSearching(false)
    })
  }, [])

  const runSearch = (next: VenueSearchCriteria) => {
    const missing = missingRequiredFields(next)
    if (missing.length > 0) {
      // AC2: the app says what is missing; nothing is sent.
      setMessage(`Please fill in the required fields: ${missing.join(', ')}`)
      setResults(null)
      return
    }
    setMessage('')
    setSearching(true)
    performSearch(next)
  }

  // Back from a venue detail page lands here with the search still in the URL.
  const initial = useRef(true)
  useEffect(() => {
    if (!allowed || !initial.current) return
    initial.current = false
    const fromUrl = criteriaFromUrl()
    if (fromUrl) performSearch(fromUrl)
  }, [allowed, performSearch])

  if (!allowed) return <RoleWarning>{VENUE_SEARCH_NOTICE}</RoleWarning>

  const update = (field: keyof VenueSearchCriteria, value: string) =>
    setCriteria((current) => ({ ...current, [field]: value }))

  const toggle = (field: 'facilities' | 'accessibility', value: string) =>
    setCriteria((current) => ({
      ...current,
      [field]: current[field].includes(value)
        ? current[field].filter((item) => item !== value)
        : [...current[field], value],
    }))

  // AC6: one click empties the form, the results and the URL.
  const clearAll = () => {
    latestSearch.current += 1
    setCriteria(EMPTY_CRITERIA)
    setResults(null)
    setMessage('')
    setSearching(false)
    window.history.replaceState({}, '', '/venue-search')
  }

  return <div className="page-stack">
    <section className="intro">
      <h1>Find a venue</h1>
      <p className="muted">Enter when the event runs and how many people are expected. Only venues that fit the requirements and are free at that time are listed.</p>
    </section>

    {optionsError && <p className="muted" role="status">{optionsError}</p>}

    <form className="panel venue-search-form" noValidate onSubmit={(event) => { event.preventDefault(); runSearch(criteria) }}>
      <div className="venue-search-grid">
        <Field label="Date" type="date" required value={criteria.date} onChange={(value) => update('date', value)} />
        <Field label="Start time" type="time" required value={criteria.startTime} onChange={(value) => update('startTime', value)} />
        <Field label="End time" type="time" required value={criteria.endTime} onChange={(value) => update('endTime', value)} />
        <Field label="Expected attendance" type="number" min="1" required placeholder="e.g. 120" value={criteria.expectedAttendance} onChange={(value) => update('expectedAttendance', value)} />
        <Field label="Minimum capacity" type="number" min="1" placeholder="Optional" value={criteria.minCapacity} onChange={(value) => update('minCapacity', value)} />

        <label className="field">
          <span>Location</span>
          <input type="text" list="venue-search-locations" placeholder="e.g. Main Tower" value={criteria.location} onChange={(event) => update('location', event.target.value)} />
          <datalist id="venue-search-locations">
            {options.locations.map((location) => <option key={location} value={location} />)}
          </datalist>
        </label>

        <label className="field">
          <span>Supported layout</span>
          <select value={criteria.layout} onChange={(event) => update('layout', event.target.value)}>
            <option value="">Any layout</option>
            {options.layouts.map((layout) => <option key={layout} value={layout}>{layout}</option>)}
          </select>
        </label>
      </div>

      <fieldset className="venue-search-options">
        <legend>Required facilities</legend>
        {options.facilities.length === 0
          ? <p className="muted">No facilities to choose from.</p>
          : <div className="checkbox-list">
              {options.facilities.map((facility) => <label key={facility} className="checkbox-option">
                <input type="checkbox" checked={criteria.facilities.includes(facility)} onChange={() => toggle('facilities', facility)} />
                {facility}
              </label>)}
            </div>}
      </fieldset>

      <fieldset className="venue-search-options">
        <legend>Accessibility requirements</legend>
        <div className="checkbox-list">
          {ACCESSIBILITY_OPTIONS.map(({ key, label }) => <label key={key} className="checkbox-option">
            <input type="checkbox" checked={criteria.accessibility.includes(key)} onChange={() => toggle('accessibility', key)} />
            {label}
          </label>)}
        </div>
      </fieldset>

      <div className="venue-search-actions">
        <button type="submit" className="button primary" disabled={searching}><SearchIcon size={15} /> Search</button>
        <button type="button" className="button secondary" onClick={clearAll}>Clear all</button>
      </div>
    </form>

    {message && <p className="field-error" role="alert">{message}</p>}

    {searching
      ? <><InlineLoading label="Searching venues…" /><VenueCardGridSkeleton count={3} /></>
      : results === null
        ? null
        : results.length === 0
          ? <p role="status">No venues are available for the selected date, time and requirements.</p>
          : <>
              <p className="muted" role="status">{results.length} {results.length === 1 ? 'venue' : 'venues'} available.</p>
              <section className="venue-card-grid">
                {results.map((venue) => <button key={venue.id} type="button" className="venue-card" onClick={() => onViewVenue(venue.id)} aria-label={`View details for ${venue.name}`}>
                  <span className="venue-card-header">
                    <strong>{venue.name}</strong>
                    <span className={`venue-status ${badgeClass(venue.availability)}`} title={venue.availability === 'Pending request' ? PENDING_HINT : undefined}>{venue.availability}</span>
                  </span>
                  <span className="venue-card-line">{venue.location || 'Not specified'}</span>
                  <span className="venue-card-line">{venue.capacity === null ? 'Capacity not specified' : `${venue.capacity} people`}</span>
                  <span className="venue-card-line">{venue.accessibility || 'No accessibility information'}</span>
                  {/* Labelled, because a bare chip row of layouts sits right
                      above one of facilities and the two look identical. */}
                  <span className="chip-row">
                    <span className="chip-row-label">Layouts</span>
                    <span className="chip-list">
                      {venue.supportedLayouts.length === 0
                        ? <span className="muted">None listed</span>
                        : venue.supportedLayouts.map((layout) => <span key={layout} className="chip">{layout}</span>)}
                    </span>
                  </span>
                  <span className="chip-row">
                    <span className="chip-row-label">Facilities</span>
                    <span className="chip-list">
                      {venue.facilities.length === 0
                        ? <span className="muted">None listed</span>
                        : venue.facilities.map((facility) => <span key={facility} className="chip">{facility}</span>)}
                    </span>
                  </span>
                  <span className="venue-card-link">View details <ArrowRightIcon size={13} /></span>
                </button>)}
              </section>
            </>}
  </div>
}
