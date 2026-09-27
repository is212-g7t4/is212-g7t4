import { useEffect, useState } from 'react'
import './App.css'
import { Sidebar, Topbar } from './components/Navigation'
import { DashboardPage } from './pages/DashboardPage'
import { EventDetailPage } from './pages/EventDetailPage'
import { ManagePage } from './pages/ManagePage'
import { MyEventsPage } from './pages/MyEventsPage'
import { SubmittedRequestsPage } from './pages/SubmittedRequestsPage'
import { SubmissionPage } from './pages/SubmissionPage'
import { VenueCataloguePage } from './pages/VenueCataloguePage'
import { fetchUsers } from './features/user/users'
import { routeTitles } from './types'
import type { EventData, Route, User } from './types'

const ACTIVE_USER_STORAGE_KEY = 'activeUserId'

const paths: Record<Route, string> = {
  dashboard: '/',
  submit: '/events/new',
  manage: '/events/evt-001/edit',
  review: '/requests/review',
  detail: '/events',
  myEvents: '/my-events',
  venues: '/venues',
}

function getRoute(): Route {
  const path = window.location.pathname
  if (path === '/events/new') return 'submit'
  if (path.includes('/edit')) return 'manage'
  if (path === '/requests/review') return 'review'
  if (path === '/my-events') return 'myEvents'
  if (path === '/venues') return 'venues'
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
  const [users, setUsers] = useState<User[]>([])
  const [activeUserId, setActiveUserId] = useState<string>(() => {
    try {
      return localStorage.getItem(ACTIVE_USER_STORAGE_KEY) || ''
    } catch {
      return ''
    }
  })
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
  const [notice, setNotice] = useState('')

  useEffect(() => {
    const handlePopState = () => {
      setRoute(getRoute())
      setEventId(getEventId())
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    let active = true
    fetchUsers().then((fetched) => {
      if (active) setUsers(fetched)
    }).catch((cause: Error) => {
      if (active) setNotice(cause.message)
    })
    return () => { active = false }
  }, [])

  const activeUser = users.find((user) => user.id === activeUserId) ?? users[0]

  useEffect(() => {
    try {
      if (activeUser) localStorage.setItem(ACTIVE_USER_STORAGE_KEY, activeUser.id)
    } catch {
      // localStorage unavailable (e.g. private browsing) — active user just won't persist.
    }
  }, [activeUser])

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

  const role = activeUser?.role ?? 'Event Organiser'
  const isManager = activeUser?.role === 'Event Coordinator' && activeUser?.managerId === null

  return <div className="app-shell">
    <Sidebar route={route} role={role} onNavigate={navigate} />
    <main className="main-content">
      <Topbar route={route} users={users} activeUserId={activeUser?.id ?? ''} onUserChange={setActiveUserId} />
      {notice && <div className="notice" role="status">{notice}</div>}
      {route === 'dashboard' && <DashboardPage onNavigate={navigate} role={role} />}
      {route === 'submit' && <SubmissionPage role={role} />}
      {route === 'manage' && <ManagePage event={event} updateEvent={updateEvent} onSave={() => setNotice('Event details saved locally.')} />}
      {route === 'review' && <SubmittedRequestsPage key={activeUser?.id} role={role} isManager={isManager} currentCoordinatorId={activeUser?.id} currentCoordinatorName={activeUser?.username} onViewDetails={navigateToEvent} />}
      {route === 'myEvents' && <MyEventsPage key={activeUser?.id} role={role} isManager={isManager} currentCoordinatorId={activeUser?.id} currentCoordinatorName={activeUser?.username} onViewDetails={navigateToEvent} />}
      {route === 'venues' && <VenueCataloguePage role={role} />}
      {route === 'detail' && eventId && <EventDetailPage key={`${eventId}-${activeUser?.id}`} eventId={eventId} role={role} isManager={isManager} currentCoordinatorId={activeUser?.id} currentCoordinatorName={activeUser?.username} backLabel={routeTitles[detailOrigin]} onBack={() => navigate(detailOrigin)} />}
    </main>
  </div>
}

export default App
