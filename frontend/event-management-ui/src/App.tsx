import { useEffect, useState } from 'react'
import './App.css'
import { Sidebar, Topbar } from './components/Navigation'
import { DashboardPage } from './pages/DashboardPage'
import { EventDetailPage } from './pages/EventDetailPage'
import { ManagePage } from './pages/ManagePage'
import { MyEventsPage } from './pages/MyEventsPage'
import { SubmittedRequestsPage } from './pages/SubmittedRequestsPage'
import { SubmissionPage } from './pages/SubmissionPage'
import { EquipmentPage } from './pages/EquipmentPage'
import { VenueCataloguePage } from './pages/VenueCataloguePage'
import { VenueCalendarPage } from './pages/VenueCalendarPage'
import { VenueDetailPage } from './pages/VenueDetailPage'
import { VenueSearchPage } from './pages/VenueSearchPage'
import { fetchUsers } from './features/user/users'
import { routeTitles } from './types'
import type { EventData, Route, User } from './types'
import { AlertIcon, CheckIcon } from './components/Icon'

const ACTIVE_USER_STORAGE_KEY = 'activeUserId'

const paths: Record<Route, string> = {
  dashboard: '/',
  submit: '/events/new',
  manage: '/events/evt-001/edit',
  review: '/requests/review',
  detail: '/events',
  myEvents: '/my-events',
  venues: '/venues',
  venueDetail: '/venues',
  venueCalendar: '/venue-availability',
  // Not '/venues/search': getRoute() reads any /venues/<something> as a
  // venue detail page.
  venueSearch: '/venue-search',
  equipment: '/equipment',
}

function getRoute(): Route {
  const path = window.location.pathname
  if (path === '/events/new') return 'submit'
  if (path.includes('/edit')) return 'manage'
  if (path === '/requests/review') return 'review'
  if (path === '/my-events') return 'myEvents'
  if (path === '/venue-availability') return 'venueCalendar'
  if (path === '/equipment') return 'equipment'
  if (path === '/venues') return 'venues'
  if (path === '/venue-search') return 'venueSearch'
  if (/^\/venues\/[^/]+$/.test(path)) return 'venueDetail'
  if (/^\/events\/[^/]+$/.test(path)) return 'detail'
  return 'dashboard'
}

function getEventId(): string | null {
  const match = window.location.pathname.match(/^\/events\/([^/]+)$/)
  return match ? match[1] : null
}

function getVenueId(): string | null {
  const match = window.location.pathname.match(/^\/venues\/([^/]+)$/)
  return match ? match[1] : null
}

function App() {
  const [route, setRoute] = useState<Route>(getRoute)
  const [eventId, setEventId] = useState<string | null>(getEventId)
  const [venueId, setVenueId] = useState<string | null>(getVenueId)
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
    venueId: '',
    venueRequirements: '',
    accessibilityNeeds: '',
    equipmentRequirements: '',
    registrationNeeds: '',
  })
  const [notice, setNotice] = useState<{ message: string; tone: 'success' | 'error' } | null>(null)

  useEffect(() => {
    if (route !== 'venueCalendar') return
    const previousTitle = document.title
    document.title = 'Venue availability calendar · ConnectSphere'
    return () => { document.title = previousTitle }
  }, [route])

  useEffect(() => {
    const handlePopState = () => {
      setRoute(getRoute())
      setEventId(getEventId())
      setVenueId(getVenueId())
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    let active = true
    fetchUsers().then((fetched) => {
      if (active) setUsers(fetched)
    }).catch((cause: Error) => {
      if (active) setNotice({ message: `Unable to load users: ${cause.message}`, tone: 'error' })
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
    setNotice(null)
    window.history.pushState({}, '', paths[nextRoute])
    setRoute(nextRoute)
  }

  const navigateToEvent = (id: string) => {
    setNotice(null)
    setDetailOrigin(route)
    setEventId(id)
    window.history.pushState({}, '', `/events/${id}`)
    setRoute('detail')
  }

  const navigateToVenue = (id: string) => {
    setNotice(null)
    setVenueId(id)
    window.history.pushState({}, '', `/venues/${id}`)
    setRoute('venueDetail')
  }

  const updateEvent = (field: keyof EventData, value: string) => {
    setEvent((current) => ({ ...current, [field]: value }))
  }

  const role = activeUser?.role ?? 'Event Organiser'
  const isManager = activeUser?.role === 'Event Coordinator' && activeUser?.managerId === null
  const resolveUserName = (userId: string | null | undefined) => users.find((user) => user.id === userId)?.username ?? null

  return <div className="app-shell">
    <Sidebar route={route} role={role} onNavigate={navigate} />
    <main className={`main-content${route === 'venueCalendar' ? ' calendar-route' : ''}`}>
      <Topbar route={route} users={users} activeUserId={activeUser?.id ?? ''} onUserChange={setActiveUserId} />
      {notice && <div className={`notice ${notice.tone}`} role={notice.tone === 'error' ? 'alert' : 'status'}>{notice.tone === 'success' ? <CheckIcon size={15} /> : <AlertIcon size={15} />}{notice.message}</div>}
      {route === 'dashboard' && <DashboardPage onNavigate={navigate} role={role} userName={activeUser?.username} />}
      {route === 'submit' && <SubmissionPage role={role} />}
      {route === 'manage' && <ManagePage event={event} updateEvent={updateEvent} onSave={() => setNotice({ message: 'Event details saved locally.', tone: 'success' })} />}
      {route === 'review' && <SubmittedRequestsPage key={activeUser?.id} role={role} isManager={isManager} currentCoordinatorId={activeUser?.id} currentCoordinatorName={activeUser?.username} resolveUserName={resolveUserName} onViewDetails={navigateToEvent} />}
      {route === 'myEvents' && <MyEventsPage key={activeUser?.id} role={role} isManager={isManager} currentCoordinatorId={activeUser?.id} currentCoordinatorName={activeUser?.username} onViewDetails={navigateToEvent} />}
      {route === 'venueCalendar' && <VenueCalendarPage user={activeUser} />}
      {route === 'equipment' && <EquipmentPage key={activeUser?.id} role={role} user={activeUser ?? null} />}
      {route === 'venues' && <VenueCataloguePage role={role} onViewVenue={navigateToVenue} />}
      {route === 'venueSearch' && <VenueSearchPage role={role} onViewVenue={navigateToVenue} />}
      {route === 'venueDetail' && venueId && <VenueDetailPage key={venueId} venueId={venueId} role={role} onBack={() => navigate('venues')} />}
      {route === 'detail' && eventId && <EventDetailPage key={`${eventId}-${activeUser?.id}`} eventId={eventId} role={role} isManager={isManager} currentCoordinatorId={activeUser?.id} currentCoordinatorName={activeUser?.username} resolveUserName={resolveUserName} backLabel={routeTitles[detailOrigin]} onBack={() => navigate(detailOrigin)} />}
    </main>
  </div>
}

export default App
