import { apiRequest } from './apiClient';
import type {
  AdminScrobbleConfigBody,
  ScrobbleConfig,
  ScrobbleConfigBody,
  ScrobbleServerConfig,
  ScrobbleServerConfigBody,
  ScrobbleUrlResponse,
  UserListen,
} from '@/types/models';

const BASE = '/api/scrobbles';

export async function getScrobbleConfig(): Promise<ScrobbleConfig> {
  return apiRequest<ScrobbleConfig>(`${BASE}/config`);
}

export async function updateScrobbleConfig(body: ScrobbleConfigBody): Promise<ScrobbleConfig> {
  return apiRequest<ScrobbleConfig>(`${BASE}/config`, { method: 'PUT', body });
}

export async function getListens(limit = 20, offset = 0): Promise<UserListen[]> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return (await apiRequest<UserListen[]>(`${BASE}/listens?${qs.toString()}`)) || [];
}

/** Returns the Last.fm authorisation URL. Rejects with the server's 503 detail when unconfigured. */
export async function getLastfmAuthUrl(forwardUrl?: string): Promise<ScrobbleUrlResponse> {
  const qs = forwardUrl ? `?forward_url=${encodeURIComponent(forwardUrl)}` : '';
  return apiRequest<ScrobbleUrlResponse>(`${BASE}/lastfm/auth-url${qs}`);
}

export async function getScrobbleUsers(): Promise<ScrobbleConfig[]> {
  return (await apiRequest<ScrobbleConfig[]>(`${BASE}/users`)) || [];
}

export async function updateUserScrobbleConfig(
  userId: string,
  body: AdminScrobbleConfigBody
): Promise<ScrobbleConfig> {
  return apiRequest<ScrobbleConfig>(`${BASE}/users/${encodeURIComponent(userId)}/config`, {
    method: 'PUT',
    body,
  });
}

export async function getScrobbleServerConfig(): Promise<ScrobbleServerConfig> {
  return apiRequest<ScrobbleServerConfig>(`${BASE}/server-config`);
}

export async function updateScrobbleServerConfig(
  body: ScrobbleServerConfigBody
): Promise<ScrobbleServerConfig | null> {
  return apiRequest<ScrobbleServerConfig | null>(`${BASE}/server-config`, { method: 'PUT', body });
}

export async function getWebhookUrl(): Promise<ScrobbleUrlResponse> {
  return apiRequest<ScrobbleUrlResponse>(`${BASE}/webhook-url`);
}

export async function rotateWebhookSecret(): Promise<ScrobbleUrlResponse> {
  return apiRequest<ScrobbleUrlResponse>(`${BASE}/webhook-secret/rotate`, { method: 'POST' });
}
