import React, { useState } from 'react';
import { Play, Pause, Plus, Check, Disc, Music, Loader2 } from 'lucide-react';
import type { DiscoveryItem, AudioPreviewTrack } from '@/types/models';
import type { UseDiscoveryReturn } from '@/hooks/useDiscovery';
import {
  TapeTransportBay,
  TapeDeckButton,
  MachinedCard,
  SearchBar,
  ObsidianModal,
} from '@/components/ui';
import { getDiscoveryAlbumDetail } from '@/services/discoveryService';

export interface DiscoverViewProps {
  discovery: UseDiscoveryReturn;
  onPlayTrack: (track: AudioPreviewTrack) => void;
  currentPreviewTrackId?: string;
  isPreviewPlaying?: boolean;
  onRequest: (item: DiscoveryItem) => Promise<void>;
  requestedIds: Set<string>;
}

export const DiscoverView: React.FC<DiscoverViewProps> = ({
  discovery,
  onPlayTrack,
  currentPreviewTrackId,
  isPreviewPlaying = false,
  onRequest,
  requestedIds,
}) => {
  const [selectedAlbum, setSelectedAlbum] = useState<DiscoveryItem | null>(null);
  const [albumDetails, setAlbumDetails] = useState<{
    tracks?: Array<{ id: string; title: string; duration_ms?: number; preview_url?: string }>;
  } | null>(null);
  const [isLoadingAlbum, setIsLoadingAlbum] = useState<boolean>(false);
  const [requestingId, setRequestingId] = useState<string | null>(null);

  const handleOpenAlbum = async (item: DiscoveryItem) => {
    setSelectedAlbum(item);
    setIsLoadingAlbum(true);
    try {
      const data = await getDiscoveryAlbumDetail(item.id);
      setAlbumDetails(data as { tracks?: Array<{ id: string; title: string; duration_ms?: number; preview_url?: string }> });
    } catch {
      setAlbumDetails(null);
    } finally {
      setIsLoadingAlbum(false);
    }
  };

  const handleRequestClick = async (e: React.MouseEvent, item: DiscoveryItem) => {
    e.stopPropagation();
    setRequestingId(item.id);
    try {
      await onRequest(item);
    } finally {
      setRequestingId(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Search and Category Transport Controls */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
        <div className="flex-1 max-w-lg">
          <SearchBar
            value={discovery.query}
            onChange={(val) => {
              if (!val) discovery.clearSearch();
              else discovery.search(val);
            }}
            placeholder="Search albums, artists, or tracks..."
          />
        </div>

        <TapeTransportBay className="flex items-center gap-1.5 self-start sm:self-auto">
          <TapeDeckButton
            size="sm"
            active={discovery.category === 'trending'}
            onClick={() => {
              discovery.clearSearch();
              discovery.setCategory('trending');
            }}
            icon={<Disc className="h-3.5 w-3.5" />}
          >
            Trending
          </TapeDeckButton>
          <TapeDeckButton
            size="sm"
            active={discovery.category === 'new_releases'}
            onClick={() => {
              discovery.clearSearch();
              discovery.setCategory('new_releases');
            }}
            icon={<Music className="h-3.5 w-3.5" />}
          >
            New Releases
          </TapeDeckButton>
        </TapeTransportBay>
      </div>

      {/* Loading state */}
      {discovery.isLoading && (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <Loader2 className="h-8 w-8 text-[#e5a00d] animate-spin" />
          <span className="text-xs uppercase tracking-widest text-neutral-400 font-mono">
            Scanning Analog Frequencies...
          </span>
        </div>
      )}

      {/* Error state */}
      {discovery.error && !discovery.isLoading && (
        <div className="p-4 bg-red-950/40 border border-red-800/50 rounded-[4px] text-xs text-red-300 font-mono">
          {discovery.error}
        </div>
      )}

      {/* Items Grid */}
      {!discovery.isLoading && discovery.items.length === 0 && !discovery.error && (
        <div className="text-center py-16 text-neutral-500 font-mono text-sm">
          No releases found for this query.
        </div>
      )}

      {!discovery.isLoading && discovery.items.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
          {discovery.items.map((item) => {
            const isRequested = requestedIds.has(item.id) || item.requested;
            const isPlayingThis = currentPreviewTrackId === item.id && isPreviewPlaying;
            const isProcessing = requestingId === item.id;

            return (
              <MachinedCard
                key={item.id}
                interactive
                onClick={() => handleOpenAlbum(item)}
                className="group flex flex-col overflow-hidden"
              >
                {/* Artwork with overlay transport controls */}
                <div className="relative aspect-square w-full bg-[#1c1c1c] overflow-hidden">
                  {item.cover_url ? (
                    <img
                      src={item.cover_url}
                      alt={item.title}
                      className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                      loading="lazy"
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).src = '/placeholder.svg';
                      }}
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center bg-[#151515]">
                      <Disc className="h-10 w-10 text-neutral-600" />
                    </div>
                  )}

                  {/* 30s Preview Key Overlay */}
                  {item.preview_url && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onPlayTrack({
                          id: item.id,
                          title: item.title,
                          artist: item.artist,
                          cover_url: item.cover_url,
                          preview_url: item.preview_url!,
                        });
                      }}
                      className="absolute bottom-2 left-2 p-2 rounded-full bg-black/80 hover:bg-[#e5a00d] text-white hover:text-black border border-[#2a2a2a] shadow-lg transition-colors"
                      aria-label="Toggle 30s preview"
                    >
                      {isPlayingThis ? (
                        <Pause className="h-3.5 w-3.5" />
                      ) : (
                        <Play className="h-3.5 w-3.5 fill-current" />
                      )}
                    </button>
                  )}
                </div>

                {/* Info & Action */}
                <div className="p-3 flex flex-col flex-1 justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="font-bold text-xs sm:text-sm text-white truncate" title={item.title}>
                      {item.title}
                    </h3>
                    <p className="text-[11px] sm:text-xs text-neutral-400 truncate" title={item.artist}>
                      {item.artist}
                    </p>
                  </div>

                  <TapeDeckButton
                    size="sm"
                    variant={isRequested ? 'default' : 'amber'}
                    disabled={isRequested || isProcessing}
                    onClick={(e) => handleRequestClick(e, item)}
                    className="w-full"
                    icon={
                      isProcessing ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : isRequested ? (
                        <Check className="h-3.5 w-3.5 text-green-400" />
                      ) : (
                        <Plus className="h-3.5 w-3.5" />
                      )
                    }
                  >
                    {isRequested ? 'Requested' : 'Request'}
                  </TapeDeckButton>
                </div>
              </MachinedCard>
            );
          })}
        </div>
      )}

      {/* Album Tracklist Modal */}
      {selectedAlbum && (
        <ObsidianModal
          isOpen={Boolean(selectedAlbum)}
          onClose={() => {
            setSelectedAlbum(null);
            setAlbumDetails(null);
          }}
          title={selectedAlbum.title}
          subtitle={`By ${selectedAlbum.artist}`}
          footer={
            <div className="flex items-center justify-between w-full">
              <span className="text-xs text-neutral-400 font-mono">
                {albumDetails?.tracks?.length || 0} Tracks
              </span>
              <TapeDeckButton
                variant="amber"
                size="md"
                disabled={requestedIds.has(selectedAlbum.id)}
                onClick={(e) => handleRequestClick(e, selectedAlbum)}
                icon={<Plus className="h-4 w-4" />}
              >
                {requestedIds.has(selectedAlbum.id) ? 'Album Requested' : 'Request Full Album'}
              </TapeDeckButton>
            </div>
          }
        >
          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <img
                src={selectedAlbum.cover_url || '/placeholder.svg'}
                alt=""
                className="h-20 w-20 rounded-[3px] object-cover border border-[#222222]"
              />
              <div>
                <h4 className="font-bold text-white text-base">{selectedAlbum.title}</h4>
                <p className="text-sm text-neutral-400">{selectedAlbum.artist}</p>
                {selectedAlbum.release_date && (
                  <p className="text-xs text-neutral-500 font-mono mt-1">
                    Released: {selectedAlbum.release_date}
                  </p>
                )}
              </div>
            </div>

            {isLoadingAlbum ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 text-[#e5a00d] animate-spin" />
              </div>
            ) : albumDetails?.tracks && albumDetails.tracks.length > 0 ? (
              <div className="divide-y divide-[#1f1f1f] border border-[#1f1f1f] rounded-[4px] overflow-hidden">
                {albumDetails.tracks.map((t, idx) => (
                  <div
                    key={t.id || idx}
                    className="flex items-center justify-between p-2.5 hover:bg-[#181818] transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="font-mono text-xs text-neutral-500 w-5">
                        {idx + 1}
                      </span>
                      <span className="text-sm text-neutral-200 truncate">{t.title}</span>
                    </div>

                    {t.preview_url && (
                      <TapeDeckButton
                        size="sm"
                        onClick={() =>
                          onPlayTrack({
                            id: t.id,
                            title: t.title,
                            artist: selectedAlbum.artist,
                            cover_url: selectedAlbum.cover_url,
                            preview_url: t.preview_url!,
                          })
                        }
                        icon={
                          currentPreviewTrackId === t.id && isPreviewPlaying ? (
                            <Pause className="h-3 w-3 text-[#e5a00d]" />
                          ) : (
                            <Play className="h-3 w-3 fill-current" />
                          )
                        }
                      />
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-neutral-500 font-mono py-4">
                No individual tracklist details available.
              </p>
            )}
          </div>
        </ObsidianModal>
      )}
    </div>
  );
};
