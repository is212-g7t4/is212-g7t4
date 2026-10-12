import type { Route } from '../types'
import { routeTitles } from '../types'

export function EventsTabs({ tabs, route, onNavigate }: { tabs: Route[]; route: Route; onNavigate: (route: Route) => void }) {
  return (
    <div className="events-tabs" role="tablist" aria-label="Events">
      {tabs.map((tab) => (
        <button
          key={tab}
          type="button"
          role="tab"
          aria-selected={route === tab}
          className={`events-tab${route === tab ? ' active' : ''}`}
          onClick={() => onNavigate(tab)}
        >
          {routeTitles[tab]}
        </button>
      ))}
    </div>
  )
}
