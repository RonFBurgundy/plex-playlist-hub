import { apiRequest } from './apiClient';
import type { QueueItem, BacklogStatus } from '@/types/models';

export async function getQueue(includeHistory: boolean = true): Promise<QueueItem[]> {
  const url = includeHistory ? '/api/queue?include_history=true' : '/api/queue';
  const res = await apiRequest<QueueItem[]>(url);
  return res || [];
}

export async function cancelQueueItem(id: string): Promise<void> {
  await apiRequest<void>(`/api/queue/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export async function retryQueueItem(id: string): Promise<void> {
  await apiRequest<void>(`/api/requests/${encodeURIComponent(id)}/retry`, {
    method: 'POST',
  });
}

export async function getBacklogStatus(): Promise<BacklogStatus> {
  try {
    const res = await apiRequest<BacklogStatus>('/api/acquisition/backlog/status');
    return res;
  } catch {
    return {
      is_running: false,
      total_missing: 0,
      in_progress: 0,
    };
  }
}

export async function triggerBacklogSearch(): Promise<{ status: string }> {
  try {
    return await apiRequest<{ status: string }>('/api/acquisition/search', {
      method: 'POST',
      body: {},
    });
  } catch {
    return { status: 'triggered' };
  }
}
