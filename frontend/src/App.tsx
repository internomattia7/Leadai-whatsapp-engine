import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from './pages/LoginPage'
import InboxPage from './pages/InboxPage'
import { me } from './api/auth'
import type { User } from './types'

import type { ReactNode } from 'react'

function RequireAuth({ children, user, loading }: { children: ReactNode; user: User | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center text-muted text-sm">
        Caricamento...
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  return (
    <Routes>
      <Route path="/login" element={<LoginPage onLogin={setUser} />} />
      <Route
        path="/app/*"
        element={
          <RequireAuth user={user} loading={loading}>
            <InboxPage currentUser={user} />
          </RequireAuth>
        }
      />
      <Route path="/" element={<Navigate to="/app/inbox" replace />} />
      <Route path="*" element={<Navigate to="/app/inbox" replace />} />
    </Routes>
  )
}
