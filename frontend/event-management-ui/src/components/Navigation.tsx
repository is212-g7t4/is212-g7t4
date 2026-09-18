import type { Role, Route } from '../types'
import { routeTitles } from '../types'
import { roles } from '../mockData'

export function Sidebar({ route, onNavigate }: { route: Route; onNavigate: (route: Route) => void }) {
  return <aside className="sidebar"><div className="brand"><span className="brand-mark">C</span><span>ConnectSphere</span></div><p className="nav-label">Workspace</p><nav className="nav-list" aria-label="Main navigation"><NavButton active={route === 'dashboard'} onClick={() => onNavigate('dashboard')} icon="⌂">Overview</NavButton><NavButton active={route === 'submit'} onClick={() => onNavigate('submit')} icon="＋">Submit event</NavButton><NavButton active={route === 'assignment'} onClick={() => onNavigate('assignment')} icon="◎">Coordinator</NavButton><NavButton active={route === 'manage'} onClick={() => onNavigate('manage')} icon="✎">Event details</NavButton><NavButton active={route === 'review'} onClick={() => onNavigate('review')} icon="✓">Request review</NavButton><NavButton active={route === 'myEvents'} onClick={() => onNavigate('myEvents')} icon="▤">My events</NavButton></nav><div className="sidebar-footer"><span className="status-dot" /> UI baseline · mock data</div></aside>
}

function NavButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: string; children: string }) {
  return <button className={`nav-button ${active ? 'active' : ''}`} onClick={onClick}><span>{icon}</span>{children}</button>
}

export function Topbar({ route, role, onRoleChange }: { route: Route; role: Role; onRoleChange: (role: Role) => void }) {
  return <header className="topbar"><div><p className="eyebrow">EVENT OPERATIONS</p><h1>{routeTitles[route]}</h1></div><label className="role-switcher">Viewing as<select value={role} onChange={(change) => onRoleChange(change.target.value as Role)} aria-label="Select mock role">{roles.map((option) => <option key={option}>{option}</option>)}</select></label></header>
}
