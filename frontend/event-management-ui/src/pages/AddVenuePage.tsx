import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { SubmissionPopup } from '../components/SubmissionPopup'
import { createVenue, emptyVenueForm, updateVenue, VENUE_STATUSES, validateVenueForm, VenueSubmissionError } from '../features/venue/venueForm'
import type { VenueFormData } from '../features/venue/venueForm'
import type { Role } from '../types'
import { canManageVenues, VENUE_ACCESS_NOTICE } from '../features/venue/permissions'
import { Field, FormSection, RoleWarning } from '../components/FormControls'
import { Spinner } from '../components/Loading'
import { fetchVenue } from '../features/venue/venues'
import { ArrowLeftIcon } from '../components/Icon'

type VenueFormPageProps = {
  role: Role
  onSaved: (venueId: string) => void
  venueId?: string
  onCancel?: () => void
}

export function AddVenuePage({ role, onSaved }: VenueFormPageProps) {
  return <VenueFormPage role={role} onSaved={onSaved} />
}

export function EditVenuePage({ role, venueId, onSaved, onCancel }: VenueFormPageProps & { venueId: string }) {
  return <VenueFormPage role={role} venueId={venueId} onSaved={onSaved} onCancel={onCancel} />
}

function VenueFormPage({ role, onSaved, venueId, onCancel }: VenueFormPageProps) {
  const [pending, setPending] = useState(false)
  const [popup, setPopup] = useState<{ title: string; messages: string[] } | null>(null)
  const [form, setForm] = useState<VenueFormData>(emptyVenueForm)
  const [loading, setLoading] = useState(Boolean(venueId))
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    if (!venueId || !canManageVenues(role)) return
    let active = true
    fetchVenue(venueId).then((venue) => {
      if (!active) return
      setForm({
        name: venue.name,
        location: venue.location,
        capacity: venue.capacity === null ? '' : String(venue.capacity),
        facilities: venue.facilities.join(', '),
        accessibility: venue.accessibility,
        supportedLayouts: venue.supportedLayouts.join(', '),
        status: venue.status,
      })
    }).catch((cause: Error) => {
      if (active) setLoadError(cause.message)
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [role, venueId])

  const update = (field: keyof VenueFormData, value: string) => {
    setForm((current) => ({ ...current, [field]: value }))
  }

  const handleSubmit = async (submitEvent: FormEvent<HTMLFormElement>) => {
    submitEvent.preventDefault()
    if (pending) return
    const { missingFields, errors } = validateVenueForm(form)
    if (missingFields.length || errors.length) {
      setPopup({ title: missingFields.length ? 'Missing Required Fields' : 'Check Venue Details', messages: [...missingFields, ...errors] })
      return
    }
    setPending(true)
    try {
      const saved = venueId ? await updateVenue(venueId, form) : await createVenue(form)
      if (!venueId) setForm(emptyVenueForm)
      setPopup({
        title: venueId ? 'Venue Updated' : 'Venue Added',
        messages: [venueId ? `${saved.name} was updated.` : `${saved.name} was added to the catalogue.`],
      })
      onSaved(saved.id)
    } catch (cause) {
      setPopup(cause instanceof VenueSubmissionError ? {
        title: cause.missingFields.length ? 'Missing Required Fields' : 'Submission Failed',
        messages: cause.missingFields.length || cause.errors.length ? [...cause.missingFields, ...cause.errors] : [cause.message],
      } : { title: 'Submission Failed', messages: ['Unable to reach the Venue Service. Your form has been kept; please try again.'] })
    } finally {
      setPending(false)
    }
  }

  if (!canManageVenues(role)) return <RoleWarning>{VENUE_ACCESS_NOTICE}</RoleWarning>

  if (loading) return <div className="page-stack"><p>Loading venue details…</p></div>
  if (loadError) return <div className="page-stack">{onCancel && <button type="button" className="button small" onClick={onCancel}><ArrowLeftIcon size={13} /> Back to venue details</button>}<p className="field-error" role="alert">{loadError}</p></div>

  return (
    <div className="page-stack">
      {popup && <SubmissionPopup {...popup} onClose={() => setPopup(null)} />}
      <section className="intro">
        {onCancel && <button type="button" className="button small" onClick={onCancel}><ArrowLeftIcon size={13} /> Back to venue details</button>}
        <h1>{venueId ? 'Edit Venue' : 'Add Venue'}</h1>
        <p className="muted">{venueId ? 'Update this venue’s details and operating status.' : 'Add a new venue to the catalogue.'}</p>
      </section>

      <form noValidate className="panel form-panel" onSubmit={handleSubmit}>
        <fieldset disabled={pending} className="submission-fields">
          <FormSection title="Venue Information" hint="Provide the venue's name, location and capacity.">
            <Field label="Venue Name" value={form.name} onChange={(value) => update('name', value)} placeholder="e.g. Grand Ballroom" required />
            <Field label="Location" value={form.location} onChange={(value) => update('location', value)} placeholder="e.g. Level 3, Main Tower" required />
            <Field label="Capacity" type="number" min="1" value={form.capacity} onChange={(value) => update('capacity', value)} placeholder="e.g. 500" required />
          </FormSection>

          <FormSection title="Facilities and Accessibility" hint="Separate multiple facilities with commas.">
            <Field label="Facilities" value={form.facilities} onChange={(value) => update('facilities', value)} placeholder="e.g. wifi, projector, stage" required />
            <Field label="Accessibility" value={form.accessibility} onChange={(value) => update('accessibility', value)} placeholder="e.g. Wheelchair accessible, elevator access" />
          </FormSection>

          <FormSection title="Layouts and Operating Information" hint="Separate multiple layouts with commas.">
            <Field label="Supported Room Layouts" value={form.supportedLayouts} onChange={(value) => update('supportedLayouts', value)} placeholder="e.g. theatre, banquet, classroom" required />

            <label className="field">
              <span>Operating Status<span className="required"> *</span></span>
              <select value={form.status} onChange={(changeEvent) => update('status', changeEvent.target.value)}>
                {VENUE_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
            </label>
          </FormSection>

          <div className="form-actions">
            <button type="submit" className="button primary">
              {pending && <Spinner size={13} />}
              {pending ? 'Saving…' : venueId ? 'Save Changes' : 'Save Venue'}
            </button>
          </div>
        </fieldset>
      </form>
    </div>
  )
}
