import type { ReactNode } from 'react'
import type { RequestStatus } from '../types'

export function FormSection({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return <section className="form-section"><h3>{title}</h3>{hint && <p className="muted section-hint">{hint}</p>}{children}</section>
}

export function Field({ label, value, onChange, textarea, required }: { label: string; value: string; onChange: (value: string) => void; textarea?: boolean; required?: boolean }) {
  const Tag = textarea ? 'textarea' : 'input'
  return <label className="field">{label}{required && <span className="required"> *</span>}<Tag value={value} onChange={(change) => onChange(change.target.value)} /></label>
}

export function StatusBadge({ status }: { status: RequestStatus | string }) {
  return <span className={`status-badge ${status.toLowerCase()}`}>{status}</span>
}

export function Impact({ label, value, tone }: { label: string; value: string; tone: 'success' | 'warning' }) {
  return <div className="impact-row"><span><span className={`impact-icon ${tone}`}>{tone === 'success' ? '✓' : '!'}</span>{label}</span><strong className={tone}>{value}</strong></div>
}
