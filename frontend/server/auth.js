// Header-based auth/authorization: derives the caller's identity and scopes
// from upstream proxy headers (or DEV_AUTH_* env vars in development).

import { isProduction, basePath } from './config.js';
import { RELATIVE_URL_PARSE_BASE } from './url-utils.js';

const RECOGNIZED_ROLES = new Set(['ios.operator', 'ios.admin', 'skybeam.admin']);
const ADMIN_ROLES = new Set(['ios.admin', 'skybeam.admin']);
const MAX_AUTH_HEADER_LENGTH = 320;
const MAX_NAME_HEADER_LENGTH = 200;
const MAX_ROLES_HEADER_LENGTH = 1000;
const BNL_EMAIL_PATTERN = /^[A-Z0-9._%+-]+@BNL\.GOV$/i;
const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001f\u007f]/;

// Safely extract a header value as a string (handles string | string[] | undefined)
const getHeader = (req, name) => {
  const value = req.headers[name];
  if (Array.isArray(value)) return value[0] || '';
  return value || '';
};

const normalizeHeaderValue = (value, maxLength = MAX_AUTH_HEADER_LENGTH) => {
  const normalized = value.trim();
  if (
    !normalized
    || normalized.length > maxLength
    || CONTROL_CHARACTER_PATTERN.test(normalized)
  ) {
    return '';
  }

  return normalized;
};

const parseRoles = (rolesHeader) => (
  normalizeHeaderValue(rolesHeader, MAX_ROLES_HEADER_LENGTH)
    .split(',')
    .map((role) => role.trim())
    .filter(Boolean)
);

const normalizeOptionalHeaderValue = (value, maxLength = MAX_NAME_HEADER_LENGTH) => {
  const normalized = normalizeHeaderValue(value, maxLength);
  return normalized || undefined;
};

const isValidUpn = (upn) => BNL_EMAIL_PATTERN.test(upn);

const normalizeUpn = (value) => {
  const upn = normalizeHeaderValue(value).toLowerCase();
  return isValidUpn(upn) ? upn : '';
};

// Keep only roles we know about, warning on (and dropping) the rest rather than
// rejecting the whole user when an unrecognized role is present.
const getRecognizedRoles = (roles) => (
  roles.filter((role) => {
    if (RECOGNIZED_ROLES.has(role)) return true;
    console.warn(`Ignoring unrecognized role: ${role}`);
    return false;
  })
);

// operator:* are granted to every recognized role but not yet enforced by the
// BFF; PV-write/scan authorization is a perimeter/backend concern for later.
const rolesToScopes = (roles) => {
  const scopes = new Set(['operator:read', 'operator:write']);
  for (const role of roles) {
    if (ADMIN_ROLES.has(role)) {
      scopes.add('admin:read');
      scopes.add('admin:write');
    }
  }
  return [...scopes];
};

const serializeForHtml = (data) => JSON.stringify(data).replace(/</g, '\\u003c');

const isAdminPath = (url) => {
  const pathname = new URL(url, RELATIVE_URL_PARSE_BASE).pathname;
  const hasBasePath = pathname === basePath || pathname.startsWith(basePath + '/');
  const appPath = hasBasePath
    ? `/${pathname.slice(basePath.length).replace(/^\/+/, '')}`
    : pathname;

  return appPath === '/admin' || appPath.startsWith('/admin/');
};

const deriveAuthDecision = (req) => {
  // Dev-only bypass: without an auth proxy in front, synthesize an identity from
  // DEV_AUTH_* env vars so the app is usable locally. Ignored in production.
  if (!isProduction && process.env.DEV_AUTH_UPN) {
    const upn = normalizeUpn(process.env.DEV_AUTH_UPN);
    const recognizedRoles = getRecognizedRoles(parseRoles(process.env.DEV_AUTH_ROLES || ''));
    if (upn && recognizedRoles.length > 0) {
      return {
        scopes: rolesToScopes(recognizedRoles),
        user: {
          upn,
          name: normalizeHeaderValue(process.env.DEV_AUTH_NAME || '', MAX_NAME_HEADER_LENGTH) || upn,
          givenName: normalizeOptionalHeaderValue(process.env.DEV_AUTH_GIVEN_NAME || ''),
          familyName: normalizeOptionalHeaderValue(process.env.DEV_AUTH_FAMILY_NAME || ''),
        },
      };
    }
  }

  const upn = normalizeUpn(getHeader(req, 'access-token-upn'));
  const name = normalizeHeaderValue(getHeader(req, 'access-token-name'), MAX_NAME_HEADER_LENGTH) || upn;
  const recognizedRoles = getRecognizedRoles(parseRoles(getHeader(req, 'access-token-roles')));

  if (!upn || recognizedRoles.length === 0) {
    return null;
  }

  return {
    scopes: rolesToScopes(recognizedRoles),
    user: {
      upn,
      name,
      givenName: normalizeOptionalHeaderValue(getHeader(req, 'access-token-given-name')),
      familyName: normalizeOptionalHeaderValue(getHeader(req, 'access-token-family-name')),
    },
  };
};

const toClientAuthState = (authDecision) => ({
  authenticated: true,
  user: authDecision.user,
  scopes: authDecision.scopes,
});

export const deriveDocumentAuthState = (req) => {
  const authDecision = deriveAuthDecision(req);

  if (!authDecision) {
    return { authenticated: false };
  }

  return toClientAuthState(authDecision);
};

export const getDocumentStatusCode = (authState, url) => {
  if (!authState.authenticated) return 401;
  if (isAdminPath(url) && !authState.scopes.includes('admin:read')) return 403;
  return 200;
};

export const createAuthStateScript = (authState) => (
  `<script id="auth-state" type="application/json">${serializeForHtml(authState)}</script>`
);

const isWriteMethod = (method) => ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase());

export const requireAdminWrite = (req, res, next) => {
  if (!isWriteMethod(req.method)) {
    next();
    return;
  }

  const authDecision = deriveAuthDecision(req);
  if (!authDecision?.scopes.includes('admin:write')) {
    res.status(403).json({ detail: 'Preset write access requires an admin role.' });
    return;
  }

  next();
};
