/**
 * Plex Playlist Hub - Alpine.js Application Controller & API Client
 * Zero-build, responsive single-page dashboard.
 */

document.addEventListener('alpine:init', () => {
  Alpine.data('plexHubApp', () => ({
    // Auth State
    isAuthenticated: false,
    currentUser: null,
    authToken: localStorage.getItem('plex_hub_token') || '',
    isLoading: true,

    // PIN Flow State
    pin: null,
    pinPollingTimer: null,
    pinError: '',
    isGeneratingPin: false,

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

    // Add Playlist Form State
    addForm: {
      url_or_id: '',
      service: '',
      targets: []
    },
    addLoading: false,
    addError: '',

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

    // Toast Notifications
    toasts: [],
    statusPollTimer: null,

    // Lifecycle
    init() {
      this.checkAuth();
      // Periodically poll sync status every 6 seconds
      this.statusPollTimer = setInterval(() => {
        if (this.isAuthenticated) {
          this.fetchSyncStatus();
        }
      }, 6000);
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
          this.initSSE();
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
      localStorage.removeItem('plex_hub_token');
      this.closeSSE();
      this.startPinFlow();
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
            clearInterval(this.pinPollingTimer);
            this.pinPollingTimer = null;
            const data = await res.json();
            if (data.token) {
              this.authToken = data.token;
              localStorage.setItem('plex_hub_token', data.token);
            }
            this.currentUser = data.user;
            this.isAuthenticated = true;
            this.pin = null;
            this.showToast(`Signed in as ${this.currentUser.username}`, 'success');
            this.loadDashboardData();
            this.initSSE();
          } else if (res.status === 403) {
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
        this.fetchMissingTracks()
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
    openAddModal() {
      const initialTargets = this.currentUser ? [String(this.currentUser.id)] : [];
      this.addForm = {
        url_or_id: '',
        service: '',
        targets: initialTargets
      };
      this.addError = '';
      this.addLoading = false;
      this.isAddModalOpen = true;
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
    }
  }));
});
