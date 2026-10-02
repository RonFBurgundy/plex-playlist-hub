import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Loader2, LogIn } from 'lucide-react';
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
  AudioPlayerBar,
  DiscoverView,
  RequestsView,
  LibraryView,
  PlaylistsView,
  ActivityView,
  SettingsView,
  ObsidianModal,
  TapeDeckButton,
  MachinedCard,
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
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const mainRef = useRef<HTMLElement | null>(null);

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
      setIsAuthModalOpen(false);
      loadPlaylistsAndUsers();
    }
  }, [auth.isAuthenticated, loadPlaylistsAndUsers]);

  const handleTabChange = (tab: MainTab) => {
    setActiveTab(tab);
    if (mainRef.current) {
      mainRef.current.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

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
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-[#0a0a0a] text-white selection:bg-[#e5a00d] selection:text-black">
      {/* Sticky Header with integrated navigation */}
      <Header
        user={auth.user}
        quota={requestsHook.quota}
        activeTab={activeTab}
        onTabChange={handleTabChange}
        isAdmin={auth.isAdmin}
        onLogin={() => setIsAuthModalOpen(true)}
        onLogout={auth.logout}
      />

      {/* Main Content Area - Locked scrolling inside container */}
      <main
        ref={mainRef}
        className="flex-1 min-h-0 overflow-y-auto overscroll-y-contain px-4 sm:px-6 py-4 pb-28"
      >
        {auth.isLoading ? (
          <div className="flex flex-col items-center justify-center py-28 gap-3">
            <Loader2 className="h-8 w-8 text-[#e5a00d] animate-spin" />
            <span className="text-xs uppercase tracking-widest text-neutral-400 font-mono">
              Calibrating Analog Deck...
            </span>
          </div>
        ) : !auth.isAuthenticated ? (
          /* Landing Hero for Unauthenticated Visitors */
          <div className="flex-1 min-h-full flex items-center justify-center p-4 relative">
            <div className="absolute w-72 h-72 bg-[#e5a00d]/10 rounded-full blur-3xl pointer-events-none" />
            <MachinedCard className="max-w-md w-full p-8 text-center space-y-6 border-[#262626] bg-[#121212] relative z-10 shadow-2xl">
              <div className="w-20 h-20 rounded-[4px] bg-[#141414] border border-[#262626] flex items-center justify-center mx-auto shadow-xl">
                <img
                  src="/trackseerr-logo.svg"
                  alt="TrackSeerr"
                  className="w-16 h-16 object-contain"
                  onError={(e) => {
                    (e.currentTarget as HTMLImageElement).src = '/static/trackseerr-logo.svg';
                  }}
                />
              </div>
              <div className="space-y-1">
                <h2 className="text-2xl font-black tracking-tight text-white uppercase font-mono">
                  Track<span className="text-[#e5a00d]">Seerr</span>
                </h2>
                <p className="text-neutral-400 text-xs font-mono">Music Discovery &amp; Request Suite</p>
              </div>

              {auth.authError && (
                <div className="p-3 bg-red-950/40 border border-red-800 text-xs text-red-300 font-mono rounded-[4px]">
                  {auth.authError}
                </div>
              )}

              <div className="space-y-3 pt-2">
                {auth.isAuthenticating ? (
                  <div className="space-y-3">
                    <div className="flex items-center justify-center gap-2 text-xs font-mono text-[#e5a00d]">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>Connecting to Plex...</span>
                    </div>
                    <p className="text-[11px] text-neutral-400 font-mono">
                      Popup window opened. Complete sign-in in the Plex window.
                    </p>
                    <TapeDeckButton
                      size="md"
                      variant="default"
                      onClick={auth.cancelLogin}
                      className="w-full"
                    >
                      Cancel Sign In
                    </TapeDeckButton>
                  </div>
                ) : (
                  <TapeDeckButton
                    size="lg"
                    variant="amber"
                    onClick={auth.loginWithPlex}
                    icon={<LogIn className="h-5 w-5" />}
                    className="w-full"
                  >
                    Sign In with Plex
                  </TapeDeckButton>
                )}
              </div>
            </MachinedCard>
          </div>
        ) : (
          /* Authenticated Dashboard Views */
          <div className="max-w-7xl mx-auto w-full">
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
          </div>
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
            <div className="h-16 w-16 rounded-[4px] bg-[#141414] border border-[#262626] flex items-center justify-center shadow-lg">
              <img
                src="/trackseerr-logo.svg"
                alt="TrackSeerr"
                className="h-14 w-14 object-contain mx-auto"
                onError={(e) => {
                  (e.currentTarget as HTMLImageElement).src = '/static/trackseerr-logo.svg';
                }}
              />
            </div>
          </div>

          <div className="space-y-1">
            <h4 className="font-bold text-base text-white">Authorize with Plex</h4>
            <p className="text-xs text-neutral-400 max-w-sm mx-auto font-mono">
              Sign in with your plex.tv credentials to manage playlists, browse recommendations,
              and submit music requests.
            </p>
          </div>

          {auth.authError && (
            <div className="p-3 bg-red-950/40 border border-red-800 text-xs text-red-300 font-mono rounded-[4px]">
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

