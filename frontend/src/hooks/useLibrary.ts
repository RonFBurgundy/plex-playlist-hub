import { useState, useEffect, useCallback, useRef } from 'react';
import type {
  ArtistItem,
  AlbumItem,
  TrackItem,
  CollectionItem,
  LibraryStats,
  ScanStatus,
  LidarrStatus,
} from '@/types/models';
import {
  getArtists,
  getAlbums,
  getTracks,
  getCollections,
  getLibraryStats,
  triggerScan as apiTriggerScan,
  getScanStatus as apiGetScanStatus,
  cancelScan as apiCancelScan,
  getLidarrStatus as apiGetLidarrStatus,
  toggleArtistMonitored as apiToggleArtistMonitored,
  toggleAlbumMonitored as apiToggleAlbumMonitored,
  toggleTrackMonitored as apiToggleTrackMonitored,
} from '@/services/libraryService';

export type LibraryTab = 'artists' | 'albums' | 'tracks' | 'collections';

export interface UseLibraryReturn {
  activeTab: LibraryTab;
  artists: ArtistItem[];
  albums: AlbumItem[];
  tracks: TrackItem[];
  collections: CollectionItem[];
  stats: LibraryStats | null;
  searchQuery: string;
  isScanning: boolean;
  scanStatus: ScanStatus | null;
  lidarrStatus: LidarrStatus | null;
  isLoading: boolean;
  error: string | null;
  setTab: (tab: LibraryTab) => void;
  setSearch: (query: string) => void;
  triggerScan: (pruneMissing?: boolean) => Promise<void>;
  cancelScan: () => Promise<void>;
  toggleArtistMonitored: (artistId: number | string, monitored: boolean) => Promise<void>;
  toggleAlbumMonitored: (albumId: number | string, monitored: boolean) => Promise<void>;
  toggleTrackMonitored: (trackId: number | string, monitored: boolean) => Promise<void>;
  refresh: () => Promise<void>;
}

export function useLibrary(): UseLibraryReturn {
  const [activeTab, setActiveTab] = useState<LibraryTab>('artists');
  const [artists, setArtists] = useState<ArtistItem[]>([]);
  const [albums, setAlbums] = useState<AlbumItem[]>([]);
  const [tracks, setTracks] = useState<TrackItem[]>([]);
  const [collections, setCollections] = useState<CollectionItem[]>([]);
  const [stats, setStats] = useState<LibraryStats | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isScanning, setIsScanning] = useState<boolean>(false);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [lidarrStatus, setLidarrStatus] = useState<LidarrStatus | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const scanPollRef = useRef<number | null>(null);

  const stopScanPolling = useCallback(() => {
    if (scanPollRef.current !== null) {
      window.clearInterval(scanPollRef.current);
      scanPollRef.current = null;
    }
  }, []);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [statsData, lidarrData] = await Promise.all([
        getLibraryStats().catch(() => null),
        apiGetLidarrStatus().catch(() => null),
      ]);
      if (statsData) setStats(statsData);
      if (lidarrData) setLidarrStatus(lidarrData);

      if (activeTab === 'artists') {
        const data = await getArtists(searchQuery);
        setArtists(data);
      } else if (activeTab === 'albums') {
        const data = await getAlbums(undefined, searchQuery);
        setAlbums(data);
      } else if (activeTab === 'tracks') {
        const data = await getTracks(undefined, undefined, searchQuery);
        setTracks(data);
      } else if (activeTab === 'collections') {
        const data = await getCollections(searchQuery);
        setCollections(data);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load library items';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [activeTab, searchQuery]);

  const loadDataRef = useRef(loadData);
  useEffect(() => {
    loadDataRef.current = loadData;
  }, [loadData]);

  const startScanPolling = useCallback(() => {
    stopScanPolling();
    scanPollRef.current = window.setInterval(async () => {
      try {
        const [status, statsData] = await Promise.all([
          apiGetScanStatus(),
          getLibraryStats().catch(() => null),
        ]);
        setScanStatus(status);
        if (statsData) {
          setStats(statsData);
        }

        const isCurrentlyScanning = Boolean(
          status.is_scanning || status.status === 'scanning' || status.status === 'running'
        );
        if (!isCurrentlyScanning) {
          setIsScanning(false);
          stopScanPolling();
          loadDataRef.current();
        }
      } catch {
        setIsScanning(false);
        stopScanPolling();
      }
    }, 1500);
  }, [stopScanPolling]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Check if a scan is already running on mount
  useEffect(() => {
    let isCancelled = false;
    const checkInitialScan = async () => {
      try {
        const status = await apiGetScanStatus();
        if (
          !isCancelled &&
          (status.is_scanning || status.status === 'scanning' || status.status === 'running')
        ) {
          setIsScanning(true);
          setScanStatus(status);
          startScanPolling();
        }
      } catch {
        // ignore error fetching initial scan status
      }
    };
    checkInitialScan();
    return () => {
      isCancelled = true;
    };
  }, [startScanPolling]);

  useEffect(() => {
    return () => {
      stopScanPolling();
    };
  }, [stopScanPolling]);

  const triggerScan = useCallback(
    async (pruneMissing: boolean = false) => {
      setError(null);
      setIsScanning(true);
      try {
        await apiTriggerScan(pruneMissing);
        startScanPolling();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Failed to trigger library scan';
        setError(msg);
        setIsScanning(false);
      }
    },
    [startScanPolling]
  );

  const cancelScan = useCallback(async () => {
    try {
      await apiCancelScan();
    } finally {
      setIsScanning(false);
      stopScanPolling();
      await loadData();
    }
  }, [loadData, stopScanPolling]);

  const toggleArtistMonitored = useCallback(
    async (artistId: number | string, monitored: boolean) => {
      await apiToggleArtistMonitored(artistId, monitored);
      setArtists((prev) =>
        prev.map((a) => (a.id === artistId ? { ...a, monitored } : a))
      );
    },
    []
  );

  const toggleAlbumMonitored = useCallback(
    async (albumId: number | string, monitored: boolean) => {
      await apiToggleAlbumMonitored(albumId, monitored);
      setAlbums((prev) =>
        prev.map((a) => (a.id === albumId ? { ...a, monitored } : a))
      );
    },
    []
  );

  const toggleTrackMonitored = useCallback(
    async (trackId: number | string, monitored: boolean) => {
      await apiToggleTrackMonitored(trackId, monitored);
      setTracks((prev) =>
        prev.map((t) => (t.id === trackId ? { ...t, monitored } : t))
      );
    },
    []
  );

  return {
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
    setTab: setActiveTab,
    setSearch: setSearchQuery,
    triggerScan,
    cancelScan,
    toggleArtistMonitored,
    toggleAlbumMonitored,
    toggleTrackMonitored,
    refresh: loadData,
  };
}
