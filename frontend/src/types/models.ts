/**
 * Domain & UI models for TrackSeerr React SPA.
 * Strictly typed with zero `any` / `as any`.
 */

export interface User {
  id: number;
  plex_username: string;
  plex_id?: string;
  email?: string;
  thumb?: string;
  is_admin: boolean;
  is_active: boolean;
  quota_limit?: number;
  quota_period_days?: number;
  requests_remaining?: number;
}

export interface UserQuota {
  remaining: number;
  limit: number;
  period_days: number;
}

export interface AuthPinResponse {
  id: number;
  code: string;
  auth_url: string;
  expires_in: number;
}

export interface AuthVerifyResponse {
  token: string;
  user: User;
}

export interface DiscoveryItem {
  id: string;
  title: string;
  artist: string;
  album?: string;
  cover_url?: string;
  release_date?: string;
  type: 'album' | 'track' | 'artist';
  preview_url?: string;
  popularity?: number;
  source?: string;
  requested?: boolean;
  in_library?: boolean;
}

export interface RequestItem {
  id: number;
  title: string;
  artist: string;
  album?: string;
  status: 'pending' | 'approved' | 'rejected' | 'fulfilled' | 'available';
  requested_by_id?: number;
  requested_by_username?: string;
  created_at: string;
  cover_url?: string;
  type?: string;
  quality_profile?: string;
}

export interface Playlist {
  id: number;
  name: string;
  source_url: string;
  source_type: 'spotify' | 'deezer' | 'm3u' | 'csv';
  target_user_ids: number[];
  is_active: boolean;
  last_synced?: string;
  track_count?: number;
  matched_count?: number;
}

export interface MissingTrack {
  id: number;
  playlist_id: number;
  playlist_name?: string;
  title: string;
  artist: string;
  album?: string;
  created_at: string;
}

export interface ArtistItem {
  id: number;
  name: string;
  monitored: boolean;
  overview?: string;
  artist_type?: string;
  disambiguation?: string;
  genres?: string[];
  images?: Array<{ cover_type: string; url: string }>;
  album_count?: number;
  track_count?: number;
}

export interface AlbumItem {
  id: number;
  artist_id: number;
  artist_name?: string;
  title: string;
  monitored: boolean;
  release_date?: string;
  album_type?: string;
  genres?: string[];
  images?: Array<{ cover_type: string; url: string }>;
  track_count?: number;
}

export interface TrackItem {
  id: number;
  album_id: number;
  artist_id: number;
  title: string;
  track_number?: number;
  disc_number?: number;
  duration_ms?: number;
  monitored: boolean;
  file_path?: string;
  has_file?: boolean;
  preview_url?: string;
}

export interface LibraryStats {
  artist_count: number;
  album_count: number;
  track_count: number;
  monitored_artist_count?: number;
}

export interface QueueItem {
  id: string;
  title: string;
  artist?: string;
  album?: string;
  status: string;
  size?: number;
  progress?: number;
  timeleft?: string;
  download_client?: string;
  protocol?: string;
  error_message?: string;
}

export interface BacklogStatus {
  is_running: boolean;
  total_missing: number;
  in_progress: number;
  last_run?: string;
}

export interface QualityProfile {
  id: number;
  name: string;
  cutoff: number;
  items?: Array<{ id: number; name: string; allowed: boolean; quality: string }>;
  upgrade_allowed?: boolean;
}

export interface DownloadClientItem {
  id: number;
  name: string;
  client_type: 'slskd' | 'sabnzbd' | 'qbittorrent' | 'deluge' | 'transmission';
  host: string;
  port: number;
  use_ssl: boolean;
  is_enabled: boolean;
  priority: number;
}

export interface IndexerItem {
  id: number;
  name: string;
  indexer_type: 'torznab' | 'newznab' | 'soulseek';
  url: string;
  api_key?: string;
  is_enabled: boolean;
  priority: number;
}

export interface SystemStatusInfo {
  version: string;
  database_status: string;
  media_path?: string;
  download_path?: string;
  plex_connected: boolean;
  lidarr_connected: boolean;
  storage?: {
    free_space: number;
    total_space: number;
  };
}

export interface AudioPreviewTrack {
  id: string;
  title: string;
  artist: string;
  cover_url?: string;
  preview_url: string;
}

export interface ScanStatus {
  status: 'idle' | 'running' | 'completed' | 'failed';
  processed_tracks: number;
  total_tracks: number;
  current_path?: string;
}

export interface LidarrStatus {
  is_migrating: boolean;
  progress: number;
  migrated_artists: number;
  total_artists: number;
  status: string;
}

export interface GeneralSettings {
  server_name: string;
  base_url: string;
  port: number;
  plex_url: string;
  plex_token: string;
  lidarr_url?: string;
  lidarr_api_key?: string;
  music_directory?: string;
}
