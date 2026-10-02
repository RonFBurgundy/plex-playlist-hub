import { apiRequest, setAuthToken } from './apiClient';
import type { AuthPinResponse, AuthVerifyResponse, User } from '@/types/models';

export async function startPlexAuth(): Promise<AuthPinResponse> {
  return apiRequest<AuthPinResponse>('/api/auth/plex/pin', {
    method: 'POST',
  });
}

export async function verifyPin(pinId: number): Promise<AuthVerifyResponse> {
  const result = await apiRequest<AuthVerifyResponse>('/api/auth/plex/verify', {
    method: 'POST',
    body: { pin_id: pinId },
  });
  if (result.token) {
    setAuthToken(result.token);
  }
  return result;
}

export async function pollPin(
  pinId: number,
  signal?: AbortSignal
): Promise<AuthVerifyResponse> {
  return apiRequest<AuthVerifyResponse>('/api/auth/plex/verify', {
    method: 'POST',
    body: { pin_id: pinId },
    signal,
  });
}

export async function getCurrentUser(): Promise<User | null> {
  try {
    const res = await apiRequest<{ user: User }>('/api/auth/me');
    return res?.user || null;
  } catch {
    return null;
  }
}

export async function logout(): Promise<void> {
  try {
    await apiRequest<void>('/api/auth/logout', { method: 'POST' });
  } finally {
    setAuthToken(null);
  }
}
