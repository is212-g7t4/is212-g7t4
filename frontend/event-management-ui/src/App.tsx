import { useEffect, useState } from 'react'
import { NotificationProvider, NotificationsPage } from './features/notifications/NotificationCenter'
import './App.css'
import { Sidebar, Topbar } from './components/Navigation'
import { DashboardPage } from './pages/DashboardPage'
import { EventDetailPage } from './pages/EventDetailPage'
import { ManagePage } from './pages/ManagePage'
import { MyEventsPage } from './pages/MyEventsPage'
import { AttendeeEventsPage } from './pages/AttendeeEventsPage'
import { AttendeeRegistrationsPage } from './pages/AttendeeRegistrationsPage'
import { SubmittedRequestsPage } from './pages/SubmittedRequestsPage'
import { ChangeRequestsPage } from './pages/ChangeRequestsPage'
import { UnassignedQueuePage } from './pages/UnassignedQueuePage'
import { CoordinatorWorkloadPage } from './pages/CoordinatorWorkloadPage'
import { EventsTabs } from './components/EventsTabs'
import { coordinatorEventTabs } from './features/event/permissions'
import { isCoordinator } from './roles'
import { SubmissionPage } from './pages/SubmissionPage'
import { EquipmentPage } from './pages/EquipmentPage'
import { EquipmentRequestsPage } from './pages/EquipmentRequestsPage'
import { SafetyChecksPage } from './pages/SafetyChecksPage'
import { NewEquipmentRequestPage } from './pages/NewEquipmentRequestPage'
import { VenueCataloguePage } from './pages/VenueCataloguePage'
import { VenueRequestsPage } from './pages/VenueRequestsPage'
import { VenueCalendarPage } from './pages/VenueCalendarPage'
import { VenueDetailPage } from './pages/VenueDetailPage'
import { VenueSearchPage } from './pages/VenueSearchPage'
import { AddVenuePage, EditVenuePage } from './pages/AddVenuePage'
import { fetchUsers } from './features/user/users'
import { routeTitles } from './types'
import type { EventData, Role, Route, User } from './types'
import { AlertIcon, CheckIcon } from './components/Icon'
import { HoldReminderAlert } from './features/venue/HoldReminderAlert'

const ACTIVE_USER_STORAGE_KEY = 'activeUserId'

const paths: Record<Route, string> = {
  notifications: '/notifications',
  dashboard: '/',
  submit: '/events/new',
  manage: '/events/evt-001/edit',
  review: '/requests/review',
  changeRequests: '/change-requests',
  queue: '/requests/queue',
  workload: '/requests/workload',
  detail: '/events',
  myEvents: '/my-events',
  browseEvents: '/events/browse',
  myRegistrations: '/registrations',
  venues: '/venues',
  venueDetail: '/venues',
  venueCalendar: '/venue-availability',
  venueRequests: '/venue-requests',
  // Not '/venues/search': getRoute() reads any /venues/<something> as a
  // venue detail page.
  venueSearch: '/venue-search',
  addVenue: '/venues/new',
  editVenue: '/venues',
  equipment: '/equipment',
  equipmentRequests: '/equipment-requests',
  safetyChecks: '/safety-checks',
  newEquipmentRequest: '/equipment-requests/new',
  editDraft: '/drafts',
}

function getRoute(): Route {
  const path = window.location.pathname
  if (path === '/notifications') return 'notifications'
  if (path === '/events/new') return 'submit'
  if (/^\/events\/[^/]+\/edit$/.test(path)) return 'manage'
  if (path === '/requests/review') return 'review'
  if (path === '/change-requests') return 'changeRequests'
  if (path === '/requests/queue') return 'queue'
  if (path === '/requests/workload') return 'workload'
  if (path === '/my-events') return 'myEvents'
  if (path === '/events/browse') return 'browseEvents'
  if (path === '/registrations') return 'myRegistrations'
  if (path === '/venue-availability') return 'venueCalendar'
  if (path === '/venue-requests') return 'venueRequests'
  if (path === '/venues/new') return 'addVenue'
  if (/^\/venues\/[^/]+\/edit$/.test(path)) return 'editVenue'
  if (path === '/equipment') return 'equipment'
  if (path === '/equipment-requests') return 'equipmentRequests'
  if (path === '/safety-checks') return 'safetyChecks'
  if (path === '/equipment-requests/new') return 'newEquipmentRequest'
  if (path === '/venues') return 'venues'
  if (path === '/venue-search') return 'venueSearch'
  if (/^\/venues\/[^/]+$/.test(path)) return 'venueDetail'
  if (/^\/events\/[^/]+$/.test(path)) return 'detail'
  if (/^\/drafts\/[^/]+$/.test(path)) return 'editDraft'
  return 'dashboard'
}

