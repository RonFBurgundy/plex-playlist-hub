/**
 * Plex Playlist Hub - Alpine.js Application Controller & API Client
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

    // Add Playlist Form State
    addTab: 'link', // 'link' | 'paste' | 'helper'
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
          this.initSSE();
          this.checkHashImport();
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
        this.fetchLidarrStatus()
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
      this.parsedTracks = [];
      this.showParsedPreview = false;
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

    // Paste & Direct Import Handling
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
      const script = `javascript:(function(){try{const h=document.querySelector('h1'),name=(h?h.innerText:document.title.replace(/\\s*\\|\\s*Spotify.*$/i,'')).trim()||'Spotify Playlist',rows=document.querySelectorAll('[data-testid="tracklist-row"]'),tracks=[];rows.forEach(r=>{const t=r.querySelector('[data-testid="internal-track-link"],div[aria-colindex="2"] a,a[href*="/track/"]'),arts=r.querySelectorAll('a[href*="/artist/"]'),alb=r.querySelector('a[href*="/album/"]'),title=t?t.innerText.trim():'',artists=Array.from(arts).map(a=>a.innerText.trim()).filter(Boolean),artist=artists.join(', ')||'Unknown Artist',album=alb?alb.innerText.trim():'';if(title){tracks.push({title,artist,album})}});if(!tracks.length){alert('Plex Playlist Hub: No tracks detected. Make sure you are on a Spotify playlist and scroll down to load songs!');return}const payload=JSON.stringify({name,tracks});navigator.clipboard.writeText(payload).then(()=>{window.open('${origin}/#import=clipboard','_blank')}).catch(()=>{prompt('Copy track data manually:',payload)})}catch(e){alert('Plex Playlist Hub: '+e.message)}})();`;
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

    getLidarrListUrl() {
      const base = window.location.origin;
      return this.selectedMissingPlaylistId 
        ? `${base}/api/missing/lidarr?playlist_id=${encodeURIComponent(this.selectedMissingPlaylistId)}`
        : `${base}/api/missing/lidarr`;
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

    async pushAllToLidarr() {
      if (this.isPushingLidarr) return;
      this.isPushingLidarr = true;
      try {
        const payload = {
          playlist_id: this.selectedMissingPlaylistId || null,
          auto_search: true
        };
        const res = await this.apiRequest('/api/missing/lidarr/push', {
          method: 'POST',
          body: payload
        });
        this.showToast(`Lidarr Push: ${res.added_to_lidarr} added, ${res.already_monitored} existing, ${res.failed} failed`, 'success');
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
          auto_search: true
        };
        const res = await this.apiRequest('/api/missing/lidarr/push', {
          method: 'POST',
          body: payload
        });
        if (res.added_to_lidarr > 0) {
          this.showToast('Queued in Lidarr successfully', 'success');
        } else if (res.already_monitored > 0) {
          this.showToast('Already monitored in Lidarr', 'info');
        } else {
          this.showToast('Failed to queue in Lidarr', 'error');
        }
      } catch (err) {
        this.showToast(`Lidarr queue failed: ${err.message}`, 'error');
      } finally {
        this.pushingTrackId = null;
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
    }
  }));
});
