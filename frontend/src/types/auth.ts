export interface AuthUser {
  upn: string;
  name: string;
  givenName?: string;
  familyName?: string;
}

export interface AuthCapabilities {
  canViewElementPicker: boolean;
  canUseIosScan: boolean;
  canAccessPresetsAdmin: boolean;
}

export interface AuthViewer {
  status: 'authenticated';
  authenticated: true;
  user: AuthUser;
  capabilities: AuthCapabilities;
}

export interface AuthDeniedState {
  status: 'authFailed' | 'forbidden';
  authenticated: false;
  user?: AuthUser;
  capabilities?: Partial<AuthCapabilities>;
}

export type AuthState =
  | AuthDeniedState
  | AuthViewer;
