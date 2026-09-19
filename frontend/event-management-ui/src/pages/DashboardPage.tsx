import type { Role, Route } from '../types'
import { StatusBadge } from '../components/FormControls'

export function DashboardPage({ onNavigate, role }: { onNavigate: (route: Route) => void; role: Role }) {
  return <div className="page-stack"><section className="welcome-panel"><div><p className="eyebrow">SPRINT WORKSPACE</p><h2>Keep every event moving.</h2><p className="muted">A focused home for submitting, coordinating, and reviewing event requests.</p></div><span className="welcome-number">04</span></section><div className="section-heading"><div><p className="eyebrow">QUICK START</p><h2>What needs your attention?</h2></div><span className="role-pill">{role}</span></div><div className="card-grid"><ActionCard number="01" title="Submit an event" text="Capture the details and requirements for a new event request." onClick={() => onNavigate('submit')} /><ActionCard number="02" title="Review requests" text="Assign coordinators, reassign ownership, and approve submitted requests." onClick={() => onNavigate('review')} /></div><section className="panel"><div className="section-heading"><div><p className="eyebrow">CURRENT EVENT</p><h2>Southeast Asia Technology Conference</h2></div><StatusBadge status="Pending" /></div><div className="event-meta"><span><strong>24 Oct 2026</strong> Date</span><span><strong>280</strong> Attendees</span><span><strong>Auditorium</strong> Venue</span></div><button className="text-button" onClick={() => onNavigate('myEvents')}>Open My Events <span>→</span></button></section></div>
}

function ActionCard({ number, title, text, onClick }: { number: string; title: string; text: string; onClick: () => void }) {
  return <button className="action-card" onClick={onClick}><span className="card-number">{number}</span><span><strong>{title}</strong><span className="muted">{text}</span></span><span className="card-arrow">→</span></button>
}
