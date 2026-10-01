import type { ReactNode } from 'react'
import type { Role, Route } from '../types'
import { StatusBadge } from '../components/FormControls'
import { ArrowRightIcon, CheckIcon, PlusIcon } from '../components/Icon'

export function DashboardPage({ onNavigate, role, userName }: { onNavigate: (route: Route) => void; role: Role; userName?: string }) {
  const firstName = userName?.trim().split(' ')[0]

  return (
    <div className="page-stack">
      <section className="welcome-panel">
        <div>
          <h2>{firstName ? `Hi ${firstName}, any events for today?` : 'Any events for today?'}</h2>
          <p className="muted">A focused home for submitting, coordinating, and reviewing event requests.</p>
        </div>
        <span className="role-pill">{role}</span>
      </section>

      <div className="card-grid">
        <ActionCard icon={<PlusIcon size={19} />} title="Submit an event" text="Capture the details and requirements for a new event request." onClick={() => onNavigate('submit')} />
        <ActionCard icon={<CheckIcon size={19} />} title="Review requests" text="Assign coordinators, reassign ownership, and approve submitted requests." onClick={() => onNavigate('review')} />
      </div>

      <section className="panel">
        <div className="section-heading">
          <h3>Current event</h3>
          <StatusBadge status="Pending" />
        </div>

        <h2>Southeast Asia Technology Conference</h2>

        <div className="event-meta">
          <span><strong>24 Oct 2026</strong> Date</span>
          <span><strong>280</strong> Attendees</span>
          <span><strong>Auditorium</strong> Venue</span>
        </div>

        <button className="text-button" onClick={() => onNavigate('manage')}>
          Open event details <ArrowRightIcon size={15} />
        </button>
      </section>
    </div>
  )
}

function ActionCard({ icon, title, text, onClick }: { icon: ReactNode; title: string; text: string; onClick: () => void }) {
  return (
    <button className="action-card" onClick={onClick}>
      <span className="action-card-icon">{icon}</span>

      <span className="action-card-body">
        <strong>{title}</strong>
        <span className="muted">{text}</span>
      </span>

      <ArrowRightIcon size={16} className="icon" />
    </button>
  )
}
