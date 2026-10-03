import { useState, useEffect, useCallback } from 'react';
import type { QueueItem, BacklogStatus } from '@/types/models';
import {
  getQueue,
  cancelQueueItem as apiCancelQueueItem,
  retryQueueItem as apiRetryQueueItem,
  getBacklogStatus,
  triggerBacklogSearch as apiTriggerBacklogSearch,
} from '@/services/queueService';

export interface UseQueueReturn {
  queueItems: QueueItem[];
  backlogStatus: BacklogStatus | null;
  isLoading: boolean;
  error: string | null;
  cancelItem: (id: string) => Promise<void>;
  retryItem: (id: string) => Promise<void>;
  triggerBacklogSearch: () => Promise<void>;
  refresh: () => Promise<void>;
}

/** All queue/backlog routes are admin-only; when `canUseAdminUi` is false nothing is fetched or polled. */
export function useQueue(canUseAdminUi: boolean = false): UseQueueReturn {
  const [queueItems, setQueueItems] = useState<QueueItem[]>([]);
  const [backlogStatus, setBacklogStatus] = useState<BacklogStatus | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!canUseAdminUi) return;
    setIsLoading(true);
    setError(null);
    try {
      const [items, backlog] = await Promise.all([
        getQueue(true),
        canUseAdminUi ? getBacklogStatus().catch(() => null) : Promise.resolve(null),
      ]);
      setQueueItems(items);
      if (backlog) setBacklogStatus(backlog);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load queue';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [canUseAdminUi]);

  useEffect(() => {
    if (!canUseAdminUi) return undefined;
    refresh();
    const interval = window.setInterval(refresh, 5000);
    return () => window.clearInterval(interval);
  }, [canUseAdminUi, refresh]);

  const cancelItem = useCallback(
    async (id: string) => {
      setError(null);
      try {
        await apiCancelQueueItem(id);
        await refresh();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Failed to cancel item';
        setError(msg);
        throw err;
      }
    },
    [refresh]
  );

  const retryItem = useCallback(
    async (id: string) => {
      setError(null);
      try {
        await apiRetryQueueItem(id);
        await refresh();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Failed to retry item';
        setError(msg);
        throw err;
      }
    },
    [refresh]
  );

  const triggerBacklogSearch = useCallback(async () => {
    setError(null);
    try {
      await apiTriggerBacklogSearch();
      await refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to trigger backlog search';
      setError(msg);
      throw err;
    }
  }, [refresh]);

  return {
    queueItems,
    backlogStatus,
    isLoading,
    error,
    cancelItem,
    retryItem,
    triggerBacklogSearch,
    refresh,
  };
}
