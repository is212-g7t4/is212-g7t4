import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Role, User } from '../types'
import { fetchEquipment } from '../features/equipment/equipment'
import type { Equipment } from '../features/equipment/equipment'
import { createEquipmentRequests, fetchRequestableEvents } from '../features/equipment/requests'
import type { SubmittedEvent } from '../features/event/submission'
import { formatSchedule } from '../features/event/dateFormat'
import { FormSection, RoleWarning } from '../components/FormControls'
import { SubmissionPopup } from '../components/SubmissionPopup'
import { InlineLoading, Spinner } from '../components/Loading'
import { ArrowLeftIcon, MinusIcon, PlusIcon } from '../components/Icon'
import { isCoordinator } from '../roles'

export const NEW_EQUIPMENT_REQUEST_ACCESS_NOTICE = 'Only Event Coordinators can request equipment.'

type DraftRow = { equipmentId: string; quantity: string; requirements: string }
type AddedItem = { equipmentId: string; quantity: number; requirements: string }

const EMPTY_ROW: DraftRow = { equipmentId: '', quantity: '', requirements: '' }

export function NewEquipmentRequestPage({ role, user, onBack, onCreated }: {
  role: Role
  user: User | null
  onBack: () => void
  onCreated: (message: string) => void
}) {
  const [events, setEvents] = useState<SubmittedEvent[]>([])
  const [equipment, setEquipment] = useState<Equipment[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [eventId, setEventId] = useState('')
  const [added, setAdded] = useState<AddedItem[]>([])
  const [draft, setDraft] = useState<DraftRow>(EMPTY_ROW)
  const [rowError, setRowError] = useState('')
  const [popup, setPopup] = useState<{ title: string; messages: string[] } | null>(null)
  const [pending, setPending] = useState(false)

  const coordinator = isCoordinator(role) ? user : null

  useEffect(() => {
    if (!coordinator) return
    let active = true
    Promise.all([fetchRequestableEvents(coordinator.id), fetchEquipment('Available')])
      .then(([eventList, equipmentList]) => {
        if (!active) return
        setEvents(eventList)
        setEquipment(equipmentList)
      })
      .catch((cause: Error) => { if (active) setLoadError(cause.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [coordinator])

  if (!coordinator) return <RoleWarning>{NEW_EQUIPMENT_REQUEST_ACCESS_NOTICE}</RoleWarning>

  const byId = new Map(equipment.map((item) => [item.id, item]))

  const updateDraft = (field: keyof DraftRow, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }))
    setRowError('')
  }

  const clearDraft = () => {
    setDraft(EMPTY_ROW)
    setRowError('')
  }

  const addDraftToRequest = () => {
    const quantity = Number(draft.quantity)
    const error = !draft.equipmentId ? 'Choose the equipment to request.'
      : draft.quantity.trim() === '' || !Number.isInteger(quantity) || quantity < 1 ? 'Quantity must be a whole number of at least 1.'
        : added.some((item) => item.equipmentId === draft.equipmentId) ? 'This equipment is already in the request. Remove it from the list to change the quantity.'
          : ''
    if (error) return setRowError(error)
    setAdded((current) => [...current, { equipmentId: draft.equipmentId, quantity, requirements: draft.requirements.trim() }])
    clearDraft()
  }

  const handleSubmit = async (submitEvent: FormEvent<HTMLFormElement>) => {
    submitEvent.preventDefault()
    if (pending) return
    const messages = [
      ...(!eventId ? ['Choose the event to request equipment for.'] : []),
      ...(!added.length ? ['Add at least one equipment item with the + button.'] : []),
      ...(draft.equipmentId || draft.quantity.trim() || draft.requirements.trim()
        ? ['Add (+) or clear (−) the equipment row that is still being filled in.'] : []),
    ]
    if (messages.length) return setPopup({ title: 'Check Equipment Request', messages })
    setPending(true)
    try {
      await createEquipmentRequests(eventId, added.map((item) => ({
        equipmentId: item.equipmentId, quantityRequested: item.quantity, technicalRequirements: item.requirements,
      })), coordinator)
      const eventName = events.find((event) => event.id === eventId)?.eventName ?? 'the event'
      onCreated(`Requested ${added.length} equipment item${added.length === 1 ? '' : 's'} for ${eventName}.`)
    } catch (cause) {
      setPopup({ title: 'Submission Failed', messages: [(cause as Error).message] })
    } finally {
      setPending(false)
    }
  }

  const backButton = <button type="button" className="button small" onClick={onBack}><ArrowLeftIcon size={13} /> Back to equipment requests</button>

  if (loading) return <div className="page-stack">{backButton}<InlineLoading label="Loading your events and equipment…" /></div>
  if (loadError) return <div className="page-stack">{backButton}<p className="field-error" role="alert">{loadError}</p></div>

  return <div className="page-stack">
    {popup && <SubmissionPopup {...popup} onClose={() => setPopup(null)} />}
    <section className="intro">
      {backButton}
      <h1>New equipment request</h1>
      <p className="muted">Request equipment for an event assigned to you. Technical Support checks stock for the event’s dates when they review it.</p>
    </section>

    <form noValidate className="panel form-panel" onSubmit={handleSubmit} aria-label="New equipment request">
      <fieldset disabled={pending} className="submission-fields">
        <FormSection title="Event" hint="Assigned events that are Under Review or Safety Changes Requested.">
          {events.length === 0 ? <p className="muted">You have no eligible events assigned to you.</p> :
            <label className="field">
              <span>Event<span className="required"> *</span></span>
              <select value={eventId} onChange={(changeEvent) => setEventId(changeEvent.target.value)}>
                <option value="">Choose an event…</option>
                {events.map((event) => <option key={event.id} value={event.id}>
                  {event.eventName} · {formatSchedule(event.preferredStartDate, event.preferredEndDate)} ({event.status})
                </option>)}
              </select>
            </label>}
        </FormSection>

        <FormSection title="Equipment" hint="Choose an item and quantity, then press + to add it to this request.">
          {added.length > 0 && <div className="table-scroll equipment-added-list">
            <table aria-label="Added equipment">
              <thead><tr><th>Equipment</th><th>Type</th><th>Quantity</th><th>Technical requirements</th><th aria-label="Remove" /></tr></thead>
              <tbody>
                {added.map((item) => {
                  const details = byId.get(item.equipmentId)
                  return <tr key={item.equipmentId}>
                    <td>{details?.description}</td>
                    <td>{details?.type}</td>
                    <td>{item.quantity}</td>
                    <td>{item.requirements || <span className="muted">None</span>}</td>
                    <td><button type="button" className="button small reject" aria-label={`Remove ${details?.description}`}
                      onClick={() => setAdded((current) => current.filter((entry) => entry.equipmentId !== item.equipmentId))}><MinusIcon size={13} /></button></td>
                  </tr>
                })}
              </tbody>
            </table>
          </div>}

          {equipment.length === 0 ? <p className="muted">No equipment is currently Available to request.</p> : <div className="equipment-draft" role="group" aria-label="Equipment row">
            <div className="equipment-draft-row">
              <label className="field">
                <span>Equipment<span className="required"> *</span></span>
                <select value={draft.equipmentId} onChange={(changeEvent) => updateDraft('equipmentId', changeEvent.target.value)}>
                  <option value="">Choose equipment…</option>
                  {equipment.map((item) => <option key={item.id} value={item.id}>{item.description} ({item.type})</option>)}
                </select>
              </label>
              <label className="field">
                <span>Quantity<span className="required"> *</span></span>
                <input type="number" min="1" value={draft.quantity} onChange={(changeEvent) => updateDraft('quantity', changeEvent.target.value)} />
              </label>
              <label className="field">
                <span>Technical requirements</span>
                <input value={draft.requirements} placeholder="e.g. 2 handheld, 2 lapel" onChange={(changeEvent) => updateDraft('requirements', changeEvent.target.value)} />
              </label>
              <div className="equipment-draft-actions">
                <button type="button" className="button small approve" aria-label="Add this equipment" title="Add this equipment" onClick={addDraftToRequest}><PlusIcon size={14} /></button>
                <button type="button" className="button small reject" aria-label="Clear this row" title="Clear this row" onClick={clearDraft}><MinusIcon size={14} /></button>
              </div>
            </div>
            {rowError && <p className="field-error" role="alert">{rowError}</p>}
          </div>}
        </FormSection>

        <div className="form-actions">
          <button type="button" className="button secondary" onClick={onBack}>Cancel</button>
          <button type="submit" className="button primary" disabled={events.length === 0}>
            {pending && <Spinner size={13} />}
            {pending ? 'Submitting…' : 'Submit request'}
          </button>
        </div>
      </fieldset>
    </form>
  </div>
}
