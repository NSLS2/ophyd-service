import { useState, useEffect, ReactNode } from 'react';
import { Routes, Route } from 'react-router';
import type { FinchConfig, RouteItem } from '@blueskyproject/finch';
import { loadFinch } from './finchLoader';

interface FinchBridgeProps {
  routes: RouteItem[];
  headerTitle: string;
  config?: FinchConfig;
  fallback?: ReactNode;
}

/**
 * Client-only bridge for @blueskyproject/finch
 *
 * Finch touches `window` at module load time, which crashes Node.js SSR.
 * This component:
 * 1. Server-renders a basic route structure with auth context intact
 * 2. On the client, awaits the shared (memoized, modulepreloaded) finch import
 * 3. Seamlessly swaps in HubAppLayout once it resolves
 */
export function ClientFinchBridge({ routes, headerTitle, config, fallback }: FinchBridgeProps) {
  const [FinchModule, setFinchModule] = useState<any>(null);

  useEffect(() => {
    let cancelled = false;

    loadFinch().then((finch) => {
      if (!cancelled) setFinchModule(finch);
    }).catch((error) => {
      console.error('Failed to load Finch', error);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  // Server-side and initial client render: use basic Routes fallback
  if (!FinchModule) {
    return (
      <>
        {fallback}
        <Routes>
          {routes.map((route) => (
            <Route key={route.path} path={route.path} element={route.element} />
          ))}
        </Routes>
      </>
    );
  }

  // Once Finch loads, render its provider and layout together.
  const { FinchConfigProvider, HubAppLayout } = FinchModule;

  return (
    <FinchConfigProvider config={config ?? {}}>
      <HubAppLayout routes={routes} headerTitle={headerTitle} />
    </FinchConfigProvider>
  );
}
