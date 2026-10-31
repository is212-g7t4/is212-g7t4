import { useEffect, useState } from 'react'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { canListEventRegistrations, fetchRegistrationCounts } from '../features/registration/registrations'
import type { RegistrationCount } from '../features/registration/registrations'
import { StatusBadge } from '../components/FormControls'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { ArrowRightIcon } from '../components/Icon'
import { EventCardSkeletonList } from '../components/Loading'
import { formatSchedule, getDateTile } from '../features/event/dateFormat'

export function OrganiserEventsPage({ organiserId, organiserName, onViewDetails, onOpenDraft }: { organiserId?: string; organiserName?: string; onViewDetails: (id: string) => void; onOpenDraft?: (id: string) => void }) {
  const [events, setEvents] = useState<SubmittedEvent[]>([])
  const [drafts, setDrafts] = useState<SubmittedEvent[]>([])
  const [draftError, setDraftError] = useState('')
  const [draftToDelete, setDraftToDelete] = useState<SubmittedEvent | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [counts, setCounts] = useState<Record<string, RegistrationCount>>({})
  const [countsError, setCountsError] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!organiserId) return
    let active = true
    eventApi(`/events?organiserId=${organiserId}`).then(async (body) => {
      const fetched = body.events as SubmittedEvent[]
      const registrationEventIds = fetched.filter((event) => canListEventRegistrations(event.status)).map((event) => event.id)
      // Counts are secondary: if they fail, still show the events.
      const fetchedCounts = await fetchRegistrationCounts(registrationEventIds).catch(() => {
        if (active) setCountsError(true)
        return {}
      })
      if (active) {
        setEvents(fetched)
        setCounts(fetchedCounts)
      }
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    // Drafts are separate from submitted events and only ever the organiser's own.
    eventApi(`/events/drafts?organiserId=${organiserId}`).then((body) => {
      if (active) setDrafts(body.events)
    }).catch((cause: Error) => {
      if (active) setDraftError(cause.message)
    })
    return () => { active = false }
  }, [organiserId])

  const deleteDraft = async (draft: SubmittedEvent) => {
    setDraftError('')
    setDeleting(true)
    try {
      await eventApi(`/events/drafts/${draft.id}?organiserId=${organiserId}`, undefined, 'DELETE')
      setDrafts((current) => current.filter((item) => item.id !== draft.id))
    } catch (cause) {
      setDraftError((cause as Error).message)
    } finally {
      setDeleting(false)
      setDraftToDelete(null)
    }
  }

  return <div className="page-stack">
    {draftToDelete && <ConfirmDialog title="Delete draft?" confirmLabel="Delete draft" pendingLabel="Deleting..." submitting={deleting}
      onCancel={() => setDraftToDelete(null)} onConfirm={() => deleteDraft(draftToDelete)}>
      You are deleting <strong>{draftToDelete.eventName}</strong>. This can't be undone.
    </ConfirmDialog>}
    <section className="intro"><h1>My events</h1><p className="muted">Events created by {organiserName || 'you'}. Open an event to see its details; registrations are shown for confirmed events.</p></section>
    {(drafts.length > 0 || draftError) && <section className="event-list-section" aria-labelledby="drafts-heading">
      <h2 id="drafts-heading" className="event-list-heading">Drafts</h2>
      {draftError && <p className="field-error" role="alert">{draftError}</p>}
      {drafts.map((draft) => {
        const tile = getDateTile(draft.preferredStartDate)
        // A button can't contain the Delete button, so the card handles clicks anywhere on it and
        // the inner button gives keyboard and screen-reader users the same "open" action.
        return <div key={draft.id} className="panel event-row-card" onClick={() => onOpenDraft?.(draft.id)}>
          <button type="button" className="draft-row-open" aria-label={`Open draft ${draft.eventName}`}>
            <span className="event-row-date">
              <span className="event-row-date-month">{tile.month}</span>
              <span className="event-row-date-day">{tile.day}</span>
            </span>
            <span className="event-row-body">
              <span className="event-row-heading">
                <strong>{draft.eventName}</strong>
                <StatusBadge status="Draft" />
              </span>
              <span className="event-row-schedule muted">{draft.preferredStartDate ? formatSchedule(draft.preferredStartDate, draft.preferredEndDate) : 'No dates yet'}</span>
              <span className="event-row-venue muted">Only you can see this draft until it is submitted</span>
            </span>
          </button>
          <button type="button" className="button reject small" aria-label={`Delete draft ${draft.eventName}`}
            onClick={(click) => { click.stopPropagation(); setDraftToDelete(draft) }}>Delete</button>
          <ArrowRightIcon size={16} className="icon" />
        </div>
      })}
    </section>}
    {drafts.length > 0 && !loading && !error && events.length > 0 && <h2 className="event-list-heading">Submitted events</h2>}
    {loading ? <EventCardSkeletonList /> : error ? <p className="field-error" role="alert">{error}</p> :
      events.length === 0 ? <p>You have not created any events yet.</p> : <>
      {countsError && <p className="field-error" role="alert">Unable to load registration counts.</p>}
      {events.map((event) => {
        const tile = getDateTile(event.preferredStartDate)
        const registrationsAvailable = canListEventRegistrations(event.status)
        const content = <>
          <span className="event-row-date">
            <span className="event-row-date-month">{tile.month}</span>
            <span className="event-row-date-day">{tile.day}</span>
          </span>
          <span className="event-row-body">
            <span className="event-row-heading">
              <strong>{event.eventName}</strong>
              <StatusBadge status={event.status} />
            </span>
            <span className="event-row-schedule muted">{formatSchedule(event.preferredStartDate, event.preferredEndDate)}</span>
            <span className="event-row-venue muted">
              {registrationsAvailable
                ? counts[event.id] ? `${counts[event.id].total} registration${counts[event.id].total === 1 ? '' : 's'}` : 'Registrations unavailable'
                : event.status === 'Rejected'
                  ? 'The event has been rejected. Submit a new request.'
                  : 'Registrations are available once the event is approved and confirmed'}
            </span>
          </span>
          <ArrowRightIcon size={16} className="icon" />
        </>
        return <button key={event.id} type="button" className="panel event-row-card" onClick={() => onViewDetails(event.id)}>{content}</button>
      })}
    </>}
  </div>
}
