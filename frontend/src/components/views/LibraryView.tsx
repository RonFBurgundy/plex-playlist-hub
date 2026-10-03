import React, { useState, useEffect, useMemo } from 'react';
import {
  RefreshCw,
  Radio,
  HardDrive,
  Disc,
  User,
  Music,
  Loader2,
  ChevronDown,
  ChevronUp,
  ArrowLeft,
  Check,
  ChevronLeft,
  ChevronRight,
  Sliders,
  Layers,
  Plus,
  Trash2,
  ExternalLink,
  BookmarkPlus,
  Globe,
} from 'lucide-react';
import type { UseLibraryReturn, LibraryTab } from '@/hooks/useLibrary';
import type { ArtistItem, AlbumItem, TrackItem, CollectionItem } from '@/types/models';
import {
  TapeTransportBay,
  TapeDeckButton,
  MachinedCard,
  SearchBar,
  TactileSwitch,
  ObsidianModal,
} from '@/components/ui';
import {
  getArtistDetail,
  getAlbumDetail,
  refreshArtist,
  setArtistMonitoringPreset,
  getCollections,
  getCollectionDetail,
  createCollection,
  deleteCollection,
  addAlbumToCollection,
  removeAlbumFromCollection,
} from '@/services/libraryService';

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
    collections,
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

  // Selected artist drilldown for Spotify + Lidarr hybrid view
  const [selectedArtistId, setSelectedArtistId] = useState<number | string | null>(null);
  const [artistDetail, setArtistDetail] = useState<(ArtistItem & { albums?: AlbumItem[] }) | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState<boolean>(false);
  const [isRefreshingArtist, setIsRefreshingArtist] = useState<boolean>(false);
  const [discographyTab, setDiscographyTab] = useState<'studio' | 'singles_eps' | 'live' | 'compilations'>('studio');
  const [expandedAlbumIds, setExpandedAlbumIds] = useState<Set<number | string>>(new Set());
  const [albumTracksMap, setAlbumTracksMap] = useState<Record<string, TrackItem[]>>({});
  const [loadingAlbumIds, setLoadingAlbumIds] = useState<Set<number | string>>(new Set());
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Collections state
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(null);
  const [selectedCollection, setSelectedCollection] = useState<CollectionItem | null>(null);
  const [isLoadingCollection, setIsLoadingCollection] = useState<boolean>(false);
  const [isCreateCollectionOpen, setIsCreateCollectionOpen] = useState<boolean>(false);
  const [newColName, setNewColName] = useState<string>('');
  const [newColSummary, setNewColSummary] = useState<string>('');
  const [newColPosterUrl, setNewColPosterUrl] = useState<string>('');
  const [isCreatingCollection, setIsCreatingCollection] = useState<boolean>(false);

  // Add to Collection modal state
  const [albumToAddToCollection, setAlbumToAddToCollection] = useState<AlbumItem | null>(null);
  const [allCollectionsForModal, setAllCollectionsForModal] = useState<CollectionItem[]>([]);
  const [isLoadingModalCollections, setIsLoadingModalCollections] = useState<boolean>(false);

  // Album Detail & Tracklist modal state
  const [selectedAlbumForModal, setSelectedAlbumForModal] = useState<(AlbumItem & { tracks?: TrackItem[] }) | null>(null);
  const [isLoadingAlbumModal, setIsLoadingAlbumModal] = useState<boolean>(false);

  // Pagination state
  const [page, setPage] = useState<number>(1);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  // Reset page and selection when tab or search query changes
  useEffect(() => {
    setPage(1);
    setSelectedCollectionId(null);
    setSelectedCollection(null);
  }, [activeTab, searchQuery]);

  // Load collection detail when selectedCollectionId changes
  useEffect(() => {
    if (!selectedCollectionId) {
      setSelectedCollection(null);
      return;
    }

    let isCancelled = false;
    const fetchDetail = async () => {
      setIsLoadingCollection(true);
      try {
        const data = await getCollectionDetail(selectedCollectionId);
        if (!isCancelled) {
          setSelectedCollection(data);
        }
      } catch {
        if (!isCancelled) {
          showToast('Failed to load collection details');
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingCollection(false);
        }
      }
    };

    fetchDetail();
    return () => {
      isCancelled = true;
    };
  }, [selectedCollectionId]);

  const handleCreateCollection = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!newColName.trim()) return;
    setIsCreatingCollection(true);
    try {
      await createCollection({
        name: newColName.trim(),
        summary: newColSummary.trim() || undefined,
        poster_url: newColPosterUrl.trim() || undefined,
        monitored: true,
      });
      setIsCreateCollectionOpen(false);
      setNewColName('');
      setNewColSummary('');
      setNewColPosterUrl('');
      await libraryHook.refresh();
      showToast(`Collection "${newColName.trim()}" created`);
    } catch {
      showToast('Failed to create collection');
    } finally {
      setIsCreatingCollection(false);
    }
  };

  const handleDeleteCollection = async (id: string, name: string) => {
    try {
      const ok = await deleteCollection(id);
      if (ok) {
        if (selectedCollectionId === id) {
          setSelectedCollectionId(null);
          setSelectedCollection(null);
        }
        await libraryHook.refresh();
        showToast(`Collection "${name}" deleted`);
      } else {
        showToast('Failed to delete collection');
      }
    } catch {
      showToast('Error deleting collection');
    }
  };

  const handleOpenAddToCollection = async (album: AlbumItem) => {
    setAlbumToAddToCollection(album);
    setIsLoadingModalCollections(true);
    try {
      const cols = await getCollections();
      setAllCollectionsForModal(cols);
    } catch {
      showToast('Failed to load collections');
    } finally {
      setIsLoadingModalCollections(false);
    }
  };

  const handleAddAlbumToCollection = async (collectionId: string, collectionName: string) => {
    if (!albumToAddToCollection) return;
    try {
      const ok = await addAlbumToCollection(collectionId, albumToAddToCollection.id);
      if (ok) {
        showToast(`Added "${albumToAddToCollection.title}" to ${collectionName}`);
        setAlbumToAddToCollection(null);
        await libraryHook.refresh();
      } else {
        showToast('Failed to add album to collection');
      }
    } catch {
      showToast('Error adding album to collection');
    }
  };

  const handleRemoveAlbumFromCollection = async (collectionId: string, albumId: number | string) => {
    try {
      const ok = await removeAlbumFromCollection(collectionId, albumId);
      if (ok) {
        setSelectedCollection((prev) => {
          if (!prev) return null;
          return {
            ...prev,
            albums: prev.albums?.filter((a) => a.id !== albumId),
            album_count: Math.max(0, (prev.album_count || 1) - 1),
          };
        });
        await libraryHook.refresh();
        showToast('Album removed from collection');
      } else {
        showToast('Failed to remove album');
      }
    } catch {
      showToast('Error removing album from collection');
    }
  };

  const handleOpenAlbumModal = async (album: AlbumItem) => {
    setSelectedAlbumForModal(album);
    setIsLoadingAlbumModal(true);
    try {
      const detailedAlbum = await getAlbumDetail(album.id);
      setSelectedAlbumForModal(detailedAlbum);
    } catch {
      showToast('Failed to load album details');
    } finally {
      setIsLoadingAlbumModal(false);
    }
  };

  const handleToggleTrackInModal = async (
    trackId: number | string,
    currentMonitored: boolean
  ) => {
    const nextVal = !currentMonitored;
    await toggleTrackMonitored(trackId, nextVal);
    setSelectedAlbumForModal((prev) => {
      if (!prev) return null;
      return {
        ...prev,
        tracks: prev.tracks?.map((t) =>
          t.id === trackId ? { ...t, monitored: nextVal } : t
        ),
      };
    });
  };

  // Load artist detail when selectedArtistId changes
  useEffect(() => {
    if (!selectedArtistId) {
      setArtistDetail(null);
      setExpandedAlbumIds(new Set());
      setAlbumTracksMap({});
      return;
    }

    let isCancelled = false;
    const fetchDetail = async () => {
      setIsLoadingDetail(true);
      try {
        const data = await getArtistDetail(selectedArtistId);
        if (!isCancelled) {
          setArtistDetail(data);
        }
      } catch {
        if (!isCancelled) {
          showToast('Failed to load artist details');
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingDetail(false);
        }
      }
    };

    fetchDetail();
    return () => {
      isCancelled = true;
    };
  }, [selectedArtistId]);

  const handleRefreshDiscography = async () => {
    if (!selectedArtistId) return;
    setIsRefreshingArtist(true);
    try {
      await refreshArtist(selectedArtistId);
      const refreshed = await getArtistDetail(selectedArtistId);
      setArtistDetail(refreshed);
      libraryHook.refresh();
      showToast('Discography refreshed');
    } catch {
      showToast('Failed to refresh discography');
    } finally {
      setIsRefreshingArtist(false);
    }
  };

  const handleApplyPreset = async (preset: 'all' | 'albums' | 'singles_eps' | 'none') => {
    if (!selectedArtistId) return;
    try {
      await setArtistMonitoringPreset(selectedArtistId, preset);
      const refreshed = await getArtistDetail(selectedArtistId);
      setArtistDetail(refreshed);
      libraryHook.refresh();
      showToast(`Master monitoring set to '${preset.replace('_', ' ')}'`);
    } catch {
      showToast('Failed to apply monitoring preset');
    }
  };

  const handleToggleExpandAlbum = async (albumId: number | string) => {
    const key = String(albumId);
    if (expandedAlbumIds.has(albumId)) {
      setExpandedAlbumIds((prev) => {
        const next = new Set(prev);
        next.delete(albumId);
        return next;
      });
      return;
    }

    setExpandedAlbumIds((prev) => new Set([...prev, albumId]));
    if (!albumTracksMap[key]) {
      setLoadingAlbumIds((prev) => new Set([...prev, albumId]));
      try {
        const albData = await getAlbumDetail(albumId);
        if (albData && albData.tracks) {
          setAlbumTracksMap((prev) => ({ ...prev, [key]: albData.tracks || [] }));
        }
      } catch {
        showToast('Failed to load album tracks');
      } finally {
        setLoadingAlbumIds((prev) => {
          const next = new Set(prev);
          next.delete(albumId);
          return next;
        });
      }
    }
  };

  const handleToggleAlbumInDetail = async (albumId: number | string, currentMonitored: boolean) => {
    const nextVal = !currentMonitored;
    await toggleAlbumMonitored(albumId, nextVal);
    setArtistDetail((prev) => {
      if (!prev) return null;
      return {
        ...prev,
        albums: prev.albums?.map((a) => (a.id === albumId ? { ...a, monitored: nextVal } : a)),
      };
    });
  };

  const handleToggleTrackInDetail = async (
    trackId: number | string,
    albumId: number | string,
    currentMonitored: boolean
  ) => {
    const nextVal = !currentMonitored;
    const albKey = String(albumId);
    await toggleTrackMonitored(trackId, nextVal);
    setAlbumTracksMap((prev) => ({
      ...prev,
      [albKey]: (prev[albKey] || []).map((t) =>
        t.id === trackId ? { ...t, monitored: nextVal } : t
      ),
    }));
  };

  const formatTrackDuration = (secondsOrMs?: number) => {
    if (!secondsOrMs) return '--:--';
    const totalSeconds =
      secondsOrMs > 1000 ? Math.floor(secondsOrMs / 1000) : Math.floor(secondsOrMs);
    const m = Math.floor(totalSeconds / 60);
    const s = totalSeconds % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  const getQualityBadge = (track: TrackItem) => {
    if (track.quality) {
      const isLossless = track.quality.toLowerCase().includes('flac');
      return {
        label: track.quality,
        className: isLossless
          ? 'bg-emerald-950/40 text-emerald-400 border border-emerald-500/30'
          : 'bg-[#e5a00d]/10 text-[#e5a00d] border border-[#e5a00d]/30',
      };
    }
    const file = track.file;
    if (!file && !track.has_file && !track.file_path) {
      return {
        label: 'Missing',
        className: 'bg-red-950/30 text-red-400 border border-red-800/40',
      };
    }
    if (file) {
      const fmt = (file.format || '').toUpperCase();
      const bits = file.bits_per_sample;
      const bitrate = file.bitrate;
      if (fmt === 'FLAC') {
        return {
          label: bits === 24 ? 'FLAC 24-bit' : 'FLAC Lossless',
          className: 'bg-emerald-950/40 text-emerald-400 border border-emerald-500/30',
        };
      }
      if (bitrate) {
        const kbps = Math.round(bitrate / 1000);
        return {
          label: `${fmt || 'MP3'} ${kbps}`,
          className:
            kbps >= 320
              ? 'bg-[#e5a00d]/10 text-[#e5a00d] border border-[#e5a00d]/30'
              : 'bg-neutral-800 text-neutral-300 border border-neutral-700',
        };
      }
      if (fmt) {
        return {
          label: fmt,
          className: 'bg-[#e5a00d]/10 text-[#e5a00d] border border-[#e5a00d]/30',
        };
      }
    }
    if (track.file_path) {
      if (track.file_path.toLowerCase().endsWith('.flac')) {
        return {
          label: 'FLAC Lossless',
          className: 'bg-emerald-950/40 text-emerald-400 border border-emerald-500/30',
        };
      }
      if (track.file_path.toLowerCase().endsWith('.mp3')) {
        return {
          label: 'MP3 320',
          className: 'bg-[#e5a00d]/10 text-[#e5a00d] border border-[#e5a00d]/30',
        };
      }
      return {
        label: 'Available',
        className: 'bg-emerald-950/40 text-emerald-400 border border-emerald-500/30',
      };
    }
    return {
      label: 'Missing',
      className: 'bg-neutral-800 text-neutral-400 border border-neutral-700',
    };
  };

  // Pagination calculation
  const pageSize = activeTab === 'tracks' ? 50 : 24;
  const currentList = useMemo(() => {
    if (activeTab === 'artists') return artists;
    if (activeTab === 'albums') return albums;
    if (activeTab === 'collections') return collections;
    return tracks;
  }, [activeTab, artists, albums, tracks, collections]);

  const totalItems = currentList.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const paginatedItems = useMemo(() => {
    const start = (page - 1) * pageSize;
    return currentList.slice(start, start + pageSize);
  }, [currentList, page, pageSize]);

  const tabs: Array<{ id: LibraryTab; label: string; icon: React.ReactNode }> = [
    { id: 'artists', label: 'Artists', icon: <User className="h-3.5 w-3.5" /> },
    { id: 'albums', label: 'Albums', icon: <Disc className="h-3.5 w-3.5" /> },
    { id: 'tracks', label: 'Tracks', icon: <Music className="h-3.5 w-3.5" /> },
    { id: 'collections', label: 'Collections', icon: <Layers className="h-3.5 w-3.5" /> },
  ];

  // Categorized albums for Artist Detail View (4 tiers: studio, singles_eps, live, compilations)
  const categorizedAlbums = useMemo(() => {
    if (!artistDetail?.albums) return { studio: [], singles_eps: [], live: [], compilations: [] };
    const all = artistDetail.albums;
    const studio = all.filter(
      (a) => !a.album_type || ['album', 'studio'].includes(a.album_type.toLowerCase())
    );
    const singles_eps = all.filter(
      (a) => a.album_type && ['single', 'ep', 'singles', 'eps'].includes(a.album_type.toLowerCase())
    );
    const live = all.filter(
      (a) => a.album_type && a.album_type.toLowerCase() === 'live'
    );
    const compilations = all.filter(
      (a) =>
        a.album_type &&
        !['album', 'studio', 'single', 'ep', 'singles', 'eps', 'live'].includes(a.album_type.toLowerCase())
    );
    return { studio, singles_eps, live, compilations };
  }, [artistDetail]);

  // Render Artist Detail Drilldown View
  if (selectedArtistId !== null) {
    const currentArtist = artistDetail || artists.find((a) => a.id === selectedArtistId);
    const currentAlbums =
      discographyTab === 'studio'
        ? categorizedAlbums.studio
        : discographyTab === 'singles_eps'
        ? categorizedAlbums.singles_eps
        : discographyTab === 'live'
        ? categorizedAlbums.live
        : categorizedAlbums.compilations;

    const genreList = Array.isArray(currentArtist?.genres)
      ? currentArtist.genres
      : typeof currentArtist?.genres === 'string'
      ? currentArtist.genres.split(',').map((g) => g.trim()).filter(Boolean)
      : [];

    return (
      <div className="space-y-6">
        {/* Toast Notification */}
        {toastMessage && (
          <div className="fixed top-20 right-4 z-50 bg-[#161616] border border-[#e5a00d] px-4 py-2.5 rounded-[4px] text-xs font-mono text-[#e5a00d] shadow-lg flex items-center gap-2">
            <Check className="h-4 w-4" />
            <span>{toastMessage}</span>
          </div>
        )}

        {/* Back Breadcrumb Navigation */}
        <div className="flex items-center justify-between">
          <TapeDeckButton
            size="sm"
            onClick={() => setSelectedArtistId(null)}
            icon={<ArrowLeft className="h-4 w-4" />}
          >
            Back to Artists
          </TapeDeckButton>

          {isAdmin && (
            <TapeDeckButton
              size="sm"
              variant="amber"
              disabled={isRefreshingArtist}
              onClick={handleRefreshDiscography}
              icon={
                isRefreshingArtist ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )
              }
            >
              Refresh Discography
            </TapeDeckButton>
          )}
        </div>

        {/* Hero Banner Header with Backdrop */}
        <MachinedCard className="p-6 relative overflow-hidden">
          {currentArtist?.banner_url && (
            <div className="absolute inset-0 z-0 pointer-events-none">
              <img
                src={currentArtist.banner_url}
                alt={currentArtist.name}
                className="w-full h-full object-cover opacity-20 filter blur-xs"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-[#141414] via-[#141414]/85 to-transparent" />
            </div>
          )}

          <div className="relative z-10 flex flex-col sm:flex-row items-center sm:items-start gap-6">
            <div className="h-32 w-32 rounded-[4px] bg-[#1a1a1a] border-2 border-[#e5a00d]/70 overflow-hidden flex-shrink-0 flex items-center justify-center shadow-xl">
              {currentArtist?.image_url ? (
                <img
                  src={currentArtist.image_url}
                  alt={currentArtist.name}
                  className="w-full h-full object-cover"
                  loading="lazy"
                />
              ) : (
                <User className="h-16 w-16 text-neutral-600" />
              )}
            </div>

            <div className="flex-1 text-center sm:text-left space-y-3 min-w-0">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="min-w-0">
                  <span className="text-[10px] font-mono uppercase tracking-widest text-[#e5a00d]">
                    Artist Catalog
                  </span>
                  <h2 className="text-2xl sm:text-3xl font-black text-white font-mono tracking-tight mt-0.5 truncate">
                    {currentArtist?.name}
                  </h2>
                </div>

                {isAdmin && currentArtist && (
                  <div className="flex items-center justify-center sm:justify-end gap-2 flex-shrink-0">
                    <span
                      className={`text-[10px] font-mono uppercase tracking-wider ${
                        currentArtist.monitored ? 'text-[#e5a00d]' : 'text-neutral-500'
                      }`}
                    >
                      {currentArtist.monitored ? 'Monitored' : 'Unmonitored'}
                    </span>
                    <TactileSwitch
                      checked={currentArtist.monitored}
                      onChange={(val) => toggleArtistMonitored(currentArtist.id, val)}
                      label={currentArtist.monitored ? 'Monitored' : 'Unmonitored'}
                    />
                  </div>
                )}
              </div>

              {/* Badges: Country, Genres, MusicBrainz */}
              <div className="flex flex-wrap items-center justify-center sm:justify-start gap-2 pt-0.5">
                {currentArtist?.country && (
                  <span className="px-2 py-0.5 rounded-[2px] text-[10px] font-mono font-bold bg-neutral-800 text-neutral-200 border border-neutral-700 flex items-center gap-1">
                    <Globe className="h-3 w-3 text-[#e5a00d]" />
                    {currentArtist.country}
                  </span>
                )}

                {genreList.map((g) => (
                  <span
                    key={g}
                    className="px-2 py-0.5 rounded-[2px] text-[10px] font-mono bg-[#e5a00d]/10 text-[#e5a00d] border border-[#e5a00d]/30"
                  >
                    {g}
                  </span>
                ))}

                {currentArtist?.mbid && (
                  <a
                    href={`https://musicbrainz.org/artist/${currentArtist.mbid}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-2 py-0.5 rounded-[2px] text-[10px] font-mono font-bold bg-[#ba478f]/20 text-[#e599cf] border border-[#ba478f]/40 flex items-center gap-1 hover:bg-[#ba478f]/30 transition-colors"
                    title={`MusicBrainz Artist: ${currentArtist.mbid}`}
                  >
                    <span>MusicBrainz</span>
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>

              {/* Bio snippet */}
              {currentArtist?.bio && (
                <p className="text-xs text-neutral-300 font-mono line-clamp-2 bg-black/40 p-2.5 rounded-[3px] border border-white/5 text-left">
                  {currentArtist.bio}
                </p>
              )}

              <div className="flex flex-wrap items-center justify-center sm:justify-start gap-4 text-xs font-mono text-neutral-400">
                <span>{artistDetail?.albums?.length || currentArtist?.album_count || 0} Releases</span>
                <span>&bull;</span>
                <span>{currentArtist?.track_count || 0} Tracks in Library</span>
              </div>

              {/* Lidarr-style Master Monitor Selector */}
              {isAdmin && (
                <div className="pt-2 border-t border-[#1f1f1f]">
                  {/* Mobile Dropdown */}
                  <div className="flex sm:hidden items-center gap-2">
                    <span className="text-[11px] font-mono text-neutral-400 flex items-center gap-1.5 shrink-0">
                      <Sliders className="h-3 w-3 text-[#e5a00d]" /> Monitor:
                    </span>
                    <select
                      className="bg-[#141414] border border-[#2a2a2a] text-xs font-mono text-neutral-300 rounded-[3px] px-2 py-1 focus:border-[#e5a00d] focus:outline-none flex-1 min-w-0"
                      defaultValue=""
                      onChange={(e) => {
                        if (e.target.value) {
                          handleApplyPreset(e.target.value as 'all' | 'albums' | 'singles_eps' | 'none');
                          e.target.value = "";
                        }
                      }}
                    >
                      <option value="" disabled>Apply Monitor Preset...</option>
                      <option value="all">Monitor All</option>
                      <option value="albums">Studio Albums Only</option>
                      <option value="singles_eps">Singles & EPs Only</option>
                      <option value="none">Unmonitor All</option>
                    </select>
                  </div>

                  {/* Desktop Button Group */}
                  <div className="hidden sm:flex flex-wrap items-center gap-2">
                    <span className="text-[11px] font-mono text-neutral-400 flex items-center gap-1.5 mr-1">
                      <Sliders className="h-3 w-3 text-[#e5a00d]" /> Monitor Presets:
                    </span>
                    <TapeDeckButton
                      size="sm"
                      onClick={() => handleApplyPreset('all')}
                      className="text-xs py-1"
                    >
                      Monitor All
                    </TapeDeckButton>
                    <TapeDeckButton
                      size="sm"
                      onClick={() => handleApplyPreset('albums')}
                      className="text-xs py-1"
                    >
                      Studio Albums Only
                    </TapeDeckButton>
                    <TapeDeckButton
                      size="sm"
                      onClick={() => handleApplyPreset('singles_eps')}
                      className="text-xs py-1"
                    >
                      Singles &amp; EPs Only
                    </TapeDeckButton>
                    <TapeDeckButton
                      size="sm"
                      onClick={() => handleApplyPreset('none')}
                      className="text-xs py-1 text-neutral-400"
                    >
                      Unmonitor All
                    </TapeDeckButton>
                  </div>
                </div>
              )}
            </div>
          </div>
        </MachinedCard>

        {/* Categorized Discography Navigation (4 tiers) */}
        <TapeTransportBay className="flex items-center gap-1.5 overflow-x-auto">
          <TapeDeckButton
            size="sm"
            active={discographyTab === 'studio'}
            onClick={() => setDiscographyTab('studio')}
            icon={<Disc className="h-3.5 w-3.5" />}
          >
            <span className="hidden sm:inline">Studio Albums</span>
            <span className="sm:hidden">Studio</span> ({categorizedAlbums.studio.length})
          </TapeDeckButton>
          <TapeDeckButton
            size="sm"
            active={discographyTab === 'singles_eps'}
            onClick={() => setDiscographyTab('singles_eps')}
            icon={<Music className="h-3.5 w-3.5" />}
          >
            <span className="hidden sm:inline">EPs & Singles</span>
            <span className="sm:hidden">Singles</span> ({categorizedAlbums.singles_eps.length})
          </TapeDeckButton>
          <TapeDeckButton
            size="sm"
            active={discographyTab === 'live'}
            onClick={() => setDiscographyTab('live')}
            icon={<Radio className="h-3.5 w-3.5" />}
          >
            <span className="hidden sm:inline">Live Recordings</span>
            <span className="sm:hidden">Live</span> ({categorizedAlbums.live.length})
          </TapeDeckButton>
          <TapeDeckButton
            size="sm"
            active={discographyTab === 'compilations'}
            onClick={() => setDiscographyTab('compilations')}
            icon={<HardDrive className="h-3.5 w-3.5" />}
          >
            <span className="hidden sm:inline">Compilations & Box Sets</span>
            <span className="sm:hidden">Compilations</span> ({categorizedAlbums.compilations.length})
          </TapeDeckButton>
        </TapeTransportBay>

        {/* Discography List */}
        {isLoadingDetail ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <Loader2 className="h-8 w-8 text-[#e5a00d] animate-spin" />
            <span className="text-xs uppercase tracking-widest text-neutral-400 font-mono">
              Loading Artist Discography...
            </span>
          </div>
        ) : (
          <div className="space-y-4">
            {currentAlbums.map((album) => {
              const isExpanded = expandedAlbumIds.has(album.id);
              const albKey = String(album.id);
              const tracksForAlb = albumTracksMap[albKey] || [];
              const isLoadingTracks = loadingAlbumIds.has(album.id);

              return (
                <MachinedCard key={album.id} className="p-4 space-y-4">
                  {/* Album Header Bar */}
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 sm:gap-4">
                    <div
                      className="flex items-center gap-3 cursor-pointer min-w-0 w-full sm:w-auto flex-1"
                      onClick={() => handleToggleExpandAlbum(album.id)}
                    >
                      <div className="h-12 w-12 rounded-[3px] bg-[#1a1a1a] border border-[#262626] overflow-hidden flex-shrink-0 flex items-center justify-center">
                        {album.cover_url ? (
                          <img
                            src={album.cover_url}
                            alt={album.title}
                            className="w-full h-full object-cover"
                            loading="lazy"
                          />
                        ) : (
                          <Disc className="h-6 w-6 text-neutral-600" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <h4 className="font-bold text-sm text-white truncate" title={album.title}>
                            {album.title}
                          </h4>
                          {isExpanded ? (
                            <ChevronUp className="h-4 w-4 text-neutral-400 flex-shrink-0" />
                          ) : (
                            <ChevronDown className="h-4 w-4 text-neutral-400 flex-shrink-0" />
                          )}
                        </div>
                        <p className="text-xs text-neutral-400 font-mono mt-0.5">
                          {album.release_date ? album.release_date.substring(0, 4) : 'Unknown Year'}{' '}
                          &bull; {album.track_count ?? tracksForAlb.length} Tracks
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 sm:gap-3 self-stretch sm:self-center justify-between sm:justify-end flex-wrap sm:flex-nowrap">
                      {isAdmin && (
                        <div className="flex items-center gap-2">
                          <span
                            className={`text-[10px] font-mono uppercase tracking-wider hidden sm:inline ${
                              album.monitored ? 'text-[#e5a00d]' : 'text-neutral-500'
                            }`}
                          >
                            {album.monitored ? 'Monitored' : 'Unmonitored'}
                          </span>
                          <TactileSwitch
                            checked={album.monitored}
                            onChange={() => handleToggleAlbumInDetail(album.id, album.monitored)}
                            label={album.monitored ? 'Monitored' : 'Unmonitored'}
                            title={
                              album.monitored
                                ? 'Monitored for automated library acquisition'
                                : 'Unmonitored'
                            }
                          />
                        </div>
                      )}
                      <div className="flex items-center gap-2">
                        <TapeDeckButton
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleOpenAddToCollection(album);
                          }}
                          icon={<BookmarkPlus className="h-3.5 w-3.5 text-[#e5a00d]" />}
                          title="Add to Collection"
                        >
                          Collect
                        </TapeDeckButton>
                        <TapeDeckButton
                          size="sm"
                          onClick={() => handleToggleExpandAlbum(album.id)}
                          icon={
                            isLoadingTracks ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : isExpanded ? (
                              <ChevronUp className="h-3.5 w-3.5" />
                            ) : (
                              <ChevronDown className="h-3.5 w-3.5" />
                            )
                          }
                        >
                          {isExpanded ? 'Collapse' : 'Tracks'}
                        </TapeDeckButton>
                      </div>
                    </div>
                  </div>

                  {/* Expandable Tracklist Table */}
                  {isExpanded && (
                    <div className="pt-2 border-t border-[#1f1f1f]">
                      {isLoadingTracks ? (
                        <div className="flex justify-center py-6">
                          <Loader2 className="h-6 w-6 text-[#e5a00d] animate-spin" />
                        </div>
                      ) : tracksForAlb.length > 0 ? (
                        <div className="divide-y divide-[#181818] border border-[#1f1f1f] rounded-[3px] overflow-hidden bg-[#0d0d0d]">
                          {tracksForAlb.map((t) => {
                            const badge = getQualityBadge(t);
                            return (
                              <div
                                key={t.id}
                                className="p-2.5 flex items-center justify-between gap-3 hover:bg-[#141414] transition-colors"
                              >
                                <div className="flex items-center gap-3 min-w-0 flex-1">
                                  <span className="font-mono text-xs text-neutral-500 w-6 text-right flex-shrink-0">
                                    {t.track_number || 1}
                                  </span>
                                  <span
                                    className="text-sm text-neutral-200 min-w-0 flex-1 truncate"
                                    title={t.title}
                                  >
                                    {t.title}
                                  </span>
                                </div>

                                <div className="flex items-center gap-3 flex-shrink-0 font-mono text-xs">
                                  <span className="text-neutral-500 hidden sm:inline">
                                    {formatTrackDuration(t.duration_ms)}
                                  </span>

                                  {/* Quality Badge */}
                                  <span
                                    className={`px-2 py-0.5 rounded-[2px] text-[10px] font-bold ${badge.className}`}
                                  >
                                    {badge.label}
                                  </span>

                                  {/* Track Monitoring Toggle */}
                                  {isAdmin && (
                                    <div className="flex items-center gap-1.5 pl-1">
                                      <span
                                        className={`text-[9px] uppercase tracking-wider hidden sm:inline ${
                                          t.monitored ? 'text-[#e5a00d]' : 'text-neutral-500'
                                        }`}
                                      >
                                        {t.monitored ? 'Monitored' : 'Unmonitored'}
                                      </span>
                                      <TactileSwitch
                                        checked={t.monitored}
                                        onChange={() =>
                                          handleToggleTrackInDetail(t.id, album.id, t.monitored)
                                        }
                                        label={t.monitored ? 'Monitored' : 'Unmonitored'}
                                      />
                                    </div>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <p className="text-xs text-neutral-500 font-mono py-4 text-center">
                          No tracks registered for this album.
                        </p>
                      )}
                    </div>
                  )}
                </MachinedCard>
              );
            })}

            {currentAlbums.length === 0 && (
              <div className="text-center py-12 text-neutral-500 font-mono text-sm">
                No releases categorized under this tab.
              </div>
            )}
          </div>
        )}

        {/* Add Album to Collection Modal (Artist Drilldown) */}
        <ObsidianModal
          isOpen={albumToAddToCollection !== null}
          onClose={() => setAlbumToAddToCollection(null)}
          title="Add to Collection"
          subtitle={`Select a collection to add "${albumToAddToCollection?.title}"`}
        >
          <div className="space-y-3">
            {isLoadingModalCollections ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 text-[#e5a00d] animate-spin" />
              </div>
            ) : allCollectionsForModal.length > 0 ? (
              <div className="divide-y divide-[#222] border border-[#262626] rounded-[4px] max-h-80 overflow-y-auto bg-[#141414]">
                {allCollectionsForModal.map((col) => (
                  <div
                    key={col.id}
                    onClick={() => handleAddAlbumToCollection(col.id, col.name)}
                    className="p-3 flex items-center justify-between gap-3 hover:bg-[#1c1c1c] cursor-pointer transition-colors"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <Layers className="h-4 w-4 text-[#e5a00d] flex-shrink-0" />
                      <div className="min-w-0">
                        <h4 className="text-sm font-bold text-white truncate">{col.name}</h4>
                        {col.summary && (
                          <p className="text-xs text-neutral-400 truncate">{col.summary}</p>
                        )}
                      </div>
                    </div>
                    <span className="text-[10px] font-mono text-neutral-400 bg-neutral-800 px-2 py-0.5 rounded-[2px] flex-shrink-0">
                      {col.album_count || 0} Albums
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-neutral-500 font-mono text-xs">
                No collections available. Create one in the Collections tab first.
              </div>
            )}
          </div>
        </ObsidianModal>
      </div>
    );
  }

  // Render Collection Detail Drilldown View
  if (selectedCollectionId !== null) {
    const col = selectedCollection || collections.find((c) => c.id === selectedCollectionId);
    return (
      <div className="space-y-6">
        {/* Toast Notification */}
        {toastMessage && (
          <div className="fixed top-20 right-4 z-50 bg-[#161616] border border-[#e5a00d] px-4 py-2.5 rounded-[4px] text-xs font-mono text-[#e5a00d] shadow-lg flex items-center gap-2">
            <Check className="h-4 w-4" />
            <span>{toastMessage}</span>
          </div>
        )}

        {/* Back Button */}
        <div className="flex items-center justify-between">
          <TapeDeckButton
            size="sm"
            onClick={() => {
              setSelectedCollectionId(null);
              setSelectedCollection(null);
            }}
            icon={<ArrowLeft className="h-4 w-4" />}
          >
            Back to Collections
          </TapeDeckButton>

          {isAdmin && col && (
            <TapeDeckButton
              size="sm"
              variant="danger"
              onClick={() => handleDeleteCollection(col.id, col.name)}
              icon={<Trash2 className="h-3.5 w-3.5" />}
            >
              Delete Collection
            </TapeDeckButton>
          )}
        </div>

        {/* Collection Hero Header */}
        <MachinedCard className="p-6">
          <div className="flex flex-col sm:flex-row items-center sm:items-start gap-6">
            <div className="h-32 w-32 rounded-[4px] bg-[#1a1a1a] border border-[#2a2a2a] overflow-hidden flex-shrink-0 flex items-center justify-center shadow-xl">
              {col?.poster_url ? (
                <img src={col.poster_url} alt={col.name} className="w-full h-full object-cover" />
              ) : col?.preview_covers && col.preview_covers.length > 0 ? (
                <div className="w-full h-full grid grid-cols-2 gap-0.5 bg-[#1f1f1f] p-0.5">
                  {col.preview_covers.slice(0, 4).map((c, idx) => (
                    <img key={idx} src={c} alt="" className="w-full h-full object-cover" />
                  ))}
                  {Array.from({ length: Math.max(0, 4 - col.preview_covers.length) }).map((_, idx) => (
                    <div key={`empty-${idx}`} className="w-full h-full bg-[#161616] flex items-center justify-center">
                      <Disc className="h-4 w-4 text-neutral-700" />
                    </div>
                  ))}
                </div>
              ) : (
                <Layers className="h-16 w-16 text-neutral-600" />
              )}
            </div>

            <div className="flex-1 text-center sm:text-left space-y-2 min-w-0">
              <span className="text-[10px] font-mono uppercase tracking-widest text-[#e5a00d]">
                Collection Drilldown
              </span>
              <h2 className="text-2xl sm:text-3xl font-black text-white font-mono tracking-tight truncate">
                {col?.name}
              </h2>
              {col?.summary && (
                <p className="text-xs text-neutral-300 font-mono">{col.summary}</p>
              )}
              <div className="flex items-center justify-center sm:justify-start gap-3 pt-1">
                <span className="px-2.5 py-0.5 rounded-[2px] text-xs font-mono font-bold bg-[#e5a00d]/10 text-[#e5a00d] border border-[#e5a00d]/30">
                  {col?.album_count ?? col?.albums?.length ?? 0} Albums
                </span>
              </div>
            </div>
          </div>
        </MachinedCard>

        {/* Albums list in collection */}
        {isLoadingCollection ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <Loader2 className="h-8 w-8 text-[#e5a00d] animate-spin" />
            <span className="text-xs uppercase tracking-widest text-neutral-400 font-mono">
              Loading Collection Albums...
            </span>
          </div>
        ) : (
          <div className="space-y-3">
            <h3 className="text-sm font-mono uppercase tracking-wider text-neutral-400">
              Included Albums ({col?.albums?.length || 0})
            </h3>
            {col?.albums && col.albums.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {col.albums.map((alb) => (
                  <MachinedCard key={alb.id} className="p-4 flex flex-col justify-between gap-3 group">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="h-12 w-12 rounded-[3px] bg-[#1a1a1a] border border-[#2a2a2a] overflow-hidden flex-shrink-0 flex items-center justify-center">
                        {alb.cover_url ? (
                          <img src={alb.cover_url} alt={alb.title} className="w-full h-full object-cover" />
                        ) : (
                          <Disc className="h-6 w-6 text-neutral-600" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <h4 className="font-bold text-sm text-white truncate" title={alb.title}>
                          {alb.title}
                        </h4>
                        <p className="text-xs text-neutral-400 truncate mt-0.5">
                          {alb.artist_name || 'Unknown Artist'} {alb.release_date ? `(${alb.release_date.slice(0, 4)})` : ''}
                        </p>
                      </div>
                    </div>

                    <div className="pt-2 border-t border-[#1f1f1f] flex items-center justify-end">
                      <TapeDeckButton
                        size="sm"
                        variant="danger"
                        onClick={() => handleRemoveAlbumFromCollection(col.id, alb.id)}
                        icon={<Trash2 className="h-3.5 w-3.5" />}
                        title="Remove from collection"
                      >
                        Remove
                      </TapeDeckButton>
                    </div>
                  </MachinedCard>
                ))}
              </div>
            ) : (
              <div className="text-center py-12 text-neutral-500 font-mono text-sm border border-dashed border-[#222] rounded-[4px]">
                No albums in this collection yet. Drill down into an artist to add albums.
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  // Main Library View (Artists / Albums / Tracks with Pagination)
  return (
    <div className="space-y-6">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-20 right-4 z-50 bg-[#161616] border border-[#e5a00d] px-4 py-2.5 rounded-[4px] text-xs font-mono text-[#e5a00d] shadow-lg flex items-center gap-2">
          <Check className="h-4 w-4" />
          <span>{toastMessage}</span>
        </div>
      )}

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

      {/* Live Scan Telemetry Banner */}
      {(isScanning || scanStatus?.is_scanning) && (
        <MachinedCard className="p-4 border-[#e5a00d]/50 bg-[#161616]/90 shadow-lg space-y-2.5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <RefreshCw className="h-5 w-5 text-[#e5a00d] animate-spin flex-shrink-0" />
              <div>
                <h4 className="text-sm font-bold text-white font-mono flex items-center gap-2">
                  <span>Library Scan In Progress</span>
                  <span className="text-xs text-[#e5a00d] font-normal">
                    {scanStatus?.processed_files || 0} / {scanStatus?.total_files_found || 0} files ({Math.round(((scanStatus?.processed_files || 0) / Math.max(1, scanStatus?.total_files_found || 1)) * 100)}%)
                  </span>
                </h4>
                <p className="text-xs text-neutral-300 font-mono mt-0.5">
                  {scanStatus?.artists_created || 0} artists &bull; {scanStatus?.albums_created || 0} albums &bull; {scanStatus?.files_indexed || 0} files indexed
                </p>
              </div>
            </div>

            <TapeDeckButton
              size="sm"
              variant="danger"
              onClick={cancelScan}
              className="self-start sm:self-center flex-shrink-0"
            >
              Cancel Scan
            </TapeDeckButton>
          </div>

          {scanStatus?.current_file && (
            <p className="truncate font-mono text-[10px] text-neutral-400">
              {scanStatus.current_file}
            </p>
          )}
        </MachinedCard>
      )}

      {/* Tab Bar / Actions */}
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

      {/* Lidarr Migration Panel (if present) */}
      {lidarrStatus && lidarrStatus.is_migrating && (
        <div className="p-3 bg-[#151515] border border-blue-800/60 rounded-[4px] flex items-center gap-3 text-xs font-mono">
          <HardDrive className="h-4 w-4 text-blue-400 animate-spin" />
          <span className="text-blue-300">
            Lidarr Migration Active: {lidarrStatus.migrated_artists} of {lidarrStatus.total_artists}{' '}
            artists migrated ({lidarrStatus.progress}%)
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

      {/* Artists Tab (Spotify + Lidarr Hybrid Cards with Artwork) */}
      {!isLoading && activeTab === 'artists' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {(paginatedItems as ArtistItem[]).map((artist) => (
              <MachinedCard
                key={artist.id}
                interactive
                onClick={() => setSelectedArtistId(artist.id)}
                className="p-4 flex flex-col justify-between gap-3 group"
              >
                <div className="flex items-center gap-3">
                  <div className="h-14 w-14 rounded-[3px] bg-[#1a1a1a] border border-[#2a2a2a] overflow-hidden flex-shrink-0 flex items-center justify-center shadow-md">
                    {artist.image_url ? (
                      <img
                        src={artist.image_url}
                        alt={artist.name}
                        className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                        loading="lazy"
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).src = '/placeholder.svg';
                        }}
                      />
                    ) : (
                      <User className="h-7 w-7 text-neutral-600" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <h4
                      className="font-bold text-sm text-white truncate group-hover:text-[#e5a00d] transition-colors"
                      title={artist.name}
                    >
                      {artist.name}
                    </h4>
                    <p className="text-xs text-neutral-400 font-mono mt-0.5">
                      {artist.album_count || 0} Albums &bull; {artist.track_count || 0} Tracks
                    </p>
                  </div>
                </div>

                <div
                  className="pt-2 border-t border-[#1f1f1f] flex items-center justify-between"
                  onClick={(e) => e.stopPropagation()}
                >
                  <span
                    className={`text-[10px] font-mono uppercase tracking-wider ${
                      artist.monitored ? 'text-[#e5a00d]' : 'text-neutral-500'
                    }`}
                  >
                    {artist.monitored ? 'Monitored' : 'Unmonitored'}
                  </span>
                  {isAdmin && (
                    <TactileSwitch
                      checked={artist.monitored}
                      onChange={(val) => toggleArtistMonitored(artist.id, val)}
                      label={artist.monitored ? 'Monitored' : 'Unmonitored'}
                      title={
                        artist.monitored
                          ? 'TrackSeerr will autonomously monitor and grab new releases'
                          : 'Unmonitored: will not automatically grab releases'
                      }
                    />
                  )}
                </div>
              </MachinedCard>
            ))}
          </div>

          {totalItems === 0 && (
            <div className="text-center py-12 text-neutral-500 font-mono text-sm">
              No artists found in library.
            </div>
          )}
        </div>
      )}

      {/* Albums Tab */}
      {!isLoading && activeTab === 'albums' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {(paginatedItems as AlbumItem[]).map((album) => (
              <MachinedCard
                key={album.id}
                interactive
                onClick={() => handleOpenAlbumModal(album)}
                className="p-4 flex flex-col justify-between gap-3 group"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="h-12 w-12 rounded-[3px] bg-[#1a1a1a] border border-[#2a2a2a] overflow-hidden flex-shrink-0 flex items-center justify-center">
                    {album.cover_url ? (
                      <img
                        src={album.cover_url}
                        alt={album.title}
                        className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                        loading="lazy"
                      />
                    ) : (
                      <Disc className="h-6 w-6 text-neutral-600" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <h4
                      className="font-bold text-sm text-white truncate group-hover:text-[#e5a00d] transition-colors"
                      title={album.title}
                    >
                      {album.title}
                    </h4>
                    <p className="text-xs text-neutral-400 truncate mt-0.5" title={album.artist_name}>
                      {album.artist_name || 'Unknown Artist'}
                    </p>
                  </div>
                </div>

                <div
                  className="pt-2 border-t border-[#1f1f1f] flex items-center justify-between"
                  onClick={(e) => e.stopPropagation()}
                >
                  <span
                    className={`text-[10px] font-mono uppercase tracking-wider hidden sm:inline ${
                      album.monitored ? 'text-[#e5a00d]' : 'text-neutral-500'
                    }`}
                  >
                    {album.monitored ? 'Monitored' : 'Unmonitored'}
                  </span>
                  <div className="flex items-center gap-2">
                    <TapeDeckButton
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleOpenAddToCollection(album);
                      }}
                      icon={<BookmarkPlus className="h-3.5 w-3.5 text-[#e5a00d]" />}
                      title="Add to Collection"
                    />
                    {isAdmin && (
                      <TactileSwitch
                        checked={album.monitored}
                        onChange={(val) => toggleAlbumMonitored(album.id, val)}
                        label={album.monitored ? 'Monitored' : 'Unmonitored'}
                        title={
                          album.monitored
                            ? 'TrackSeerr will autonomously monitor and grab new releases'
                            : 'Unmonitored: will not automatically grab releases'
                        }
                      />
                    )}
                  </div>
                </div>
              </MachinedCard>
            ))}
          </div>

          {totalItems === 0 && (
            <div className="text-center py-12 text-neutral-500 font-mono text-sm">
              No albums found in library.
            </div>
          )}
        </div>
      )}

      {/* Tracks Tab */}
      {!isLoading && activeTab === 'tracks' && (
        <div className="space-y-4">
          <div className="divide-y divide-[#1f1f1f] border border-[#222222] rounded-[4px] bg-[#121212] overflow-hidden">
            {(paginatedItems as TrackItem[]).map((track) => {
              const badge = getQualityBadge(track);
              return (
                <div
                  key={track.id}
                  className="p-3 flex items-center justify-between gap-4 hover:bg-[#181818] transition-colors"
                >
                  <div className="min-w-0 flex-1">
                    <h4 className="font-bold text-sm text-neutral-200 truncate" title={track.title}>
                      {track.title}
                    </h4>
                    <p className="text-xs text-neutral-400 truncate font-mono mt-0.5">
                      {track.file_path || 'No audio file linked'}
                    </p>
                  </div>

                  <div className="flex items-center gap-3 flex-shrink-0">
                    <span
                      className={`px-2 py-0.5 rounded-[2px] text-[10px] font-mono font-bold ${badge.className}`}
                    >
                      {badge.label}
                    </span>

                    <div className="flex items-center gap-2">
                      <span
                        className={`text-[10px] font-mono uppercase tracking-wider hidden sm:inline ${
                          track.monitored ? 'text-[#e5a00d]' : 'text-neutral-500'
                        }`}
                      >
                        {track.monitored ? 'Monitored' : 'Unmonitored'}
                      </span>
                      {isAdmin && (
                        <TactileSwitch
                          checked={track.monitored}
                          onChange={(val) => toggleTrackMonitored(track.id, val)}
                          label={track.monitored ? 'Monitored' : 'Unmonitored'}
                          title={
                            track.monitored
                              ? 'TrackSeerr will autonomously monitor and grab track releases'
                              : 'Unmonitored'
                          }
                        />
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
            {totalItems === 0 && (
              <div className="p-8 text-center text-neutral-500 font-mono text-sm">
                No tracks found in library.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Collections Tab */}
      {!isLoading && activeTab === 'collections' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-[#1f1f1f]">
            <span className="text-xs font-mono uppercase tracking-wider text-neutral-400">
              Custom Collections ({totalItems})
            </span>
            {isAdmin && (
              <TapeDeckButton
                size="sm"
                variant="amber"
                onClick={() => setIsCreateCollectionOpen(true)}
                icon={<Plus className="h-3.5 w-3.5" />}
              >
                New Collection
              </TapeDeckButton>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {(paginatedItems as CollectionItem[]).map((col) => (
              <MachinedCard
                key={col.id}
                className="p-4 flex flex-col justify-between gap-3 cursor-pointer group hover:border-[#e5a00d]/50 transition-colors"
                onClick={() => setSelectedCollectionId(col.id)}
              >
                <div>
                  <div className="h-44 w-full rounded-[3px] bg-[#1a1a1a] border border-[#2a2a2a] overflow-hidden flex items-center justify-center mb-3">
                    {col.poster_url ? (
                      <img
                        src={col.poster_url}
                        alt={col.name}
                        className="w-full h-full object-cover"
                        loading="lazy"
                      />
                    ) : col.preview_covers && col.preview_covers.length > 0 ? (
                      <div className="w-full h-full grid grid-cols-2 gap-0.5 bg-[#141414] p-0.5">
                        {col.preview_covers.slice(0, 4).map((c, idx) => (
                          <img key={idx} src={c} alt="" className="w-full h-full object-cover" />
                        ))}
                        {Array.from({ length: Math.max(0, 4 - col.preview_covers.length) }).map(
                          (_, idx) => (
                            <div
                              key={`empty-${idx}`}
                              className="w-full h-full bg-[#181818] flex items-center justify-center"
                            >
                              <Disc className="h-4 w-4 text-neutral-700" />
                            </div>
                          )
                        )}
                      </div>
                    ) : (
                      <Layers className="h-12 w-12 text-neutral-600 group-hover:text-[#e5a00d] transition-colors" />
                    )}
                  </div>

                  <h4 className="font-bold text-sm text-white truncate" title={col.name}>
                    {col.name}
                  </h4>
                  {col.summary && (
                    <p className="text-xs text-neutral-400 line-clamp-2 mt-1 font-mono">
                      {col.summary}
                    </p>
                  )}
                </div>

                <div className="pt-2 border-t border-[#1f1f1f] flex items-center justify-between">
                  <span className="text-[10px] font-mono text-[#e5a00d] bg-[#e5a00d]/10 px-2 py-0.5 rounded-[2px] border border-[#e5a00d]/20">
                    {col.album_count || 0} Albums
                  </span>
                  {isAdmin && (
                    <TapeDeckButton
                      size="sm"
                      variant="danger"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteCollection(col.id, col.name);
                      }}
                      icon={<Trash2 className="h-3 w-3" />}
                      title="Delete Collection"
                    />
                  )}
                </div>
              </MachinedCard>
            ))}
          </div>

          {totalItems === 0 && (
            <div className="text-center py-12 text-neutral-500 font-mono text-sm">
              No collections found. Click &quot;New Collection&quot; to build your first playlist or box set collection.
            </div>
          )}
        </div>
      )}

      {/* Pagination Toolbar */}
      {!isLoading && totalItems > pageSize && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-4 border-t border-[#1f1f1f] text-xs font-mono">
          <span className="text-neutral-400">
            Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, totalItems)} of {totalItems} items
          </span>
          <div className="flex items-center gap-2">
            <TapeDeckButton
              size="sm"
              disabled={page <= 1}
              onClick={() => {
                setPage((p) => Math.max(1, p - 1));
                window.scrollTo({ top: 0, behavior: 'smooth' });
              }}
              icon={<ChevronLeft className="h-3.5 w-3.5" />}
            >
              Previous
            </TapeDeckButton>
            <span className="text-neutral-300 px-2">
              Page {page} of {totalPages}
            </span>
            <TapeDeckButton
              size="sm"
              disabled={page >= totalPages}
              onClick={() => {
                setPage((p) => Math.min(totalPages, p + 1));
                window.scrollTo({ top: 0, behavior: 'smooth' });
              }}
              icon={<ChevronRight className="h-3.5 w-3.5" />}
            >
              Next
            </TapeDeckButton>
          </div>
        </div>
      )}

      {/* Create Collection Modal */}
      <ObsidianModal
        isOpen={isCreateCollectionOpen}
        onClose={() => setIsCreateCollectionOpen(false)}
        title="Create Collection"
        subtitle="Organize albums into custom playlists, box sets, or anthologies"
        footer={
          <div className="flex items-center justify-end gap-2">
            <TapeDeckButton
              size="sm"
              onClick={() => setIsCreateCollectionOpen(false)}
            >
              Cancel
            </TapeDeckButton>
            <TapeDeckButton
              size="sm"
              variant="amber"
              disabled={!newColName.trim() || isCreatingCollection}
              onClick={() => handleCreateCollection()}
              icon={
                isCreatingCollection ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Plus className="h-3.5 w-3.5" />
                )
              }
            >
              Create Collection
            </TapeDeckButton>
          </div>
        }
      >
        <form onSubmit={handleCreateCollection} className="space-y-4">
          <div>
            <label className="block text-xs font-mono uppercase tracking-wider text-neutral-400 mb-1">
              Collection Name *
            </label>
            <input
              type="text"
              value={newColName}
              onChange={(e) => setNewColName(e.target.value)}
              placeholder="e.g. 90s Grunge Essentials"
              required
              className="w-full bg-[#181818] border border-[#2e2e2e] focus:border-[#e5a00d] rounded-[3px] px-3 py-2 text-sm text-white placeholder-neutral-500 outline-none font-mono"
            />
          </div>

          <div>
            <label className="block text-xs font-mono uppercase tracking-wider text-neutral-400 mb-1">
              Summary / Notes (Optional)
            </label>
            <textarea
              value={newColSummary}
              onChange={(e) => setNewColSummary(e.target.value)}
              placeholder="Brief description of this collection..."
              rows={3}
              className="w-full bg-[#181818] border border-[#2e2e2e] focus:border-[#e5a00d] rounded-[3px] px-3 py-2 text-sm text-white placeholder-neutral-500 outline-none font-mono resize-none"
            />
          </div>

          <div>
            <label className="block text-xs font-mono uppercase tracking-wider text-neutral-400 mb-1">
              Poster URL (Optional)
            </label>
            <input
              type="url"
              value={newColPosterUrl}
              onChange={(e) => setNewColPosterUrl(e.target.value)}
              placeholder="https://... (Leave blank to use 2x2 collage of album covers)"
              className="w-full bg-[#181818] border border-[#2e2e2e] focus:border-[#e5a00d] rounded-[3px] px-3 py-2 text-sm text-white placeholder-neutral-500 outline-none font-mono"
            />
          </div>
        </form>
      </ObsidianModal>

      {/* Add Album to Collection Modal (Main View) */}
      <ObsidianModal
        isOpen={albumToAddToCollection !== null}
        onClose={() => setAlbumToAddToCollection(null)}
        title="Add to Collection"
        subtitle={`Select a collection to add "${albumToAddToCollection?.title}"`}
      >
        <div className="space-y-3">
          {isLoadingModalCollections ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 text-[#e5a00d] animate-spin" />
            </div>
          ) : allCollectionsForModal.length > 0 ? (
            <div className="divide-y divide-[#222] border border-[#262626] rounded-[4px] max-h-80 overflow-y-auto bg-[#141414]">
              {allCollectionsForModal.map((col) => (
                <div
                  key={col.id}
                  onClick={() => handleAddAlbumToCollection(col.id, col.name)}
                  className="p-3 flex items-center justify-between gap-3 hover:bg-[#1c1c1c] cursor-pointer transition-colors"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Layers className="h-4 w-4 text-[#e5a00d] flex-shrink-0" />
                    <div className="min-w-0">
                      <h4 className="text-sm font-bold text-white truncate">{col.name}</h4>
                      {col.summary && (
                        <p className="text-xs text-neutral-400 truncate">{col.summary}</p>
                      )}
                    </div>
                  </div>
                  <span className="text-[10px] font-mono text-neutral-400 bg-neutral-800 px-2 py-0.5 rounded-[2px] flex-shrink-0">
                    {col.album_count || 0} Albums
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-neutral-500 font-mono text-xs">
              No collections available. Create one in the Collections tab first.
            </div>
          )}
        </div>
      </ObsidianModal>

      {/* Album Detail & Tracklist Modal (Albums Tab) */}
      <ObsidianModal
        isOpen={selectedAlbumForModal !== null}
        onClose={() => setSelectedAlbumForModal(null)}
        title="Album Details"
        subtitle={
          selectedAlbumForModal
            ? `${selectedAlbumForModal.title}${
                selectedAlbumForModal.artist_name
                  ? ` • ${selectedAlbumForModal.artist_name}`
                  : ''
              }`
            : undefined
        }
        footer={
          <div className="flex flex-wrap items-center justify-between w-full gap-2">
            <div className="flex items-center gap-2">
              <TapeDeckButton
                size="sm"
                onClick={() => {
                  if (selectedAlbumForModal) {
                    handleOpenAddToCollection(selectedAlbumForModal);
                  }
                }}
                icon={<BookmarkPlus className="h-3.5 w-3.5 text-[#e5a00d]" />}
              >
                Collect
              </TapeDeckButton>
              <TapeDeckButton
                size="sm"
                onClick={() => {
                  if (selectedAlbumForModal) {
                    const artistId = selectedAlbumForModal.artist_id;
                    setSelectedAlbumForModal(null);
                    setSelectedArtistId(artistId);
                  }
                }}
                icon={<User className="h-3.5 w-3.5" />}
              >
                Go to Artist
              </TapeDeckButton>
            </div>
            <TapeDeckButton
              size="sm"
              onClick={() => setSelectedAlbumForModal(null)}
            >
              Close
            </TapeDeckButton>
          </div>
        }
      >
        {selectedAlbumForModal && (
          <div className="space-y-4">
            {/* Header: Album cover thumbnail, title, artist name, year, genre, and total tracks */}
            <div className="flex items-center gap-4 p-3 bg-[#181818] border border-[#262626] rounded-[4px]">
              <div className="h-16 w-16 sm:h-20 sm:w-20 rounded-[3px] bg-[#1a1a1a] border border-[#2a2a2a] overflow-hidden flex-shrink-0 flex items-center justify-center shadow-md">
                {selectedAlbumForModal.cover_url ? (
                  <img
                    src={selectedAlbumForModal.cover_url}
                    alt={selectedAlbumForModal.title}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <Disc className="h-8 w-8 text-neutral-600" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <h3
                  className="text-base sm:text-lg font-bold text-white truncate font-mono"
                  title={selectedAlbumForModal.title}
                >
                  {selectedAlbumForModal.title}
                </h3>
                <button
                  type="button"
                  onClick={() => {
                    const artistId = selectedAlbumForModal.artist_id;
                    setSelectedAlbumForModal(null);
                    setSelectedArtistId(artistId);
                  }}
                  className="text-sm text-[#e5a00d] hover:underline truncate block font-mono text-left"
                  title="View Artist Discography"
                >
                  {selectedAlbumForModal.artist_name || 'Unknown Artist'}
                </button>
                <div className="flex flex-wrap items-center gap-2 pt-1 text-xs font-mono text-neutral-400">
                  <span>
                    {selectedAlbumForModal.release_date
                      ? selectedAlbumForModal.release_date.slice(0, 4)
                      : 'Unknown Year'}
                  </span>
                  {selectedAlbumForModal.genres &&
                    selectedAlbumForModal.genres.length > 0 && (
                      <>
                        <span>&bull;</span>
                        <span className="px-1.5 py-0.5 rounded-[2px] text-[10px] bg-[#e5a00d]/10 text-[#e5a00d] border border-[#e5a00d]/30">
                          {Array.isArray(selectedAlbumForModal.genres)
                            ? selectedAlbumForModal.genres.join(', ')
                            : selectedAlbumForModal.genres}
                        </span>
                      </>
                    )}
                  <span>&bull;</span>
                  <span>
                    {selectedAlbumForModal.tracks?.length ??
                      selectedAlbumForModal.track_count ??
                      0}{' '}
                    Tracks
                  </span>
                </div>
              </div>
            </div>

            {/* Body: Loading indicator or scrollable tracklist table/list */}
            {isLoadingAlbumModal ? (
              <div className="flex flex-col items-center justify-center py-12 gap-2">
                <Loader2 className="h-8 w-8 text-[#e5a00d] animate-spin" />
                <span className="text-xs uppercase tracking-widest text-neutral-400 font-mono">
                  Loading Album Tracks...
                </span>
              </div>
            ) : selectedAlbumForModal.tracks &&
              selectedAlbumForModal.tracks.length > 0 ? (
              <div className="divide-y divide-[#181818] border border-[#1f1f1f] rounded-[3px] overflow-hidden bg-[#0d0d0d] max-h-80 overflow-y-auto">
                {selectedAlbumForModal.tracks.map((t) => {
                  const badge = getQualityBadge(t);
                  return (
                    <div
                      key={t.id}
                      className="p-2.5 flex items-center justify-between gap-3 hover:bg-[#141414] transition-colors"
                    >
                      <div className="flex items-center gap-3 min-w-0 flex-1">
                        <span className="font-mono text-xs text-neutral-500 w-6 text-right flex-shrink-0">
                          {t.track_number || 1}
                        </span>
                        <span
                          className="text-sm text-neutral-200 min-w-0 flex-1 truncate"
                          title={t.title}
                        >
                          {t.title}
                        </span>
                      </div>

                      <div className="flex items-center gap-3 flex-shrink-0 font-mono text-xs">
                        <span className="text-neutral-500 hidden sm:inline">
                          {formatTrackDuration(t.duration_ms)}
                        </span>

                        {/* Quality Badge */}
                        <span
                          className={`px-2 py-0.5 rounded-[2px] text-[10px] font-bold ${badge.className}`}
                        >
                          {badge.label}
                        </span>

                        {/* Track Monitoring Toggle */}
                        {isAdmin && (
                          <div className="flex items-center gap-1.5 pl-1">
                            <span
                              className={`text-[9px] uppercase tracking-wider hidden sm:inline ${
                                t.monitored ? 'text-[#e5a00d]' : 'text-neutral-500'
                              }`}
                            >
                              {t.monitored ? 'Monitored' : 'Unmonitored'}
                            </span>
                            <TactileSwitch
                              checked={t.monitored}
                              onChange={() =>
                                handleToggleTrackInModal(t.id, t.monitored)
                              }
                              label={t.monitored ? 'Monitored' : 'Unmonitored'}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-neutral-500 font-mono py-8 text-center">
                No tracks registered for this album.
              </p>
            )}
          </div>
        )}
      </ObsidianModal>
    </div>
  );
};
