import { apiRequest } from './apiClient';
import type { Playlist } from '@/types/models';

export async function getPlaylists(): Promise<Playlist[]> {
  const res = await apiRequest<Playlist[]>('/api/playlists');
  return res || [];
}

export async function toggleUserTarget(playlistId: number | string, targetUserIds: string[]): Promise<void> {
  await apiRequest<void>(`/api/playlists/${playlistId}/targets`, {
    method: 'PUT',
    body: { target_user_ids: targetUserIds },
  });
}

export async function togglePlaylistActive(playlistId: number | string, isEnabled: boolean): Promise<void> {
  await apiRequest<void>(`/api/playlists/${playlistId}/enabled`, {
    method: 'PUT',
    body: { is_enabled: isEnabled },
  });
}

export async function deletePlaylist(playlistId: number | string): Promise<void> {
  await apiRequest<void>(`/api/playlists/${playlistId}`, {
    method: 'DELETE',
  });
}

export async function triggerSync(): Promise<{ status: string }> {
  return apiRequest<{ status: string }>('/api/sync', {
    method: 'POST',
  });
}

export interface ImportPlaylistPayload {
  name: string;
  source_type: string;
  source_url?: string;
  tracks?: string[];
  target_user_ids?: string[];
}

export async function importPlaylist(payload: ImportPlaylistPayload): Promise<Playlist> {
  return apiRequest<Playlist>('/api/playlists/import', {
    method: 'POST',
    body: payload,
  });
}
