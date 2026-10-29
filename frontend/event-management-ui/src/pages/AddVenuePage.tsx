import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { SubmissionPopup } from '../components/SubmissionPopup'
import { createVenue, emptyVenueForm, updateVenue, updateVenueSafetyInfo, VENUE_STATUSES, validateVenueForm, VenueSubmissionError } from '../features/venue/venueForm'
import type { VenueFormData, VenueSafetyInfo } from '../features/venue/venueForm'
import type { Role, User } from '../types'
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
  user?: Pick<User, 'id' | 'role'>
}

const emptySafety: VenueSafetyInfo = { emergencyAccessDetails: '', knownRestrictions: '' }

export function AddVenuePage({ role, onSaved }: VenueFormPageProps) {
  return <VenueFormPage role={role} onSaved={onSaved} />
}

export function EditVenuePage({ role, venueId, onSaved, onCancel, user }: VenueFormPageProps & { venueId: string }) {
  return <VenueFormPage role={role} venueId={venueId} onSaved={onSaved} onCancel={onCancel} user={user} />
}

function VenueFormPage({ role, onSaved, venueId, onCancel, user }: VenueFormPageProps) {
  const [pending, setPending] = useState(false)
  const [popup, setPopup] = useState<{ title: string; messages: string[] } | null>(null)
  const [form, setForm] = useState<VenueFormData>(emptyVenueForm)
  const [loading, setLoading] = useState(Boolean(venueId))
  const [loadError, setLoadError] = useState('')
  // SCRUM-167: what was loaded, so the safety save only runs when it changed.
  const [savedSafety, setSavedSafety] = useState<VenueSafetyInfo>(emptySafety)
  const canEditSafety = user?.role === 'Venue Staff'

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
        setupTimeMinutes: String(venue.setupTimeMinutes ?? 0),
        turnaroundTimeMinutes: String(venue.turnaroundTimeMinutes ?? 0),
        emergencyAccessDetails: venue.emergencyAccessDetails ?? '',
        knownRestrictions: venue.knownRestrictions ?? '',
      })
      setSavedSafety({
        emergencyAccessDetails: venue.emergencyAccessDetails ?? '',
        knownRestrictions: venue.knownRestrictions ?? '',
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
      const safety = { emergencyAccessDetails: form.emergencyAccessDetails, knownRestrictions: form.knownRestrictions }
      const safetyChanged = safety.emergencyAccessDetails.trim() !== savedSafety.emergencyAccessDetails.trim()
        || safety.knownRestrictions.trim() !== savedSafety.knownRestrictions.trim()
      if (venueId && user && canEditSafety && safetyChanged) {
        try {
          await updateVenueSafetyInfo(venueId, safety)
          setSavedSafety(safety)
        } catch (cause) {
          // The profile is already saved; keep the form filled so staff can retry.
          const reason = cause instanceof VenueSubmissionError
            ? (cause.errors.length ? cause.errors.join(' ') : cause.message)
            : 'Unable to reach the Venue Service.'
          setPopup({
            title: 'Safety Information Not Saved',
            messages: [`Venue details were saved, but the safety information was not: ${reason}`],
          })
          return
        }
      }
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

            <Field label="Setup Time (minutes)" type="number" min="0" value={form.setupTimeMinutes} onChange={(value) => update('setupTimeMinutes', value)} placeholder="e.g. 30" required />
            <Field label="Turnaround Time (minutes)" type="number" min="0" value={form.turnaroundTimeMinutes} onChange={(value) => update('turnaroundTimeMinutes', value)} placeholder="e.g. 45" required />
          </FormSection>

          {venueId && <FormSection title="Safety Information" hint="Recorded for the Safety Officer's operational safety review.">
            <fieldset disabled={!canEditSafety} className="submission-fields">
              <Field textarea label="Emergency Access Details" value={form.emergencyAccessDetails} onChange={(value) => update('emergencyAccessDetails', value)} placeholder="e.g. Exits on north and south walls; assembly point at the front lawn; fire engine access via Gate 2" />
              <Field textarea label="Known Restrictions" value={form.knownRestrictions} onChange={(value) => update('knownRestrictions', value)} placeholder="e.g. Noise curfew 10pm; no open flames; floor load limit 500 kg/m²" />
            </fieldset>
            {!canEditSafety && <p className="muted">Only Venue Staff can edit safety information.</p>}
          </FormSection>}

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
