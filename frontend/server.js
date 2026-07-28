// Shared server configuration for both development and production environments

import fs from 'node:fs/promises';
import path from 'node:path';
import zlib from 'node:zlib';
import express from 'express';
import correlator from 'express-correlation-id';
import { createServer as createViteServer } from 'vite';

// Service configuration    
const isProduction = process.env.NODE_ENV === 'production';
const basePath = process.env.BASE || '/';
const certPath = process.env.SSL_CERT_PATH || '';
const keyPath = process.env.SSL_KEY_PATH || '';
const sslConfig = certPath && keyPath
  ? {
      cert: await fs.readFile(path.resolve(certPath)),
      key: await fs.readFile(path.resolve(keyPath)),
    }
  : undefined;
const port = process.env.PORT ? Number.parseInt(process.env.PORT, 10) : (sslConfig ? 443 : 5173);
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

const parseRoles = (rolesHeader) => (
  normalizeHeaderValue(rolesHeader, MAX_ROLES_HEADER_LENGTH)
    .split(',')
    .map((role) => role.trim())
    .filter(Boolean)
);

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

const normalizeOptionalHeaderValue = (value, maxLength = MAX_NAME_HEADER_LENGTH) => {
  const normalized = normalizeHeaderValue(value, maxLength);
  return normalized || undefined;
};

const isValidUpn = (upn) => BNL_EMAIL_PATTERN.test(upn);

const normalizeUpn = (value) => {
  const upn = normalizeHeaderValue(value).toLowerCase();
  return isValidUpn(upn) ? upn : '';
};

const rolesAreValid = (roles) => (
  roles.length > 0 && roles.every((role) => RECOGNIZED_ROLES.has(role))
);

const serializeForHtml = (data) => JSON.stringify(data).replace(/</g, '\\u003c');

const isPresetsAdminPath = (url) => {
  const pathname = new URL(url, 'http://localhost').pathname;
  const appPath = basePath !== '/' && pathname.startsWith(basePath)
    ? `/${pathname.slice(basePath.length).replace(/^\/+/, '')}`
    : pathname;

  return appPath === '/presets-admin' || appPath.startsWith('/presets-admin/');
};

const deriveAuthDecision = (req) => {
  const upn = normalizeUpn(getHeader(req, 'access-token-upn'));
  const name = normalizeHeaderValue(getHeader(req, 'access-token-name'), MAX_NAME_HEADER_LENGTH) || upn;
  const roles = parseRoles(getHeader(req, 'access-token-roles'));

  if (!upn || !rolesAreValid(roles)) {
    return null;
  }

  const isAdmin = roles.some((role) => ADMIN_ROLES.has(role));

  return {
    roles,
    isAdmin,
    user: {
      upn,
      name,
      givenName: normalizeOptionalHeaderValue(getHeader(req, 'access-token-given-name')),
      familyName: normalizeOptionalHeaderValue(getHeader(req, 'access-token-family-name')),
    },
    capabilities: {
      canViewElementPicker: true,
      canUseIosScan: true,
      canAccessPresetsAdmin: isAdmin,
    },
  };
};

const toClientAuthState = (authDecision) => ({
  status: 'authenticated',
  authenticated: true,
  user: authDecision.user,
  capabilities: authDecision.capabilities,
});

const deriveDocumentAuthState = (req, url) => {
  const authDecision = deriveAuthDecision(req);

  if (!authDecision) {
    return { status: 'authFailed', authenticated: false };
  }

  if (isPresetsAdminPath(url) && !authDecision.capabilities.canAccessPresetsAdmin) {
    return {
      status: 'forbidden',
      authenticated: false,
      user: authDecision.user,
      capabilities: authDecision.capabilities,
    };
  }

  return toClientAuthState(authDecision);
};

const getDocumentStatusCode = (authState) => {
  if (authState.status === 'authenticated') return 200;
  if (authState.status === 'forbidden') return 403;
  return 401;
};

const createAuthStateScript = (authState) => (
  `<script id="auth-state" type="application/json">${serializeForHtml(authState)}</script>`
);

const isWriteMethod = (method) => ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase());

const requirePresetsAdmin = (req, res, next) => {
  if (!isWriteMethod(req.method)) {
    next();
    return;
  }

  const authDecision = deriveAuthDecision(req);
  if (!authDecision?.capabilities.canAccessPresetsAdmin) {
    res.status(403).json({ detail: 'Preset write access requires an admin role.' });
    return;
  }

  next();
};

// Cached production assets (client-side only - finch doesn't support SSR)
let templateHtml = isProduction
  ? await fs.readFile('./dist/client/index.html', 'utf-8')
  : '';

