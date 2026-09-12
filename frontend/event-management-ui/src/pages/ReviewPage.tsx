import { useState } from 'react'
import type { MockRequest, RequestStatus, Role } from '../types'
import { StatusBadge } from '../components/FormControls'

export function ReviewPage({ role, requests, setRequests, onAction }: { role: Role; requests: MockRequest[]; setRequests: (requests: MockRequest[]) => void; onAction: (message: string) => void }) {
  const [reasonId, setReasonId] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const canReview = role === 'Venue Staff'
  const updateStatus = (id: number, status: RequestStatus) => { setRequests(requests.map((request) => request.id === id ? { ...request, status } : request)); setReasonId(null); onAction(`Request ${status.toLowerCase()} locally.`) }

  return <div className="page-stack"><section className="intro"><p className="muted">Venue Staff can make a mock decision on submitted event requests.</p>{!canReview && <div className="role-warning">Switch the role selector to <strong>Venue Staff</strong> to show review actions.</div>}</section><section className="panel table-panel"><div className="table-scroll"><table><thead><tr><th>Event request</th><th>Date</th><th>Venue</th><th>Attendance</th><th>Status</th><th>Action</th></tr></thead><tbody>{requests.map((request) => <tr key={request.id}><td><strong>{request.title}</strong><small>Request #{request.id.toString().padStart(3, '0')}</small></td><td>{request.date}</td><td>{request.venue}</td><td>{request.attendance}</td><td><StatusBadge status={request.status} /></td><td>{canReview && request.status === 'Pending' ? <div className="table-actions"><button className="button small approve" onClick={() => updateStatus(request.id, 'Approved')}>Approve</button><button className="button small reject" onClick={() => setReasonId(request.id)}>Reject</button></div> : <span className="muted">No action</span>}{reasonId === request.id && <div className="reject-box"><label htmlFor="reason">Reason for rejection</label><textarea id="reason" value={reason} onChange={(change) => setReason(change.target.value)} placeholder="Add a mock reason" /><button className="button small reject" onClick={() => updateStatus(request.id, 'Rejected')}>Confirm rejection</button></div>}</td></tr>)}</tbody></table></div></section></div>
}
