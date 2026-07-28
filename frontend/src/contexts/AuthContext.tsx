import { createContext, useContext, useState, type ReactNode } from 'react';
import type { AuthState, AuthViewer } from '../types/auth';

interface AuthContextValue {
  auth: AuthState;
  viewer: AuthViewer | null;
  isAuthenticated: () => boolean;
  isAuthFailed: () => boolean;
  isForbidden: () => boolean;
  canAccessPresetsAdmin: () => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthProviderProps {
  children: ReactNode;
  initialAuthState?: AuthState;
}

export function AuthProvider({ children, initialAuthState }: AuthProviderProps) {
  const [auth] = useState<AuthState>(initialAuthState ?? { status: 'authFailed', authenticated: false });

  const viewer = auth.status === 'authenticated' ? auth : null;

  const isAuthenticated = (): boolean => auth.status === 'authenticated';

  const isAuthFailed = (): boolean => auth.status === 'authFailed';

  const isForbidden = (): boolean => auth.status === 'forbidden';

  const canAccessPresetsAdmin = (): boolean => {
    return viewer?.capabilities.canAccessPresetsAdmin ?? false;
  };

  const value: AuthContextValue = {
    auth,
    viewer,
    isAuthenticated,
    isAuthFailed,
    isForbidden,
    canAccessPresetsAdmin,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