if (isProduction) {
  // Finch ships as one large (~6 MB) client-only chunk that gates the first
  // meaningful paint. Two build-agnostic mitigations, computed once at startup:
  //   1. <link rel="modulepreload"> so the chunk downloads during HTML parse,
  //      in parallel with the entry bundle, instead of after hydration.
  //   2. Brotli/Gzip precompression so sirv can serve it precompressed
  //      (~6 MB -> ~1.3 MB Brotli) without per-request CPU cost.
  const assetsDir = './dist/client/assets';
  const assetFiles = await fs.readdir(assetsDir).catch(() => []);

  const finchChunk = assetFiles.find((f) => /^finch\.es-.*\.js$/.test(f));
  if (finchChunk) {
    const preload = `<link rel="modulepreload" crossorigin href="/assets/${finchChunk}">`;
    templateHtml = templateHtml.replace('</head>', `    ${preload}\n  </head>`);
  }

  const fileExists = (p) => fs.access(p).then(() => true, () => false);
  await Promise.all(
    assetFiles
      .filter((f) => /\.(js|css)$/.test(f))
      .map(async (f) => {
        const full = path.join(assetsDir, f);
        const raw = await fs.readFile(full);
        const brPath = `${full}.br`;
        const gzPath = `${full}.gz`;
        if (!(await fileExists(brPath))) {
          await fs.writeFile(brPath, zlib.brotliCompressSync(raw, {
            params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 11 },
          }));
        }
        if (!(await fileExists(gzPath))) {
          await fs.writeFile(gzPath, zlib.gzipSync(raw, { level: 9 }));
        }
      }),
  );
}

// Create http server
const app = express();

// Middleware: Depends on environment
/** @type {import('vite').ViteDevServer | undefined} */
let vite;

// Middleware: Correlation ID
app.use(correlator({ header: 'X-Request-ID' }));

app.use('/auth', (_req, res) => {
  res.status(404).json({ detail: 'Not Found' });
});

// API proxy — forward backend requests in both dev and production.
// Mirrors the proxy config in vite.config.ts (which only applies to
// the standalone Vite dev server, not middleware mode).
const { createProxyMiddleware } = await import('http-proxy-middleware');

const PRESETS_TARGET = process.env.PRESETS_TARGET || 'http://localhost:8005';
const CONFIG_TARGET  = process.env.CONFIG_TARGET  || 'http://localhost:8004';
const CONTROL_TARGET = process.env.CONTROL_TARGET || 'http://localhost:8003';

app.use('/api/presets', requirePresetsAdmin, createProxyMiddleware({
  target: PRESETS_TARGET, changeOrigin: true,
  pathRewrite: (path) => '/api/v1' + path,
}));
app.use('/api/config', createProxyMiddleware({
  target: CONFIG_TARGET, changeOrigin: true,
  pathRewrite: (path) => '/api/v1' + path,
}));
app.use('/api/control', createProxyMiddleware({
  target: CONTROL_TARGET, changeOrigin: true,
  pathRewrite: (path) => '/api/v1' + path,
}));

if (isProduction) {
  // Production middleware layers
  const compression = (await import('compression')).default;
  const sirv = (await import('sirv')).default;

  app.use(compression());
  app.use(basePath, sirv('./dist/client', { extensions: [], brotli: true, gzip: true }));
} else {
  // Vite server as middleware
  vite = await createViteServer({
    server: { middlewareMode: true },
    appType: 'custom',
    base: basePath,
  });

  app.use(vite.middlewares);
}

// Serve HTML - catch-all route for SSR
app.use(async (req, res) => {
  try {
    const url = req.originalUrl;

    /** @type {string} */
    let template;
    /** @type {import('./src/entry-server.tsx').render | undefined} */
    let render;

    if (isProduction) {
      // Production: Use pre-built SSR bundle for fast server-side rendering
      template = templateHtml;
      render = (await import('./dist/server/entry-server.js')).render;
      const authState = deriveDocumentAuthState(req, url);
      const rendered = await render(url, authState);
      
      const html = template
        .replace(`<!--app-head-->`, rendered.head ?? '')
        .replace(`<!--app-html-->`, rendered.html ?? '')
        .replace(`<!--auth-state-->`, createAuthStateScript(authState));
      
      res.status(getDocumentStatusCode(authState)).set({ 'Content-Type': 'text/html' }).send(html);
    } else {
      // Development: Use Vite's SSR module loading with HMR
      template = await fs.readFile('./index.html', 'utf-8');
      template = await vite.transformIndexHtml(url, template);
      render = (await vite.ssrLoadModule('/src/entry-server.tsx')).render;
      
      const authState = deriveDocumentAuthState(req, url);
      const rendered = await render(url, authState);
      
      const html = template
        .replace(`<!--app-head-->`, rendered.head ?? '')
        .replace(`<!--app-html-->`, rendered.html ?? '')
        .replace(`<!--auth-state-->`, createAuthStateScript(authState));
      
      res.status(getDocumentStatusCode(authState)).set({ 'Content-Type': 'text/html' }).send(html);
    }
  } catch (e) {
    vite?.ssrFixStacktrace(e);
    console.error(e.stack);
    res.status(500).end('Internal Server Error');
  }
});

// Start http(s) server
if (sslConfig) {
  const { createServer } = await import('node:https');

  createServer(sslConfig, app).listen(port, () => {
    console.log(`Server started at https://localhost:${port}`);
  });
} else {
  app.listen(port, () => {
    console.log(`Server started at http://localhost:${port}`);
  });
}
