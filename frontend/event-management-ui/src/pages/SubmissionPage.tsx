import { useState } from 'react'
import type { FormEvent } from 'react'
import { SubmissionPopup } from '../components/SubmissionPopup'
import { eventApi, SubmissionError, validateEvent } from '../features/event/submission'
import type { EventData, Role } from '../types'
import { Field, FormSection } from '../components/FormControls'

export function SubmissionPage({ role }: { role: Role }) {
  const [pending, setPending] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [popup, setPopup] = useState<{ title: string; messages: string[] } | null>(null)
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
  })

  const updateEvent = (field: keyof EventData, value: string) => {
    setEvent((previousEvent) => ({
      ...previousEvent,
      [field]: value,
    }))
  }

  const handleSubmit = async (submitEvent: FormEvent<HTMLFormElement>) => {
    submitEvent.preventDefault()
    if (pending || submitted) return
    const { missingFields, errors } = validateEvent(event)
    if (missingFields.length || errors.length) {
      setPopup({ title: missingFields.length ? 'Missing Required Fields' : 'Check Event Details', messages: [...missingFields, ...errors] })
      return
    }
    setPending(true)
    try {
      const saved = await eventApi('/events', event)
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
      setPending(false)
    }
  }
  if (role !== 'Event Organiser') return <p className="role-warning">Only Event Organisers can submit event requests.</p>

  return (
    <div className="page-stack">
      {popup && <SubmissionPopup {...popup} onClose={() => setPopup(null)} />}
      {submitted && <p role="status">Status: Submitted. Your request is in the coordinator queue.</p>}
      <section className="intro">
        <h1>Create Event Request</h1>

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
        <fieldset disabled={pending || submitted} className="submission-fields">
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
              updateEvent('expectedAttendance', value)
            }
            placeholder="e.g. 150"
            required
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
        </FormSection>

        <div className="form-actions">
          <button
            type="submit"
            className="button primary"
          >
            {pending ? 'Submitting…' : submitted ? 'Submitted' : 'Submit Request'}
          </button>
        </div>
        </fieldset>
      </form>
    </div>
  )
}
