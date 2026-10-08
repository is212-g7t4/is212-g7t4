import type { ReactNode } from 'react'
import type { Role, Route, User } from '../types'
import { routeTitles } from '../types'
import { canViewCalendar } from '../features/calendar/permissions'
import { canManageEquipment } from '../features/equipment/permissions'
import { canViewMyEvents } from '../features/event/permissions'
import { canSearchVenues, canViewVenues } from '../features/venue/permissions'
import { BuildingIcon, CheckIcon, EditIcon, HomeIcon, ListIcon, PlusIcon, SearchIcon } from './Icon'

export function Sidebar({ route, role, onNavigate }: { route: Route; role: Role; onNavigate: (route: Route) => void }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">C</span>
        <span>ConnectSphere</span>
      </div>

      <p className="nav-label">Workspace</p>

      <nav className="nav-list" aria-label="Main navigation">
        <NavButton active={route === 'dashboard'} onClick={() => onNavigate('dashboard')} icon={<HomeIcon size={17} />}>Overview</NavButton>
        <NavButton active={route === 'submit'} onClick={() => onNavigate('submit')} icon={<PlusIcon size={17} />}>Submit event</NavButton>
        <NavButton active={route === 'manage'} onClick={() => onNavigate('manage')} icon={<EditIcon size={17} />}>Event details</NavButton>
        {role !== 'Event Organiser' && (
          <NavButton active={route === 'review'} onClick={() => onNavigate('review')} icon={<CheckIcon size={17} />}>Request review</NavButton>
        )}
        {canViewMyEvents(role) && (
          <NavButton active={route === 'myEvents'} onClick={() => onNavigate('myEvents')} icon={<ListIcon size={17} />}>My events</NavButton>
        )}
        {role === 'Attendee' && (
          <NavButton active={route === 'browseEvents'} onClick={() => onNavigate('browseEvents')} icon={<SearchIcon size={17} />}>Browse events</NavButton>
        )}
        {canViewVenues(role) && (
          <NavButton active={route === 'venues' || route === 'venueDetail' || route === 'editVenue'} onClick={() => onNavigate('venues')} icon={<BuildingIcon size={17} />}>Venues</NavButton>
        )}
        {canSearchVenues(role) && (
          <NavButton active={route === 'venueSearch'} onClick={() => onNavigate('venueSearch')} icon={<SearchIcon size={17} />}>Find a venue</NavButton>
        )}
        {canViewCalendar(role) && (
          <NavButton active={route === 'venueCalendar'} onClick={() => onNavigate('venueCalendar')} icon={<ListIcon size={17} />}>Venue availability calendar</NavButton>
        )}
        {canManageEquipment(role) && (
          <NavButton active={route === 'equipment'} onClick={() => onNavigate('equipment')} icon={<ListIcon size={17} />}>Equipment</NavButton>
        )}
        {(canManageEquipment(role) || role === 'Event Coordinator') && (
          <NavButton active={route === 'equipmentRequests'} onClick={() => onNavigate('equipmentRequests')} icon={<CheckIcon size={17} />}>Equipment requests</NavButton>
        )}
      </nav>

      <div className="sidebar-footer">
        <span className="status-dot" />
        <span className="sidebar-footer-label">UI baseline · mock data</span>
      </div>
    </aside>
  )
}

function NavButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: ReactNode; children: string }) {
  return (
    <button className={`nav-button ${active ? 'active' : ''}`} onClick={onClick}>
      <span className="icon">{icon}</span>
      <span className="nav-button-label">{children}</span>
    </button>
  )
}

export function Topbar({ route, users, activeUserId, onUserChange }: { route: Route; users: User[]; activeUserId: string; onUserChange: (userId: string) => void }) {
  return (
    <header className="topbar">
      <h1>{routeTitles[route]}</h1>

      <label className="role-switcher">
        Viewing as
        <select
          value={activeUserId}
          onChange={(change) => onUserChange(change.target.value)}
          aria-label="Select active user"
          disabled={users.length === 0}
        >
          {users.length === 0
            ? <option value="">No users available</option>
            : users.map((user) => <option key={user.id} value={user.id}>{user.username} — {user.role}</option>)}
        </select>
      </label>
    </header>
  )
}
