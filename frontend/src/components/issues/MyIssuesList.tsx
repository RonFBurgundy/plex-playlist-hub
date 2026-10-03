import React from 'react';
import { Loader2 } from 'lucide-react';
import { MachinedCard } from '@/components/ui';
import type { UseIssuesReturn } from '@/hooks/useIssues';
import { ISSUE_TYPE_LABELS } from '@/types/models';
import { IssueStatusChip } from './IssueStatusChip';

export interface MyIssuesListProps {
  issuesHook: UseIssuesReturn;
}

export const MyIssuesList: React.FC<MyIssuesListProps> = ({ issuesHook }) => {
  const { issues, isLoading, error } = issuesHook;

  if (isLoading && issues.length === 0) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 text-[var(--accent-amber)] animate-spin" />
      </div>
    );
  }

  if (error && issues.length === 0) {
    return (
      <div className="p-4 border border-[var(--status-error)] rounded-[4px] text-xs text-[var(--status-error)] font-mono">
        {error}
      </div>
    );
  }

  if (issues.length === 0) {
    return (
      <div className="text-center py-16 text-[var(--text-muted)] font-mono text-sm">
        You have not reported any issues.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {issues.map((issue) => (
        <MachinedCard key={issue.id} className="p-3 flex flex-col gap-2">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h4 className="font-bold text-sm text-[var(--text-primary)] truncate" title={issue.media_title}>
                {issue.media_title}
              </h4>
              <p className="text-xs text-[var(--text-secondary)] truncate" title={issue.artist}>
                {issue.artist}
              </p>
            </div>
            <IssueStatusChip status={issue.status} />
          </div>
          <p className="text-[11px] font-mono uppercase text-[var(--text-muted)]">
            {ISSUE_TYPE_LABELS[issue.issue_type]}
            {issue.created_at ? ` - ${new Date(issue.created_at).toLocaleDateString()}` : ''}
          </p>
          <p className="text-xs text-[var(--text-secondary)] break-words line-clamp-3">
            {issue.problem_details}
          </p>
        </MachinedCard>
      ))}
    </div>
  );
};
