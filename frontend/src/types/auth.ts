export interface AuthUser {
  upn: string;
  name: string;
  givenName?: string;
  familyName?: string;
}

// operator:* are granted but not yet enforced by the BFF; PV-write/scan
// authorization is a perimeter/backend concern handled in a later change.
export type AuthScope =
  | 'operator:read'
  | 'operator:write'
  | 'admin:read'
  | 'admin:write';

export interface AuthViewer {
  status: 'authenticated';
  authenticated: true;
  user: AuthUser;
  scopes: AuthScope[];
}

export interface AuthUnauthenticatedState {
  status: 'unauthenticated';
  authenticated: false;
}

export type AuthState =
  | AuthUnauthenticatedState
  | AuthViewer;

// Single source of truth for "is this state authenticated"; also narrows to AuthViewer.
export function isAuthenticatedState(state: AuthState): state is AuthViewer {
  return state.status === 'authenticated';
}
