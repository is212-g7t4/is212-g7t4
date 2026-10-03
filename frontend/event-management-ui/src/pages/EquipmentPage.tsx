import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Role, User } from '../types'
import { EQUIPMENT_STATUSES, EQUIPMENT_TYPES, createEquipment, fetchEquipment } from '../features/equipment/equipment'
import type { Equipment, EquipmentStatus } from '../features/equipment/equipment'
import { EQUIPMENT_ACCESS_NOTICE, canManageEquipment } from '../features/equipment/permissions'
import { Field, RoleWarning } from '../components/FormControls'
import { InlineLoading } from '../components/Loading'

type StatusFilter = EquipmentStatus | 'All'

const ADD_NEW = '__add_new__'
const MAX_TYPE_LENGTH = 100

function statusClass(status: string): string {
  return status.toLowerCase().replace(/\s+/g, '-')
}

export function EquipmentPage({ role, user }: { role: Role; user: User | null }) {
  const [items, setItems] = useState<Equipment[]>([])
  const [filter, setFilter] = useState<StatusFilter>('Available')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [formError, setFormError] = useState('')
  const [success, setSuccess] = useState('')
  const [saving, setSaving] = useState(false)
  const [equipmentType, setEquipmentType] = useState<string>(EQUIPMENT_TYPES[0])
  const [customType, setCustomType] = useState('')
  const [description, setDescription] = useState('')
  const [quantity, setQuantity] = useState('')
  const [location, setLocation] = useState('')
  const [status, setStatus] = useState<EquipmentStatus>('Available')

  const allowed = canManageEquipment(role)

  const load = useCallback((activeFilter: StatusFilter) => {
    return fetchEquipment(activeFilter === 'All' ? undefined : activeFilter)
      .then((list) => { setItems(list); setError('') })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!allowed) return
    void load(filter)
  }, [allowed, filter, load])

  if (!allowed) return <RoleWarning>{EQUIPMENT_ACCESS_NOTICE}</RoleWarning>

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSuccess('')
    const total = Number(quantity)
    const chosenType = equipmentType === ADD_NEW ? customType.trim() : equipmentType
    if (!chosenType) return setFormError('Enter a name for the new equipment type.')
    if (chosenType.length > MAX_TYPE_LENGTH) return setFormError(`Equipment type must be ${MAX_TYPE_LENGTH} characters or fewer.`)
    if (!description.trim() || !location.trim()) return setFormError('Description and location are required.')
    if (quantity.trim() === '' || !Number.isInteger(total) || total < 0) return setFormError('Quantity must be a whole number of 0 or more.')
    if (!user) return setFormError('Select a user before adding equipment.')
    setFormError('')
    setSaving(true)
    try {
      const created = await createEquipment({ equipmentType: chosenType, description: description.trim(), totalQuantity: total, location: location.trim(), status }, user)
      setSuccess(`Added ${created.type}: ${created.description}.`)
      setDescription('')
      setCustomType('')
      setQuantity('')
      setLocation('')
      await load(filter)
    } catch (cause) {
      setFormError((cause as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return <div className="page-stack">
    <section className="intro"><h1>Equipment catalogue</h1><p className="muted">Record the equipment we physically own and review what is currently available.</p></section>

    <form className="panel form-panel" onSubmit={submit} aria-label="Add equipment" noValidate>
      <section className="form-section">
        <h3>Add equipment</h3>
        <div className="field-row">
          <label className="field">
            <span>Type<span className="required"> *</span></span>
            <select value={equipmentType} onChange={(event) => setEquipmentType(event.target.value)}>
              {EQUIPMENT_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
              <option value={ADD_NEW}>Add new…</option>
            </select>
          </label>
          <label className="field">
            <span>Status</span>
            <select value={status} onChange={(event) => setStatus(event.target.value as EquipmentStatus)}>
              {EQUIPMENT_STATUSES.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
        </div>
        {equipmentType === ADD_NEW && <Field label="New equipment type" value={customType} onChange={setCustomType} required placeholder="e.g. Drone" />}
        <Field label="Description" value={description} onChange={setDescription} required placeholder="e.g. Wireless handheld microphone" />
        <div className="field-row">
          <Field label="Total quantity" value={quantity} onChange={setQuantity} required type="number" min="0" />
          <Field label="Location" value={location} onChange={setLocation} required placeholder="e.g. AV Store, Level 1" />
        </div>
        {formError && <p className="field-error" role="alert">{formError}</p>}
        {success && <p role="status">{success}</p>}
      </section>
      <div className="form-actions">
        <button type="submit" className="button primary" disabled={saving}>{saving ? 'Adding…' : 'Add equipment'}</button>
      </div>
    </form>

    <section className="panel table-panel">
      <div className="form-section">
        <label className="field">
          <span>Show</span>
          <select value={filter} onChange={(event) => { setLoading(true); setFilter(event.target.value as StatusFilter) }} aria-label="Filter by status">
            <option value="All">All equipment</option>
            {EQUIPMENT_STATUSES.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
      </div>
      {loading ? <InlineLoading label="Loading equipment…" /> : error ? <p className="field-error" role="alert">{error}</p> : items.length === 0 ? <p className="muted form-section">No equipment found.</p> : <div className="table-scroll">
        <table>
          <thead><tr><th>Type</th><th>Description</th><th>Quantity</th><th>Location</th><th>Status</th><th>Setup requirements</th></tr></thead>
          <tbody>
            {items.map((item) => <tr key={item.id}>
              <td>{item.type}</td>
              <td>{item.description}</td>
              <td>{item.totalQuantity}</td>
              <td>{item.location}</td>
              <td><span className={`equipment-status ${statusClass(item.status)}`}>{item.status}</span></td>
              <td>{item.setupRequirements}</td>
            </tr>)}
          </tbody>
        </table>
      </div>}
    </section>
  </div>
}
