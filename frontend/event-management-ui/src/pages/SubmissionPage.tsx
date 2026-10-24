import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { SubmissionPopup } from '../components/SubmissionPopup'
import { eventApi, SubmissionError, validateDraft, validateEvent } from '../features/event/submission'
import type { EventData, Role } from '../types'
import { Field, FormSection, RoleWarning } from '../components/FormControls'
import { Spinner } from '../components/Loading'

const EVENT_FIELDS: (keyof EventData)[] = [
  'eventName', 'description', 'purpose', 'preferredStartDate', 'preferredEndDate', 'expectedAttendance',
  'venueRequirements', 'accessibilityNeeds', 'equipmentRequirements', 'registrationNeeds',
  'withdrawalDeadline',
]

// `draftId` opens one of the organiser's drafts; without it the form starts empty.
export function SubmissionPage({ role, currentOrganiserId, draftId: openedDraftId }: { role: Role; currentOrganiserId?: string; draftId?: string }) {
  // Set by the first save, so saving again updates this draft instead of creating another.
  const [draftId, setDraftId] = useState(openedDraftId)
  const [draftNotice, setDraftNotice] = useState('')
  const [loadingDraft, setLoadingDraft] = useState(Boolean(openedDraftId))
  // Which action is in flight, so only that button shows a progress label.
  const [pending, setPending] = useState<'draft' | 'submit' | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const [popup, setPopup] = useState<{ title: string; messages: string[] } | null>(null)
  const [attendanceError, setAttendanceError] = useState('')
  const [event, setEvent] = useState<EventData>({
    eventName: '',
    description: '',
    purpose: '',
    preferredStartDate: '',
    preferredEndDate: '',
    expectedAttendance: '',
    venueRequirements: '',
    accessibilityNeeds: '',
    equipmentRequirements: '',
    registrationNeeds: '',
    withdrawalDeadline: '',
  })

  useEffect(() => {
    if (!openedDraftId || !currentOrganiserId) return
    let active = true
    eventApi(`/events/${openedDraftId}?organiserId=${currentOrganiserId}`).then((draft) => {
      if (active) setEvent(Object.fromEntries(EVENT_FIELDS.map((field) => [field, draft[field] ?? ''])) as unknown as EventData)
    }).catch((cause: Error) => {
      if (active) setPopup({ title: 'Unable to Open Draft', messages: [cause.message] })
    }).finally(() => { if (active) setLoadingDraft(false) })
    return () => { active = false }
  }, [openedDraftId, currentOrganiserId])

  const updateEvent = (field: keyof EventData, value: string) => {
    setDraftNotice('')
    setEvent((previousEvent) => ({
      ...previousEvent,
      [field]: value,
    }))
  }

  const handleSaveDraft = async () => {
    if (pending || submitted || !currentOrganiserId) return
    const { missingFields, errors } = validateDraft(event)
    if (missingFields.length || errors.length) {
      setPopup({ title: missingFields.length ? 'Name Your Draft' : 'Check Event Details', messages: [...missingFields, ...errors] })
      return
    }
    setPending('draft')
    try {
      const saved = draftId
        ? await eventApi(`/events/drafts/${draftId}`, { ...event, organiserId: currentOrganiserId }, 'PATCH')
        : await eventApi('/events/drafts', { ...event, organiserId: currentOrganiserId })
      setDraftId(saved.id)
      setDraftNotice('Draft saved. Only you can see it; find it under My events.')
    } catch (cause) {
      setPopup({ title: 'Draft Not Saved', messages: [
        cause instanceof SubmissionError ? cause.message : 'Unable to reach the Event Service. Your form has been kept; please try again.',
      ] })
    } finally {
      setPending(null)
    }
  }

  const handleSubmit = async (submitEvent: FormEvent<HTMLFormElement>) => {
    submitEvent.preventDefault()
    if (pending || submitted) return
    const { missingFields, errors } = validateEvent(event)
    const attendanceValidationError = missingFields.includes('Expected Attendance')
      ? 'Expected Attendance is required.'
      : errors.find((error) => error.startsWith('Expected Attendance')) || ''
    setAttendanceError(attendanceValidationError)
    if (missingFields.length || errors.length) {
      setPopup({ title: missingFields.length ? 'Missing Required Fields' : 'Check Event Details', messages: [...missingFields, ...errors] })
      return
    }
    setPending('submit')
    try {
      const saved = draftId && currentOrganiserId
        ? await eventApi(`/events/drafts/${draftId}/submit`, { ...event, organiserId: currentOrganiserId })
        : await eventApi('/events', currentOrganiserId ? { ...event, organiserId: currentOrganiserId } : event)
      setSubmitted(true)
      setPopup({ title: 'Event Submitted', messages: [
        `${saved.eventName} was submitted on ${new Date(saved.submittedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })} SGT.`,
      ] })
    } catch (cause) {
      setPopup(cause instanceof SubmissionError ? {
        title: cause.missingFields.length ? 'Missing Required Fields' : 'Submission Failed',
        messages: cause.missingFields.length || cause.errors.length ? [...cause.missingFields, ...cause.errors] : [cause.message],
      } : { title: 'Submission Failed', messages: ['Unable to reach the Event Service. Your form has been kept; please try again.'] })
    } finally {
      setPending(null)
    }
  }
  if (role !== 'Event Organiser') return <RoleWarning>Only Event Organisers can submit event requests.</RoleWarning>

  return (
    <div className="page-stack">
      {popup && <SubmissionPopup {...popup} onClose={() => setPopup(null)} />}
      {submitted && <p role="status">Status: Submitted. Your request is in the coordinator queue.</p>}
      {draftNotice && !submitted && <p role="status">{draftNotice}</p>}
      <section className="intro">
        <h1>{draftId ? 'Edit Draft Event Request' : 'Create Event Request'}</h1>

        <p className="muted">
          Provide the details and requirements for your event.
          Your request will be reviewed by an Event Coordinator.
        </p>
      </section>

      <form
        noValidate
        className="panel form-panel"
        onSubmit={handleSubmit}
      >
        <fieldset disabled={pending !== null || submitted || loadingDraft} className="submission-fields">
        <FormSection
          title="Event Information"
          hint="Provide the basic information about your event."
        >
          <Field
            label="Event Name"
            value={event.eventName}
            onChange={(value) =>
              updateEvent('eventName', value)
            }
            placeholder="e.g. Southeast Asia Technology Conference"
            required
          />

          <Field
            label="Description"
            value={event.description}
            onChange={(value) =>
              updateEvent('description', value)
            }
            placeholder="Provide a brief description of your event."
            textarea
            required
          />

          <Field
            label="Purpose"
            value={event.purpose}
            onChange={(value) =>
              updateEvent('purpose', value)
            }
            placeholder="What is the purpose of this event?"
            textarea
            required
          />
        </FormSection>

        <FormSection
          title="Date and Attendance"
          hint="Provide your preferred event period in Singapore time (SGT) and expected number of attendees."
        >
          <div className="field-row">
            <Field
              label="Preferred Start Date & Time"
              type="datetime-local"
              value={event.preferredStartDate}
              onChange={(value) =>
                updateEvent('preferredStartDate', value)
              }
              required
            />

            <Field
              label="Preferred End Date & Time"
              type="datetime-local"
              value={event.preferredEndDate}
              onChange={(value) =>
                updateEvent('preferredEndDate', value)
              }
              required
            />
          </div>

          <Field
            label="Expected Attendance"
            type="number"
            min="1"
            value={event.expectedAttendance}
            onChange={(value) =>
              { updateEvent('expectedAttendance', value); setAttendanceError('') }
            }
            placeholder="e.g. 150"
            required
            error={attendanceError}
          />
        </FormSection>

        <FormSection
          title="Event Requirements"
          hint="The following fields are optional. Provide any requirements that ConnectSphere should consider when reviewing your event."
        >
          <Field
            label="Venue Requirements"
            value={event.venueRequirements}
            onChange={(value) =>
              updateEvent('venueRequirements', value)
            }
            placeholder="e.g. Theatre-style room with stage and breakout area."
            textarea
          />

          <Field
            label="Accessibility Needs"
            value={event.accessibilityNeeds}
            onChange={(value) =>
              updateEvent('accessibilityNeeds', value)
            }
            placeholder="e.g. Wheelchair-accessible entrance and seating."
            textarea
          />

          <Field
            label="Equipment Requirements"
            value={event.equipmentRequirements}
            onChange={(value) =>
              updateEvent('equipmentRequirements', value)
            }
            placeholder="e.g. Projector and two wireless microphones."
            textarea
          />

          <Field
            label="Registration Needs"
            value={event.registrationNeeds}
            onChange={(value) =>
              updateEvent('registrationNeeds', value)
            }
            placeholder="e.g. Attendee registration is required."
            textarea
          />

          <Field
            label="Withdrawal Deadline"
            type="datetime-local"
            value={event.withdrawalDeadline || ''}
            onChange={(value) => updateEvent('withdrawalDeadline', value)}
          />
          <p className="muted">
            Optional. If left blank, attendees may withdraw until the event starts.
          </p>
        </FormSection>

        <div className="form-actions">
          {currentOrganiserId && !submitted && (
            <button type="button" className="button" onClick={handleSaveDraft}>
              {pending === 'draft' && <Spinner size={13} />}
              {pending === 'draft' ? 'Saving…' : 'Save as Draft'}
            </button>
          )}
          <button
            type="submit"
            className="button primary"
          >
            {pending === 'submit' && <Spinner size={13} />}
            {pending === 'submit' ? 'Submitting…' : submitted ? 'Submitted' : 'Submit Request'}
          </button>
        </div>
        </fieldset>
      </form>
    </div>
  )
}
