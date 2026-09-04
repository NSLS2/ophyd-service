// Shared server configuration for both development and production environments

import fs from 'node:fs/promises';
import path from 'node:path';
import zlib from 'node:zlib';
import { createServer as createHttpServer } from 'node:http';
import express from 'express';
import correlator from 'express-correlation-id';
import { createServer as createViteServer } from 'vite';

// Service configuration    
const isProduction = process.env.NODE_ENV === 'production';

// Fail fast if the dev-auth bypass env vars are present in production.
if (isProduction && (process.env.DEV_AUTH_UPN || process.env.DEV_AUTH_ROLES)) {
  throw new Error('DEV_AUTH_* must not be set when NODE_ENV=production');
}

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
// Placeholder origin only — it lets `new URL()` parse relative request URLs; never dereferenced.
const RELATIVE_URL_PARSE_BASE = 'http://placeholder.for.parsing.relative.url';

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

const deriveDocumentAuthState = (req) => {
  const authDecision = deriveAuthDecision(req);

  if (!authDecision) {
    return { authenticated: false };
  }

  return toClientAuthState(authDecision);
};

const getDocumentStatusCode = (authState, url) => {
  if (!authState.authenticated) return 401;
  if (isAdminPath(url) && !authState.scopes.includes('admin:read')) return 403;
  return 200;
};

const createAuthStateScript = (authState) => (
  `<script id="auth-state" type="application/json">${serializeForHtml(authState)}</script>`
);

const isWriteMethod = (method) => ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase());

