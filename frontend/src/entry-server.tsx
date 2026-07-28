import React from 'react';
import ReactDOMServer from 'react-dom/server';
import { StaticRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './contexts/AuthContext';
import type { AuthState } from './types/auth';
import App from './App';

export async function render(url: string, initialAuthState: AuthState) {
  const queryClient = new QueryClient();

  const html = ReactDOMServer.renderToString(
    <React.StrictMode>
      <StaticRouter location={url}>
        <QueryClientProvider client={queryClient}>
          <AuthProvider initialAuthState={initialAuthState}>
            <App />
          </AuthProvider>
        </QueryClientProvider>
      </StaticRouter>
    </React.StrictMode>
  );

  return { html, head: '' };
}
