import { useCallback, useEffect, useRef, useState } from 'react'
import './venueClosures.css'
import { ChevronDownIcon, RefreshIcon, ListIcon } from '../../components/Icon'
import type { User } from '../../types'
import { createClosure, listClosures } from './venueClosures'
import type { VenueClosure } from './venueClosures'

const formatDate = (value: string) => new Intl.DateTimeFormat('en-SG', {
  timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
}).format(new Date(value)) + ' SGT'
const message = (cause: unknown, fallback: string) => cause instanceof Error ? cause.message : fallback

// The parent keys this panel by venue and identity, so changes discard all local state.
export function VenueClosuresPanel({ venueId, venueName, user }: { venueId: string; venueName: string; user: Pick<User, 'id' | 'role'> }) {
  const [open, setOpen] = useState(false)
  const [start, setStart] = useState(''), [end, setEnd] = useState(''), [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false), [success, setSuccess] = useState(false)
  const [saveError, setSaveError] = useState(''), [listError, setListError] = useState('')
  const [rows, setRows] = useState<VenueClosure[]>([])
  const [cursor, setCursor] = useState<string | null>(null), [loading, setLoading] = useState(true)
  const readRequest = useRef<AbortController | null>(null), saveRequest = useRef<AbortController | null>(null)
  const { id, role } = user
  const load = useCallback(async (next?: string) => {
    readRequest.current?.abort()
    const controller = new AbortController()
    readRequest.current = controller
    setLoading(true); setListError('')
    if (!next) { setRows([]); setCursor(null) }
    try {
      const page = await listClosures(venueId, { id, role }, next, controller.signal)
      if (controller.signal.aborted) return
      setRows(current => next ? [...current, ...page.closures.filter(row => !current.some(old => old.closureId === row.closureId))] : page.closures)
      setCursor(page.nextCursor)
    } catch (cause) {
      if (!controller.signal.aborted) setListError(message(cause, 'Unable to load recorded closures.'))
    } finally { if (!controller.signal.aborted) setLoading(false) }
  }, [venueId, id, role])
  useEffect(() => {
    // Synchronize the venue/identity-scoped remote list on mount.
    // oxlint-disable-next-line react/set-state-in-effect
    void load()
    return () => { readRequest.current?.abort(); saveRequest.current?.abort() }
  }, [load])
  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (saveRequest.current && !saveRequest.current.signal.aborted) return
    const controller = new AbortController()
    saveRequest.current = controller
    setSaving(true); setSaveError(''); setSuccess(false)
    try {
      await createClosure(venueId, start, end, reason, user, controller.signal)
      if (controller.signal.aborted) return
      setSuccess(true); setOpen(false); setStart(''); setEnd(''); setReason('')
      void load()
    } catch (cause) {
      if (!controller.signal.aborted) setSaveError(message(cause, 'Unable to record closure.'))
    } finally {
      if (!controller.signal.aborted) { setSaving(false); saveRequest.current = null }
    }
  }
  return <section className="venue-closures" aria-label="Temporary venue closures">
    <div className="closure-section-header">
      <div><h3>Temporary venue closures</h3><p className="muted">Record and review temporary closure periods.</p></div>
      <button type="button" className="button closure-primary closure-disclosure" disabled={saving} aria-expanded={open} aria-controls="venue-closure-form" onClick={() => setOpen(!open)}>Record temporary closure <ChevronDownIcon size={16} /></button>
    </div>
    <div className="closure-notice">
      <p>Closures are recorded only; booking and availability enforcement is handled separately.</p>
      <p>All closure dates and times are Singapore time (SGT, UTC+08:00). Ongoing and future periods are allowed.</p>
    </div>
    {open && <form id="venue-closure-form" className="venue-closure-form" aria-label="Record temporary closure" onSubmit={save}>
      <div className="closure-form-heading"><h4>New closure</h4><p><span className="required-marker" aria-hidden="true">*</span> Required fields</p></div>
      <div className="field closure-field-wide"><label htmlFor="closure-venue">Closure venue</label><input id="closure-venue" readOnly aria-describedby="closure-venue-help" value={venueName} /><small id="closure-venue-help">Preselected venue. This cannot be changed here.</small></div>
      <div className="field"><div className="closure-field-label"><label htmlFor="closure-start">Closure start (SGT)</label><span className="required-marker" aria-hidden="true">*</span></div><input id="closure-start" type="datetime-local" required disabled={saving} value={start} onChange={e => setStart(e.target.value)} /></div>
      <div className="field"><div className="closure-field-label"><label htmlFor="closure-end">Closure end (SGT)</label><span className="required-marker" aria-hidden="true">*</span></div><input id="closure-end" type="datetime-local" required disabled={saving} value={end} onChange={e => setEnd(e.target.value)} /></div>
      <div className="field closure-field-wide"><div className="closure-field-label"><label htmlFor="closure-reason">Reason</label><span className="required-marker" aria-hidden="true">*</span></div><textarea id="closure-reason" required disabled={saving} value={reason} onChange={e => setReason(e.target.value)} /></div>
      <div className="venue-detail-action-buttons">
        <button type="button" className="button" disabled={saving} onClick={() => setOpen(false)}>Cancel closure</button>
        <button className="button closure-primary" disabled={saving}>{saving ? 'Saving closure…' : 'Save closure'}</button>
      </div>
    </form>}
    {success && <p className="closure-success" role="status">Closure recorded.</p>}
    {saveError && <p className="field-error" role="alert">{saveError}</p>}
    <div className="closure-history-header">
      <h4>Recorded closures</h4>
      <button type="button" className="button closure-secondary" onClick={() => void load()}><RefreshIcon size={15} /> Refresh closures</button>
    </div>
    {listError && <p className="field-error" role="alert">{listError}</p>}
    {loading && <p role="status">Loading closures…</p>}
    {!loading && !listError && rows.length === 0 && <div className="closure-empty"><ListIcon size={22} /><div><p>No recorded closures.</p><span>Recorded closure periods will appear here.</span></div></div>}
    <ul className="closure-list" aria-label="Recorded closures">{rows.map(row => <li key={row.closureId}>
      <strong>{row.reason}</strong>
      <p>{formatDate(row.startDateTime)} – {formatDate(row.endDateTime)}</p>
      <p className="muted">Recorded by: {row.createdBy ?? 'Not recorded'} · {row.createdAt ? formatDate(row.createdAt) : 'Creation time not recorded'}</p>
      <small>Closure ID: {row.closureId}</small>
    </li>)}</ul>
    {cursor && <button type="button" className="button" disabled={loading} onClick={() => void load(cursor)}>Load more closures</button>}
  </section>
}
