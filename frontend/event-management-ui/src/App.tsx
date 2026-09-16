import { useEffect, useState } from 'react'
import './App.css'
import { Sidebar, Topbar } from './components/Navigation'
import { DashboardPage } from './pages/DashboardPage'
import { ManagePage } from './pages/ManagePage'
import { SubmittedRequestsPage } from './pages/SubmittedRequestsPage'
import { SubmissionPage } from './pages/SubmissionPage'
import type { EventData, Role, Route } from './types'

const paths: Record<Route, string> = {
  dashboard: '/',
  submit: '/events/new',
  manage: '/events/evt-001/edit',
  review: '/requests/review',
  assigned: '/events/assigned',
}

function getRoute(): Route {
  const path = window.location.pathname
  if (path === '/events/new') return 'submit'
  if (path.includes('/edit')) return 'manage'
  if (path === '/requests/review') return 'review'
  if (path === '/events/assigned') return 'assigned'
  return 'dashboard'
}

function App() {
  const [route, setRoute] = useState<Route>(getRoute)
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
  const [notice, setNotice] = useState('')

  useEffect(() => {
    const handlePopState = () => setRoute(getRoute())
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const navigate = (nextRoute: Route) => {
    setNotice('')
    window.history.pushState({}, '', paths[nextRoute])
    setRoute(nextRoute)
  }

  const updateEvent = (field: keyof EventData, value: string) => {
    setEvent((current) => ({ ...current, [field]: value }))
  }

  return <div className="app-shell">
    <Sidebar route={route} role={role} onNavigate={navigate} />
    <main className="main-content">
      <Topbar route={route} role={role} onRoleChange={setRole} />
      {notice && <div className="notice" role="status">{notice}</div>}
      {route === 'dashboard' && <DashboardPage onNavigate={navigate} role={role} />}
      {route === 'submit' && <SubmissionPage role={role} />}
      {route === 'manage' && <ManagePage event={event} updateEvent={updateEvent} onSave={() => setNotice('Event details saved locally.')} />}
      {route === 'review' && <SubmittedRequestsPage key={role} role={role} />}
      {route === 'assigned' && <SubmittedRequestsPage key={role} role={role} assignedOnly />}
    </main>
  </div>
}

export default App
