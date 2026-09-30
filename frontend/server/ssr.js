// Production asset prep (SSR template caching + finch preload/precompression)
// and the SSR catch-all request handler shared by dev and production.

import fs from 'node:fs/promises';
import path from 'node:path';
import zlib from 'node:zlib';
import { isProduction } from './config.js';
import { deriveDocumentAuthState, getDocumentStatusCode, createAuthStateScript } from './auth.js';

// Cached production assets (client-side only - finch doesn't support SSR).
// Finch ships as one large (~6 MB) client-only chunk that gates the first
// meaningful paint. Two build-agnostic mitigations, computed once at startup:
//   1. <link rel="modulepreload"> so the chunk downloads during HTML parse,
//      in parallel with the entry bundle, instead of after hydration.
//   2. Brotli/Gzip precompression so sirv can serve it precompressed
//      (~6 MB -> ~1.3 MB Brotli) without per-request CPU cost.
export const prepareProductionAssets = async () => {
  let templateHtml = await fs.readFile('./dist/client/index.html', 'utf-8');

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

  return templateHtml;
};

// Builds the catch-all SSR request handler used for both dev and production.
export const createSsrHandler = ({ templateHtml, vite }) => async (req, res) => {
  try {
    const url = req.originalUrl;

    /** @type {string} */
    let template;
    /** @type {import('../src/entry-server.tsx').render | undefined} */
    let render;

    if (isProduction) {
      // Production: Use pre-built SSR bundle for fast server-side rendering
      template = templateHtml;
      render = (await import('../dist/server/entry-server.js')).render;
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
};
