import { apiRequest } from './apiClient';
import type { CreateIssuePayload, Issue } from '@/types/models';

export interface ListIssuesParams {
  media_title?: string;
  artist?: string;
}

/** Lists the caller's issues (admins see all server-side). */
export async function getIssues(params: ListIssuesParams = {}): Promise<Issue[]> {
  const qs = new URLSearchParams();
  if (params.media_title) qs.set('media_title', params.media_title);
  if (params.artist) qs.set('artist', params.artist);
  const query = qs.toString();
  const res = await apiRequest<Issue[] | null>(query ? `/api/issues?${query}` : '/api/issues');
  return res ?? [];
}

export async function createIssue(payload: CreateIssuePayload): Promise<Issue> {
  return apiRequest<Issue>('/api/issues', { method: 'POST', body: payload });
}
