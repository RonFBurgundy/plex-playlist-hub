/**
 * TrackSeerr - Alpine.js Application Controller & API Client
 * Zero-build, responsive single-page dashboard.
 */

document.addEventListener('alpine:init', () => {
  Alpine.data('plexHubApp', () => ({
    // Auth State
    isAuthenticated: false,
    currentUser: null,
    authToken: '',
    isLoading: true,

    // PIN Flow State
    pin: null,
    pinPollingTimer: null,
    pinError: '',
    isGeneratingPin: false,

    // Overseerr / Arr Primary Tab Navigation
    activeTab: 'discover', // 'discover' | 'requests' | 'playlists' | 'settings'

    // Discovery State
    discoveryState: {
      query: '',
      category: 'trending', // 'trending' | 'new_releases' | 'all' | 'albums' | 'tracks'
      items: [],
      isLoading: false,
    },

    // 30s Audio Preview Player
    audioPlayer: {
      currentTrack: null,
      isPlaying: false,
      audioElement: null,
      progress: 0,
      init(app) {
        if (typeof Audio !== 'undefined') {
          this.audioElement = new Audio();
          this.audioElement.addEventListener('timeupdate', () => {
            if (this.audioElement && this.audioElement.duration) {
              this.progress = (this.audioElement.currentTime / this.audioElement.duration) * 100;
            }
          });
          this.audioElement.addEventListener('ended', () => {
            this.isPlaying = false;
            this.progress = 0;
          });
          this.audioElement.addEventListener('pause', () => {
            this.isPlaying = false;
          });
          this.audioElement.addEventListener('play', () => {
            this.isPlaying = true;
          });
          this.audioElement.addEventListener('error', () => {
            this.isPlaying = false;
            app.showToast('Unable to stream 30s preview', 'error');
          });
        }
      },
      play(item) {
        if (!item || !item.preview_url) {
          return;
        }
        if (this.audioElement) {
          if (this.currentTrack?.id === item.id && this.audioElement.src) {
            this.audioElement.play().catch(() => {});
            this.isPlaying = true;
            return;
          }
          this.currentTrack = item;
          this.progress = 0;
          this.audioElement.src = item.preview_url;
          this.audioElement.play().catch(() => {});
          this.isPlaying = true;
        }
      },
      pause() {
        if (this.audioElement) {
          this.audioElement.pause();
          this.isPlaying = false;
        }
      },
      stop() {
        this.pause();
        this.currentTrack = null;
        this.progress = 0;
        if (this.audioElement) {
          this.audioElement.src = '';
        }
      },
      toggle(item) {
        if (this.currentTrack?.id === item.id && this.isPlaying) {
          this.pause();
        } else {
          this.play(item);
        }
      }
    },

    // Requests State
    requestsState: {
      items: [],
      filter: 'all',
      isLoading: false,
    },
    isSubmittingRequest: false,

    get pendingRequestsCount() {
      return (this.requestsState.items || []).filter(r => r.status === 'pending').length;
    },

    get filteredRequests() {
      if (this.requestsState.filter === 'all') {
        return this.requestsState.items || [];
      }
      return (this.requestsState.items || []).filter(r => r.status === this.requestsState.filter);
    },

    // Data State
    playlists: [],
    users: [],
    syncStatus: {
      is_syncing: false,
      last_run_at: null,
      last_run_stats: {
        total_playlists: 0,
        success_count: 0,
        total_matched: 0,
        total_missing: 0
      }
    },
    missingTracks: [],
    missingTracksCount: 0,

    // UI View State
    searchQuery: '',
    serviceFilter: 'all',
    viewMode: 'grid', // 'grid' | 'table'
    isAddModalOpen: false,
    isMissingModalOpen: false,
    selectedMissingPlaylistId: '',
    missingSearch: '',

    // Lidarr & Automated Feeds State
    lidarrConfig: { configured: false, url: null, auto_search: false, status: null },
    isLidarrDrawerOpen: false,
    isPushingLidarr: false,
    pushingTrackId: null,
    lidarrQueue: {
      is_running: false,
      is_paused: false,
      total_items: 0,
      processed_items: 0,
      remaining_items: 0,
      successful_items: 0,
      failed_items: 0,
      current_artist: null,
      current_album: null,
      delay_seconds: 3.0,
      is_rate_limited: false,
      rate_limit_seconds_remaining: 0,
      message: 'Idle'
    },
    lidarrQueueTimer: null,

    // Add Playlist Form State
    addTab: 'link', // 'link' | 'featured' | 'smart' | 'm3u' | 'paste' | 'helper'
    addForm: {
      url_or_id: '',
      service: '',
      targets: []
    },
    pasteForm: {
      name: '',
      rawText: '',
      service: 'spotify',
      targets: []
    },
    parsedTracks: [],
    showParsedPreview: false,
    addLoading: false,
    addError: '',

    // Featured Charts & Smart Mix State
    featuredCharts: [],
    smartMixPresets: [],
    isLoadingFeatured: false,
    isGeneratingMix: false,

    // M3U Import State
    m3uFile: null,
    m3uContent: '',
    m3uName: '',
    m3uParsedCount: 0,
    m3uImporting: false,

    // Match Memory & Manual Search State
    isMatchModalOpen: false,
    isMatchMemoryDrawerOpen: false,
    activeMissingTrack: null,
    matchSearchQuery: '',
    isSearchingPlex: false,
    plexSearchResults: [],
    matchOverrides: [],
    isSavingMatch: false,
    isDeletingMatchId: null,

    // Target User Updates Tracking
    targetUpdating: {},

    // Terminal Drawer State
    isTerminalOpen: false,
    isTerminalExpanded: false,
    autoScrollLogs: true,
    sseConnected: false,
    sseSource: null,
    sseReconnectTimer: null,
    logs: [],

    // Media Management & Arr Settings State
    settingsSubTab: 'media', // 'media' | 'status'
    settingsState: {
      mediaManagement: {
        artist_folder_format: '{Artist Name}',
        album_folder_format: '{Album Title} ({Release Year}){[ - Album Type]}',
        standard_track_format: '{track:00} - {Track Title}{[ (Quality Full)]}',
        compilation_track_format: '{track:00} - {Artist Name} - {Track Title}{[ (Quality Full)]}',
        multi_disc_folder_format: '{Medium Format} {medium:00}',
        root_folder_path: '/music',
        colon_replacement_format: ' - ',
        clean_artist_names: true
      },
      presets: {},
      previewPaths: [],
      isLoading: false,
      isSaving: false,
      previewTimer: null,
    },

    // Activity Queue State
    activityQueue: [],
    activeDownloadsCount: 0,
    isQueueLoading: false,
    isQueueRefreshing: false,

    // Download Clients & Indexers State
    downloadClients: [],
    isClientsLoading: false,
    isClientModalOpen: false,
    clientForm: {
      id: null,
      name: '',
      driver_type: 'slskd',
      host_url: '',
      api_key: '',
      username: '',
      password: '',
      priority: 1,
      enabled: true,
      extra_settings_json: '',
    },
    clientTesting: false,
    clientTestResult: null,
    clientSaving: false,

    indexers: [],
    isIndexersLoading: false,
    isIndexerModalOpen: false,
    indexerForm: {
      id: null,
      name: '',
      indexer_type: 'torznab',
      host_url: '',
      api_key: '',
      categories: '3000,3010,3020,3030,3040',
      priority: 1,
      enabled: true,
    },
    indexerTesting: false,
    indexerTestResult: null,
    indexerSaving: false,

    // Toast Notifications
    toasts: [],
    statusPollTimer: null,

    // Lifecycle
    init() {
      this.checkAuth();
      this.audioPlayer.init(this);
      // Periodically poll sync status and activity queue every 5 seconds
      this.statusPollTimer = setInterval(() => {
        if (this.isAuthenticated) {
          this.fetchSyncStatus();
          if (this.activeTab === 'activity') {
            this.loadQueue(true);
          }
        }
      }, 5000);

      window.addEventListener('hashchange', () => this.checkHashImport());
    },

    // HTTP Helper
    async apiRequest(endpoint, options = {}) {
      const headers = {
        'Accept': 'application/json',
        ...(options.headers || {})
      };

      if (this.authToken) {
        headers['Authorization'] = `Bearer ${this.authToken}`;
      }

      if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(options.body);
      }

      const config = {
        credentials: 'same-origin',
        ...options,
        headers
      };

      try {
        const response = await fetch(endpoint, config);

        if (response.status === 401) {
          if (this.isAuthenticated) {
            this.handleUnauthorized();
          }
          throw new Error('Unauthorized');
        }

        if (response.status === 204) {
          return null;
        }

        const data = await response.json().catch(() => null);

        if (!response.ok) {
          const detail = data?.detail || `HTTP Error ${response.status}: ${response.statusText}`;
          throw new Error(detail);
        }

        return data;
      } catch (err) {
        throw err;
      }
    },

    // Auth & Session
    async checkAuth() {
      this.isLoading = true;
      try {
        const res = await this.apiRequest('/api/auth/me');
        if (res && res.user) {
          this.currentUser = res.user;
          this.isAuthenticated = true;
          this.loadDashboardData();
          this.loadTrending();
          this.loadRequests();
          this.initSSE();
          this.checkHashImport();
          this.loadSettings();
          this.loadQueue(true);
        } else {
          this.handleUnauthorized();
        }
      } catch (err) {
        this.handleUnauthorized();
      } finally {
        this.isLoading = false;
      }
    },

    handleUnauthorized() {
      this.isAuthenticated = false;
      this.currentUser = null;
      this.authToken = '';
      this.closeSSE();
      this.startPinFlow();
    },

    // -----------------------------------------------------------------------
    // Discovery & Requests Methods
    // -----------------------------------------------------------------------
    formatYear(dateStr) {
      if (!dateStr) return '';
      const match = String(dateStr).match(/\b(19\d{2}|20\d{2})\b/);
      return match ? match[0] : String(dateStr).slice(0, 4);
    },

    async setDiscoveryCategory(category) {
      this.discoveryState.category = category;
      if (category === 'trending') {
        this.discoveryState.query = '';
        await this.loadTrending();
      } else if (category === 'new_releases') {
        this.discoveryState.query = '';
        await this.loadNewReleases();
      } else {
        if (this.discoveryState.query) {
          await this.searchDiscovery();
        } else {
          await this.loadTrending();
        }
      }
    },

    async loadTrending() {
      this.discoveryState.isLoading = true;
      try {
        const res = await this.apiRequest('/api/discovery/trending?limit=30');
        if (res && res.items) {
          this.discoveryState.items = res.items;
        }
      } catch (err) {
        console.error('Failed to load trending items:', err);
      } finally {
        this.discoveryState.isLoading = false;
      }
    },

    async loadNewReleases() {
      this.discoveryState.isLoading = true;
      try {
        const res = await this.apiRequest('/api/discovery/new-releases?limit=30');
        if (res && res.items) {
          this.discoveryState.items = res.items;
        }
      } catch (err) {
        console.error('Failed to load new releases:', err);
      } finally {
        this.discoveryState.isLoading = false;
      }
    },

    async searchDiscovery() {
      const q = (this.discoveryState.query || '').trim();
      if (!q) {
        if (this.discoveryState.category === 'new_releases') {
          return this.loadNewReleases();
        }
        return this.loadTrending();
      }
      this.discoveryState.isLoading = true;
      try {
        let typeParam = 'all';
        if (this.discoveryState.category === 'albums') typeParam = 'album';
        if (this.discoveryState.category === 'tracks') typeParam = 'track';

        const res = await this.apiRequest(`/api/discovery/search?q=${encodeURIComponent(q)}&type=${typeParam}&limit=30`);
        if (res && res.items) {
          this.discoveryState.items = res.items;
        }
      } catch (err) {
        this.showToast('Search failed: ' + err.message, 'error');
      } finally {
        this.discoveryState.isLoading = false;
      }
    },

    async loadRequests() {
      this.requestsState.isLoading = true;
      try {
        const res = await this.apiRequest('/api/requests');
        if (res && res.requests) {
          this.requestsState.items = res.requests;
        }
      } catch (err) {
        console.error('Failed to load requests:', err);
      } finally {
        this.requestsState.isLoading = false;
      }
    },

    setRequestFilter(filter) {
      this.requestsState.filter = filter;
    },

    async createRequest(item) {
      if (this.isSubmittingRequest) return;
      this.isSubmittingRequest = true;
      try {
        const payload = {
          item_type: item.item_type || 'album',
          title: item.title,
          artist: item.artist,
          album: item.album || item.title,
          cover_url: item.cover_url || null,
          release_date: item.release_date || null,
          foreign_id: item.id || null,
          preview_url: item.preview_url || null,
        };
        const created = await this.apiRequest('/api/requests', {
          method: 'POST',
          body: payload,
        });
        if (created) {
          item.status = created.status || 'requested';
          item.request_id = created.id;
          this.showToast(`Requested "${item.title}" successfully`, 'success');
          await this.loadRequests();
        }
      } catch (err) {
        this.showToast(err.message || 'Failed to submit request', 'error');
      } finally {
        this.isSubmittingRequest = false;
      }
    },

    async approveRequest(requestId) {
      try {
        const updated = await this.apiRequest(`/api/requests/${requestId}/approve`, {
          method: 'POST',
        });
        if (updated) {
          this.showToast(`Request approved for "${updated.title}"`, 'success');
          await this.loadRequests();
        }
      } catch (err) {
        this.showToast(err.message || 'Failed to approve request', 'error');
      }
    },

    async rejectRequest(requestId) {
      try {
        const updated = await this.apiRequest(`/api/requests/${requestId}/reject`, {
          method: 'POST',
        });
        if (updated) {
          this.showToast(`Request rejected for "${updated.title}"`, 'info');
          await this.loadRequests();
        }
      } catch (err) {
        this.showToast(err.message || 'Failed to reject request', 'error');
      }
    },

    async deleteRequest(requestId) {
      try {
        await this.apiRequest(`/api/requests/${requestId}`, {
          method: 'DELETE',
        });
        this.showToast('Request canceled', 'info');
        await this.loadRequests();
      } catch (err) {
        this.showToast(err.message || 'Failed to cancel request', 'error');
      }
    },

    async startPinFlow() {
      this.isGeneratingPin = true;
      this.pinError = '';
      if (this.pinPollingTimer) {
        clearInterval(this.pinPollingTimer);
        this.pinPollingTimer = null;
      }

      try {
        const data = await this.apiRequest('/api/auth/plex/pin', { method: 'POST' });
        this.pin = data;
        this.pollPin();
      } catch (err) {
        this.pinError = err.message || 'Failed to generate Plex PIN';
      } finally {
        this.isGeneratingPin = false;
      }
    },

    pollPin() {
      if (this.pinPollingTimer) clearInterval(this.pinPollingTimer);

      this.pinPollingTimer = setInterval(async () => {
        if (!this.pin?.id) {
          clearInterval(this.pinPollingTimer);
          return;
        }

        try {
          const res = await fetch('/api/auth/plex/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ pin_id: this.pin.id })
          });

          if (res.status === 200) {
            if (this.plexPopup && !this.plexPopup.closed) {
              try {
                this.plexPopup.close();
              } catch (e) {}
              this.plexPopup = null;
            }
            clearInterval(this.pinPollingTimer);
            this.pinPollingTimer = null;
            const data = await res.json();
            this.currentUser = data.user;
            this.isAuthenticated = true;
            this.pin = null;
            this.showToast(`Signed in as ${this.currentUser.username}`, 'success');
            this.loadDashboardData();
            this.initSSE();
            this.checkHashImport();
          } else if (res.status === 403) {
            if (this.plexPopup && !this.plexPopup.closed) {
              try {
                this.plexPopup.close();
              } catch (e) {}
              this.plexPopup = null;
            }
            clearInterval(this.pinPollingTimer);
            this.pinPollingTimer = null;
            const data = await res.json().catch(() => null);
            this.pinError = data?.detail || 'Forbidden: Access denied to this Plex Media Server';
            this.showToast(this.pinError, 'error');
          } else if (res.status === 400) {
            // Still waiting for user authorization on plex.tv
          } else {
            // Unexpected status, stop polling to avoid flooding
            clearInterval(this.pinPollingTimer);
          }
        } catch (e) {
          // Network hiccup during poll, continue waiting
        }
      }, 2000);
    },

    openPlexAuth() {
      if (!this.pin?.auth_url) return;
      const width = 600;
      const height = 700;
      const left = Math.max(0, Math.floor((window.innerWidth - width) / 2 + window.screenX));
      const top = Math.max(0, Math.floor((window.innerHeight - height) / 2 + window.screenY));
      this.plexPopup = window.open(
        this.pin.auth_url,
        'plex_oauth_popup',
        `width=${width},height=${height},top=${top},left=${left},scrollbars=yes,status=no,toolbar=no,menubar=no`
      );
    },

    async logout() {
      try {
        await this.apiRequest('/api/auth/logout', { method: 'POST' });
      } catch (e) {
        // Continue logging out locally
      }
      this.handleUnauthorized();
      this.showToast('Successfully logged out', 'info');
    },

    // Data Loaders
    async loadDashboardData() {
      await Promise.allSettled([
        this.fetchPlaylists(),
        this.fetchUsers(),
        this.fetchSyncStatus(),
        this.fetchMissingTracks(),
        this.fetchLidarrStatus(),
        this.fetchLidarrQueue()
      ]);
    },

    async fetchPlaylists() {
      try {
        const data = await this.apiRequest('/api/playlists');
        this.playlists = Array.isArray(data) ? data : [];
      } catch (err) {
        this.showToast(`Failed to load playlists: ${err.message}`, 'error');
      }
    },

    async fetchUsers() {
      try {
        const data = await this.apiRequest('/api/users');
        this.users = Array.isArray(data) ? data : [];
      } catch (err) {
        this.showToast(`Failed to load users: ${err.message}`, 'error');
      }
    },

    async refreshUsers() {
      try {
        const data = await this.apiRequest('/api/users/refresh', { method: 'POST' });
        this.users = Array.isArray(data) ? data : [];
        this.showToast('Plex Home users refreshed successfully', 'success');
      } catch (err) {
        this.showToast(`Failed to refresh users: ${err.message}`, 'error');
      }
    },

    async fetchSyncStatus() {
      try {
        const data = await this.apiRequest('/api/sync/status');
        if (data) {
          const prevSyncing = this.syncStatus.is_syncing;
          this.syncStatus = data;
          // If a sync just completed, refresh playlists and missing tracks
          if (prevSyncing && !data.is_syncing) {
            this.fetchPlaylists();
            this.fetchMissingTracks();
            this.showToast('Background synchronization completed', 'success');
          }
        }
      } catch (err) {
        // Silently fail periodic poll
      }
    },

    async triggerSync() {
      try {
        const res = await this.apiRequest('/api/sync', { method: 'POST' });
        if (res.status === 'already_running') {
          this.showToast('Synchronization is already running', 'info');
        } else {
          this.syncStatus.is_syncing = true;
          this.isTerminalOpen = true;
          this.showToast('Synchronization initiated', 'success');
        }
      } catch (err) {
        this.showToast(`Failed to start sync: ${err.message}`, 'error');
      }
    },

    // Target Toggling
    canToggleTarget(targetUserId) {
      if (!this.currentUser) return false;
      if (this.currentUser.is_admin) return true;
      return String(this.currentUser.id) === String(targetUserId);
    },

    async toggleUserTarget(playlist, targetUserId) {
      if (!this.canToggleTarget(targetUserId)) {
        this.showToast('Only administrators can manage other users\' playlist targets', 'info');
        return;
      }

      const key = `${playlist.id}_${targetUserId}`;
      if (this.targetUpdating[key]) return;

      const currentTargets = Array.isArray(playlist.targets) ? [...playlist.targets] : [];
      const uidStr = String(targetUserId);
      const isTargeted = currentTargets.map(String).includes(uidStr);

      let newTargets;
      if (isTargeted) {
        newTargets = currentTargets.filter(id => String(id) !== uidStr);
      } else {
        newTargets = [...currentTargets, uidStr];
      }

      this.targetUpdating[key] = true;
      // Optimistic update
      const oldTargets = playlist.targets;
      playlist.targets = newTargets;

      try {
        const res = await this.apiRequest(`/api/playlists/${encodeURIComponent(playlist.id)}/targets`, {
          method: 'PUT',
          body: { user_ids: newTargets }
        });
        if (res && Array.isArray(res.targets)) {
          playlist.targets = res.targets;
        }
      } catch (err) {
        // Rollback
        playlist.targets = oldTargets;
        this.showToast(`Failed to update target: ${err.message}`, 'error');
      } finally {
        delete this.targetUpdating[key];
      }
    },

    // Add Playlist Modal
    openAddModal(tab = 'link') {
      const initialTargets = this.currentUser ? [String(this.currentUser.id)] : [];
      this.addTab = tab;
      this.addForm = {
        url_or_id: '',
        service: '',
        targets: [...initialTargets]
      };
      this.pasteForm = {
        name: '',
        rawText: '',
        service: 'spotify',
        targets: [...initialTargets]
      };
      this.m3uFile = null;
      this.m3uContent = '';
      this.m3uName = '';
      this.m3uParsedCount = 0;
      this.parsedTracks = [];
      this.showParsedPreview = false;
      this.addError = '';
      this.addLoading = false;
      this.isAddModalOpen = true;

      // Preload featured charts and smart mix presets
      this.fetchFeaturedCharts();
      this.fetchSmartMixPresets();
    },

    closeAddModal() {
      this.isAddModalOpen = false;
      this.addError = '';
      this.addLoading = false;
    },

    detectedServiceHint() {
      const val = (this.addForm.url_or_id || '').trim().toLowerCase();
      if (val.includes('spotify.com') || val.startsWith('spotify:')) return 'Spotify';
      if (val.includes('deezer.com')) return 'Deezer';
      if (/^[0-9a-zA-Z]{22}$/.test(val)) return 'Spotify (ID detected)';
      if (/^\d{5,15}$/.test(val)) return 'Deezer (ID detected)';
      return null;
    },

    toggleAddFormTarget(userId) {
      const uid = String(userId);
      if (this.addForm.targets.includes(uid)) {
        this.addForm.targets = this.addForm.targets.filter(id => id !== uid);
      } else {
        this.addForm.targets.push(uid);
      }
    },

    selectAllAddTargets() {
      this.addForm.targets = this.users.map(u => String(u.id));
    },

    clearAllAddTargets() {
      this.addForm.targets = [];
    },

    async submitAddPlaylist() {
      const input = (this.addForm.url_or_id || '').trim();
      if (!input) {
        this.addError = 'Please provide a Spotify or Deezer playlist URL, URI, or ID.';
        return;
      }

      this.addLoading = true;
      this.addError = '';

      try {
        const payload = {
          url_or_id: input,
          service: this.addForm.service || null,
          targets: this.addForm.targets
        };

        const newPlaylist = await this.apiRequest('/api/playlists', {
          method: 'POST',
          body: payload
        });

        this.playlists.unshift(newPlaylist);
        this.showToast(`Playlist "${newPlaylist.name}" added successfully`, 'success');
        this.closeAddModal();
      } catch (err) {
        this.addError = err.message || 'Failed to add playlist. Check URL format.';
      } finally {
        this.addLoading = false;
      }
    },

    // Featured Charts Presets
    async fetchFeaturedCharts() {
      if (this.featuredCharts.length > 0) return;
      this.isLoadingFeatured = true;
      try {
        const data = await this.apiRequest('/api/playlists/featured');
        this.featuredCharts = Array.isArray(data) ? data : [];
      } catch (err) {
        // Silently log or toast
      } finally {
        this.isLoadingFeatured = false;
      }
    },

    async subscribeFeatured(chart) {
      this.addLoading = true;
      this.addError = '';
      try {
        const payload = {
          url_or_id: chart.url_or_id,
          service: chart.service,
          targets: this.addForm.targets.length ? this.addForm.targets : (this.currentUser ? [String(this.currentUser.id)] : [])
        };
        const newPlaylist = await this.apiRequest('/api/playlists', {
          method: 'POST',
          body: payload
        });
        this.playlists.unshift(newPlaylist);
        this.showToast(`Subscribed to chart "${newPlaylist.name}"!`, 'success');
        this.closeAddModal();
      } catch (err) {
        this.addError = err.message || 'Failed to subscribe to chart';
        this.showToast(this.addError, 'error');
      } finally {
        this.addLoading = false;
      }
    },

    // Smart Mix Presets
    async fetchSmartMixPresets() {
      if (this.smartMixPresets.length > 0) return;
      try {
        const data = await this.apiRequest('/api/playlists/smart-mix/presets');
        this.smartMixPresets = Array.isArray(data) ? data : [];
      } catch (err) {
        // Ignore
      }
    },

    async createSmartMix(mixType, customName = '') {
      this.isGeneratingMix = true;
      this.addError = '';
      try {
        const payload = {
          mix_type: mixType,
          name: customName || null,
          targets: this.addForm.targets.length ? this.addForm.targets : (this.currentUser ? [String(this.currentUser.id)] : [])
        };
        const res = await this.apiRequest('/api/playlists/smart-mix', {
          method: 'POST',
          body: payload
        });
        this.showToast(`Generated smart playlist "${res.name}" with ${res.matched_count} tracks!`, 'success');
        this.closeAddModal();
        await this.fetchPlaylists();
      } catch (err) {
        this.addError = err.message || 'Failed to generate smart mix. Ensure you have played music on Plexamp.';
        this.showToast(this.addError, 'error');
      } finally {
        this.isGeneratingMix = false;
      }
    },

    // M3U Drag-and-Drop & File Import
    handleM3UFileSelect(event) {
      const file = event.target.files?.[0];
      if (!file) return;
      this.m3uFile = file;

      // Extract filename without .m3u / .m3u8 extension
      const rawName = file.name.replace(/\.(m3u8?|txt)$/i, '');
      this.m3uName = rawName || 'Imported M3U Playlist';

      const reader = new FileReader();
      reader.onload = (e) => {
        this.m3uContent = e.target.result || '';
        const lines = this.m3uContent.split(/\r?\n/).filter(l => l.trim() && !l.trim().startsWith('#EXTM3U'));
        const infLines = lines.filter(l => l.trim().startsWith('#EXTINF:'));
        this.m3uParsedCount = infLines.length > 0 ? infLines.length : Math.max(1, lines.length);
      };
      reader.readAsText(file);
    },

    async submitM3UImport() {
      if (!this.m3uContent || !this.m3uContent.trim()) {
        this.addError = 'Please choose a valid .m3u or .m3u8 playlist file.';
        return;
      }
      const name = (this.m3uName || '').trim() || 'Imported M3U Playlist';
      this.m3uImporting = true;
      this.addError = '';

      try {
        const payload = {
          name: name,
          content: this.m3uContent,
          targets: this.addForm.targets.length ? this.addForm.targets : (this.currentUser ? [String(this.currentUser.id)] : [])
        };
        const res = await this.apiRequest('/api/playlists/import/m3u', {
          method: 'POST',
          body: payload
        });
        this.showToast(`Imported "${res.name}" (${res.matched_count}/${res.track_count} matched in Plex)`, 'success');
        this.closeAddModal();
        this.m3uFile = null;
        this.m3uContent = '';
        this.m3uName = '';
        await this.fetchPlaylists();
        await this.fetchMissingTracks();
      } catch (err) {
        this.addError = err.message || 'Failed to import M3U file.';
        this.showToast(this.addError, 'error');
      } finally {
        this.m3uImporting = false;
      }
    },
    togglePasteFormTarget(userId) {
      const uid = String(userId);
      if (this.pasteForm.targets.includes(uid)) {
        this.pasteForm.targets = this.pasteForm.targets.filter(id => id !== uid);
      } else {
        this.pasteForm.targets.push(uid);
      }
    },

    selectAllPasteTargets() {
      this.pasteForm.targets = this.users.map(u => String(u.id));
    },

    clearAllPasteTargets() {
      this.pasteForm.targets = [];
    },

    onPasteInput() {
      const res = this.parseImportText(this.pasteForm.rawText);
      if (res.name && (!this.pasteForm.name || this.pasteForm.name === 'Spotify Playlist')) {
        this.pasteForm.name = res.name;
      }
      this.parsedTracks = res.tracks;
    },

    parseImportText(rawText) {
      if (!rawText || !rawText.trim()) {
        return { name: '', tracks: [] };
      }
      const text = rawText.trim();

      // 1. Try parsing JSON (from bookmarklet or exported format)
      if (text.startsWith('{') || text.startsWith('[')) {
        try {
          const parsed = JSON.parse(text);
          if (Array.isArray(parsed)) {
            const tracks = parsed.filter(t => t && (t.title || t.name)).map(t => ({
              title: String(t.title || t.name).trim(),
              artist: String(t.artist || '').trim(),
              album: String(t.album || '').trim()
            }));
            if (tracks.length > 0) {
              return { name: '', tracks };
            }
          } else if (parsed && typeof parsed === 'object') {
            const name = parsed.name || parsed.title || '';
            const rawTracks = Array.isArray(parsed.tracks) ? parsed.tracks : [];
            const tracks = rawTracks.filter(t => t && (t.title || t.name)).map(t => ({
              title: String(t.title || t.name).trim(),
              artist: String(t.artist || '').trim(),
              album: String(t.album || '').trim()
            }));
            if (tracks.length > 0) {
              return { name: String(name).trim(), tracks };
            }
          }
        } catch (e) {
          // Continue to line parsing
        }
      }

      // 2. Line-by-line parsing
      const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
      const tracks = [];

      for (const line of lines) {
        // Tab-separated (Spotify Desktop or table copy: Index \t Title \t Artist \t Album \t Duration)
        if (line.includes('\t')) {
          const cols = line.split('\t').map(c => c.trim()).filter(Boolean);
          if (cols.length >= 2) {
            if (/^\d+$/.test(cols[0]) && cols.length >= 3) {
              tracks.push({
                title: cols[1],
                artist: cols[2],
                album: cols[3] || ''
              });
            } else {
              tracks.push({
                title: cols[0],
                artist: cols[1],
                album: cols[2] || ''
              });
            }
            continue;
          }
        }

        // CSV parsing: "Title","Artist","Album"
        if (line.includes('","') || (line.startsWith('"') && line.includes(','))) {
          const match = line.match(/^"([^"]+)",\s*"([^"]+)"(?:,\s*"([^"]+)")?/);
          if (match) {
            tracks.push({
              title: match[1].trim(),
              artist: match[2].trim(),
              album: match[3] ? match[3].trim() : ''
            });
            continue;
          }
        }

        // Artist - Title
        if (line.includes(' - ')) {
          const parts = line.split(' - ').map(p => p.trim());
          if (parts.length >= 2) {
            tracks.push({
              title: parts[1],
              artist: parts[0],
              album: parts[2] || ''
            });
            continue;
          }
        }

        // Title by Artist
        const byMatch = line.match(/^(.+?)\s+by\s+(.+)$/i);
        if (byMatch) {
          tracks.push({
            title: byMatch[1].trim(),
            artist: byMatch[2].trim(),
            album: ''
          });
          continue;
        }

        // Comma separated fallback: Title, Artist
        if (line.includes(',')) {
          const parts = line.split(',').map(p => p.trim());
          if (parts.length >= 2) {
            tracks.push({
              title: parts[0],
              artist: parts[1],
              album: parts[2] || ''
            });
            continue;
          }
        }

        // Plain line fallback (as title)
        if (line.length > 1 && !line.startsWith('http://') && !line.startsWith('https://')) {
          tracks.push({
            title: line,
            artist: '',
            album: ''
          });
        }
      }

      return { name: '', tracks };
    },

    async pasteFromClipboard() {
      try {
        if (!navigator.clipboard || !navigator.clipboard.readText) {
          this.showToast('Clipboard API not available. Please press Ctrl+V in the box below.', 'info');
          return;
        }
        const clipText = await navigator.clipboard.readText();
        if (clipText && clipText.trim()) {
          this.pasteForm.rawText = clipText;
          this.onPasteInput();
          if (this.parsedTracks.length > 0) {
            this.showToast(`Loaded ${this.parsedTracks.length} tracks from clipboard!`, 'success');
          } else {
            this.showToast('Pasted clipboard content. Check track formatting.', 'info');
          }
        } else {
          this.showToast('Clipboard is empty. Copy tracks from Spotify and try again.', 'info');
        }
      } catch (err) {
        this.showToast('Browser blocked automatic clipboard read. Please press Ctrl+V inside the box below.', 'info');
      }
    },

    readClipboardAndSwitch() {
      this.addTab = 'paste';
      this.pasteFromClipboard();
    },

    getBookmarkletHref() {
      const origin = window.location.origin;
      const script = `javascript:(function(){try{const h=document.querySelector('h1'),name=(h?h.innerText:document.title.replace(/\\s*\\|\\s*Spotify.*$/i,'')).trim()||'Spotify Playlist',rows=document.querySelectorAll('[data-testid="tracklist-row"]'),tracks=[];rows.forEach(r=>{const t=r.querySelector('[data-testid="internal-track-link"],div[aria-colindex="2"] a,a[href*="/track/"]'),arts=r.querySelectorAll('a[href*="/artist/"]'),alb=r.querySelector('a[href*="/album/"]'),title=t?t.innerText.trim():'',artists=Array.from(arts).map(a=>a.innerText.trim()).filter(Boolean),artist=artists.join(', ')||'Unknown Artist',album=alb?alb.innerText.trim():'';if(title){tracks.push({title,artist,album})}});if(!tracks.length){alert('TrackSeerr: No tracks detected. Make sure you are on a Spotify playlist and scroll down to load songs!');return}const payload=JSON.stringify({name,tracks});navigator.clipboard.writeText(payload).then(()=>{window.open('${origin}/#import=clipboard','_blank')}).catch(()=>{prompt('Copy track data manually:',payload)})}catch(e){alert('TrackSeerr: '+e.message)}})();`;
      return script.replace(/\\s+/g, ' ');
    },

    checkHashImport() {
      if (window.location.hash.includes('import=clipboard')) {
        history.replaceState(null, '', window.location.pathname + window.location.search);
        if (this.isAuthenticated) {
          this.openAddModal('paste');
          this.pasteFromClipboard();
        }
      }
    },

    async submitImportPlaylist() {
      const name = (this.pasteForm.name || '').trim();
      if (!name) {
        this.addError = 'Please provide a playlist name.';
        return;
      }
      if (!this.parsedTracks || this.parsedTracks.length === 0) {
        this.addError = 'No tracks detected. Please paste tracks into the box.';
        return;
      }

      this.addLoading = true;
      this.addError = '';

      try {
        const payload = {
          name: name,
          service: this.pasteForm.service || 'spotify',
          tracks: this.parsedTracks,
          targets: this.pasteForm.targets
        };

        const res = await this.apiRequest('/api/playlists/import', {
          method: 'POST',
          body: payload
        });

        this.showToast(`Imported "${res.name}" (${res.track_count} tracks, ${res.matched_count} matched in Plex)`, 'success');
        this.closeAddModal();
        await this.fetchPlaylists();
        await this.fetchMissingTracks();
      } catch (err) {
        this.addError = err.message || 'Failed to import playlist.';
      } finally {
        this.addLoading = false;
      }
    },

    // Playlist Active / Paused Toggle
    canTogglePlaylistActive(playlist) {
      if (!this.currentUser) return false;
      if (this.currentUser.is_admin) return true;
      return String(playlist.creator_id) === String(this.currentUser.id);
    },

    async togglePlaylistActive(playlist) {
      if (!this.canTogglePlaylistActive(playlist)) {
        this.showToast('Only administrators or the playlist creator can change sync status', 'info');
        return;
      }
      const currentVal = playlist.enabled !== false;
      const newVal = !currentVal;
      playlist.enabled = newVal;

      try {
        const res = await this.apiRequest(`/api/playlists/${encodeURIComponent(playlist.id)}/enabled`, {
          method: 'PUT',
          body: { enabled: newVal }
        });
        if (res && typeof res.enabled === 'boolean') {
          playlist.enabled = res.enabled;
        }
        this.showToast(`Playlist "${playlist.name}" is now ${playlist.enabled ? 'Active' : 'Paused'}`, 'info');
      } catch (err) {
        playlist.enabled = currentVal;
        this.showToast(`Failed to update playlist status: ${err.message}`, 'error');
      }
    },

    // Delete Playlist
    canDeletePlaylist(playlist) {
      if (!this.currentUser) return false;
      if (this.currentUser.is_admin) return true;
      return String(playlist.creator_id) === String(this.currentUser.id);
    },

    async deletePlaylist(playlist) {
      if (!this.canDeletePlaylist(playlist)) {
        this.showToast('Only administrators or the playlist creator can delete this playlist', 'error');
        return;
      }

      const confirmed = window.confirm(`Are you sure you want to remove playlist "${playlist.name}"?`);
      if (!confirmed) return;

      try {
        await this.apiRequest(`/api/playlists/${encodeURIComponent(playlist.id)}`, {
          method: 'DELETE'
        });
        this.playlists = this.playlists.filter(p => p.id !== playlist.id);
        this.showToast(`Deleted playlist "${playlist.name}"`, 'info');
      } catch (err) {
        this.showToast(`Failed to delete playlist: ${err.message}`, 'error');
      }
    },

    // Missing Tracks & CSV Export
    async fetchMissingTracks(playlistId = '') {
      try {
        const endpoint = playlistId
          ? `/api/missing?playlist_id=${encodeURIComponent(playlistId)}`
          : '/api/missing';
        const data = await this.apiRequest(endpoint);
        this.missingTracks = Array.isArray(data) ? data : [];
        if (!playlistId) {
          this.missingTracksCount = this.missingTracks.length;
        }
      } catch (err) {
        this.showToast(`Failed to load missing tracks: ${err.message}`, 'error');
      }
    },

    openMissingModal(playlistId = '') {
      this.selectedMissingPlaylistId = playlistId || '';
      this.missingSearch = '';
      this.fetchMissingTracks(this.selectedMissingPlaylistId);
      this.isMissingModalOpen = true;
    },

    closeMissingModal() {
      this.isMissingModalOpen = false;
    },

    exportMissingCsv() {
      const url = this.selectedMissingPlaylistId
        ? `/api/missing/csv?playlist_id=${encodeURIComponent(this.selectedMissingPlaylistId)}`
        : '/api/missing/csv';

      // Safe trigger download
      const a = document.createElement('a');
      a.href = url;
      a.setAttribute('download', '');
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      this.showToast('Safe CSV download started', 'info');
    },

    getTrackSearchUrl(track) {
      if (track.url) return track.url;
      const q = encodeURIComponent(`${track.artist || ''} ${track.title || ''}`.trim());
      return `https://open.spotify.com/search/${q}`;
    },

    getPlaylistName(playlistId) {
      const found = this.playlists.find(p => String(p.id) === String(playlistId));
      return found ? found.name : playlistId;
    },

    // Match Memory & Manual Search
    openManualMatchModal(track) {
      this.activeMissingTrack = track;
      this.matchSearchQuery = `${track.title || ''} ${track.artist || ''}`.trim();
      this.plexSearchResults = [];
      this.isMatchModalOpen = true;
      if (this.matchSearchQuery) {
        this.searchPlexTracks(this.matchSearchQuery);
      }
    },

    closeManualMatchModal() {
      this.isMatchModalOpen = false;
      this.activeMissingTrack = null;
      this.plexSearchResults = [];
      this.matchSearchQuery = '';
    },

    async searchPlexTracks(query) {
      const q = (query || this.matchSearchQuery || '').trim();
      if (!q) return;
      this.isSearchingPlex = true;
      try {
        const res = await this.apiRequest(`/api/missing/search?query=${encodeURIComponent(q)}&limit=15`);
        this.plexSearchResults = Array.isArray(res) ? res : [];
      } catch (err) {
        this.showToast(`Plex library search failed: ${err.message}`, 'error');
      } finally {
        this.isSearchingPlex = false;
      }
    },

    async linkMatchOverride(track, plexItem) {
      this.isSavingMatch = true;
      try {
        const payload = {
          source_title: track.title,
          source_artist: track.artist,
          plex_rating_key: String(plexItem.rating_key),
          plex_title: plexItem.title,
          plex_artist: plexItem.artist
        };
        await this.apiRequest('/api/missing/match', {
          method: 'POST',
          body: payload
        });
        this.showToast(`Linked "${track.title}" to "${plexItem.artist} - ${plexItem.title}" in Match Memory!`, 'success');

        // Remove from missing tracks locally
        this.missingTracks = this.missingTracks.filter(t =>
          !(t.title.toLowerCase() === track.title.toLowerCase() && t.artist.toLowerCase() === track.artist.toLowerCase())
        );
        this.missingTracksCount = this.missingTracks.length;
        this.closeManualMatchModal();

        // Refresh matches list if drawer is open
        if (this.isMatchMemoryDrawerOpen) {
          this.fetchMatchOverrides();
        }
      } catch (err) {
        this.showToast(`Failed to link match override: ${err.message}`, 'error');
      } finally {
        this.isSavingMatch = false;
      }
    },

    toggleMatchMemoryDrawer() {
      this.isMatchMemoryDrawerOpen = !this.isMatchMemoryDrawerOpen;
      if (this.isMatchMemoryDrawerOpen) {
        this.fetchMatchOverrides();
      }
    },

    async fetchMatchOverrides() {
      try {
        const data = await this.apiRequest('/api/missing/matches');
        this.matchOverrides = Array.isArray(data) ? data : [];
      } catch (err) {
        this.showToast(`Failed to load Match Memory: ${err.message}`, 'error');
      }
    },

    async deleteMatchOverride(overrideId) {
      this.isDeletingMatchId = overrideId;
      try {
        await this.apiRequest(`/api/missing/match/${overrideId}`, {
          method: 'DELETE'
        });
        this.matchOverrides = this.matchOverrides.filter(m => m.id !== overrideId);
        this.showToast('Removed Match Memory override', 'info');
      } catch (err) {
        this.showToast(`Failed to remove override: ${err.message}`, 'error');
      } finally {
        this.isDeletingMatchId = null;
      }
    },

    // Lidarr & Feed Management
    async fetchLidarrStatus() {
      try {
        const data = await this.apiRequest('/api/missing/lidarr/status');
        if (data) {
          this.lidarrConfig = data;
        }
      } catch (err) {
        // Silently handle if lidarr status fails to load
      }
    },

    toggleLidarrDrawer() {
      this.isLidarrDrawerOpen = !this.isLidarrDrawerOpen;
    },

    getRssFeedUrl() {
      const base = window.location.origin;
      return this.selectedMissingPlaylistId 
        ? `${base}/api/missing/rss?playlist_id=${encodeURIComponent(this.selectedMissingPlaylistId)}`
        : `${base}/api/missing/rss`;
    },

    getTextFeedUrl() {
      const base = window.location.origin;
      return this.selectedMissingPlaylistId 
        ? `${base}/api/missing/text?playlist_id=${encodeURIComponent(this.selectedMissingPlaylistId)}`
        : `${base}/api/missing/text`;
    },

    getWebhookUrl() {
      return `${window.location.origin}/api/sync/webhook`;
    },

    async copyToClipboard(text, label = 'URL') {
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
        } else {
          const ta = document.createElement('textarea');
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
        }
        this.showToast(`Copied ${label} to clipboard!`, 'success');
      } catch (err) {
        this.showToast(`Failed to copy to clipboard: ${err.message}`, 'error');
      }
    },

    async fetchLidarrQueue() {
      try {
        const data = await this.apiRequest('/api/missing/lidarr/queue');
        if (data) {
          const wasRunning = this.lidarrQueue.is_running;
          this.lidarrQueue = data;
          if (data.is_running || data.is_paused) {
            this.startLidarrQueuePolling();
          } else if (wasRunning && !data.is_running) {
            this.stopLidarrQueuePolling();
            this.fetchMissingTracks(this.selectedMissingPlaylistId);
          }
        }
      } catch (err) {
        // Silently handle
      }
    },

    startLidarrQueuePolling() {
      if (this.lidarrQueueTimer) return;
      this.lidarrQueueTimer = setInterval(() => {
        this.fetchLidarrQueue();
      }, 2000);
    },

    stopLidarrQueuePolling() {
      if (this.lidarrQueueTimer) {
        clearInterval(this.lidarrQueueTimer);
        this.lidarrQueueTimer = null;
      }
    },

    async pushNextBatchToLidarr(batchSize = 25) {
      if (this.isPushingLidarr) return;
      this.isPushingLidarr = true;
      try {
        const payload = {
          playlist_id: this.selectedMissingPlaylistId || null,
          batch_size: batchSize,
          trickle: true,
          auto_search: this.lidarrConfig.auto_search !== false
        };
        const res = await this.apiRequest('/api/missing/lidarr/push', {
          method: 'POST',
          body: payload
        });
        this.showToast(res.message || `Queued next ${batchSize} tracks into Lidarr`, 'success');
        await this.fetchLidarrQueue();
      } catch (err) {
        this.showToast(`Lidarr batch failed: ${err.message}`, 'error');
      } finally {
        this.isPushingLidarr = false;
      }
    },

    async pushAllToLidarr(useTrickle = true) {
      if (this.isPushingLidarr) return;
      this.isPushingLidarr = true;
      try {
        const payload = {
          playlist_id: this.selectedMissingPlaylistId || null,
          auto_search: this.lidarrConfig.auto_search !== false,
          trickle: useTrickle
        };
        const res = await this.apiRequest('/api/missing/lidarr/push', {
          method: 'POST',
          body: payload
        });
        if (res.trickle) {
          this.showToast(res.message || 'Queued missing tracks into Lidarr trickle worker', 'success');
          await this.fetchLidarrQueue();
        } else {
          this.showToast(`Lidarr Push: ${res.added} added, ${res.already_monitored} existing, ${res.failed} failed`, 'success');
          await this.fetchMissingTracks(this.selectedMissingPlaylistId);
        }
      } catch (err) {
        this.showToast(`Lidarr push failed: ${err.message}`, 'error');
      } finally {
        this.isPushingLidarr = false;
      }
    },

    async pushTrackToLidarr(trackId) {
      if (this.pushingTrackId) return;
      this.pushingTrackId = trackId;
      try {
        const payload = {
          track_ids: [trackId],
          auto_search: this.lidarrConfig.auto_search !== false,
          trickle: false
        };
        const res = await this.apiRequest('/api/missing/lidarr/push', {
          method: 'POST',
          body: payload
        });
        if (res.added > 0 || res.already_monitored > 0) {
          this.showToast('Queued in Lidarr successfully', 'success');
          const t = this.missingTracks.find(item => item.id === trackId);
          if (t) t.lidarr_status = 'monitored';
        } else {
          this.showToast('Failed to queue in Lidarr', 'error');
        }
      } catch (err) {
        this.showToast(`Lidarr queue failed: ${err.message}`, 'error');
      } finally {
        this.pushingTrackId = null;
      }
    },

    async pauseLidarrQueue() {
      try {
        await this.apiRequest('/api/missing/lidarr/queue/pause', { method: 'POST' });
        this.showToast('Lidarr trickle worker paused', 'info');
        await this.fetchLidarrQueue();
      } catch (err) {
        this.showToast(`Failed to pause worker: ${err.message}`, 'error');
      }
    },

    async resumeLidarrQueue() {
      try {
        await this.apiRequest('/api/missing/lidarr/queue/resume', { method: 'POST' });
        this.showToast('Lidarr trickle worker resumed', 'success');
        await this.fetchLidarrQueue();
      } catch (err) {
        this.showToast(`Failed to resume worker: ${err.message}`, 'error');
      }
    },

    async cancelLidarrQueue() {
      try {
        await this.apiRequest('/api/missing/lidarr/queue/cancel', { method: 'POST' });
        this.showToast('Lidarr trickle worker canceled', 'info');
        await this.fetchLidarrQueue();
      } catch (err) {
        this.showToast(`Failed to cancel worker: ${err.message}`, 'error');
      }
    },

    // Live Sync SSE Terminal
    initSSE() {
      this.closeSSE();

      try {
        const source = new EventSource('/api/sync/stream');
        this.sseSource = source;

        source.onopen = () => {
          this.sseConnected = true;
        };

        source.onmessage = (event) => {
          if (!event.data || event.data.trim() === '') return;
          this.appendLog(event.data);
        };

        source.onerror = () => {
          this.sseConnected = false;
          source.close();
          this.sseSource = null;
          // Exponential backoff reconnect
          if (!this.sseReconnectTimer) {
            this.sseReconnectTimer = setTimeout(() => {
              this.sseReconnectTimer = null;
              if (this.isAuthenticated) {
                this.initSSE();
              }
            }, 5000);
          }
        };
      } catch (e) {
        this.sseConnected = false;
      }
    },

    closeSSE() {
      if (this.sseSource) {
        this.sseSource.close();
        this.sseSource = null;
      }
      if (this.sseReconnectTimer) {
        clearTimeout(this.sseReconnectTimer);
        this.sseReconnectTimer = null;
      }
      this.sseConnected = false;
    },

    appendLog(rawText) {
      let level = 'info';
      let timestamp = '';
      let message = rawText;

      // Extract Python log format: 2026-10-01 01:23:45,678 [LEVEL] logger: message
      const logMatch = rawText.match(/^(\d{4}-\d{2}-\d{2}[^\[]+)?\s*\[(\w+)\]\s*(.*)$/);
      if (logMatch) {
        timestamp = (logMatch[1] || '').trim();
        level = (logMatch[2] || 'info').toLowerCase();
        message = logMatch[3] || '';
      } else if (rawText.toLowerCase().includes('error')) {
        level = 'error';
      } else if (rawText.toLowerCase().includes('warn')) {
        level = 'warning';
      }

      this.logs.push({
        id: Date.now() + Math.random(),
        timestamp: timestamp || new Date().toLocaleTimeString(),
        level,
        message,
        raw: rawText
      });

      // Keep maximum 400 log lines to preserve memory
      if (this.logs.length > 400) {
        this.logs.shift();
      }

      if (this.autoScrollLogs) {
        this.$nextTick(() => {
          const terminal = document.getElementById('terminal-content');
          if (terminal) {
            terminal.scrollTop = terminal.scrollHeight;
          }
        });
      }
    },

    clearLogs() {
      this.logs = [];
    },

    toggleTerminal() {
      this.isTerminalOpen = !this.isTerminalOpen;
    },

    // Toast Notifications
    showToast(message, type = 'info') {
      const id = Date.now() + Math.random();
      this.toasts.push({ id, message, type });
      setTimeout(() => {
        this.dismissToast(id);
      }, 4200);
    },

    dismissToast(id) {
      this.toasts = this.toasts.filter(t => t.id !== id);
    },

    // Filtered Computations
    get filteredPlaylists() {
      return this.playlists.filter(p => {
        // Service filter
        if (this.serviceFilter !== 'all' && p.service !== this.serviceFilter) {
          return false;
        }
        // Search query
        if (this.searchQuery.trim()) {
          const q = this.searchQuery.toLowerCase();
          const nameMatch = (p.name || '').toLowerCase().includes(q);
          const descMatch = (p.description || '').toLowerCase().includes(q);
          const idMatch = String(p.id).toLowerCase().includes(q);
          return nameMatch || descMatch || idMatch;
        }
        return true;
      });
    },

    get filteredMissingTracks() {
      return this.missingTracks.filter(t => {
        if (this.missingSearch.trim()) {
          const q = this.missingSearch.toLowerCase();
          const titleMatch = (t.title || '').toLowerCase().includes(q);
          const artistMatch = (t.artist || '').toLowerCase().includes(q);
          const albumMatch = (t.album || '').toLowerCase().includes(q);
          return titleMatch || artistMatch || albumMatch;
        }
        return true;
      });
    },

    // Format Helpers
    formatDate(dateString) {
      if (!dateString) return 'Never';
      try {
        const d = new Date(dateString);
        return isNaN(d.getTime()) ? dateString : d.toLocaleString();
      } catch (e) {
        return dateString;
      }
    },

    formatRelativeTime(dateString) {
      if (!dateString) return 'Never';
      try {
        const d = new Date(dateString);
        if (isNaN(d.getTime())) return dateString;
        const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
        if (diffSec < 60) return `${diffSec}s ago`;
        const diffMin = Math.floor(diffSec / 60);
        if (diffMin < 60) return `${diffMin}m ago`;
        const diffHours = Math.floor(diffMin / 60);
        if (diffHours < 24) return `${diffHours}h ago`;
        return `${Math.floor(diffHours / 24)}d ago`;
      } catch (e) {
        return dateString;
      }
    },

    // -----------------------------------------------------------------------
    // Media Management & Arr Settings Methods
    // -----------------------------------------------------------------------
    async loadSettings() {
      this.settingsState.isLoading = true;
      try {
        const data = await this.apiRequest('/api/settings/media-management');
        if (data && data.settings) {
          this.settingsState.mediaManagement = {
            artist_folder_format: data.settings.artist_folder_format || '{Artist Name}',
            album_folder_format: data.settings.album_folder_format || '{Album Title} ({Release Year}){[ - Album Type]}',
            standard_track_format: data.settings.standard_track_format || '{track:00} - {Track Title}{[ (Quality Full)]}',
            compilation_track_format: data.settings.compilation_track_format || '{track:00} - {Artist Name} - {Track Title}{[ (Quality Full)]}',
            multi_disc_folder_format: data.settings.multi_disc_folder_format || '{Medium Format} {medium:00}',
            root_folder_path: data.settings.root_folder_path || '/music',
            colon_replacement_format: data.settings.colon_replacement_format || ' - ',
            clean_artist_names: Boolean(data.settings.clean_artist_names),
          };
        }
        if (data && data.presets) {
          this.settingsState.presets = data.presets;
        }
        await this.updatePreview(true);
        this.loadDownloadClients();
        this.loadIndexers();
      } catch (err) {
        console.error('Failed to load media management settings:', err);
      } finally {
        this.settingsState.isLoading = false;
      }
    },

    updatePreview(immediate = false) {
      if (this.settingsState.previewTimer) {
        clearTimeout(this.settingsState.previewTimer);
        this.settingsState.previewTimer = null;
      }

      const executePreview = async () => {
        try {
          const res = await this.apiRequest('/api/settings/media-management/preview', {
            method: 'POST',
            body: this.settingsState.mediaManagement
          });
          if (res && res.previews) {
            this.settingsState.previewPaths = res.previews;
          }
        } catch (err) {
          console.error('Failed to update template preview:', err);
        }
      };

      if (immediate) {
        return executePreview();
      }

      this.settingsState.previewTimer = setTimeout(executePreview, 250);
    },

    async saveSettings() {
      if (!this.currentUser?.is_admin) {
        this.showToast('Administrator privileges required to save settings', 'error');
        return;
      }
      this.settingsState.isSaving = true;
      try {
        const res = await this.apiRequest('/api/settings/media-management', {
          method: 'POST',
          body: this.settingsState.mediaManagement
        });
        if (res) {
          this.showToast('Media management settings saved successfully!', 'success');
          await this.updatePreview(true);
        }
      } catch (err) {
        this.showToast(err.message || 'Failed to save settings', 'error');
      } finally {
        this.settingsState.isSaving = false;
      }
    },

    applyPreset(presetName) {
      const preset = this.settingsState.presets[presetName];
      if (!preset) return;
      this.settingsState.mediaManagement = {
        ...this.settingsState.mediaManagement,
        ...preset
      };
      this.updatePreview(true);
      this.showToast(`Applied preset: ${presetName}`, 'info');
    },

    insertToken(fieldName, token) {
      if (!this.settingsState.mediaManagement[fieldName]) {
        this.settingsState.mediaManagement[fieldName] = '';
      }
      this.settingsState.mediaManagement[fieldName] += token;
      this.updatePreview();
    },

    // -----------------------------------------------------------------------
    // Activity / Queue Methods
    // -----------------------------------------------------------------------
    async loadQueue(silent = false) {
      if (!silent) this.isQueueLoading = true;
      this.isQueueRefreshing = true;
      try {
        const data = await this.apiRequest('/api/queue?include_history=true');
        if (Array.isArray(data)) {
          this.activityQueue = data;
          this.activeDownloadsCount = data.filter(
            (i) => i.status === 'queued' || i.status === 'downloading' || i.status === 'importing'
          ).length;
        }
      } catch (err) {
        if (!silent) {
          console.error('Failed to load queue:', err);
          this.showToast('Failed to load activity queue', 'error');
        }
      } finally {
        if (!silent) this.isQueueLoading = false;
        this.isQueueRefreshing = false;
      }
    },

    async cancelDownload(downloadId) {
      if (!confirm('Are you sure you want to cancel and remove this download?')) return;
      try {
        await this.apiRequest(`/api/queue/${downloadId}`, { method: 'DELETE' });
        this.showToast('Download cancelled', 'info');
        await this.loadQueue(true);
      } catch (err) {
        this.showToast(err.message || 'Failed to cancel download', 'error');
      }
    },

    formatBytes(bytes) {
      if (!bytes || bytes <= 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    },

    formatEta(seconds) {
      if (!seconds || seconds <= 0) return '';
      if (seconds < 60) return `${seconds}s`;
      const mins = Math.floor(seconds / 60);
      const secs = seconds % 60;
      if (mins < 60) return `${mins}m ${secs}s`;
      const hrs = Math.floor(mins / 60);
      return `${hrs}h ${mins % 60}m`;
    },

    // -----------------------------------------------------------------------
    // Download Clients Settings Methods
    // -----------------------------------------------------------------------
    async loadDownloadClients() {
      this.isClientsLoading = true;
      try {
        const data = await this.apiRequest('/api/settings/download-clients');
        this.downloadClients = Array.isArray(data) ? data : [];
      } catch (err) {
        console.error('Failed to load download clients:', err);
      } finally {
        this.isClientsLoading = false;
      }
    },

    openAddClientModal(driverType = 'slskd') {
      const defaultNames = {
        slskd: 'slskd',
        sabnzbd: 'SABnzbd',
        qbittorrent: 'qBittorrent',
        lidarr: 'Lidarr'
      };
      const defaultUrls = {
        slskd: 'http://localhost:5030',
        sabnzbd: 'http://localhost:8080',
        qbittorrent: 'http://localhost:8080',
        lidarr: 'http://localhost:8686'
      };
      this.clientForm = {
        id: null,
        name: defaultNames[driverType] || 'Client',
        driver_type: driverType,
        host_url: defaultUrls[driverType] || 'http://localhost:8080',
        api_key: '',
        username: '',
        password: '',
        priority: 1,
        enabled: true,
        extra_settings_json: '',
      };
      this.clientTestResult = null;
      this.isClientModalOpen = true;
    },

    openEditClientModal(client) {
      this.clientForm = {
        id: client.id,
        name: client.name,
        driver_type: client.driver_type,
        host_url: client.host_url,
        api_key: client.api_key || '',
        username: client.username || '',
        password: client.password || '',
        priority: client.priority ?? 1,
        enabled: Boolean(client.enabled),
        extra_settings_json: client.extra_settings_json || '',
      };
      this.clientTestResult = null;
      this.isClientModalOpen = true;
    },

    closeClientModal() {
      this.isClientModalOpen = false;
      this.clientTestResult = null;
    },

    async testDownloadClient() {
      this.clientTesting = true;
      this.clientTestResult = null;
      try {
        const res = await this.apiRequest('/api/settings/download-clients/test', {
          method: 'POST',
          body: {
            driver_type: this.clientForm.driver_type,
            host_url: this.clientForm.host_url,
            api_key: this.clientForm.api_key,
            username: this.clientForm.username,
            password: this.clientForm.password,
            extra_settings_json: this.clientForm.extra_settings_json,
          }
        });
        this.clientTestResult = res;
      } catch (err) {
        this.clientTestResult = { success: false, message: err.message || 'Connection failed' };
      } finally {
        this.clientTesting = false;
      }
    },

    async saveDownloadClient() {
      this.clientSaving = true;
      try {
        await this.apiRequest('/api/settings/download-clients', {
          method: 'POST',
          body: this.clientForm
        });
        this.showToast('Download client saved', 'success');
        this.closeClientModal();
        await this.loadDownloadClients();
      } catch (err) {
        this.showToast(err.message || 'Failed to save download client', 'error');
      } finally {
        this.clientSaving = false;
      }
    },

    async deleteDownloadClient(clientId) {
      if (!confirm('Are you sure you want to delete this download client?')) return;
      try {
        await this.apiRequest(`/api/settings/download-clients/${clientId}`, { method: 'DELETE' });
        this.showToast('Download client removed', 'info');
        await this.loadDownloadClients();
      } catch (err) {
        this.showToast(err.message || 'Failed to delete client', 'error');
      }
    },

    async toggleClientEnabled(client) {
      try {
        await this.apiRequest('/api/settings/download-clients', {
          method: 'POST',
          body: {
            id: client.id,
            name: client.name,
            driver_type: client.driver_type,
            host_url: client.host_url,
            enabled: !client.enabled,
            priority: client.priority,
          }
        });
        await this.loadDownloadClients();
      } catch (err) {
        this.showToast(err.message || 'Failed to update client status', 'error');
      }
    },

    // -----------------------------------------------------------------------
    // Indexers Settings Methods
    // -----------------------------------------------------------------------
    async loadIndexers() {
      this.isIndexersLoading = true;
      try {
        const data = await this.apiRequest('/api/settings/indexers');
        this.indexers = Array.isArray(data) ? data : [];
      } catch (err) {
        console.error('Failed to load indexers:', err);
      } finally {
        this.isIndexersLoading = false;
      }
    },

    openAddIndexerModal(indexerType = 'torznab') {
      this.indexerForm = {
        id: null,
        name: indexerType === 'torznab' ? 'Torznab / Prowlarr' : 'Newznab Indexer',
        indexer_type: indexerType,
        host_url: 'http://localhost:9696/1/api',
        api_key: '',
        categories: '3000,3010,3020,3030,3040',
        priority: 1,
        enabled: true,
      };
      this.indexerTestResult = null;
      this.isIndexerModalOpen = true;
    },

    openEditIndexerModal(indexer) {
      this.indexerForm = {
        id: indexer.id,
        name: indexer.name,
        indexer_type: indexer.indexer_type,
        host_url: indexer.host_url,
        api_key: indexer.api_key || '',
        categories: indexer.categories || '3000,3010,3020,3030,3040',
        priority: indexer.priority ?? 1,
        enabled: Boolean(indexer.enabled),
      };
      this.indexerTestResult = null;
      this.isIndexerModalOpen = true;
    },

    closeIndexerModal() {
      this.isIndexerModalOpen = false;
      this.indexerTestResult = null;
    },

    async testIndexer() {
      this.indexerTesting = true;
      this.indexerTestResult = null;
      try {
        const res = await this.apiRequest('/api/settings/indexers/test', {
          method: 'POST',
          body: {
            indexer_type: this.indexerForm.indexer_type,
            host_url: this.indexerForm.host_url,
            api_key: this.indexerForm.api_key,
            categories: this.indexerForm.categories,
          }
        });
        this.indexerTestResult = res;
      } catch (err) {
        this.indexerTestResult = { success: false, message: err.message || 'Indexer test failed' };
      } finally {
        this.indexerTesting = false;
      }
    },

    async saveIndexer() {
      this.indexerSaving = true;
      try {
        await this.apiRequest('/api/settings/indexers', {
          method: 'POST',
          body: this.indexerForm
        });
        this.showToast('Indexer saved', 'success');
        this.closeIndexerModal();
        await this.loadIndexers();
      } catch (err) {
        this.showToast(err.message || 'Failed to save indexer', 'error');
      } finally {
        this.indexerSaving = false;
      }
    },

    async deleteIndexer(indexerId) {
      if (!confirm('Are you sure you want to delete this indexer?')) return;
      try {
        await this.apiRequest(`/api/settings/indexers/${indexerId}`, { method: 'DELETE' });
        this.showToast('Indexer removed', 'info');
        await this.loadIndexers();
      } catch (err) {
        this.showToast(err.message || 'Failed to delete indexer', 'error');
      }
    },

    async toggleIndexerEnabled(indexer) {
      try {
        await this.apiRequest('/api/settings/indexers', {
          method: 'POST',
          body: {
            id: indexer.id,
            name: indexer.name,
            indexer_type: indexer.indexer_type,
            host_url: indexer.host_url,
            enabled: !indexer.enabled,
            priority: indexer.priority,
          }
        });
        await this.loadIndexers();
      } catch (err) {
        this.showToast(err.message || 'Failed to update indexer status', 'error');
      }
    }
  }));
});
