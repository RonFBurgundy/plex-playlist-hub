import React from 'react';
import { RefreshCw, Radio, HardDrive, Disc, User, Music, Loader2 } from 'lucide-react';
import type { UseLibraryReturn, LibraryTab } from '@/hooks/useLibrary';
import {
  TapeTransportBay,
  TapeDeckButton,
  MachinedCard,
  SearchBar,
  TactileSwitch,
} from '@/components/ui';

export interface LibraryViewProps {
  libraryHook: UseLibraryReturn;
  isAdmin?: boolean;
}

export const LibraryView: React.FC<LibraryViewProps> = ({
  libraryHook,
  isAdmin = false,
}) => {
  const {
    activeTab,
    artists,
    albums,
    tracks,
    stats,
    searchQuery,
    isScanning,
    scanStatus,
    lidarrStatus,
    isLoading,
    error,
    setTab,
    setSearch,
    triggerScan,
    cancelScan,
    toggleArtistMonitored,
    toggleAlbumMonitored,
    toggleTrackMonitored,
  } = libraryHook;

  const tabs: Array<{ id: LibraryTab; label: string; icon: React.ReactNode }> = [
    { id: 'artists', label: 'Artists', icon: <User className="h-3.5 w-3.5" /> },
    { id: 'albums', label: 'Albums', icon: <Disc className="h-3.5 w-3.5" /> },
    { id: 'tracks', label: 'Tracks', icon: <Music className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="space-y-6">
      {/* Stats Summary Bar */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-[#121212] border border-[#222222] p-3 rounded-[4px]">
            <span className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">
              Artists
            </span>
            <p className="text-xl font-mono font-bold text-white mt-1">
              {stats.artist_count}
            </p>
          </div>
          <div className="bg-[#121212] border border-[#222222] p-3 rounded-[4px]">
            <span className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">
              Albums
            </span>
            <p className="text-xl font-mono font-bold text-white mt-1">
              {stats.album_count}
            </p>
          </div>
          <div className="bg-[#121212] border border-[#222222] p-3 rounded-[4px]">
            <span className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">
              Tracks
            </span>
            <p className="text-xl font-mono font-bold text-white mt-1">
              {stats.track_count}
            </p>
          </div>
          <div className="bg-[#121212] border border-[#222222] p-3 rounded-[4px]">
            <span className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">
              Monitored
            </span>
            <p className="text-xl font-mono font-bold text-[#e5a00d] mt-1">
              {stats.monitored_artist_count ?? '-'}
            </p>
          </div>
        </div>
      )}

      {/* Scan Banner / Actions */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
        <TapeTransportBay className="flex items-center gap-1.5 overflow-x-auto">
          {tabs.map((tab) => (
            <TapeDeckButton
              key={tab.id}
              size="sm"
              active={activeTab === tab.id}
              onClick={() => setTab(tab.id)}
              icon={tab.icon}
            >
              {tab.label}
            </TapeDeckButton>
          ))}
        </TapeTransportBay>

        {isAdmin && (
          <div className="flex items-center gap-2">
            {isScanning ? (
              <TapeDeckButton
                size="sm"
                variant="danger"
                onClick={cancelScan}
                icon={<Loader2 className="h-3.5 w-3.5 animate-spin" />}
              >
                Cancel Scan
              </TapeDeckButton>
            ) : (
              <TapeDeckButton
                size="sm"
                variant="amber"
                onClick={() => triggerScan(false)}
                icon={<RefreshCw className="h-3.5 w-3.5" />}
              >
                Scan Library
              </TapeDeckButton>
            )}
          </div>
        )}
      </div>

      {/* Live Scan Status Indicator */}
      {isScanning && scanStatus && (
        <div className="p-3 bg-[#161616] border border-[#e5a00d]/40 rounded-[4px] flex items-center justify-between text-xs font-mono">
          <div className="flex items-center gap-2.5">
            <Radio className="h-4 w-4 text-[#e5a00d] animate-pulse" />
            <span className="text-neutral-300">
              Scanning disk: {scanStatus.processed_tracks} / {scanStatus.total_tracks} tracks processed
            </span>
          </div>
          {scanStatus.current_path && (
            <span className="text-neutral-500 truncate max-w-xs hidden sm:inline">
              {scanStatus.current_path}
            </span>
          )}
        </div>
      )}

      {/* Lidarr Migration Panel (if present) */}
      {lidarrStatus && lidarrStatus.is_migrating && (
        <div className="p-3 bg-[#151515] border border-blue-800/60 rounded-[4px] flex items-center gap-3 text-xs font-mono">
          <HardDrive className="h-4 w-4 text-blue-400 animate-spin" />
          <span className="text-blue-300">
            Lidarr Migration Active: {lidarrStatus.migrated_artists} of {lidarrStatus.total_artists} artists migrated ({lidarrStatus.progress}%)
          </span>
        </div>
      )}

      {/* Filter / Search Bar */}
      <SearchBar
        value={searchQuery}
        onChange={setSearch}
        placeholder={`Filter ${activeTab}...`}
      />

      {/* Loading state */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <Loader2 className="h-8 w-8 text-[#e5a00d] animate-spin" />
          <span className="text-xs uppercase tracking-widest text-neutral-400 font-mono">
            Indexing Library Catalog...
          </span>
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <div className="p-4 bg-red-950/40 border border-red-800/50 rounded-[4px] text-xs text-red-300 font-mono">
          {error}
        </div>
      )}

      {/* Artists Tab */}
      {!isLoading && activeTab === 'artists' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {artists.map((artist) => (
            <MachinedCard key={artist.id} className="p-4 flex items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <h4 className="font-bold text-sm text-white truncate" title={artist.name}>
                  {artist.name}
                </h4>
                <p className="text-xs text-neutral-400 font-mono mt-0.5">
                  {artist.album_count || 0} Albums &middot; {artist.track_count || 0} Tracks
                </p>
              </div>

              {isAdmin && (
                <TactileSwitch
                  checked={artist.monitored}
                  onChange={(val) => toggleArtistMonitored(artist.id, val)}
                  aria-label={`Toggle monitoring for ${artist.name}`}
                />
              )}
            </MachinedCard>
          ))}
          {artists.length === 0 && (
            <div className="col-span-full text-center py-12 text-neutral-500 font-mono text-sm">
              No artists found in library.
            </div>
          )}
        </div>
      )}

      {/* Albums Tab */}
      {!isLoading && activeTab === 'albums' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {albums.map((album) => (
            <MachinedCard key={album.id} className="p-4 flex items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <h4 className="font-bold text-sm text-white truncate" title={album.title}>
                  {album.title}
                </h4>
                <p className="text-xs text-neutral-400 truncate mt-0.5" title={album.artist_name}>
                  {album.artist_name || 'Unknown Artist'}
                </p>
              </div>

              {isAdmin && (
                <TactileSwitch
                  checked={album.monitored}
                  onChange={(val) => toggleAlbumMonitored(album.id, val)}
                  aria-label={`Toggle monitoring for ${album.title}`}
                />
              )}
            </MachinedCard>
          ))}
          {albums.length === 0 && (
            <div className="col-span-full text-center py-12 text-neutral-500 font-mono text-sm">
              No albums found in library.
            </div>
          )}
        </div>
      )}

      {/* Tracks Tab */}
      {!isLoading && activeTab === 'tracks' && (
        <div className="divide-y divide-[#1f1f1f] border border-[#222222] rounded-[4px] bg-[#121212] overflow-hidden">
          {tracks.map((track) => (
            <div
              key={track.id}
              className="p-3 flex items-center justify-between gap-4 hover:bg-[#181818] transition-colors"
            >
              <div className="min-w-0 flex-1">
                <h4 className="font-bold text-sm text-neutral-200 truncate" title={track.title}>
                  {track.title}
                </h4>
                <p className="text-xs text-neutral-400 truncate">
                  {track.file_path || 'No audio file linked'}
                </p>
              </div>

              {isAdmin && (
                <TactileSwitch
                  checked={track.monitored}
                  onChange={(val) => toggleTrackMonitored(track.id, val)}
                  aria-label={`Toggle monitoring for ${track.title}`}
                />
              )}
            </div>
          ))}
          {tracks.length === 0 && (
            <div className="p-8 text-center text-neutral-500 font-mono text-sm">
              No tracks found in library.
            </div>
          )}
        </div>
      )}
    </div>
  );
};
