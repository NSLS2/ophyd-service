import type * as Finch from '@blueskyproject/finch';

let finchPromise: Promise<typeof Finch> | null = null;

export function loadFinch(): Promise<typeof Finch> {
  finchPromise ??= import('@blueskyproject/finch').catch((error) => {
    finchPromise = null;
    throw error;
  });
  return finchPromise;
}