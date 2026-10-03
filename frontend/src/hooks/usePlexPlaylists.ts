import { useState, useEffect, useCallback, useRef } from 'react';
import type {
  AdoptedPlexPlaylist,
  PlexCopyResult,
  PlexMix,
  PlexMixSnapshot,
  PlexPlaylistItem,
  PlexPlaylistOwner,
  PlexPlaylistSummary,
  PlexUserOption,
} from '@/types/models';
import {
  getPlexUsers,
  getPlexPlaylists,
  getPlexPlaylistItems,
  renamePlexPlaylist,
  deletePlexPlaylist,
  removePlexPlaylistItem,
  movePlexPlaylistItem,
  copyPlexPlaylist,
  adoptPlexPlaylist,
  setPlexPlaylistFlags,
  getPlexMixes,
  snapshotPlexMix,
  getPlexMixSnapshots,
  updatePlexMixSnapshot,
  deletePlexMixSnapshot,
} from '@/services/plexPlaylistService';

export type MoveDirection = 'up' | 'down';

export interface UsePlexPlaylistsReturn {
  users: PlexUserOption[];
  selectedUser: string | undefined;
  setSelectedUser: (username: string) => void;
  playlists: PlexPlaylistSummary[];
  includeIgnored: boolean;
  setIncludeIgnored: (value: boolean) => void;
  isLoading: boolean;
  error: string | null;
  clearError: () => void;
  refresh: () => Promise<void>;

  selected: PlexPlaylistSummary | null;
  items: PlexPlaylistItem[];
  isItemsLoading: boolean;
  isMutating: boolean;
  copyResults: PlexCopyResult[] | null;
  selectPlaylist: (playlist: PlexPlaylistSummary | null) => Promise<void>;

  toggleIgnored: (playlist: PlexPlaylistSummary) => Promise<void>;
  setOwner: (playlist: PlexPlaylistSummary, owner: Exclude<PlexPlaylistOwner, 'plexamp'>) => Promise<void>;
  renamePlaylist: (playlist: PlexPlaylistSummary, title: string) => Promise<boolean>;
  deletePlaylist: (playlist: PlexPlaylistSummary) => Promise<boolean>;
  removeItem: (item: PlexPlaylistItem) => Promise<void>;
  moveItem: (item: PlexPlaylistItem, direction: MoveDirection) => Promise<void>;
  copyToUsers: (playlist: PlexPlaylistSummary, targets: string[]) => Promise<PlexCopyResult[]>;
  adopt: (playlist: PlexPlaylistSummary) => Promise<AdoptedPlexPlaylist | null>;

  mixes: PlexMix[];
  snapshots: PlexMixSnapshot[];
  isMixesLoading: boolean;
  loadMixes: () => Promise<void>;
  saveMix: (mix: PlexMix, title: string, autoRefresh: boolean) => Promise<boolean>;
  toggleSnapshotRefresh: (snapshot: PlexMixSnapshot, autoRefresh: boolean) => Promise<void>;
  removeSnapshot: (snapshot: PlexMixSnapshot) => Promise<void>;
}

