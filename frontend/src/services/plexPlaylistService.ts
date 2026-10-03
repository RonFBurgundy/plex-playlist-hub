import { apiRequest } from './apiClient';
import type {
  AdoptedPlexPlaylist,
  PlexAddItemsBody,
  PlexCopyBody,
  PlexCopyResult,
  PlexFlagsBody,
  PlexMix,
  PlexMixSnapshot,
  PlexMixSnapshotBody,
  PlexMoveItemBody,
  PlexPlaylistItem,
  PlexPlaylistSummary,
  PlexUserOption,
} from '@/types/models';

const BASE = '/api/plex-playlists';

function userQuery(user?: string, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams();
  if (user) params.set('user', user);
  for (const [k, v] of Object.entries(extra)) params.set(k, v);
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

const pl = (ratingKey: string): string => `${BASE}/${encodeURIComponent(ratingKey)}`;

export async function getPlexUsers(): Promise<PlexUserOption[]> {
  return (await apiRequest<PlexUserOption[]>(`${BASE}/users`)) || [];
}

export async function getPlexPlaylists(
  user: string | undefined,
  includeIgnored: boolean
): Promise<PlexPlaylistSummary[]> {
  const res = await apiRequest<PlexPlaylistSummary[]>(
    `${BASE}${userQuery(user, { include_ignored: String(includeIgnored) })}`
  );
  return res || [];
}

export async function getPlexPlaylistItems(
  ratingKey: string,
  user?: string
): Promise<PlexPlaylistItem[]> {
  return (await apiRequest<PlexPlaylistItem[]>(`${pl(ratingKey)}/items${userQuery(user)}`)) || [];
}

export async function renamePlexPlaylist(
  ratingKey: string,
  title: string,
  user?: string
): Promise<PlexPlaylistSummary> {
  return apiRequest<PlexPlaylistSummary>(`${pl(ratingKey)}${userQuery(user)}`, {
    method: 'PATCH',
    body: { title },
  });
}

export async function deletePlexPlaylist(ratingKey: string, user?: string): Promise<void> {
  await apiRequest<void>(`${pl(ratingKey)}${userQuery(user)}`, { method: 'DELETE' });
}

export async function addPlexPlaylistItems(
  ratingKey: string,
  body: PlexAddItemsBody,
  user?: string
): Promise<PlexPlaylistItem[]> {
  return (
    (await apiRequest<PlexPlaylistItem[]>(`${pl(ratingKey)}/items${userQuery(user)}`, {
      method: 'POST',
      body,
    })) || []
  );
}

export async function removePlexPlaylistItem(
  ratingKey: string,
  playlistItemId: number,
  user?: string
): Promise<void> {
  await apiRequest<void>(`${pl(ratingKey)}/items/${playlistItemId}${userQuery(user)}`, {
    method: 'DELETE',
  });
}

export async function movePlexPlaylistItem(
  ratingKey: string,
  playlistItemId: number,
  body: PlexMoveItemBody,
  user?: string
): Promise<PlexPlaylistItem[]> {
  return (
    (await apiRequest<PlexPlaylistItem[]>(
      `${pl(ratingKey)}/items/${playlistItemId}/move${userQuery(user)}`,
      { method: 'POST', body }
    )) || []
  );
}

export async function copyPlexPlaylist(
  ratingKey: string,
  body: PlexCopyBody,
  user?: string
): Promise<PlexCopyResult[]> {
  return (
    (await apiRequest<PlexCopyResult[]>(`${pl(ratingKey)}/copy${userQuery(user)}`, {
      method: 'POST',
      body,
    })) || []
  );
}

export async function adoptPlexPlaylist(ratingKey: string, user?: string): Promise<AdoptedPlexPlaylist> {
  return apiRequest<AdoptedPlexPlaylist>(`${pl(ratingKey)}/adopt${userQuery(user)}`, { method: 'POST' });
}

export async function setPlexPlaylistFlags(
  ratingKey: string,
  body: PlexFlagsBody,
  user?: string
): Promise<PlexPlaylistSummary> {
  return apiRequest<PlexPlaylistSummary>(`${pl(ratingKey)}/flags${userQuery(user)}`, {
    method: 'PUT',
    body,
  });
}

export async function getPlexMixes(user?: string): Promise<PlexMix[]> {
  return (await apiRequest<PlexMix[]>(`${BASE}/mixes${userQuery(user)}`)) || [];
}

export async function snapshotPlexMix(
  body: PlexMixSnapshotBody,
  user?: string
): Promise<PlexMixSnapshot> {
  return apiRequest<PlexMixSnapshot>(`${BASE}/mixes/snapshot${userQuery(user)}`, {
    method: 'POST',
    body,
  });
}

export async function getPlexMixSnapshots(user?: string): Promise<PlexMixSnapshot[]> {
  return (await apiRequest<PlexMixSnapshot[]>(`${BASE}/mixes/snapshots${userQuery(user)}`)) || [];
}

export async function updatePlexMixSnapshot(
  id: string,
  autoRefresh: boolean
): Promise<PlexMixSnapshot> {
  return apiRequest<PlexMixSnapshot>(`${BASE}/mixes/snapshots/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: { auto_refresh: autoRefresh },
  });
}

export async function deletePlexMixSnapshot(id: string): Promise<void> {
  await apiRequest<void>(`${BASE}/mixes/snapshots/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}
