import { apiRequest } from './apiClient';
import type {
  ArtistItem,
  AlbumItem,
  TrackItem,
  LibraryStats,
  ScanStatus,
  LidarrStatus,
} from '@/types/models';

export async function getLibraryStats(): Promise<LibraryStats> {
  return apiRequest<LibraryStats>('/api/library/stats');
}

export async function getArtists(query?: string, monitoredOnly: boolean = false): Promise<ArtistItem[]> {
  const params = new URLSearchParams();
  if (query) params.set('query', query);
  if (monitoredOnly) params.set('monitored_only', 'true');
  params.set('limit', '500');
  const res = await apiRequest<ArtistItem[]>(`/api/library/artists?${params.toString()}`);
  return res || [];
}

export async function getArtistDetail(artistId: number | string): Promise<ArtistItem & { albums?: AlbumItem[] }> {
  return apiRequest<ArtistItem & { albums?: AlbumItem[] }>(`/api/library/artists/${artistId}`);
}

export async function getAlbums(artistId?: number | string, query?: string, monitoredOnly: boolean = false): Promise<AlbumItem[]> {
  const params = new URLSearchParams();
  if (artistId !== undefined) params.set('artist_id', String(artistId));
  if (query) params.set('query', query);
  if (monitoredOnly) params.set('monitored_only', 'true');
  params.set('limit', '500');
  const res = await apiRequest<AlbumItem[]>(`/api/library/albums?${params.toString()}`);
  return res || [];
}

export async function getAlbumDetail(albumId: number | string): Promise<AlbumItem & { tracks?: TrackItem[] }> {
  return apiRequest<AlbumItem & { tracks?: TrackItem[] }>(`/api/library/albums/${albumId}`);
}

export async function getTracks(albumId?: number | string, artistId?: number | string, query?: string): Promise<TrackItem[]> {
  const params = new URLSearchParams();
  if (albumId !== undefined) params.set('album_id', String(albumId));
  if (artistId !== undefined) params.set('artist_id', String(artistId));
  if (query) params.set('query', query);
  params.set('limit', '500');
  const res = await apiRequest<TrackItem[]>(`/api/library/tracks?${params.toString()}`);
  return res || [];
}

export async function toggleArtistMonitored(artistId: number | string, monitored: boolean): Promise<void> {
  await apiRequest<void>(`/api/library/artists/${artistId}/monitored`, {
    method: 'PUT',
    body: { monitored },
  });
}

export async function toggleAlbumMonitored(albumId: number | string, monitored: boolean): Promise<void> {
  await apiRequest<void>(`/api/library/albums/${albumId}/monitored`, {
    method: 'PUT',
    body: { monitored },
  });
}

export async function toggleTrackMonitored(trackId: number | string, monitored: boolean): Promise<void> {
  await apiRequest<void>(`/api/library/tracks/${trackId}/monitored`, {
    method: 'PUT',
    body: { monitored },
  });
}

export async function refreshArtist(
  artistId: number | string
): Promise<{ success: boolean; artist_id: string; refreshed_at?: string }> {
  return apiRequest<{ success: boolean; artist_id: string; refreshed_at?: string }>(
    `/api/library/artists/${artistId}/refresh`,
    {
      method: 'POST',
    }
  );
}

export async function setArtistMonitoringPreset(
  artistId: number | string,
  option: 'all' | 'albums' | 'singles_eps' | 'none'
): Promise<void> {
  await apiRequest<void>(`/api/library/artists/${artistId}/monitored`, {
    method: 'PUT',
    body: {
      monitored: option !== 'none',
      cascade_children: true,
      monitor_option: option,
    },
  });
}

export async function triggerScan(pruneMissing: boolean = false): Promise<void> {
  await apiRequest<void>('/api/library/scan', {
    method: 'POST',
    body: { prune_missing: pruneMissing },
  });
}

export async function getScanStatus(): Promise<ScanStatus> {
  return apiRequest<ScanStatus>('/api/library/scan/status');
}

export async function cancelScan(): Promise<void> {
  await apiRequest<void>('/api/library/scan/cancel', {
    method: 'POST',
  });
}

export async function getLidarrStatus(): Promise<LidarrStatus> {
  return apiRequest<LidarrStatus>('/api/library/migrate-lidarr/status');
}

export async function startLidarrMigration(autoSwitch: boolean = true): Promise<void> {
  await apiRequest<void>('/api/library/migrate-lidarr', {
    method: 'POST',
    body: { auto_switch: autoSwitch },
  });
}
