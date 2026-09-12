import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import './App.css'

type Role = 'Requester' | 'Event Coordinator' | 'Venue Staff' | 'Technical Support'
type Route = 'dashboard' | 'submit' | 'assignment' | 'manage' | 'review'
type RequestStatus = 'Pending' | 'Approved' | 'Rejected'

interface EventData {
  title: string
  description: string
  purpose: string
  date: string
  venue: string
  equipment: string
  attendance: string
}

const roles: Role[] = ['Requester', 'Event Coordinator', 'Venue Staff', 'Technical Support']
const users = [
  { name: 'Alicia Tan', role: 'Event Coordinator', initials: 'AT' },
  { name: 'Marcus Lim', role: 'Event Coordinator', initials: 'ML' },
  { name: 'Priya Nair', role: 'Event Coordinator', initials: 'PN' },
]
const initialRequests = [
  { id: 1, title: 'Southeast Asia Technology Conference', date: '24 Oct 2026', venue: 'Auditorium, 300 seats', attendance: '280', status: 'Pending' as RequestStatus },
  { id: 2, title: 'Design Thinking Workshop', date: '02 Nov 2026', venue: 'Innovation Lab', attendance: '70', status: 'Pending' as RequestStatus },
]
const initialEvent: EventData = {
  title: 'Southeast Asia Technology Conference',
  description: 'A one-day conference connecting students and technology leaders.',
  purpose: 'Share practical insights about emerging technology careers.',
  date: '24 Oct 2026, 9:00 AM - 5:00 PM',
  venue: 'Auditorium, 300 seats',
  equipment: 'Projector, 2 wireless microphones, stage lighting',
  attendance: '280 attendees',
}

function getRoute(): Route {
  const path = window.location.pathname
  if (path === '/events/new') return 'submit'
  if (path.includes('assign-coordinator')) return 'assignment'
  if (path.includes('/edit')) return 'manage'
  if (path === '/requests/review') return 'review'
  return 'dashboard'
}

const paths: Record<Route, string> = {
  dashboard: '/',
  submit: '/events/new',
  assignment: '/events/evt-001/assign-coordinator',
  manage: '/events/evt-001/edit',
  review: '/requests/review',
}
const routeTitles: Record<Route, string> = { dashboard: 'Overview', submit: 'Submit an event', assignment: 'Coordinator assignment', manage: 'Event information', review: 'Request review' }

function App() {
  const [route, setRoute] = useState<Route>(getRoute)
  const [role, setRole] = useState<Role>('Requester')
  const [event, setEvent] = useState<EventData>(initialEvent)
  const [coordinator, setCoordinator] = useState(users[0].name)
  const [requests, setRequests] = useState(initialRequests)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    const handlePopState = () => setRoute(getRoute())
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const go = (nextRoute: Route) => {
    setNotice('')
    window.history.pushState({}, '', paths[nextRoute])
    setRoute(nextRoute)
  }
  const updateEvent = (field: keyof EventData, value: string) => setEvent((current) => ({ ...current, [field]: value }))

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">C</span><span>ConnectSphere</span></div>
      <p className="nav-label">Workspace</p>
      <nav className="nav-list" aria-label="Main navigation">
        <NavButton active={route === 'dashboard'} onClick={() => go('dashboard')} icon="⌂">Overview</NavButton>
        <NavButton active={route === 'submit'} onClick={() => go('submit')} icon="＋">Submit event</NavButton>
        <NavButton active={route === 'assignment'} onClick={() => go('assignment')} icon="◎">Coordinator</NavButton>
        <NavButton active={route === 'manage'} onClick={() => go('manage')} icon="✎">Event details</NavButton>
        <NavButton active={route === 'review'} onClick={() => go('review')} icon="✓">Request review</NavButton>
      </nav>
      <div className="sidebar-footer"><span className="status-dot" /> UI baseline · mock data</div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div><p className="eyebrow">EVENT OPERATIONS</p><h1>{routeTitles[route]}</h1></div><label className="role-switcher">Viewing as<select value={role} onChange={(change) => setRole(change.target.value as Role)} aria-label="Select mock role">{roles.map((option) => <option key={option}>{option}</option>)}</select></label></header>
      {notice && <div className="notice" role="status">{notice}</div>}
      {route === 'dashboard' && <Dashboard onNavigate={go} role={role} />}
      {route === 'submit' && <SubmissionPage event={event} updateEvent={updateEvent} onSubmit={() => setNotice('Event request saved locally as a mock submission.')} />}
      {route === 'assignment' && <AssignmentPage coordinator={coordinator} setCoordinator={setCoordinator} onSave={() => setNotice(`Coordinator updated locally to ${coordinator}.`)} />}
      {route === 'manage' && <ManagePage event={event} updateEvent={updateEvent} onSave={() => setNotice('Event details saved locally.')} />}
      {route === 'review' && <ReviewPage role={role} requests={requests} setRequests={setRequests} onAction={setNotice} />}
    </main>
  </div>
}

function NavButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: string; children: string }) { return <button className={`nav-button ${active ? 'active' : ''}`} onClick={onClick}><span>{icon}</span>{children}</button> }
function Dashboard({ onNavigate, role }: { onNavigate: (route: Route) => void; role: Role }) { return <div className="page-stack"><section className="welcome-panel"><div><p className="eyebrow">SPRINT WORKSPACE</p><h2>Keep every event moving.</h2><p className="muted">A focused home for submitting, coordinating, and reviewing event requests.</p></div><span className="welcome-number">04</span></section><div className="section-heading"><div><p className="eyebrow">QUICK START</p><h2>What needs your attention?</h2></div><span className="role-pill">{role}</span></div><div className="card-grid"><ActionCard number="01" title="Submit an event" text="Capture the details and requirements for a new event request." onClick={() => onNavigate('submit')} /><ActionCard number="02" title="Assign a coordinator" text="Choose a coordinator to own the next step of an event." onClick={() => onNavigate('assignment')} /><ActionCard number="03" title="Review requests" text="Approve or reject submitted venue requests." onClick={() => onNavigate('review')} /></div><section className="panel"><div className="section-heading"><div><p className="eyebrow">CURRENT EVENT</p><h2>Southeast Asia Technology Conference</h2></div><StatusBadge status="Pending" /></div><div className="event-meta"><span><strong>24 Oct 2026</strong> Date</span><span><strong>280</strong> Attendees</span><span><strong>Auditorium</strong> Venue</span></div><button className="text-button" onClick={() => onNavigate('manage')}>Open event details <span>→</span></button></section></div> }
function ActionCard({ number, title, text, onClick }: { number: string; title: string; text: string; onClick: () => void }) { return <button className="action-card" onClick={onClick}><span className="card-number">{number}</span><span><strong>{title}</strong><span className="muted">{text}</span></span><span className="card-arrow">→</span></button> }
function SubmissionPage({ event, updateEvent, onSubmit }: { event: EventData; updateEvent: (field: keyof EventData, value: string) => void; onSubmit: () => void }) { return <div className="page-stack"><section className="intro"><p className="muted">Create a mock request with the details Event services will eventually own.</p></section><form className="panel form-panel" onSubmit={(submitEvent) => { submitEvent.preventDefault(); onSubmit() }}><FormSection title="Event basics" hint="Required fields from the event request story."><Field label="Event title" value={event.title} onChange={(value) => updateEvent('title', value)} required /><Field label="Description" value={event.description} onChange={(value) => updateEvent('description', value)} textarea required /><Field label="Purpose" value={event.purpose} onChange={(value) => updateEvent('purpose', value)} textarea required /></FormSection><FormSection title="Date and capacity"><div className="field-row"><Field label="Preferred date and time" value={event.date} onChange={(value) => updateEvent('date', value)} required /><Field label="Expected attendance" value={event.attendance} onChange={(value) => updateEvent('attendance', value)} required /></div></FormSection><FormSection title="Requirements" hint="These optional requests help shape the event plan."><Field label="Venue request" value={event.venue} onChange={(value) => updateEvent('venue', value)} textarea /><Field label="Requested equipment" value={event.equipment} onChange={(value) => updateEvent('equipment', value)} textarea /></FormSection><div className="form-actions"><button type="button" className="button secondary">Save draft</button><button type="submit" className="button primary">Submit request</button></div></form></div> }
function AssignmentPage({ coordinator, setCoordinator, onSave }: { coordinator: string; setCoordinator: (value: string) => void; onSave: () => void }) { return <div className="page-stack"><section className="panel event-summary"><div><p className="eyebrow">EVENT EVT-001</p><h2>Southeast Asia Technology Conference</h2><p className="muted">24 Oct 2026 · Auditorium · 280 attendees</p></div><StatusBadge status="Pending" /></section><section className="panel"><div className="section-heading"><div><p className="eyebrow">DELEGATION</p><h2>Select an event coordinator</h2><p className="muted">Assign or reassign ownership for this event.</p></div><span className="current-assignee">Current: {coordinator}</span></div><div className="user-list">{users.map((user) => <button className={`user-row ${coordinator === user.name ? 'selected' : ''}`} key={user.name} onClick={() => setCoordinator(user.name)}><span className="avatar">{user.initials}</span><span><strong>{user.name}</strong><small>{user.role}</small></span><span className="radio-mark">{coordinator === user.name ? '●' : '○'}</span></button>)}</div><div className="form-actions"><button className="button primary" onClick={onSave}>Save assignment</button></div></section></div> }
function ManagePage({ event, updateEvent, onSave }: { event: EventData; updateEvent: (field: keyof EventData, value: string) => void; onSave: () => void }) { return <div className="page-stack"><div className="two-column"><section className="panel"><div className="section-heading"><div><p className="eyebrow">EDIT EVENT</p><h2>Event information</h2></div><StatusBadge status="Pending" /></div><Field label="Event title" value={event.title} onChange={(value) => updateEvent('title', value)} /><Field label="Description" value={event.description} onChange={(value) => updateEvent('description', value)} textarea /><Field label="Purpose" value={event.purpose} onChange={(value) => updateEvent('purpose', value)} textarea /><Field label="Date and time" value={event.date} onChange={(value) => updateEvent('date', value)} /><Field label="Venue request" value={event.venue} onChange={(value) => updateEvent('venue', value)} textarea /><button className="button primary" onClick={onSave}>Save changes</button></section><section className="panel"><div className="section-heading"><div><p className="eyebrow">IMPACT CHECK</p><h2>Planning indicators</h2><p className="muted">Placeholder signals for later validation.</p></div></div><Impact label="Venue suitability" value="Review" tone="warning" /><Impact label="Equipment availability" value="Ready" tone="success" /><Impact label="Schedule conflicts" value="No conflicts" tone="success" /><Impact label="Overall impact" value="Medium" tone="warning" /></section></div></div> }
function ReviewPage({ role, requests, setRequests, onAction }: { role: Role; requests: typeof initialRequests; setRequests: (requests: typeof initialRequests) => void; onAction: (message: string) => void }) { const [reasonId, setReasonId] = useState<number | null>(null); const [reason, setReason] = useState(''); const canReview = role === 'Venue Staff'; const updateStatus = (id: number, status: RequestStatus) => { setRequests(requests.map((request) => request.id === id ? { ...request, status } : request)); setReasonId(null); onAction(`Request ${status.toLowerCase()} locally.`) }; return <div className="page-stack"><section className="intro"><p className="muted">Venue Staff can make a mock decision on submitted event requests.</p>{!canReview && <div className="role-warning">Switch the role selector to <strong>Venue Staff</strong> to show review actions.</div>}</section><section className="panel table-panel"><div className="table-scroll"><table><thead><tr><th>Event request</th><th>Date</th><th>Venue</th><th>Attendance</th><th>Status</th><th>Action</th></tr></thead><tbody>{requests.map((request) => <tr key={request.id}><td><strong>{request.title}</strong><small>Request #{request.id.toString().padStart(3, '0')}</small></td><td>{request.date}</td><td>{request.venue}</td><td>{request.attendance}</td><td><StatusBadge status={request.status} /></td><td>{canReview && request.status === 'Pending' ? <div className="table-actions"><button className="button small approve" onClick={() => updateStatus(request.id, 'Approved')}>Approve</button><button className="button small reject" onClick={() => setReasonId(request.id)}>Reject</button></div> : <span className="muted">No action</span>}{reasonId === request.id && <div className="reject-box"><label htmlFor="reason">Reason for rejection</label><textarea id="reason" value={reason} onChange={(change) => setReason(change.target.value)} placeholder="Add a mock reason" /><button className="button small reject" onClick={() => updateStatus(request.id, 'Rejected')}>Confirm rejection</button></div>}</td></tr>)}</tbody></table></div></section></div> }
function FormSection({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) { return <section className="form-section"><h3>{title}</h3>{hint && <p className="muted section-hint">{hint}</p>}{children}</section> }
function Field({ label, value, onChange, textarea, required }: { label: string; value: string; onChange: (value: string) => void; textarea?: boolean; required?: boolean }) { const Tag = textarea ? 'textarea' : 'input'; return <label className="field">{label}{required && <span className="required"> *</span>}<Tag value={value} onChange={(change) => onChange(change.target.value)} /></label> }
function StatusBadge({ status }: { status: RequestStatus | string }) { return <span className={`status-badge ${status.toLowerCase()}`}>{status}</span> }
function Impact({ label, value, tone }: { label: string; value: string; tone: 'success' | 'warning' }) { return <div className="impact-row"><span><span className={`impact-icon ${tone}`}>{tone === 'success' ? '✓' : '!'}</span>{label}</span><strong className={tone}>{value}</strong></div> }

export default App
