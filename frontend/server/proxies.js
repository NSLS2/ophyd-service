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
// handler must be wired onto the Node HTTP(S) server by the caller.

import {
  PRESETS_TARGET,
  CONFIG_TARGET,
  CONTROL_TARGET,
  TILED_TARGET,
  QUEUESERVER_TARGET,
  TILED_API_KEY,
  QSERVER_API_KEY,
} from './config.js';
import { RELATIVE_URL_PARSE_BASE } from './url-utils.js';
import { requireAdminWrite } from './auth.js';

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

// Mounts every backend proxy on `app` and returns the control-service proxy so
// the caller can wire its WS `upgrade` handler onto the Node HTTP(S) server.
export const mountApiProxies = async (app) => {
  const { createProxyMiddleware } = await import('http-proxy-middleware');

  app.use('/api/presets', requireAdminWrite, createProxyMiddleware({
    target: PRESETS_TARGET, changeOrigin: true,
    pathRewrite: (path) => `/api/v1${path}`,
  }));
  app.use('/api/config', createProxyMiddleware({
    target: CONFIG_TARGET, changeOrigin: true,
    pathRewrite: (path) => `/api/v1${path}`,
  }));
  const controlProxy = createProxyMiddleware({
    target: CONTROL_TARGET, changeOrigin: true, ws: true,
    // Mounted at root so pathFilter sees the full URL for both HTTP and the
    // auto-subscribed WS upgrade handler; otherwise Express strips '/api/control'
    // from req.url for HTTP and pathFilter never matches, dropping requests into
    // the SSR catch-all.
    pathFilter: '/api/control',
    pathRewrite: rewriteControlPath,
  });
  app.use(controlProxy);
  // Finch's TiledLookup emits `sort=-` (no field) — rewrite to `sort=-time`.
  app.use('/api/tiled', createProxyMiddleware({
    target: TILED_TARGET, changeOrigin: true,
    pathRewrite: rewriteTiledPath,
  }));
  app.use('/api/queueserver', createProxyMiddleware({
    target: QUEUESERVER_TARGET, changeOrigin: true,
    pathRewrite: (path) => `/api${path}`,
    on: {
      proxyReq: (proxyReq) => {
        if (QSERVER_API_KEY) proxyReq.setHeader('Authorization', `ApiKey ${QSERVER_API_KEY}`);
      },
    },
  }));

  return controlProxy;
};