const requireAdminWrite = (req, res, next) => {
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
const httpServer = sslConfig ? undefined : createHttpServer(app);

// Middleware: Depends on environment
/** @type {import('vite').ViteDevServer | undefined} */
let vite;

// Middleware: Correlation ID
app.use(correlator({ header: 'X-Request-ID' }));

app.use('/auth', (_req, res) => {
  res.status(404).json({ detail: 'Not Found' });
});

// API proxy — forward backend requests in both dev and production. This is
// the only proxy exercised by `npm run dev` / `npm run preview` (Vite runs in
// middleware mode and ignores `server.proxy` from vite.config.ts, which is
// therefore just a dev-only escape hatch for the raw `vite` CLI).
//
// Express strips the mount prefix before the proxy sees the path. Most backend
// services expose `/api/v1/*`; queueserver exposes `/api/*`.
//
// Finch's ophyd WebSocket (`useOphydPVSocket` et al.) upgrades on
// `/api/control/*-socket`, so `/api/control` uses `ws: true` and its upgrade
// handler is wired onto the Node HTTP(S) server further down.
const { createProxyMiddleware } = await import('http-proxy-middleware');

const PRESETS_TARGET     = process.env.PRESETS_TARGET     || 'http://localhost:8005';
const CONFIG_TARGET      = process.env.CONFIG_TARGET      || 'http://localhost:8004';
const CONTROL_TARGET     = process.env.CONTROL_TARGET     || 'http://localhost:8003';
const TILED_TARGET       = process.env.TILED_TARGET       || 'http://localhost:8000';
const QUEUESERVER_TARGET = process.env.QUEUESERVER_TARGET || 'http://localhost:60610';
const TILED_API_KEY      = process.env.TILED_API_KEY      || '';
const QSERVER_API_KEY    = process.env.QSERVER_API_KEY    || '';
const PROXY_DEBUG        = process.env.PROXY_DEBUG === '1';

const toAbsoluteProxyUrl = (target, proxyReq) => {
  const proxyPath = proxyReq.path || '';
  try {
    return new URL(proxyPath, target).toString();
  } catch {
    return `${target}${proxyPath}`;
  }
};

const logProxyHop = (label, target, req, proxyReq) => {
  if (!PROXY_DEBUG) return;
  const upstream = toAbsoluteProxyUrl(target, proxyReq);
  console.log(
    `[proxy:${label}] ${req.method} in="${req.originalUrl}" mountPath="${req.url}" out="${proxyReq.path}" upstream="${upstream}"`,
  );
};

const logProxyUpgrade = (label, target, req, proxyReq) => {
  if (!PROXY_DEBUG) return;
  const upstream = toAbsoluteProxyUrl(target, proxyReq);
  console.log(
    `[proxy-ws:${label}] in="${req.url || ''}" out="${proxyReq.path}" upstream="${upstream}"`,
  );
};

const rewriteTiledPath = (path) => {
  const rewritten = `/api/v1${path}`.replace(/sort=-(?=&|$)/, 'sort=-time');
  if (!TILED_API_KEY) return rewritten;

  const url = new URL(rewritten, RELATIVE_URL_PARSE_BASE);
  url.searchParams.set('api_key', TILED_API_KEY);
  return `${url.pathname}${url.search}`;
};

const rewriteControlPath = (path) => (
  path.startsWith('/api/control')
    ? path.replace(/^\/api\/control/, '/api/v1')
    : `/api/v1${path}`
);

app.use('/api/presets', requireAdminWrite, createProxyMiddleware({
  target: PRESETS_TARGET, changeOrigin: true,
  pathRewrite: (path) => `/api/v1${path}`,
  on: {
    proxyReq: (proxyReq, req) => logProxyHop('presets', PRESETS_TARGET, req, proxyReq),
  },
}));
app.use('/api/config', createProxyMiddleware({
  target: CONFIG_TARGET, changeOrigin: true,
  pathRewrite: (path) => `/api/v1${path}`,
  on: {
    proxyReq: (proxyReq, req) => logProxyHop('config', CONFIG_TARGET, req, proxyReq),
  },
}));
const controlProxy = createProxyMiddleware({
  target: CONTROL_TARGET, changeOrigin: true, ws: true,
  // Mounted at root so pathFilter sees the full URL for both HTTP and the
  // auto-subscribed WS upgrade handler; otherwise Express strips '/api/control'
  // from req.url for HTTP and pathFilter never matches, dropping requests into
  // the SSR catch-all.
  pathFilter: '/api/control',
  pathRewrite: rewriteControlPath,
  on: {
    proxyReq: (proxyReq, req) => logProxyHop('control', CONTROL_TARGET, req, proxyReq),
    proxyReqWs: (proxyReq, req) => logProxyUpgrade('control', CONTROL_TARGET, req, proxyReq),
  },
});
app.use(controlProxy);
// Finch's TiledLookup emits `sort=-` (no field) — rewrite to `sort=-time`.
app.use('/api/tiled', createProxyMiddleware({
  target: TILED_TARGET, changeOrigin: true,
  pathRewrite: rewriteTiledPath,
  on: {
    proxyReq: (proxyReq, req) => logProxyHop('tiled', TILED_TARGET, req, proxyReq),
  },
}));
app.use('/api/queueserver', createProxyMiddleware({
  target: QUEUESERVER_TARGET, changeOrigin: true,
  pathRewrite: (path) => `/api${path}`,
  on: {
    proxyReq: (proxyReq, req) => {
      logProxyHop('queueserver', QUEUESERVER_TARGET, req, proxyReq);
      if (QSERVER_API_KEY) proxyReq.setHeader('Authorization', `ApiKey ${QSERVER_API_KEY}`);
    },
  },
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
    server: httpServer
      ? { middlewareMode: true, hmr: { server: httpServer } }
      : { middlewareMode: true },
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
      const authState = deriveDocumentAuthState(req);
      const rendered = await render(url, authState);
      
      const html = template
        .replace(`<!--app-head-->`, rendered.head ?? '')
        .replace(`<!--app-html-->`, rendered.html ?? '')
        .replace(`<!--auth-state-->`, createAuthStateScript(authState));
      
      const status = getDocumentStatusCode(authState, url);
      res.status(status).set({ 'Content-Type': 'text/html' }).send(html);
    } else {
      // Development: Use Vite's SSR module loading with HMR
      template = await fs.readFile('./index.html', 'utf-8');
      template = await vite.transformIndexHtml(url, template);
      render = (await vite.ssrLoadModule('/src/entry-server.tsx')).render;
      
      const authState = deriveDocumentAuthState(req);
      const rendered = await render(url, authState);
      
      const html = template
        .replace(`<!--app-head-->`, rendered.head ?? '')
        .replace(`<!--app-html-->`, rendered.html ?? '')
        .replace(`<!--auth-state-->`, createAuthStateScript(authState));
      
      const status = getDocumentStatusCode(authState, url);
      const authSummary = authState.authenticated
        ? `${authState.user.upn} [${authState.scopes.join(',')}]`
        : 'anonymous';
      console.log(`[ssr] ${req.method} ${url} -> ${status} (auth: ${authSummary})`);
      res.status(status).set({ 'Content-Type': 'text/html' }).send(html);
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

  const httpsServer = createServer(sslConfig, app);
  // Forward WS upgrades to the control proxy; http-proxy-middleware does not auto-subscribe.
  httpsServer.on('upgrade', controlProxy.upgrade);
  httpsServer.listen(port, () => {
    console.log(`Server started at https://localhost:${port}`);
  });
} else {
  httpServer.on('upgrade', controlProxy.upgrade);
  httpServer.listen(port, () => {
    console.log(`Server started at http://localhost:${port}`);
  });
}
