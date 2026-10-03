import type { Registration } from './registrations'

export function RegistrationTable({ registrations }: { registrations: Registration[] }) {
  if (registrations.length === 0) return <p>No registrations yet.</p>
  return <div className="table-scroll">
    <table>
      <thead><tr><th>Name</th><th>Email</th><th>Organisation</th><th>Registered</th><th>Status</th></tr></thead>
      <tbody>{registrations.map((registration) => <tr key={registration.id}>
        <td>{registration.attendeeName}</td>
        <td>{registration.attendeeEmail}</td>
        <td>{registration.attendeeOrganization || '—'}</td>
        <td>{registration.registrationDate ? new Date(registration.registrationDate).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' }) : 'Not recorded'}</td>
        <td>{registration.status}</td>
      </tr>)}</tbody>
    </table>
  </div>
}
