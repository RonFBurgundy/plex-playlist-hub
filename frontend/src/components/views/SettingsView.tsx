import React, { useState, useEffect } from 'react';
import {
  Sliders,
  Folder,
  Download,
  Search,
  Radio,
  Layers,
  Activity,
  Check,
  Save,
  Loader2,
  Trash2,
  Plus,
} from 'lucide-react';
import type {
  GeneralSettings,
  QualityProfile,
  DownloadClientItem,
  IndexerItem,
  SystemStatusInfo,
} from '@/types/models';
import {
  TapeTransportBay,
  TapeDeckButton,
  MachinedCard,
  TactileSwitch,
} from '@/components/ui';
import {
  getGeneralSettings,
  updateGeneralSettings,
  getQualityProfiles,
  saveQualityProfile,
  deleteQualityProfile,
  getClientSettings,
  saveClientSettings,
  deleteClientSettings,
  testClientConnection,
  getIndexerSettings,
  saveIndexer,
  deleteIndexer,
  testIndexer,
  getSystemStatus,
} from '@/services/settingsService';

export type SettingsTab =
  | 'general'
  | 'media'
  | 'clients'
  | 'indexers'
  | 'lidarr'
  | 'profiles'
  | 'status';

export const SettingsView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const [generalSettings, setGeneralSettings] = useState<GeneralSettings | null>(null);
  const [qualityProfiles, setQualityProfiles] = useState<QualityProfile[]>([]);
  const [clients, setClients] = useState<DownloadClientItem[]>([]);
  const [indexers, setIndexers] = useState<IndexerItem[]>([]);
  const [systemStatus, setSystemStatus] = useState<SystemStatusInfo | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // New item form states
  const [newClientName, setNewClientName] = useState<string>('');
  const [newClientType, setNewClientType] = useState<DownloadClientItem['client_type']>('slskd');
  const [newClientHost, setNewClientHost] = useState<string>('localhost');
  const [newClientPort, setNewClientPort] = useState<number>(5030);

  const [newIndexerName, setNewIndexerName] = useState<string>('');
  const [newIndexerUrl, setNewIndexerUrl] = useState<string>('');
  const [newIndexerKey, setNewIndexerKey] = useState<string>('');

  const [newProfileName, setNewProfileName] = useState<string>('');
  const [newProfileCutoff, setNewProfileCutoff] = useState<number>(1);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  const loadData = async () => {
    setIsLoading(true);
    try {
      const [gen, prof, cli, idx, sys] = await Promise.all([
        getGeneralSettings().catch(() => null),
        getQualityProfiles().catch(() => []),
        getClientSettings().catch(() => []),
        getIndexerSettings().catch(() => []),
        getSystemStatus().catch(() => null),
      ]);
      if (gen) setGeneralSettings(gen);
      setQualityProfiles(prof);
      setClients(cli);
      setIndexers(idx);
      if (sys) setSystemStatus(sys);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSaveGeneral = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!generalSettings) return;
    setIsSaving(true);
    try {
      await updateGeneralSettings(generalSettings);
      showToast('Settings saved successfully');
    } catch {
      showToast('Failed to save settings');
    } finally {
      setIsSaving(false);
    }
  };

  const handleAddClient = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newClientName.trim()) return;
    setIsSaving(true);
    try {
      await saveClientSettings({
        name: newClientName.trim(),
        client_type: newClientType,
        host: newClientHost,
        port: newClientPort,
        use_ssl: false,
        is_enabled: true,
        priority: 1,
      });
      setNewClientName('');
      await loadData();
      showToast('Download client added');
    } catch {
      showToast('Failed to add client');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteClient = async (id: number) => {
    if (!confirm('Delete this download client?')) return;
    try {
      await deleteClientSettings(id);
      await loadData();
      showToast('Client deleted');
    } catch {
      showToast('Failed to delete client');
    }
  };

  const handleTestClient = async (client: DownloadClientItem) => {
    try {
      const res = await testClientConnection(client);
      showToast(res.success ? 'Connection verified!' : `Connection failed: ${res.message}`);
    } catch {
      showToast('Connection test error');
    }
  };

  const handleAddIndexer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newIndexerName.trim() || !newIndexerUrl.trim()) return;
    setIsSaving(true);
    try {
      await saveIndexer({
        name: newIndexerName.trim(),
        url: newIndexerUrl.trim(),
        api_key: newIndexerKey.trim(),
        indexer_type: 'torznab',
        is_enabled: true,
        priority: 1,
      });
      setNewIndexerName('');
      setNewIndexerUrl('');
      setNewIndexerKey('');
      await loadData();
      showToast('Indexer registered');
    } catch {
      showToast('Failed to save indexer');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteIndexer = async (id: number) => {
    if (!confirm('Delete this indexer?')) return;
    try {
      await deleteIndexer(id);
      await loadData();
      showToast('Indexer removed');
    } catch {
      showToast('Failed to delete indexer');
    }
  };

  const handleTestIndexer = async (indexer: IndexerItem) => {
    try {
      const res = await testIndexer(indexer);
      showToast(res.success ? 'Indexer responded OK' : `Indexer error: ${res.message}`);
    } catch {
      showToast('Test indexer failed');
    }
  };

  const handleAddProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProfileName.trim()) return;
    setIsSaving(true);
    try {
      await saveQualityProfile({
        name: newProfileName.trim(),
        cutoff: newProfileCutoff,
        upgrade_allowed: true,
      });
      setNewProfileName('');
      await loadData();
      showToast('Quality profile created');
    } catch {
      showToast('Failed to save profile');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteProfile = async (id: number) => {
    if (!confirm('Delete this quality profile?')) return;
    try {
      await deleteQualityProfile(id);
      await loadData();
      showToast('Profile deleted');
    } catch {
      showToast('Failed to delete profile');
    }
  };

  const subTabs: Array<{ id: SettingsTab; label: string; icon: React.ReactNode }> = [
    { id: 'general', label: 'General', icon: <Sliders className="h-3.5 w-3.5" /> },
    { id: 'media', label: 'Media', icon: <Folder className="h-3.5 w-3.5" /> },
    { id: 'clients', label: 'Clients', icon: <Download className="h-3.5 w-3.5" /> },
    { id: 'indexers', label: 'Indexers', icon: <Search className="h-3.5 w-3.5" /> },
    { id: 'lidarr', label: 'Lidarr', icon: <Radio className="h-3.5 w-3.5" /> },
    { id: 'profiles', label: 'Profiles', icon: <Layers className="h-3.5 w-3.5" /> },
    { id: 'status', label: 'Status', icon: <Activity className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="space-y-6">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-20 right-4 z-50 bg-[#161616] border border-[#e5a00d] px-4 py-2.5 rounded-[4px] text-xs font-mono text-[#e5a00d] shadow-lg flex items-center gap-2">
          <Check className="h-4 w-4" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Subtab Navigation Bar */}
      <TapeTransportBay className="flex items-center gap-1.5 overflow-x-auto">
        {subTabs.map((st) => (
          <TapeDeckButton
            key={st.id}
            size="sm"
            active={activeTab === st.id}
            onClick={() => setActiveTab(st.id)}
            icon={st.icon}
          >
            {st.label}
          </TapeDeckButton>
        ))}
      </TapeTransportBay>

      {/* Loading state */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <Loader2 className="h-8 w-8 text-[#e5a00d] animate-spin" />
          <span className="text-xs uppercase tracking-widest text-neutral-400 font-mono">
            Reading System Configuration...
          </span>
        </div>
      )}

      {/* General Settings Subtab */}
      {!isLoading && activeTab === 'general' && (
        <MachinedCard className="p-6 max-w-2xl">
          <form onSubmit={handleSaveGeneral} className="space-y-5">
            <div>
              <label className="block text-xs uppercase font-mono tracking-wider text-neutral-300 mb-1.5">
                Server Name
              </label>
              <input
                type="text"
                value={generalSettings?.server_name || ''}
                onChange={(e) =>
                  setGeneralSettings((prev) =>
                    prev ? { ...prev, server_name: e.target.value } : null
                  )
                }
                className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-3 py-2 text-sm text-white focus:outline-none focus:border-[#e5a00d]"
              />
            </div>

            <div>
              <label className="block text-xs uppercase font-mono tracking-wider text-neutral-300 mb-1.5">
                Base URL
              </label>
              <input
                type="text"
                value={generalSettings?.base_url || ''}
                onChange={(e) =>
                  setGeneralSettings((prev) =>
                    prev ? { ...prev, base_url: e.target.value } : null
                  )
                }
                className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-3 py-2 text-sm text-white focus:outline-none focus:border-[#e5a00d]"
              />
            </div>

            <div className="flex justify-end pt-3">
              <TapeDeckButton
                type="submit"
                variant="amber"
                size="md"
                disabled={isSaving}
                icon={
                  isSaving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4" />
                  )
                }
              >
                Save General Settings
              </TapeDeckButton>
            </div>
          </form>
        </MachinedCard>
      )}

      {/* Media Management Subtab */}
      {!isLoading && activeTab === 'media' && (
        <MachinedCard className="p-6 max-w-2xl space-y-4">
          <h4 className="text-sm font-bold uppercase font-mono text-white">Media Folders</h4>
          <div>
            <label className="block text-xs uppercase font-mono tracking-wider text-neutral-400 mb-1">
              Music Library Path
            </label>
            <input
              type="text"
              readOnly
              value={generalSettings?.music_directory || '/data/media/music'}
              className="w-full bg-[#0d0d0d] border border-[#222222] rounded-[3px] px-3 py-2 text-sm text-neutral-400 font-mono"
            />
          </div>
        </MachinedCard>
      )}

      {/* Download Clients Subtab */}
      {!isLoading && activeTab === 'clients' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {clients.map((c) => (
              <MachinedCard key={c.id} className="p-4 flex items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm text-white">{c.name}</span>
                    <span className="px-1.5 py-0.5 rounded-[2px] bg-[#1a1a1a] text-[10px] font-mono uppercase text-[#e5a00d]">
                      {c.client_type}
                    </span>
                  </div>
                  <p className="text-xs text-neutral-400 font-mono mt-1">
                    {c.host}:{c.port}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <TapeDeckButton
                    size="sm"
                    onClick={() => handleTestClient(c)}
                  >
                    Test
                  </TapeDeckButton>
                  <TapeDeckButton
                    size="sm"
                    variant="danger"
                    onClick={() => handleDeleteClient(c.id)}
                    icon={<Trash2 className="h-3 w-3" />}
                    aria-label="Delete client"
                  />
                </div>
              </MachinedCard>
            ))}
          </div>

          <MachinedCard className="p-5 max-w-xl">
            <h4 className="text-xs font-bold uppercase font-mono text-white mb-4">
              Add Download Client
            </h4>
            <form onSubmit={handleAddClient} className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-mono text-neutral-300 mb-1">Name</label>
                  <input
                    type="text"
                    required
                    value={newClientName}
                    onChange={(e) => setNewClientName(e.target.value)}
                    placeholder="e.g. Local Soulseek"
                    className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-2.5 py-1.5 text-xs text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-mono text-neutral-300 mb-1">Type</label>
                  <select
                    value={newClientType}
                    onChange={(e) =>
                      setNewClientType(e.target.value as DownloadClientItem['client_type'])
                    }
                    className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-2.5 py-1.5 text-xs text-white"
                  >
                    <option value="slskd">slskd</option>
                    <option value="sabnzbd">SABnzbd</option>
                    <option value="qbittorrent">qBittorrent</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-mono text-neutral-300 mb-1">Host</label>
                  <input
                    type="text"
                    required
                    value={newClientHost}
                    onChange={(e) => setNewClientHost(e.target.value)}
                    className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-2.5 py-1.5 text-xs text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-mono text-neutral-300 mb-1">Port</label>
                  <input
                    type="number"
                    required
                    value={newClientPort}
                    onChange={(e) => setNewClientPort(Number(e.target.value))}
                    className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-2.5 py-1.5 text-xs text-white"
                  />
                </div>
              </div>

              <div className="flex justify-end pt-2">
                <TapeDeckButton
                  type="submit"
                  size="sm"
                  variant="amber"
                  disabled={isSaving}
                  icon={<Plus className="h-3.5 w-3.5" />}
                >
                  Add Client
                </TapeDeckButton>
              </div>
            </form>
          </MachinedCard>
        </div>
      )}

      {/* Indexers Subtab */}
      {!isLoading && activeTab === 'indexers' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {indexers.map((idx) => (
              <MachinedCard key={idx.id} className="p-4 flex items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm text-white">{idx.name}</span>
                    <span className="px-1.5 py-0.5 rounded-[2px] bg-[#1a1a1a] text-[10px] font-mono uppercase text-[#e5a00d]">
                      {idx.indexer_type}
                    </span>
                  </div>
                  <p className="text-xs text-neutral-400 font-mono mt-1 truncate max-w-xs">
                    {idx.url}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <TapeDeckButton
                    size="sm"
                    onClick={() => handleTestIndexer(idx)}
                  >
                    Test
                  </TapeDeckButton>
                  <TapeDeckButton
                    size="sm"
                    variant="danger"
                    onClick={() => handleDeleteIndexer(idx.id)}
                    icon={<Trash2 className="h-3 w-3" />}
                    aria-label="Delete indexer"
                  />
                </div>
              </MachinedCard>
            ))}
          </div>

          <MachinedCard className="p-5 max-w-xl">
            <h4 className="text-xs font-bold uppercase font-mono text-white mb-4">
              Add New Indexer (Torznab / Newznab)
            </h4>
            <form onSubmit={handleAddIndexer} className="space-y-4">
              <div>
                <label className="block text-[11px] font-mono text-neutral-300 mb-1">Name</label>
                <input
                  type="text"
                  required
                  value={newIndexerName}
                  onChange={(e) => setNewIndexerName(e.target.value)}
                  placeholder="e.g. Redacted Torznab"
                  className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-2.5 py-1.5 text-xs text-white"
                />
              </div>

              <div>
                <label className="block text-[11px] font-mono text-neutral-300 mb-1">URL</label>
                <input
                  type="url"
                  required
                  value={newIndexerUrl}
                  onChange={(e) => setNewIndexerUrl(e.target.value)}
                  placeholder="http://prowlarr:9696/1/api"
                  className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-2.5 py-1.5 text-xs text-white"
                />
              </div>

              <div>
                <label className="block text-[11px] font-mono text-neutral-300 mb-1">API Key</label>
                <input
                  type="password"
                  value={newIndexerKey}
                  onChange={(e) => setNewIndexerKey(e.target.value)}
                  className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-2.5 py-1.5 text-xs text-white"
                />
              </div>

              <div className="flex justify-end pt-2">
                <TapeDeckButton
                  type="submit"
                  size="sm"
                  variant="amber"
                  disabled={isSaving}
                  icon={<Plus className="h-3.5 w-3.5" />}
                >
                  Save Indexer
                </TapeDeckButton>
              </div>
            </form>
          </MachinedCard>
        </div>
      )}

      {/* Lidarr Subtab */}
      {!isLoading && activeTab === 'lidarr' && (
        <MachinedCard className="p-6 max-w-2xl space-y-4">
          <h4 className="text-sm font-bold uppercase font-mono text-white">Lidarr Integration</h4>
          <div>
            <label className="block text-xs uppercase font-mono tracking-wider text-neutral-300 mb-1.5">
              Lidarr URL
            </label>
            <input
              type="text"
              value={generalSettings?.lidarr_url || ''}
              onChange={(e) =>
                setGeneralSettings((prev) =>
                  prev ? { ...prev, lidarr_url: e.target.value } : null
                )
              }
              placeholder="http://localhost:8686"
              className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-3 py-2 text-sm text-white focus:outline-none focus:border-[#e5a00d]"
            />
          </div>

          <div>
            <label className="block text-xs uppercase font-mono tracking-wider text-neutral-300 mb-1.5">
              Lidarr API Key
            </label>
            <input
              type="password"
              value={generalSettings?.lidarr_api_key || ''}
              onChange={(e) =>
                setGeneralSettings((prev) =>
                  prev ? { ...prev, lidarr_api_key: e.target.value } : null
                )
              }
              className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-3 py-2 text-sm text-white focus:outline-none focus:border-[#e5a00d]"
            />
          </div>

          <div className="flex justify-end pt-3">
            <TapeDeckButton
              type="button"
              variant="amber"
              size="md"
              onClick={handleSaveGeneral}
              disabled={isSaving}
              icon={<Save className="h-4 w-4" />}
            >
              Save Lidarr Config
            </TapeDeckButton>
          </div>
        </MachinedCard>
      )}

      {/* Quality Profiles Subtab */}
      {!isLoading && activeTab === 'profiles' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {qualityProfiles.map((p) => (
              <MachinedCard key={p.id} className="p-4 flex items-center justify-between gap-3">
                <div>
                  <span className="font-bold text-sm text-white">{p.name}</span>
                  <p className="text-xs text-neutral-400 font-mono mt-1">
                    Cutoff Tier: {p.cutoff}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <TactileSwitch
                    checked={Boolean(p.upgrade_allowed)}
                    onChange={() => {}}
                    label="Upgrade"
                  />
                  <TapeDeckButton
                    size="sm"
                    variant="danger"
                    onClick={() => handleDeleteProfile(p.id)}
                    icon={<Trash2 className="h-3 w-3" />}
                    aria-label="Delete profile"
                  />
                </div>
              </MachinedCard>
            ))}
          </div>

          <MachinedCard className="p-5 max-w-xl">
            <h4 className="text-xs font-bold uppercase font-mono text-white mb-4">
              Add Quality Profile
            </h4>
            <form onSubmit={handleAddProfile} className="space-y-4">
              <div>
                <label className="block text-[11px] font-mono text-neutral-300 mb-1">
                  Profile Name
                </label>
                <input
                  type="text"
                  required
                  value={newProfileName}
                  onChange={(e) => setNewProfileName(e.target.value)}
                  placeholder="e.g. FLAC Lossless Only"
                  className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-2.5 py-1.5 text-xs text-white"
                />
              </div>

              <div>
                <label className="block text-[11px] font-mono text-neutral-300 mb-1">
                  Cutoff Score / Level
                </label>
                <input
                  type="number"
                  required
                  value={newProfileCutoff}
                  onChange={(e) => setNewProfileCutoff(Number(e.target.value))}
                  className="w-full bg-[#0d0d0d] border border-[#2a2a2a] rounded-[3px] px-2.5 py-1.5 text-xs text-white"
                />
              </div>

              <div className="flex justify-end pt-2">
                <TapeDeckButton
                  type="submit"
                  size="sm"
                  variant="amber"
                  disabled={isSaving}
                  icon={<Plus className="h-3.5 w-3.5" />}
                >
                  Create Profile
                </TapeDeckButton>
              </div>
            </form>
          </MachinedCard>
        </div>
      )}

      {/* System Status Subtab */}
      {!isLoading && activeTab === 'status' && (
        <MachinedCard className="p-6 max-w-2xl space-y-4">
          <h4 className="text-sm font-bold uppercase font-mono text-white">System Diagnostics</h4>
          <div className="divide-y divide-[#1f1f1f] text-xs font-mono">
            <div className="py-2.5 flex justify-between">
              <span className="text-neutral-400">TrackSeerr Version:</span>
              <span className="text-white">{systemStatus?.version || '1.0.0'}</span>
            </div>
            <div className="py-2.5 flex justify-between">
              <span className="text-neutral-400">Database Engine:</span>
              <span className="text-green-400">{systemStatus?.database_status || 'SQLite OK'}</span>
            </div>
            <div className="py-2.5 flex justify-between">
              <span className="text-neutral-400">Plex Server Connection:</span>
              <span className={systemStatus?.plex_connected ? 'text-green-400' : 'text-neutral-400'}>
                {systemStatus?.plex_connected ? 'Connected' : 'Configured'}
              </span>
            </div>
            <div className="py-2.5 flex justify-between">
              <span className="text-neutral-400">Lidarr Connection:</span>
              <span className={systemStatus?.lidarr_connected ? 'text-green-400' : 'text-neutral-500'}>
                {systemStatus?.lidarr_connected ? 'Connected' : 'Standalone Mode'}
              </span>
            </div>
          </div>
        </MachinedCard>
      )}
    </div>
  );
};
