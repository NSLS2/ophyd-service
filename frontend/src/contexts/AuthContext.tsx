import { createContext, useContext, useState, type ReactNode } from 'react';
import type { AuthState, AuthScope, AuthUser } from '../types/auth';
import { isAuthenticatedState } from '../types/auth';

interface AuthContextValue {
  auth: AuthState;
  user: AuthUser | null;
  isAuthenticated: () => boolean;
  hasScope: (scope: AuthScope) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthProviderProps {
  children: ReactNode;
  initialAuthState?: AuthState;
}

export function AuthProvider({ children, initialAuthState }: AuthProviderProps) {
  const [auth] = useState<AuthState>(initialAuthState ?? { authenticated: false });

  const user = isAuthenticatedState(auth) ? auth.user : null;

  const isAuthenticated = (): boolean => isAuthenticatedState(auth);

  const hasScope = (scope: AuthScope): boolean => (
    isAuthenticatedState(auth) && auth.scopes.includes(scope)
  );

  const value: AuthContextValue = {
    auth,
    user,
    isAuthenticated,
    hasScope,
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