function errMsg(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export function usePlexPlaylists(): UsePlexPlaylistsReturn {
  const [users, setUsers] = useState<PlexUserOption[]>([]);
  const [selectedUser, setSelectedUserState] = useState<string | undefined>(undefined);
  const [playlists, setPlaylists] = useState<PlexPlaylistSummary[]>([]);
  const [includeIgnored, setIncludeIgnored] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<PlexPlaylistSummary | null>(null);
  const [items, setItems] = useState<PlexPlaylistItem[]>([]);
  const [isItemsLoading, setIsItemsLoading] = useState<boolean>(false);
  const [isMutating, setIsMutating] = useState<boolean>(false);
  const [copyResults, setCopyResults] = useState<PlexCopyResult[] | null>(null);

  const [mixes, setMixes] = useState<PlexMix[]>([]);
  const [snapshots, setSnapshots] = useState<PlexMixSnapshot[]>([]);
  const [isMixesLoading, setIsMixesLoading] = useState<boolean>(false);

  // Guards against out-of-order responses when the user/filter changes quickly.
  const listReq = useRef(0);
  const itemsReq = useRef(0);
  const mixesReq = useRef(0);
  const usersReady = useRef(false);

  const clearError = useCallback(() => setError(null), []);

  // Users: resolve once, default to self.
  useEffect(() => {
    let cancelled = false;
    getPlexUsers()
      .then((list) => {
        if (cancelled) return;
        setUsers(list);
        const self = list.find((u) => u.is_self) ?? list[0];
        setSelectedUserState(self?.username);
        usersReady.current = true;
        if (!self) setIsLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(errMsg(err, 'Failed to load Plex users'));
        usersReady.current = true;
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refresh = useCallback(async () => {
    const req = ++listReq.current;
    setIsLoading(true);
    try {
      const list = await getPlexPlaylists(selectedUser, includeIgnored);
      if (req !== listReq.current) return;
      setPlaylists(list);
      setError(null);
    } catch (err: unknown) {
      if (req !== listReq.current) return;
      setError(errMsg(err, 'Failed to load Plex playlists'));
    } finally {
      if (req === listReq.current) setIsLoading(false);
    }
  }, [selectedUser, includeIgnored]);

  useEffect(() => {
    if (!usersReady.current || selectedUser === undefined) return;
    void refresh();
  }, [refresh, selectedUser]);

  const setSelectedUser = useCallback((username: string) => {
    setSelected(null);
    setItems([]);
    setPlaylists([]);
    setMixes([]);
    setSnapshots([]);
    setCopyResults(null);
    setSelectedUserState(username);
  }, []);

  const selectPlaylist = useCallback(
    async (playlist: PlexPlaylistSummary | null) => {
      setCopyResults(null);
      setSelected(playlist);
      setItems([]);
      if (!playlist) return;
      const req = ++itemsReq.current;
      setIsItemsLoading(true);
      try {
        const list = await getPlexPlaylistItems(playlist.rating_key, selectedUser);
        if (req !== itemsReq.current) return;
        setItems(list);
      } catch (err: unknown) {
        if (req !== itemsReq.current) return;
        setError(errMsg(err, 'Failed to load playlist tracks'));
      } finally {
        if (req === itemsReq.current) setIsItemsLoading(false);
      }
    },
    [selectedUser]
  );

  /** Replace a summary in the list and the open selection. */
  const patchSummary = useCallback((next: PlexPlaylistSummary) => {
    setPlaylists((prev) => prev.map((p) => (p.rating_key === next.rating_key ? next : p)));
    setSelected((prev) => (prev && prev.rating_key === next.rating_key ? next : prev));
  }, []);

  const toggleIgnored = useCallback(
    async (playlist: PlexPlaylistSummary) => {
      const snapshotList = playlists;
      const nextIgnored = !playlist.ignored;
      patchSummary({ ...playlist, ignored: nextIgnored });
      try {
        const updated = await setPlexPlaylistFlags(playlist.rating_key, { ignored: nextIgnored }, selectedUser);
        patchSummary(updated);
        if (updated.ignored && !includeIgnored) {
          setPlaylists((prev) => prev.filter((p) => p.rating_key !== updated.rating_key));
        }
      } catch (err: unknown) {
        setPlaylists(snapshotList);
        setSelected((prev) => (prev && prev.rating_key === playlist.rating_key ? playlist : prev));
        setError(errMsg(err, 'Failed to update ignore flag'));
      }
    },
    [playlists, selectedUser, includeIgnored, patchSummary]
  );

  const setOwner = useCallback(
    async (playlist: PlexPlaylistSummary, owner: Exclude<PlexPlaylistOwner, 'plexamp'>) => {
      const snapshotList = playlists;
      patchSummary({ ...playlist, owner });
      try {
        const updated = await setPlexPlaylistFlags(playlist.rating_key, { owner }, selectedUser);
        patchSummary(updated);
      } catch (err: unknown) {
        setPlaylists(snapshotList);
        setSelected((prev) => (prev && prev.rating_key === playlist.rating_key ? playlist : prev));
        setError(errMsg(err, 'Failed to change playlist protection'));
      }
    },
    [playlists, selectedUser, patchSummary]
  );

  const renamePlaylist = useCallback(
    async (playlist: PlexPlaylistSummary, title: string): Promise<boolean> => {
      const trimmed = title.trim();
      if (!trimmed) return false;
      setIsMutating(true);
      try {
        const updated = await renamePlexPlaylist(playlist.rating_key, trimmed, selectedUser);
        patchSummary(updated);
        return true;
      } catch (err: unknown) {
        setError(errMsg(err, 'Failed to rename playlist'));
        return false;
      } finally {
        setIsMutating(false);
      }
    },
    [selectedUser, patchSummary]
  );

  const deletePlaylist = useCallback(
    async (playlist: PlexPlaylistSummary): Promise<boolean> => {
      setIsMutating(true);
      try {
        await deletePlexPlaylist(playlist.rating_key, selectedUser);
        setPlaylists((prev) => prev.filter((p) => p.rating_key !== playlist.rating_key));
        setSelected(null);
        setItems([]);
        return true;
      } catch (err: unknown) {
        setError(errMsg(err, 'Failed to delete playlist'));
        return false;
      } finally {
        setIsMutating(false);
      }
    },
    [selectedUser]
  );

  const removeItem = useCallback(
    async (item: PlexPlaylistItem) => {
      if (!selected) return;
      const before = items;
      const key = selected.rating_key;
      setItems(before.filter((i) => i.playlist_item_id !== item.playlist_item_id));
      setPlaylists((prev) =>
        prev.map((p) => (p.rating_key === key ? { ...p, track_count: Math.max(0, p.track_count - 1) } : p))
      );
      try {
        await removePlexPlaylistItem(key, item.playlist_item_id, selectedUser);
      } catch (err: unknown) {
        setItems(before);
        setPlaylists((prev) =>
          prev.map((p) => (p.rating_key === key ? { ...p, track_count: p.track_count + 1 } : p))
        );
        setError(errMsg(err, 'Failed to remove track'));
      }
    },
    [selected, items, selectedUser]
  );

  const moveItem = useCallback(
    async (item: PlexPlaylistItem, direction: MoveDirection) => {
      if (!selected) return;
      const idx = items.findIndex((i) => i.playlist_item_id === item.playlist_item_id);
      if (idx < 0) return;
      const target = direction === 'up' ? idx - 1 : idx + 1;
      if (target < 0 || target >= items.length) return;

      // Plex moves "after" a given item; null means the top.
      const afterId =
        direction === 'up'
          ? idx - 2 >= 0
            ? items[idx - 2].playlist_item_id
            : null
          : items[target].playlist_item_id;

      const before = items;
      const reordered = [...items];
      reordered.splice(idx, 1);
      reordered.splice(target, 0, item);
      setItems(reordered);
      try {
        const fresh = await movePlexPlaylistItem(
          selected.rating_key,
          item.playlist_item_id,
          { after_playlist_item_id: afterId },
          selectedUser
        );
        if (fresh.length > 0) setItems(fresh);
      } catch (err: unknown) {
        setItems(before);
        setError(errMsg(err, 'Failed to move track'));
      }
    },
    [selected, items, selectedUser]
  );

  const copyToUsers = useCallback(
    async (playlist: PlexPlaylistSummary, targets: string[]): Promise<PlexCopyResult[]> => {
      setIsMutating(true);
      setCopyResults(null);
      try {
        const results = await copyPlexPlaylist(playlist.rating_key, { target_users: targets }, selectedUser);
        setCopyResults(results);
        // A copy into the current profile adds a new playlist; pick it up.
        if (results.some((r) => r.success && r.username.toLowerCase() === (selectedUser ?? '').toLowerCase())) {
          void refresh();
        }
        return results;
      } catch (err: unknown) {
        setError(errMsg(err, 'Failed to copy playlist'));
        return [];
      } finally {
        setIsMutating(false);
      }
    },
    [selectedUser, refresh]
  );

  const adopt = useCallback(
    async (playlist: PlexPlaylistSummary): Promise<AdoptedPlexPlaylist | null> => {
      setIsMutating(true);
      try {
        const created = await adoptPlexPlaylist(playlist.rating_key, selectedUser);
        const linked: PlexPlaylistSummary = {
          ...playlist,
          trackseerr_playlist_id: created.id,
        };
        patchSummary(linked);
        return created;
      } catch (err: unknown) {
        setError(errMsg(err, 'Failed to adopt playlist'));
        return null;
      } finally {
        setIsMutating(false);
      }
    },
    [selectedUser, patchSummary]
  );

  const loadMixes = useCallback(async () => {
    const req = ++mixesReq.current;
    setIsMixesLoading(true);
    try {
      const [m, s] = await Promise.all([getPlexMixes(selectedUser), getPlexMixSnapshots(selectedUser)]);
      if (req !== mixesReq.current) return;
      setMixes(m);
      setSnapshots(s);
    } catch (err: unknown) {
      if (req !== mixesReq.current) return;
      setError(errMsg(err, 'Failed to load Plex mixes'));
    } finally {
      if (req === mixesReq.current) setIsMixesLoading(false);
    }
  }, [selectedUser]);

  const saveMix = useCallback(
    async (mix: PlexMix, title: string, autoRefresh: boolean): Promise<boolean> => {
      setIsMutating(true);
      try {
        const snap = await snapshotPlexMix(
          {
            mix_key: mix.mix_key,
            title: title.trim() || undefined,
            auto_refresh: autoRefresh,
          },
          selectedUser
        );
        setSnapshots((prev) => [...prev.filter((s) => s.id !== snap.id), snap]);
        setMixes((prev) => prev.map((m) => (m.mix_key === mix.mix_key ? { ...m, snapshot_id: snap.id } : m)));
        void refresh();
        return true;
      } catch (err: unknown) {
        setError(errMsg(err, 'Failed to save mix as playlist'));
        return false;
      } finally {
        setIsMutating(false);
      }
    },
    [selectedUser, refresh]
  );

  const toggleSnapshotRefresh = useCallback(
    async (snapshot: PlexMixSnapshot, autoRefresh: boolean) => {
      const before = snapshots;
      setSnapshots((prev) => prev.map((s) => (s.id === snapshot.id ? { ...s, auto_refresh: autoRefresh } : s)));
      try {
        const updated = await updatePlexMixSnapshot(snapshot.id, autoRefresh);
        setSnapshots((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      } catch (err: unknown) {
        setSnapshots(before);
        setError(errMsg(err, 'Failed to update auto-refresh'));
      }
    },
    [snapshots]
  );

  const removeSnapshot = useCallback(
    async (snapshot: PlexMixSnapshot) => {
      const beforeSnaps = snapshots;
      const beforeMixes = mixes;
      setSnapshots((prev) => prev.filter((s) => s.id !== snapshot.id));
      setMixes((prev) => prev.map((m) => (m.snapshot_id === snapshot.id ? { ...m, snapshot_id: null } : m)));
      try {
        await deletePlexMixSnapshot(snapshot.id);
      } catch (err: unknown) {
        setSnapshots(beforeSnaps);
        setMixes(beforeMixes);
        setError(errMsg(err, 'Failed to remove snapshot'));
      }
    },
    [snapshots, mixes]
  );

  return {
    users,
    selectedUser,
    setSelectedUser,
    playlists,
    includeIgnored,
    setIncludeIgnored,
    isLoading,
    error,
    clearError,
    refresh,
    selected,
    items,
    isItemsLoading,
    isMutating,
    copyResults,
    selectPlaylist,
    toggleIgnored,
    setOwner,
    renamePlaylist,
    deletePlaylist,
    removeItem,
    moveItem,
    copyToUsers,
    adopt,
    mixes,
    snapshots,
    isMixesLoading,
    loadMixes,
    saveMix,
    toggleSnapshotRefresh,
    removeSnapshot,
  };
}
