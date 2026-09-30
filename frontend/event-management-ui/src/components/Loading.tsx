export function Spinner({ size = 16 }: { size?: number }) {
  return <span className="spinner" style={{ width: size, height: size }} aria-hidden="true" />
}

export function InlineLoading({ label }: { label: string }) {
  return (
    <p className="inline-loading" role="status">
      <Spinner size={14} /> {label}
    </p>
  )
}

function Bone({ width, height = 12 }: { width: string; height?: number }) {
  return <span className="skeleton" style={{ width, height }} />
}

export function EventCardSkeleton() {
  return (
    <div className="panel event-card skeleton-block" aria-hidden="true">
      <header className="event-card-header">
        <div className="skeleton-stack">
          <Bone width="55%" height={18} />
        </div>
        <Bone width="72px" height={22} />
      </header>

      <div className="event-details">
        {Array.from({ length: 4 }).map((_, index) => (
          <div className="event-detail" key={index}>
            <Bone width="40%" height={9} />
            <div style={{ marginTop: 8 }}>
              <Bone width="80%" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function EventCardSkeletonList({ count = 2 }: { count?: number }) {
  return (
    <div className="skeleton-stack" role="status" aria-label="Loading">
      {Array.from({ length: count }).map((_, index) => <EventCardSkeleton key={index} />)}
    </div>
  )
}

export function VenueCardSkeleton() {
  return (
    <div className="venue-card skeleton-block" aria-hidden="true">
      <span className="venue-card-header">
        <Bone width="60%" height={16} />
        <Bone width="70px" height={20} />
      </span>
      <Bone width="45%" />
      <Bone width="35%" />
      <span className="chip-list">
        <Bone width="56px" height={20} />
        <Bone width="64px" height={20} />
      </span>
    </div>
  )
}

export function VenueCardGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="venue-card-grid" role="status" aria-label="Loading venues">
      {Array.from({ length: count }).map((_, index) => <VenueCardSkeleton key={index} />)}
    </div>
  )
}

export function DetailPanelSkeleton() {
  return (
    <article className="panel event-card skeleton-block" role="status" aria-label="Loading">
      <header className="event-card-header">
        <Bone width="45%" height={20} />
        <Bone width="72px" height={22} />
      </header>

      <div className="event-details">
        {Array.from({ length: 6 }).map((_, index) => (
          <div className="event-detail" key={index}>
            <Bone width="35%" height={9} />
            <div style={{ marginTop: 8 }}>
              <Bone width={index % 2 === 0 ? '85%' : '60%'} />
            </div>
          </div>
        ))}
      </div>
    </article>
  )
}

export function TableSkeleton({ rows = 4, columns = 5 }: { rows?: number; columns?: number }) {
  return (
    <div className="panel table-panel skeleton-block" role="status" aria-label="Loading">
      <div className="table-scroll">
        <table>
          <tbody>
            {Array.from({ length: rows }).map((_, row) => (
              <tr key={row}>
                {Array.from({ length: columns }).map((_, col) => (
                  <td key={col}><Bone width={col === 0 ? '80%' : '55%'} /></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
