import type { EventAmendment } from './submission'
import { FIELD_INPUTS, fieldLabels, sentenceList } from './eventDetails'
import { formatDateTime, formatTimestamp } from './formatDates'

// SCRUM-16 AC2/AC4/AC5: every amendment round, built like ClarificationHistory.
// The from → to list names each date separately, so it uses the form labels
// rather than the shared "Date/time" one.
function fieldLabel(field: string): string {
  return FIELD_INPUTS.find((input) => input.field === field)?.label || field
}

function displayValue(field: string, value: string): string {
  if (!value) return '(blank)'
  const isDate = FIELD_INPUTS.some((input) => input.field === field && input.type === 'datetime')
  return isDate ? formatDateTime(value) : value
}

export function AmendmentHistory({ amendments, resolveUserName }: {
  amendments: EventAmendment[]
  resolveUserName?: (userId: string | null | undefined) => string | null
}) {
  if (amendments.length === 0) return null

  return <section className="event-card-section">
    <h3>Amendments</h3>
    <div className="page-stack">
      {[...amendments].reverse().map((amendment) => <article className="panel" key={amendment.id}>
        <p><strong>Fields to amend:</strong> {sentenceList(fieldLabels(amendment.fields))}</p>
        <p>{amendment.reason}</p>
        <p className="muted">Requested by {resolveUserName?.(amendment.requestedBy) || amendment.requestedBy} on {formatTimestamp(amendment.requestedAt)}</p>
        {amendment.resubmittedAt ? <>
          <p><strong>Resubmitted on {formatTimestamp(amendment.resubmittedAt)}</strong></p>
          {amendment.changes && Object.keys(amendment.changes).length > 0 && <ul aria-label="Amended fields">
            {Object.entries(amendment.changes).map(([field, change]) => <li key={field}>
              {fieldLabel(field)}: {displayValue(field, change.from)} → {displayValue(field, change.to)}
            </li>)}
          </ul>}
          {amendment.note && <p><strong>Organiser note:</strong> {amendment.note}</p>}
        </> : <p className="muted">Awaiting the Event Organiser's amendment.</p>}
      </article>)}
    </div>
  </section>
}
