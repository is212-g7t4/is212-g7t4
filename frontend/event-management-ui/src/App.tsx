import { useEffect, useState } from 'react'
import './App.css'
import { Sidebar, Topbar } from './components/Navigation'
import { users } from './mockData'
import { AssignmentPage } from './pages/AssignmentPage'
import { DashboardPage } from './pages/DashboardPage'
import { EventDetailPage } from './pages/EventDetailPage'
import { ManagePage } from './pages/ManagePage'
import { MyEventsPage } from './pages/MyEventsPage'
import { SubmittedRequestsPage } from './pages/SubmittedRequestsPage'
import { SubmissionPage } from './pages/SubmissionPage'
import { routeTitles } from './types'
import type { EventData, Role, Route } from './types'

const paths: Record<Route, string> = {
  dashboard: '/',
  submit: '/events/new',
  assignment: '/events/evt-001/assign-coordinator',
  manage: '/events/evt-001/edit',
  review: '/requests/review',
  detail: '/events',
  myEvents: '/my-events',
}

function getRoute(): Route {
  const path = window.location.pathname
  if (path === '/events/new') return 'submit'
  if (path.includes('assign-coordinator')) return 'assignment'
  if (path.includes('/edit')) return 'manage'
  if (path === '/requests/review') return 'review'
  if (path === '/my-events') return 'myEvents'
  if (/^\/events\/[^/]+$/.test(path)) return 'detail'
  return 'dashboard'
}

function getEventId(): string | null {
  const match = window.location.pathname.match(/^\/events\/([^/]+)$/)
  return match ? match[1] : null
}

function App() {
  const [route, setRoute] = useState<Route>(getRoute)
  const [eventId, setEventId] = useState<string | null>(getEventId)
  const [detailOrigin, setDetailOrigin] = useState<Route>('review')
  const [role, setRole] = useState<Role>('Requester')
  const [event, setEvent] = useState<EventData>({
  eventName: '',
  description: '',
  purpose: '',
  preferredStartDate: '',
  preferredEndDate: '',
  expectedAttendance: '',
  venueRequirements: '',
  accessibilityNeeds: '',
  equipmentRequirements: '',
  registrationNeeds: '',
})
  const [coordinator, setCoordinator] = useState(users[0].name)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    const handlePopState = () => {
      setRoute(getRoute())
      setEventId(getEventId())
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const navigate = (nextRoute: Route) => {
    setNotice('')
    window.history.pushState({}, '', paths[nextRoute])
    setRoute(nextRoute)
  }

  const navigateToEvent = (id: string) => {
    setNotice('')
    setDetailOrigin(route)
    setEventId(id)
    window.history.pushState({}, '', `/events/${id}`)
    setRoute('detail')
  }

  const updateEvent = (field: keyof EventData, value: string) => {
    setEvent((current) => ({ ...current, [field]: value }))
  }

  return <div className="app-shell">
    <Sidebar route={route} onNavigate={navigate} />
    <main className="main-content">
      <Topbar route={route} role={role} onRoleChange={setRole} />
      {notice && <div className="notice" role="status">{notice}</div>}
      {route === 'dashboard' && <DashboardPage onNavigate={navigate} role={role} />}
      {route === 'submit' && <SubmissionPage role={role} />}
      {route === 'assignment' && <AssignmentPage coordinator={coordinator} setCoordinator={setCoordinator} onSave={() => setNotice(`Coordinator updated locally to ${coordinator}.`)} />}
      {route === 'manage' && <ManagePage event={event} updateEvent={updateEvent} onSave={() => setNotice('Event details saved locally.')} />}
      {route === 'review' && <SubmittedRequestsPage key={role} role={role} onViewDetails={navigateToEvent} />}
      {route === 'myEvents' && <MyEventsPage key={role} role={role} onViewDetails={navigateToEvent} />}
      {route === 'detail' && eventId && <EventDetailPage key={eventId} eventId={eventId} role={role} backLabel={routeTitles[detailOrigin]} onBack={() => navigate(detailOrigin)} />}
    </main>
  </div>
}

export default App
