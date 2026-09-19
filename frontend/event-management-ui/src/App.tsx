import { useEffect, useState } from 'react'
import './App.css'
import { Sidebar, Topbar } from './components/Navigation'
import { DashboardPage } from './pages/DashboardPage'
import { EventDetailPage } from './pages/EventDetailPage'
import { ManagePage } from './pages/ManagePage'
import { MyEventsPage } from './pages/MyEventsPage'
import { SubmittedRequestsPage } from './pages/SubmittedRequestsPage'
import { SubmissionPage } from './pages/SubmissionPage'
import { AssignmentPage } from './pages/AssignmentPage'
import { users } from './mockData'
import { routeTitles } from './types'
import type { Role, Route } from './types'

const paths: Record<Route, string> = {
  dashboard: '/',
  submit: '/events/new',
  assignment: '/coordinator',
  manage: '/events/evt-001/edit',
  review: '/requests/review',
  detail: '/events',
  myEvents: '/my-events',
}

function getRoute(): Route {
  const path = window.location.pathname
  if (path === '/events/new') return 'submit'
  if (path === '/coordinator') return 'assignment'
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

function getManageEventId(): string | null {
  const match = window.location.pathname.match(/^\/events\/([^/]+)\/edit$/)
  return match ? match[1] : null
}

function App() {
  const [route, setRoute] = useState<Route>(getRoute)
  const [eventId, setEventId] = useState<string | null>(getEventId)
  const [manageEventId, setManageEventId] = useState<string | null>(getManageEventId)
  const [detailOrigin, setDetailOrigin] = useState<Route>('review')
  const [role, setRole] = useState<Role>('Requester')
  const [activeCoordinatorId, setActiveCoordinatorId] = useState(users[0].id)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    const handlePopState = () => {
      setRoute(getRoute())
      setEventId(getEventId())
      setManageEventId(getManageEventId())
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

  const navigateToManage = (id: string) => {
    setNotice('')
    setManageEventId(id)
    window.history.pushState({}, '', `/events/${id}/edit`)
    setRoute('manage')
  }

  const activeCoordinator = users.find((user) => user.id === activeCoordinatorId) ?? users[0]

  return <div className="app-shell">
    <Sidebar route={route} onNavigate={navigate} />
    <main className="main-content">
      <Topbar route={route} role={role} onRoleChange={setRole} />
      {notice && <div className="notice" role="status">{notice}</div>}
      {route === 'dashboard' && <DashboardPage onNavigate={navigate} role={role} />}
      {route === 'submit' && <SubmissionPage role={role} />}
      {route === 'assignment' && <AssignmentPage
        coordinator={activeCoordinator.name}
        setCoordinator={(value) => {
          const selected = users.find((user) => user.name === value)
          if (selected) {
            setActiveCoordinatorId(selected.id)
            setNotice(`Logged in as ${selected.name}.`)
          }
        }}
        onSave={() => setNotice(`Logged in as ${activeCoordinator.name}.`)}
      />}
      {route === 'manage' && manageEventId && <ManagePage eventId={manageEventId} coordinatorId={activeCoordinatorId} onSaved={setNotice} />}
      {route === 'review' && <SubmittedRequestsPage key={`${role}-${activeCoordinatorId}`} role={role} currentCoordinatorId={activeCoordinatorId} currentCoordinatorName={activeCoordinator.name} onViewDetails={navigateToEvent} />}
      {route === 'myEvents' && <MyEventsPage key={`${role}-${activeCoordinatorId}`} role={role} currentCoordinatorId={activeCoordinatorId} currentCoordinatorName={activeCoordinator.name} onViewDetails={navigateToEvent} />}
      {route === 'detail' && eventId && <EventDetailPage key={`${eventId}-${activeCoordinatorId}`} eventId={eventId} role={role} currentCoordinatorId={activeCoordinatorId} currentCoordinatorName={activeCoordinator.name} backLabel={routeTitles[detailOrigin]} onBack={() => navigate(detailOrigin)} onEdit={navigateToManage} />}
    </main>
  </div>
}

export default App
