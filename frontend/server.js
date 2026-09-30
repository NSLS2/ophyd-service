// Server entrypoint: wires together config, auth, API proxies, and SSR
// rendering for both development and production.

import { createServer as createHttpServer } from 'node:http';
import express from 'express';
import correlator from 'express-correlation-id';
import { isProduction, basePath, sslConfig, port } from './server/config.js';
import { mountApiProxies } from './server/proxies.js';
import { prepareProductionAssets, createSsrHandler } from './server/ssr.js';

const app = express();
const httpServer = sslConfig ? undefined : createHttpServer(app);

/** @type {import('vite').ViteDevServer | undefined} */
let vite;

app.use(correlator({ header: 'X-Request-ID' }));

app.use('/auth', (_req, res) => {
  res.status(404).json({ detail: 'Not Found' });
});

const controlProxy = await mountApiProxies(app);

let templateHtml = '';
if (isProduction) {
  templateHtml = await prepareProductionAssets();

  // Production middleware layers
  const compression = (await import('compression')).default;
  const sirv = (await import('sirv')).default;

  app.use(compression());
  app.use(basePath, sirv('./dist/client', { extensions: [], brotli: true, gzip: true }));
} else {
  // Vite server as middleware — devDependency only, imported dynamically so
  // production (where vite is pruned from node_modules) never loads it.
  const { createServer: createViteServer } = await import('vite');
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
app.use(createSsrHandler({ templateHtml, vite }));

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

