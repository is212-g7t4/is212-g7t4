import { useState, type FormEvent } from 'react'
import { Field } from '../../components/FormControls'
import { AlertIcon } from '../../components/Icon'
import { signIn, type Session } from './session'

export function LoginPage({ onSignedIn }: { onSignedIn: (session: Session) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      onSignedIn(await signIn(email, password))
    } catch (cause) {
      setError((cause as Error).message)
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <form className="panel login-panel" onSubmit={submit} aria-label="Sign in">
        <div className="brand">
          <span className="brand-mark">C</span>
          <span>ConnectSphere</span>
        </div>
        <h1>Sign in</h1>
        <Field label="Email" type="email" value={email} onChange={setEmail} required />
        <Field label="Password" type="password" value={password} onChange={setPassword} required />
        {error && <div className="notice error" role="alert"><AlertIcon size={15} />{error}</div>}
        <button className="button primary" type="submit" disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
