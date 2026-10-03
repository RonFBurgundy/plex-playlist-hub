import React from 'react';
import type { PlexPlaylistKind, PlexPlaylistOwner } from '@/types/models';

const BADGE = 'px-2 py-0.5 rounded-[2px] border text-[10px] font-mono uppercase tracking-wide';

export const PlexKindBadge: React.FC<{ kind: PlexPlaylistKind }> = ({ kind }) => (
  <span
    className={`${BADGE} ${
      kind === 'smart'
        ? 'bg-[#e5a00d]/10 border-[#e5a00d]/40 text-[#e5a00d]'
        : 'bg-[#1a1a1a] border-[#2a2a2a] text-neutral-300'
    }`}
  >
    {kind === 'smart' ? 'Smart' : 'Regular'}
  </span>
);

const OWNER_LABEL: Record<PlexPlaylistOwner, string> = {
  trackseerr: 'TrackSeerr',
  user: 'Yours',
  plexamp: 'Plexamp',
};

const OWNER_STYLE: Record<PlexPlaylistOwner, string> = {
  trackseerr: 'bg-[#22c55e]/10 border-[#22c55e]/40 text-[#22c55e]',
  user: 'bg-[#1a1a1a] border-[#383838] text-white',
  plexamp: 'bg-[#1a1a1a] border-[#2a2a2a] text-neutral-400',
};

export const PlexOwnerBadge: React.FC<{ owner: PlexPlaylistOwner }> = ({ owner }) => (
  <span className={`${BADGE} ${OWNER_STYLE[owner]}`}>{OWNER_LABEL[owner]}</span>
);
