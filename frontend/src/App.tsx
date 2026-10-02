import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, LogIn, Disc } from 'lucide-react';
import type { Playlist, User } from '@/types/models';
import {
  useAuth,
  useAudioPlayer,
  useDiscovery,
  useRequests,
  useLibrary,
  useQueue,
} from '@/hooks';
import {
  Header,
  Navigation,
  MobileDrawer,
  AudioPlayerBar,
  DiscoverView,
  RequestsView,
  LibraryView,
  PlaylistsView,
  ActivityView,
  SettingsView,
  ObsidianModal,
  TapeDeckButton,
} from '@/components';
import type { MainTab } from '@/components/layout/Navigation';
import {
  getPlaylists,
  toggleUserTarget,
  togglePlaylistActive,
  deletePlaylist,
  triggerSync,
  importPlaylist,
} from '@/services/playlistService';
import { apiRequest } from '@/services/apiClient';

export const App: React.FC = () => {
  const auth = useAuth();
  const audioPlayer = useAudioPlayer();
  const discovery = useDiscovery();
  const requestsHook = useRequests();
  const libraryHook = useLibrary();
  const queueHook = useQueue();

  const [activeTab, setActiveTab] = useState<MainTab>('discover');
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState<boolean>(false);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);

  // Playlists & users data
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [isPlaylistsLoading, setIsPlaylistsLoading] = useState<boolean>(false);

  // Set of requested IDs to update UI state
  const [requestedIds, setRequestedIds] = useState<Set<string>>(new Set());

  const loadPlaylistsAndUsers = useCallback(async () => {
    setIsPlaylistsLoading(true);
    try {
      const [plData, usrData] = await Promise.all([
        getPlaylists().catch(() => []),
        apiRequest<User[]>('/api/users').catch(() => []),
      ]);
      setPlaylists(plData);
      setUsers(usrData);
    } finally {
      setIsPlaylistsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (auth.isAuthenticated) {
      loadPlaylistsAndUsers();
    }
  }, [auth.isAuthenticated, loadPlaylistsAndUsers]);

  // Request an item from discovery
  const handleRequestItem = async (item: {
    id: string;
    title: string;
    artist: string;
    album?: string;
    cover_url?: string;
    type?: string;
  }) => {
    await requestsHook.submitRequest({
      title: item.title,
      artist: item.artist,
      album: item.album,
      cover_url: item.cover_url,
      type: item.type,
    });
    setRequestedIds((prev) => new Set([...prev, item.id]));
  };

  const handleSyncPlaylists = async () => {
    await triggerSync();
    await loadPlaylistsAndUsers();
  };

  const handleToggleTarget = async (playlistId: number | string, userIds: string[]) => {
    await toggleUserTarget(playlistId, userIds);
    await loadPlaylistsAndUsers();
  };

  const handleTogglePlaylistActive = async (playlistId: number | string, isEnabled: boolean) => {
    await togglePlaylistActive(playlistId, isEnabled);
    await loadPlaylistsAndUsers();
  };

  const handleDeletePlaylist = async (playlistId: number | string) => {
    await deletePlaylist(playlistId);
    await loadPlaylistsAndUsers();
  };

  const handleImportPlaylist = async (payload: {
    name: string;
    source_type: string;
    source_url?: string;
    tracks?: string[];
  }) => {
    await importPlaylist(payload);
    await loadPlaylistsAndUsers();
  };

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white flex flex-col selection:bg-[#e5a00d] selection:text-black">
      {/* Header */}
      <Header
        user={auth.user}
        quota={requestsHook.quota}
        isMobileMenuOpen={isMobileMenuOpen}
        onToggleMobileMenu={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
        onLogin={() => setIsAuthModalOpen(true)}
        onLogout={auth.logout}
      />

      {/* Primary Recessed Tape Deck Navigation */}
      <Navigation
        activeTab={activeTab}
        onTabChange={(tab) => {
          setActiveTab(tab);
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }}
        isAdmin={auth.isAdmin}
      />

      {/* Mobile Slide-over Drawer */}
      <MobileDrawer
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
        activeTab={activeTab}
        onTabChange={(tab) => {
          setActiveTab(tab);
          setIsMobileMenuOpen(false);
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }}
        user={auth.user}
        quota={requestsHook.quota}
        isAdmin={auth.isAdmin}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-6 pb-28">
        {auth.isLoading ? (
          <div className="flex flex-col items-center justify-center py-28 gap-3">
            <Loader2 className="h-8 w-8 text-[#e5a00d] animate-spin" />
            <span className="text-xs uppercase tracking-widest text-neutral-400 font-mono">
              Calibrating Analog Deck...
            </span>
          </div>
        ) : (
          <>
            {activeTab === 'discover' && (
              <DiscoverView
                discovery={discovery}
                onPlayTrack={audioPlayer.play}
                currentPreviewTrackId={audioPlayer.currentTrack?.id}
                isPreviewPlaying={audioPlayer.isPlaying}
                onRequest={handleRequestItem}
                requestedIds={requestedIds}
              />
            )}

            {activeTab === 'requests' && (
              <RequestsView
                requestsHook={requestsHook}
                isAdmin={auth.isAdmin}
              />
            )}

            {activeTab === 'library' && (
              <LibraryView
                libraryHook={libraryHook}
                isAdmin={auth.isAdmin}
              />
            )}

            {activeTab === 'playlists' && (
              <PlaylistsView
                playlists={playlists}
                users={users}
                currentUserId={typeof auth.user?.id === 'number' ? auth.user.id : undefined}
                onSync={handleSyncPlaylists}
                onToggleTarget={handleToggleTarget}
                onImport={handleImportPlaylist}
                onToggleActive={handleTogglePlaylistActive}
                onDelete={handleDeletePlaylist}
                isLoading={isPlaylistsLoading}
                isAdmin={auth.isAdmin}
              />
            )}

            {activeTab === 'activity' && (
              <ActivityView
                queueHook={queueHook}
                isAdmin={auth.isAdmin}
              />
            )}

            {activeTab === 'settings' && auth.isAdmin && (
              <SettingsView />
            )}
          </>
        )}
      </main>

      {/* Persistent Audio Player Bar */}
      <AudioPlayerBar
        currentTrack={audioPlayer.currentTrack}
        isPlaying={audioPlayer.isPlaying}
        progress={audioPlayer.progress}
        duration={audioPlayer.duration}
        currentTime={audioPlayer.currentTime}
        onToggle={audioPlayer.toggle}
        onStop={audioPlayer.stop}
        onSeek={audioPlayer.seek}
      />

      {/* Plex Sign-In Modal */}
      <ObsidianModal
        isOpen={isAuthModalOpen}
        onClose={() => {
          setIsAuthModalOpen(false);
          auth.cancelLogin();
        }}
        title="Sign In with Plex"
        subtitle="Authorize your account via Plex OAuth"
      >
        <div className="space-y-5 text-center py-4">
          <div className="flex justify-center">
            <div className="h-16 w-16 rounded-full bg-[#181818] border border-[#2a2a2a] flex items-center justify-center">
              <Disc className="h-8 w-8 text-[#e5a00d]" />
            </div>
          </div>

          <div className="space-y-1">
            <h4 className="font-bold text-base text-white">Authorize with Plex</h4>
            <p className="text-xs text-neutral-400 max-w-sm mx-auto">
              Sign in with your plex.tv credentials to manage playlists, browse recommendations,
              and submit music requests.
            </p>
          </div>

          {auth.authError && (
            <div className="p-3 bg-red-950/40 border border-red-800 text-xs text-red-300 font-mono rounded">
              {auth.authError}
            </div>
          )}

          <div className="flex flex-col items-center gap-3 pt-2">
            <TapeDeckButton
              size="lg"
              variant="amber"
              onClick={async () => {
                await auth.loginWithPlex();
              }}
              disabled={auth.isAuthenticating}
              icon={
                auth.isAuthenticating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <LogIn className="h-4 w-4" />
                )
              }
              className="w-full max-w-xs"
            >
              {auth.isAuthenticating ? 'Waiting for Plex...' : 'Authorize with Plex'}
            </TapeDeckButton>

            {auth.isAuthenticating && (
              <p className="text-[11px] text-neutral-500 font-mono animate-pulse">
                Popup open. Complete the sign-in prompt in the Plex window.
              </p>
            )}
          </div>
        </div>
      </ObsidianModal>
    </div>
  );
};

export default App;
