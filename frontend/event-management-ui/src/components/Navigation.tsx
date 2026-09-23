import type { Route, User } from '../types'
import { routeTitles } from '../types'

export function Sidebar({ route, onNavigate }: { route: Route; onNavigate: (route: Route) => void }) {
  return <aside className="sidebar"><div className="brand"><span className="brand-mark">C</span><span>ConnectSphere</span></div><p className="nav-label">Workspace</p><nav className="nav-list" aria-label="Main navigation"><NavButton active={route === 'dashboard'} onClick={() => onNavigate('dashboard')} icon="⌂">Overview</NavButton><NavButton active={route === 'submit'} onClick={() => onNavigate('submit')} icon="＋">Submit event</NavButton><NavButton active={route === 'manage'} onClick={() => onNavigate('manage')} icon="✎">Event details</NavButton><NavButton active={route === 'review'} onClick={() => onNavigate('review')} icon="✓">Request review</NavButton><NavButton active={route === 'myEvents'} onClick={() => onNavigate('myEvents')} icon="▤">My events</NavButton></nav><div className="sidebar-footer"><span className="status-dot" /> UI baseline · mock data</div></aside>
}

function NavButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: string; children: string }) {
  return <button className={`nav-button ${active ? 'active' : ''}`} onClick={onClick}><span>{icon}</span>{children}</button>
}

export function Topbar({ route, users, activeUserId, onUserChange }: { route: Route; users: User[]; activeUserId: string; onUserChange: (userId: string) => void }) {
  return <header className="topbar"><div><p className="eyebrow">EVENT OPERATIONS</p><h1>{routeTitles[route]}</h1></div><label className="role-switcher">Viewing as<select value={activeUserId} onChange={(change) => onUserChange(change.target.value)} aria-label="Select active user">{users.map((user) => <option key={user.id} value={user.id}>{user.username} — {user.role}</option>)}</select></label></header>
}
