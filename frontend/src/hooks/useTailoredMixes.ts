import { useState, useEffect, useCallback, useRef } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type {
  MixConfig,
  MixConfigCreateBody,
  MixConfigUpdateBody,
  MixTrack,
  ScrobbleConfig,
  TailoredMixResult,
} from '@/types/models';
import {
  getMixes,
  createMix,
  updateMix,
  deleteMix,
  previewMix,
  generateMix,
  getMixResult,
} from '@/services/mixService';
import { getScrobbleUsers } from '@/services/scrobbleService';

const POLL_INTERVAL_MS = 3000;
const POLL_MAX_MS = 60000;

export interface UseTailoredMixesReturn {
  mixes: MixConfig[];
  isLoading: boolean;
  error: string | null;
  clearError: () => void;
  users: ScrobbleConfig[];
  selectedUserId: string | undefined;
  setSelectedUserId: (id: string | undefined) => void;
  results: Record<string, TailoredMixResult>;
  previews: Record<string, MixTrack[]>;
  busyIds: Set<string>;
  generatingIds: Set<string>;
  create: (body: MixConfigCreateBody) => Promise<boolean>;
  update: (id: string, body: MixConfigUpdateBody) => Promise<void>;
  remove: (id: string) => Promise<void>;
  preview: (id: string) => Promise<void>;
  generate: (id: string) => Promise<void>;
}

function msg(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export function useTailoredMixes(isAdmin: boolean): UseTailoredMixesReturn {
  const [mixes, setMixes] = useState<MixConfig[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [users, setUsers] = useState<ScrobbleConfig[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<string | undefined>(undefined);
  const [results, setResults] = useState<Record<string, TailoredMixResult>>({});
  const [previews, setPreviews] = useState<Record<string, MixTrack[]>>({});
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [generatingIds, setGeneratingIds] = useState<Set<string>>(new Set());

  const timers = useRef<Map<string, number>>(new Map());
  const mounted = useRef<boolean>(true);
  const listReq = useRef<number>(0);

  const clearError = useCallback(() => setError(null), []);

  const setIn = (
    setter: Dispatch<SetStateAction<Set<string>>>,
    id: string,
    on: boolean
  ): void => {
    setter((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const stopPolling = useCallback((id: string) => {
    const t = timers.current.get(id);
    if (t !== undefined) {
      window.clearTimeout(t);
      timers.current.delete(id);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const pending = timers.current;
    return () => {
      mounted.current = false;
      pending.forEach((t) => window.clearTimeout(t));
      pending.clear();
    };
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    getScrobbleUsers()
      .then((u) => {
        if (mounted.current) setUsers(u);
      })
      .catch((err: unknown) => {
        if (mounted.current) setError(msg(err, 'Failed to load users'));
      });
  }, [isAdmin]);

  const load = useCallback(async () => {
    const req = ++listReq.current;
    setIsLoading(true);
    try {
      const list = await getMixes(isAdmin ? selectedUserId : undefined);
      if (!mounted.current || req !== listReq.current) return;
      setMixes(list);
      // Hydrate last results (404 -> null) in parallel.
      const fetched = await Promise.all(
        list.map(async (m) => {
          try {
            return await getMixResult(m.id);
          } catch {
            return null;
          }
        })
      );
      if (!mounted.current || req !== listReq.current) return;
      const map: Record<string, TailoredMixResult> = {};
      fetched.forEach((r) => {
        if (r) map[r.mix_id] = r;
      });
      setResults(map);
    } catch (err) {
      if (mounted.current && req === listReq.current) setError(msg(err, 'Failed to load mixes'));
    } finally {
      if (mounted.current && req === listReq.current) setIsLoading(false);
    }
  }, [isAdmin, selectedUserId]);

  useEffect(() => {
    void load();
  }, [load]);

  const withBusy = useCallback(async (id: string, fn: () => Promise<void>, fallback: string) => {
    setIn(setBusyIds, id, true);
    try {
      await fn();
    } catch (err) {
      if (mounted.current) setError(msg(err, fallback));
    } finally {
      if (mounted.current) setIn(setBusyIds, id, false);
    }
  }, []);

  const create = useCallback(
    async (body: MixConfigCreateBody): Promise<boolean> => {
      try {
        const created = await createMix(
          isAdmin && selectedUserId ? { ...body, user_id: selectedUserId } : body
        );
        if (mounted.current) setMixes((prev) => [...prev, created]);
        return true;
      } catch (err) {
        if (mounted.current) setError(msg(err, 'Failed to create mix'));
        return false;
      }
    },
    [isAdmin, selectedUserId]
  );

  const update = useCallback(
    (id: string, body: MixConfigUpdateBody) =>
      withBusy(
        id,
        async () => {
          const updated = await updateMix(id, body);
          if (mounted.current) setMixes((prev) => prev.map((m) => (m.id === id ? updated : m)));
        },
        'Failed to update mix'
      ),
    [withBusy]
  );

  const remove = useCallback(
    (id: string) =>
      withBusy(
        id,
        async () => {
          stopPolling(id);
          await deleteMix(id);
          if (!mounted.current) return;
          setMixes((prev) => prev.filter((m) => m.id !== id));
          setResults((prev) => {
            const next = { ...prev };
            delete next[id];
            return next;
          });
        },
        'Failed to delete mix'
      ),
    [withBusy, stopPolling]
  );

  const preview = useCallback(
    (id: string) =>
      withBusy(
        id,
        async () => {
          const res = await previewMix(id);
          if (mounted.current) setPreviews((prev) => ({ ...prev, [id]: res.tracks }));
        },
        'Failed to preview mix'
      ),
    [withBusy]
  );

  const generate = useCallback(
    async (id: string) => {
      stopPolling(id);
      const baseline = results[id]?.generated_at ?? null;
      setIn(setGeneratingIds, id, true);
      try {
        await generateMix(id);
      } catch (err) {
        if (mounted.current) {
          setError(msg(err, 'Failed to start mix generation'));
          setIn(setGeneratingIds, id, false);
        }
        return;
      }

      const startedAt = Date.now();
      const tick = async (): Promise<void> => {
        if (!mounted.current) return;
        try {
          const res = await getMixResult(id);
          if (!mounted.current) return;
          if (res && res.generated_at !== baseline) {
            setResults((prev) => ({ ...prev, [id]: res }));
            setMixes((prev) =>
              prev.map((m) => (m.id === id ? { ...m, last_generated_at: res.generated_at } : m))
            );
            timers.current.delete(id);
            setIn(setGeneratingIds, id, false);
            return;
          }
        } catch (err) {
          if (!mounted.current) return;
          setError(msg(err, 'Failed to read mix result'));
          timers.current.delete(id);
          setIn(setGeneratingIds, id, false);
          return;
        }
        if (Date.now() - startedAt >= POLL_MAX_MS) {
          timers.current.delete(id);
          setIn(setGeneratingIds, id, false);
          setError('Mix generation is taking longer than expected. Check back shortly.');
          return;
        }
        timers.current.set(id, window.setTimeout(() => void tick(), POLL_INTERVAL_MS));
      };
      timers.current.set(id, window.setTimeout(() => void tick(), POLL_INTERVAL_MS));
    },
    [results, stopPolling]
  );

  return {
    mixes,
    isLoading,
    error,
    clearError,
    users,
    selectedUserId,
    setSelectedUserId,
    results,
    previews,
    busyIds,
    generatingIds,
    create,
    update,
    remove,
    preview,
    generate,
  };
}
