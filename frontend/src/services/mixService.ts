import { apiRequest } from './apiClient';
import type {
  MixConfig,
  MixConfigCreateBody,
  MixConfigUpdateBody,
  MixGenerateResponse,
  MixPreviewResult,
  TailoredMixResult,
} from '@/types/models';

const BASE = '/api/mixes';

function userQuery(userId?: string): string {
  return userId ? `?user_id=${encodeURIComponent(userId)}` : '';
}

const one = (id: string): string => `${BASE}/${encodeURIComponent(id)}`;

export async function getMixes(userId?: string): Promise<MixConfig[]> {
  return (await apiRequest<MixConfig[]>(`${BASE}${userQuery(userId)}`)) || [];
}

export async function createMix(body: MixConfigCreateBody): Promise<MixConfig> {
  return apiRequest<MixConfig>(BASE, { method: 'POST', body });
}

export async function updateMix(id: string, body: MixConfigUpdateBody): Promise<MixConfig> {
  return apiRequest<MixConfig>(one(id), { method: 'PUT', body });
}

export async function deleteMix(id: string): Promise<void> {
  await apiRequest<void>(one(id), { method: 'DELETE' });
}

export async function previewMix(id: string): Promise<MixPreviewResult> {
  return apiRequest<MixPreviewResult>(`${one(id)}/preview`, { method: 'POST' });
}

export async function generateMix(id: string): Promise<MixGenerateResponse> {
  return apiRequest<MixGenerateResponse>(`${one(id)}/generate`, { method: 'POST' });
}

/** Resolves null when no result exists yet (404). Other failures reject. */
export async function getMixResult(id: string): Promise<TailoredMixResult | null> {
  try {
    return await apiRequest<TailoredMixResult>(`${one(id)}/result`);
  } catch (err) {
    if (err instanceof Error && /not found|404/i.test(err.message)) return null;
    throw err;
  }
}
