import React from 'react'
import { hydrateRoot, createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './contexts/AuthContext'
import type { AuthState } from './types/auth'
import '@blueskyproject/finch/style.css'
import { loadFinch } from './components/finchLoader'
import App from './App.tsx'
import './index.css'

const queryClient = new QueryClient()

void loadFinch().catch(() => undefined)

function readInitialAuthState(): AuthState {
  const element = document.getElementById('auth-state')
  if (!element?.textContent) {
    return { status: 'authFailed', authenticated: false }
  }

  try {
    return JSON.parse(element.textContent) as AuthState
  } catch {
    return { status: 'authFailed', authenticated: false }
  } finally {
    element.remove()
  }
}

const initialAuthState = readInitialAuthState()

const app = (
  <React.StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <AuthProvider initialAuthState={initialAuthState}>
          <App />
        </AuthProvider>
      </QueryClientProvider>
    </BrowserRouter>
  </React.StrictMode>
)

const rootElement = document.getElementById('root')!

if (rootElement.hasChildNodes()) {
  hydrateRoot(rootElement, app)
} else {
  createRoot(rootElement).render(app)
}
