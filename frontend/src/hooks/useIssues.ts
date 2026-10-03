import { useState, useEffect, useCallback } from 'react';
import type { CreateIssuePayload, Issue } from '@/types/models';
import { getIssues, createIssue } from '@/services/issueService';

export interface UseIssuesReturn {
  issues: Issue[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  /** Creates an issue; rethrows so the caller can map the HTTP status. */
  submit: (payload: CreateIssuePayload) => Promise<Issue>;
  /** Returns the current user's open or in-progress issue for this media, if any. */
  findActive: (mediaTitle: string, artist: string) => Issue | undefined;
}

const norm = (v: string): string => v.trim().toLowerCase();

export function useIssues(currentUserId?: string | number): UseIssuesReturn {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setIssues(await getIssues());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load issues');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const submit = useCallback(async (payload: CreateIssuePayload): Promise<Issue> => {
    const created = await createIssue(payload);
    setIssues((prev) => [created, ...prev.filter((i) => i.id !== created.id)]);
    return created;
  }, []);

  const findActive = useCallback(
    (mediaTitle: string, artist: string): Issue | undefined =>
      issues.find(
        (i) =>
          currentUserId !== undefined &&
          String(i.user_id) === String(currentUserId) &&
          i.status !== 'resolved' &&
          norm(i.media_title) === norm(mediaTitle) &&
          norm(i.artist) === norm(artist)
      ),
    [issues, currentUserId]
  );

  return { issues, isLoading, error, refresh, submit, findActive };
}
