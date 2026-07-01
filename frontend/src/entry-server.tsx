import React from 'react';
import ReactDOMServer from 'react-dom/server';
import { StaticRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './contexts/AuthContext';
import type { AuthData } from './types/auth';
import App from './App';

export async function render(url: string, authData: AuthData) {
  const queryClient = new QueryClient();

  const html = ReactDOMServer.renderToString(
    <React.StrictMode>
      <StaticRouter location={url}>
        <QueryClientProvider client={queryClient}>
          <AuthProvider authData={authData}>
            <App />
          </AuthProvider>
        </QueryClientProvider>
      </StaticRouter>
    </React.StrictMode>
  );

  // Escape < to prevent XSS if authData contains malicious content like </script>
  const safeJson = JSON.stringify(authData).replace(/</g, '\\u003c');
  const head = `<script>window.__AUTH_DATA__=${safeJson};</script>`;

  return { html, head };
}
