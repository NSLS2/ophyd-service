import { FormEvent, useState } from 'react'
import './LoginGate.css'

const ADMIN_USERNAME = 'admin'
const ADMIN_PASSWORD = 'admin123'

export interface LoginGateProps {
  onAuth: () => void
}

export function LoginGate({ onAuth }: LoginGateProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (username === ADMIN_USERNAME && password === ADMIN_PASSWORD) {
      setError('')
      onAuth()
    } else {
      setError('Invalid username or password.')
    }
  }

  return (
    <div className="login-gate">
      <form className="login-gate__card" onSubmit={handleSubmit}>
        <h2 className="login-gate__title">Presets Admin</h2>
        <p className="login-gate__subtitle">Sign in to manage preset tables.</p>

        <label className="login-gate__field">
          <span className="login-gate__label">Username</span>
          <input
            className="login-gate__input"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>

        <label className="login-gate__field">
          <span className="login-gate__label">Password</span>
          <input
            className="login-gate__input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>

        {error && <div className="login-gate__error">{error}</div>}

        <button className="login-gate__submit" type="submit">
          Sign In
        </button>
      </form>
    </div>
  )
}
