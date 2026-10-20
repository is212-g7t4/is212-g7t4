import type { EventClarification } from './submission'

function formatTimestamp(value: string): string {
  return `${new Date(value).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })} SGT`
}

export function ClarificationHistory({ clarifications, resolveUserName }: {
  clarifications: EventClarification[]
  resolveUserName?: (userId: string | null | undefined) => string | null
}) {
  if (clarifications.length === 0) return null

  return <section className="event-card-section">
    <h3>Clarifications</h3>
    <div className="page-stack">
      {[...clarifications].reverse().map((clarification) => <article className="panel" key={clarification.id}>
        <p><strong>Coordinator question</strong></p>
        <p>{clarification.question}</p>
        <p className="muted">Requested by {resolveUserName?.(clarification.requestedBy) || clarification.requestedBy} on {formatTimestamp(clarification.requestedAt)}</p>
        {clarification.response ? <>
          <p><strong>Organiser response</strong></p>
          <p>{clarification.response}</p>
          {clarification.respondedAt && <p className="muted">Responded on {formatTimestamp(clarification.respondedAt)}</p>}
        </> : <p className="muted">Awaiting the Event Organiser's response.</p>}
      </article>)}
    </div>
  </section>
}
