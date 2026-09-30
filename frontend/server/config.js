// Environment-derived server configuration shared across the other server modules.

import fs from 'node:fs/promises';
import path from 'node:path';

export const isProduction = process.env.NODE_ENV === 'production';

// Fail fast if the dev-auth bypass env vars are present in production.
if (isProduction && (process.env.DEV_AUTH_UPN || process.env.DEV_AUTH_ROLES)) {
  throw new Error('DEV_AUTH_* must not be set when NODE_ENV=production');
}

export const basePath = process.env.BASE || '/';

const certPath = process.env.SSL_CERT_PATH || '';
const keyPath = process.env.SSL_KEY_PATH || '';
export const sslConfig = certPath && keyPath
  ? {
      cert: await fs.readFile(path.resolve(certPath)),
      key: await fs.readFile(path.resolve(keyPath)),
    }
  : undefined;

export const port = process.env.PORT ? Number.parseInt(process.env.PORT, 10) : (sslConfig ? 443 : 5173);

export const PRESETS_TARGET     = process.env.PRESETS_TARGET     || 'http://localhost:8005';
export const CONFIG_TARGET      = process.env.CONFIG_TARGET      || 'http://localhost:8004';
export const CONTROL_TARGET     = process.env.CONTROL_TARGET     || 'http://localhost:8003';
export const TILED_TARGET       = process.env.TILED_TARGET       || 'http://localhost:8000';
export const QUEUESERVER_TARGET = process.env.QUEUESERVER_TARGET || 'http://localhost:60610';
export const TILED_API_KEY      = process.env.TILED_API_KEY      || '';
export const QSERVER_API_KEY    = process.env.QSERVER_API_KEY    || '';
