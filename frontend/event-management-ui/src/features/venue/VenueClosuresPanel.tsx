import { useCallback, useEffect, useRef, useState } from 'react'
import './venueClosures.css'
import { ChevronDownIcon, RefreshIcon, ListIcon } from '../../components/Icon'
import { createClosure, listClosures, previewClosure } from './venueClosures'
import type { VenueClosure, ClosurePreview } from './venueClosures'

const formatDate = (value: string) => new Intl.DateTimeFormat('en-SG', {
  timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
}).format(new Date(value)) + ' SGT'
const message = (cause: unknown, fallback: string) => cause instanceof Error ? cause.message : fallback

// The parent keys this panel by venue and identity, so changes discard all local state.
export function VenueClosuresPanel({ venueId, venueName }: { venueId: string; venueName: string }) {
  const [rejectedCount, setRejectedCount] = useState(0)
  const [uncertain, setUncertain] = useState(false)
  const [reconciled, setReconciled] = useState(false)
  const [preview, setPreview] = useState<ClosurePreview | null>(null)
  const [open, setOpen] = useState(false)
  const [start, setStart] = useState(''), [end, setEnd] = useState(''), [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false), [success, setSuccess] = useState(false)
  const [saveError, setSaveError] = useState(''), [listError, setListError] = useState('')
  const [rows, setRows] = useState<VenueClosure[]>([])
  const [cursor, setCursor] = useState<string | null>(null), [loading, setLoading] = useState(true)
  const readRequest = useRef<AbortController | null>(null), saveRequest = useRef<AbortController | null>(null)
  const load = useCallback(async (next?: string) => {
    readRequest.current?.abort()
    const controller = new AbortController()
    readRequest.current = controller
    setLoading(true); setListError(''); setReconciled(false)
    if (!next) { setRows([]); setCursor(null) }
    try {
      const page = await listClosures(venueId, next, controller.signal)
      if (controller.signal.aborted) return
      setRows(current => next ? [...current, ...page.closures.filter(row => !current.some(old => old.closureId === row.closureId))] : page.closures)
      setCursor(page.nextCursor)
      setReconciled(page.nextCursor === null)
    } catch (cause) {
      if (!controller.signal.aborted) setListError(message(cause, 'Unable to load recorded closures.'))
    } finally { if (!controller.signal.aborted) setLoading(false) }
  }, [venueId])
  useEffect(() => {
    // Synchronize the venue-scoped remote list on mount.
    // oxlint-disable-next-line react/set-state-in-effect
    void load()
    return () => { readRequest.current?.abort(); saveRequest.current?.abort() }
  }, [load])
  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (uncertain || (saveRequest.current && !saveRequest.current.signal.aborted)) return
    const controller = new AbortController()
    saveRequest.current = controller
    setSaving(true); setSaveError(''); setSuccess(false)
    try {
      if (!preview) {
        const result = await previewClosure(venueId, start, end, reason, controller.signal)
        if (!controller.signal.aborted) setPreview(result)
        return
      }
      const saved = await createClosure(venueId, start, end, reason, preview.confirmationToken, controller.signal)
      if (controller.signal.aborted) return
      setRejectedCount(saved.rejectedCount); setPreview(null); setSuccess(true); setOpen(false); setStart(''); setEnd(''); setReason('')
      void load()
    } catch (cause) {
      if (controller.signal.aborted) return
      setPreview(null)
      if (cause instanceof Error && 'code' in cause && cause.code === 'CLOSURE_PREVIEW_CHANGED') {
        setSaveError('The affected requests changed. Review the refreshed impact and confirm again.')
        try {
          const result = await previewClosure(venueId, start, end, reason, controller.signal)
          if (!controller.signal.aborted) setPreview(result)
        } catch (refreshError) {
          if (!controller.signal.aborted) setSaveError(`Impact changed. ${message(refreshError, 'Unable to refresh preview.')} Preview again before confirming.`)
        }
      } else {
        if (preview && cause instanceof Error && 'uncertain' in cause && cause.uncertain) { setUncertain(true); void load() }
        setSaveError(message(cause, 'Unable to record closure.'))
      }
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
      <p>Saving a closure rejects overlapping Pending, Pending Review and Approved booking requests. Review the impact before confirming.</p>
      <p>All closure dates and times are Singapore time (SGT, UTC+08:00). Ongoing and future periods are allowed.</p>
    </div>
    {open && <form id="venue-closure-form" className="venue-closure-form" aria-label="Record temporary closure" onSubmit={save} onChange={() => setPreview(null)}>
      <div className="closure-form-heading"><h4>New closure</h4><p><span className="required-marker" aria-hidden="true">*</span> Required fields</p></div>
      <div className="field closure-field-wide"><label htmlFor="closure-venue">Closure venue</label><input id="closure-venue" readOnly aria-describedby="closure-venue-help" value={venueName} /><small id="closure-venue-help">Preselected venue. This cannot be changed here.</small></div>
      <div className="field"><div className="closure-field-label"><label htmlFor="closure-start">Closure start (SGT)</label><span className="required-marker" aria-hidden="true">*</span></div><input id="closure-start" type="datetime-local" required disabled={saving} value={start} onChange={e => setStart(e.target.value)} /></div>
      <div className="field"><div className="closure-field-label"><label htmlFor="closure-end">Closure end (SGT)</label><span className="required-marker" aria-hidden="true">*</span></div><input id="closure-end" type="datetime-local" required disabled={saving} value={end} onChange={e => setEnd(e.target.value)} /></div>
      <div className="field closure-field-wide"><div className="closure-field-label"><label htmlFor="closure-reason">Reason</label><span className="required-marker" aria-hidden="true">*</span></div><textarea id="closure-reason" required disabled={saving} value={reason} onChange={e => setReason(e.target.value)} /></div>
      {preview && <section className="closure-confirmation closure-field-wide" aria-label="Confirm temporary closure" tabIndex={-1} ref={node => { node?.focus() }}>
        <h4>Confirm temporary closure</h4>
        <p>{preview.affectedCount} booking requests will be rejected.</p>
        <p><strong>{venueName}</strong>: {formatDate(preview.closure.startDateTime)} – {formatDate(preview.closure.endDateTime)}</p>
        <p>{preview.closure.reason}</p>
        {preview.affectedCount === 0 && <p>No current requests are affected. The closure will still be recorded.</p>}
        <ul className="closure-impact-list" aria-label="Affected booking requests" tabIndex={0}>{preview.affectedRequests.map(row => <li key={row.id}>
          <strong>{row.eventName}</strong> · {row.venueName}
          <p>{formatDate(row.requestedStartTime)} – {formatDate(row.requestedEndTime)}</p>
          <p>{row.status} · Request ID: {row.id}</p>
        </li>)}</ul>
        <button className="button closure-secondary" type="button" disabled={saving} onClick={() => setPreview(null)}>Back to edit</button>
      </section>}
      <div className="venue-detail-action-buttons">
        <button type="button" className="button" disabled={saving} onClick={() => { setOpen(false); setPreview(null) }}>Discard closure draft</button>
        <button className="button closure-primary" disabled={saving || uncertain}>{saving ? 'Working…' : preview ? 'Confirm closure and reject requests' : 'Preview affected requests'}</button>
      </div>
    </form>}
    {success && <div className="closure-success" role="status"><p>Closure recorded.</p><p>{rejectedCount} booking requests rejected.</p></div>}
    {saveError && <p className="field-error" role="alert">{saveError}</p>}
    {uncertain && <button type="button" className="button closure-secondary" disabled={!reconciled || loading || !!listError || !!cursor} onClick={() => { setUncertain(false); setSaveError(''); setPreview(null) }}>I checked all recorded closures; start a new preview</button>}
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
