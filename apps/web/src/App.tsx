import { type FormEvent, useEffect, useState } from 'react'
import './App.css'
import { ApiError, login, logout, me, setUnauthorizedHandler, type User } from './api'
import { Chat } from './components/Chat'
import { Datasources } from './components/Datasources'

function LoginScreen({ onLoggedIn }: { onLoggedIn: (user: User) => void }) {
  const [email, setEmail] = useState('alice@nimbus.dev')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const user = await login(email, password)
      onLoggedIn(user)
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : 'login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-screen">
      <form className="login-form" onSubmit={handleSubmit}>
        <h1>Nimbus</h1>
        <label>
          Email
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
        </label>
        <label>
          Password
          <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required />
        </label>
        {error && <div className="error">{error}</div>}
        <button type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [checkingSession, setCheckingSession] = useState(true)

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setCheckingSession(false))
    return () => setUnauthorizedHandler(null)
  }, [])

  async function handleLogout() {
    await logout().catch(() => undefined)
    setUser(null)
  }

  if (checkingSession) return null

  if (!user) return <LoginScreen onLoggedIn={setUser} />

  return (
    <div className="app">
      <header className="app-header">
        <h1>Nimbus</h1>
        <div className="session">
          <span>{user.display_name}</span>
          <button onClick={handleLogout}>Logout</button>
        </div>
      </header>
      <main className="app-body">
        <Datasources />
        <Chat />
      </main>
    </div>
  )
}

export default App
