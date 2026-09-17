import type { ReactNode } from 'react'
import type { RequestStatus } from '../types'

export function FormSection({
  title,
  hint,
  children,
}: {
  title: string
  hint?: string
  children: ReactNode
}) {
  return (
    <section className="form-section">
      <h3>{title}</h3>

      {hint && (
        <p className="muted section-hint">
          {hint}
        </p>
      )}

      {children}
    </section>
  )
}

type FieldProps = {
  label: string
  value: string
  onChange: (value: string) => void
  textarea?: boolean
  required?: boolean
  type?: 'text' | 'number' | 'datetime-local' | 'date'
  placeholder?: string
  min?: string
}

export function Field({
  label,
  value,
  onChange,
  textarea = false,
  required = false,
  type = 'text',
  placeholder,
  min,
}: FieldProps) {
  return (
    <label className="field">
      <span>
        {label}
        {required && <span className="required"> *</span>}
      </span>

      {textarea ? (
        <textarea
          required={required}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
        />
      ) : (
        <input
          type={type}
          required={required}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          min={min}
        />
      )}
    </label>
  )
}

export function StatusBadge({
  status,
}: {
  status: RequestStatus | string
}) {
  return (
    <span className={`status-badge ${status.toLowerCase()}`}>
      {status}
    </span>
  )
}

export function Impact({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone: 'success' | 'warning'
}) {
  return (
    <div className="impact-row">
      <span>
        <span className={`impact-icon ${tone}`}>
          {tone === 'success' ? '✓' : '!'}
        </span>

        {label}
      </span>

      <strong className={tone}>
        {value}
      </strong>
    </div>
  )
}
