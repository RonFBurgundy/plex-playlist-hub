import React, { useState } from 'react';
import { Flag } from 'lucide-react';
import { TapeDeckButton } from '@/components/ui';
import type { UseIssuesReturn } from '@/hooks/useIssues';
import { ReportIssueModal } from './ReportIssueModal';
import { IssueStatusChip } from './IssueStatusChip';

export interface IssueReportButtonProps {
  mediaTitle: string;
  artist: string;
  requestId?: string;
  issuesHook: UseIssuesReturn;
  className?: string;
}

/** Shows an "Already reported" chip when an active issue exists, else a Report issue button. */
export const IssueReportButton: React.FC<IssueReportButtonProps> = ({
  mediaTitle,
  artist,
  requestId,
  issuesHook,
  className = '',
}) => {
  const [open, setOpen] = useState<boolean>(false);
  const existing = issuesHook.findActive(mediaTitle, artist);

  if (existing) {
    return (
      <span className={className}>
        <IssueStatusChip status={existing.status} prefix="Already reported" />
      </span>
    );
  }

  return (
    <>
      <TapeDeckButton
        size="sm"
        className={className}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        icon={<Flag className="h-3.5 w-3.5" />}
      >
        Report issue
      </TapeDeckButton>
      <ReportIssueModal
        isOpen={open}
        onClose={() => setOpen(false)}
        mediaTitle={mediaTitle}
        artist={artist}
        requestId={requestId}
        onSubmit={issuesHook.submit}
      />
    </>
  );
};
