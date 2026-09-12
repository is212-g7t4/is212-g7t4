import { useState } from 'react'
import EventRequestForm from './features/event/EventRequestForm'
import './App.css'

function App() {
  const [showEventForm, setShowEventForm] = useState(false)

  return (
    <div className="app">
      <button
        className="create-event-button"
        onClick={() => setShowEventForm(true)}
      >
        Create Event Request
      </button>

      {showEventForm && (
        <div
          className="modal-overlay"
          onClick={() => setShowEventForm(false)}
        >
          <div
            className="modal-content"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="modal-close-button"
              onClick={() => setShowEventForm(false)}
              aria-label="Close"
            >
              ×
            </button>

            <EventRequestForm />
          </div>
        </div>
      )}
    </div>
  )
}

export default App