function getEventId(): string | null {
  const match = window.location.pathname.match(/^\/events\/([^/]+)$/)
  return match ? match[1] : null
}

function getDraftId(): string | null {
  const match = window.location.pathname.match(/^\/drafts\/([^/]+)$/)
  return match ? match[1] : null
}

function getVenueId(): string | null {
  const match = window.location.pathname.match(/^\/venues\/([^/]+)(?:\/edit)?$/)
  return match ? match[1] : null
}

function App() {
  const [targetBookingId, setTargetBookingId] = useState(() => new URLSearchParams(window.location.search).get('booking'))
  const [route, setRoute] = useState<Route>(getRoute)
  const [eventId, setEventId] = useState<string | null>(getEventId)
  const [venueId, setVenueId] = useState<string | null>(getVenueId)
  const [draftId, setDraftId] = useState<string | null>(getDraftId)
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
      setDraftId(getDraftId())
      setTargetBookingId(new URLSearchParams(window.location.search).get('booking'))
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
    setTargetBookingId(null)
    setDetailOrigin(route)
    setEventId(id)
    window.history.pushState({}, '', `/events/${id}`)
    setRoute('detail')
  }

  const navigateToDraft = (id: string) => {
    setNotice(null)
    setDraftId(id)
    window.history.pushState({}, '', `/drafts/${id}`)
    setRoute('editDraft')
  }

  const navigateToVenue = (id: string) => {
    setNotice(null)
    setVenueId(id)
    window.history.pushState({}, '', `/venues/${id}`)
    setRoute('venueDetail')
  }

  const navigateToVenueEdit = (id: string) => {
    setNotice(null)
    setVenueId(id)
    window.history.pushState({}, '', `/venues/${id}/edit`)
    setRoute('editVenue')
  }

  const updateEvent = (field: keyof EventData, value: string) => {
    setEvent((current) => ({ ...current, [field]: value }))
  }

  const role: Role = activeUser?.role ?? 'Event Organiser'
  const eventTabs = isCoordinator(role) ? coordinatorEventTabs(role) : []
  const inEventsPage = eventTabs.includes(route)
  const resolveUserName = (userId: string | null | undefined) => users.find((user) => user.id === userId)?.username ?? null

  const openNotification = (path: string) => {
    setNotice(null)
    setDetailOrigin('notifications')
    window.history.pushState({}, '', path)
    setRoute(getRoute()); setEventId(getEventId())
    setTargetBookingId(new URLSearchParams(window.location.search).get('booking'))
  }
  return <NotificationProvider user={activeUser} onNavigate={openNotification}><div className="app-shell">
    <Sidebar route={route} role={role} onNavigate={navigate} />
    <main className={`main-content${route === 'venueCalendar' ? ' calendar-route' : ''}`}>
      <Topbar route={route} title={inEventsPage ? 'Events' : undefined} users={users} activeUserId={activeUser?.id ?? ''} onUserChange={setActiveUserId} onNotifications={() => navigate('notifications')} />
      {route === 'notifications' && <div className="page-stack"><NotificationsPage /></div>}
      {notice && <div className={`notice ${notice.tone}`} role={notice.tone === 'error' ? 'alert' : 'status'}>{notice.tone === 'success' ? <CheckIcon size={15} /> : <AlertIcon size={15} />}{notice.message}</div>}
      <HoldReminderAlert user={activeUser} />
      {route === 'dashboard' && <DashboardPage onNavigate={navigate} role={role} userName={activeUser?.username} />}
      {route === 'submit' && <SubmissionPage role={role} currentOrganiserId={activeUser?.id} />}
      {route === 'editDraft' && draftId && <SubmissionPage key={`${draftId}-${activeUser?.id}`} role={role} currentOrganiserId={activeUser?.id} draftId={draftId} />}
      {route === 'manage' && <ManagePage event={event} updateEvent={updateEvent} onSave={() => setNotice({ message: 'Event details saved locally.', tone: 'success' })} />}
      {inEventsPage && <EventsTabs tabs={eventTabs} route={route} onNavigate={navigate} />}
      {route === 'review' && <SubmittedRequestsPage key={activeUser?.id} role={role} currentCoordinatorId={activeUser?.id} currentCoordinatorName={activeUser?.username} resolveUserName={resolveUserName} onViewDetails={navigateToEvent} />}
      {route === 'changeRequests' && <ChangeRequestsPage key={activeUser?.id} role={role} coordinatorId={activeUser?.id} coordinatorName={activeUser?.username} />}
      {route === 'queue' && <UnassignedQueuePage key={activeUser?.id} role={role} currentUserId={activeUser?.id} resolveUserName={resolveUserName} onViewDetails={navigateToEvent} />}
      {route === 'workload' && <CoordinatorWorkloadPage key={activeUser?.id} role={role} currentUserId={activeUser?.id} resolveUserName={resolveUserName} onViewDetails={navigateToEvent} />}
      {route === 'myEvents' && <MyEventsPage key={activeUser?.id} role={role} currentCoordinatorId={activeUser?.id} currentCoordinatorName={activeUser?.username} onViewDetails={navigateToEvent} onOpenDraft={navigateToDraft} />}
      {route === 'browseEvents' && <AttendeeEventsPage key={activeUser?.id} role={role} attendeeId={activeUser?.id} />}
      {route === 'myRegistrations' && <AttendeeRegistrationsPage key={activeUser?.id} role={role} attendeeId={activeUser?.id} />}
      {route === 'venueCalendar' && <VenueCalendarPage user={activeUser} />}
      {route === 'venueRequests' && <VenueRequestsPage key={activeUser?.id} role={role} user={activeUser ?? null} resolveUserName={resolveUserName} />}
      {route === 'equipment' && <EquipmentPage key={activeUser?.id} role={role} user={activeUser ?? null} />}
      {route === 'safetyChecks' && <SafetyChecksPage key={activeUser?.id} role={role} safetyOfficerId={activeUser?.id} onViewDetails={navigateToEvent} />}
      {route === 'equipmentRequests' && <EquipmentRequestsPage key={activeUser?.id} role={role} user={activeUser ?? null} resolveUserName={resolveUserName} onCreate={() => navigate('newEquipmentRequest')} />}
      {route === 'newEquipmentRequest' && <NewEquipmentRequestPage key={activeUser?.id} role={role} user={activeUser ?? null} onBack={() => navigate('equipmentRequests')} onCreated={(message) => { navigate('equipmentRequests'); setNotice({ message, tone: 'success' }) }} />}
      {route === 'venueSearch' && <VenueSearchPage role={role} onViewVenue={navigateToVenue} />}
      {route === 'venues' && <VenueCataloguePage role={role} onViewVenue={navigateToVenue} onAddVenue={() => navigate('addVenue')} />}
      {route === 'venueDetail' && venueId && <VenueDetailPage key={venueId} venueId={venueId} role={role} user={activeUser} coordinators={users.filter((u) => u.role === 'Event Coordinator' || u.role === 'Event Coordinator Lead')} onBack={() => navigate('venues')} onEdit={() => navigateToVenueEdit(venueId)} />}
      {route === 'addVenue' && <AddVenuePage role={role} onSaved={navigateToVenue} />}
      {route === 'editVenue' && venueId && <EditVenuePage key={venueId} venueId={venueId} role={role} onSaved={navigateToVenue} onCancel={() => navigateToVenue(venueId)} />}
      {route === 'detail' && eventId && <EventDetailPage key={`${eventId}-${activeUser?.id}-${targetBookingId}`} targetBookingId={targetBookingId ?? undefined} eventId={eventId} role={role} currentCoordinatorId={activeUser?.id} currentCoordinatorName={activeUser?.username} resolveUserName={resolveUserName} backLabel={routeTitles[detailOrigin]} onBack={() => navigate(detailOrigin)} />}
    </main>
  </div></NotificationProvider>
}

export default App
