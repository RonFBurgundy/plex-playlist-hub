import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  RefreshCw,
  Play,
  X,
  RotateCcw,
  DownloadCloud,
  AlertTriangle,
  Loader2,
  List,
  Activity,
  Terminal,
  Search,
  Trash2,
  Download,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import type { UseQueueReturn } from '@/hooks/useQueue';
import type { SystemEventItem, SystemLogItem } from '@/types/models';
import {
  getSystemEvents,
  clearSystemEvents,
  getSystemLogs,
  clearSystemLogs,
} from '@/services/systemService';
import { getAuthToken } from '@/services/apiClient';
import {
  TapeTransportBay,
  TapeDeckButton,
  MachinedCard,
} from '@/components/ui';

export interface ActivityViewProps {
  queueHook: UseQueueReturn;
}

type ActivitySubTab = 'queue' | 'events' | 'logs';

export const ActivityView: React.FC<ActivityViewProps> = ({
  queueHook,
}) => {
  const {
    queueItems,
    backlogStatus,
    isLoading: isQueueLoading,
    error: queueError,
    cancelItem,
    retryItem,
    triggerBacklogSearch,
    refresh: refreshQueue,
  } = queueHook;

  // Active Sub-tab state
  const [activitySubTab, setActivitySubTab] = useState<ActivitySubTab>('queue');

  // Queue tab state
  const [busyId, setBusyId] = useState<string | null>(null);
  const [isTriggeringBacklog, setIsTriggeringBacklog] = useState<boolean>(false);

  // ---------------------------------------------------------------------------
  // Events tab state
  // ---------------------------------------------------------------------------
  const [events, setEvents] = useState<SystemEventItem[]>([]);
  const [totalEvents, setTotalEvents] = useState<number>(0);
  const [eventsPage, setEventsPage] = useState<number>(1);
  const eventsPageSize = 50;
  const [eventsLoading, setEventsLoading] = useState<boolean>(false);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [eventSeverityFilter, setEventSeverityFilter] = useState<string>('all');
  const [eventTypeFilter, setEventTypeFilter] = useState<string>('all');
  const [eventSearchInput, setEventSearchInput] = useState<string>('');
  const [activeEventSearch, setActiveEventSearch] = useState<string>('');
  const [clearingEvents, setClearingEvents] = useState<boolean>(false);

  // ---------------------------------------------------------------------------
  // Logs tab state
  // ---------------------------------------------------------------------------
  const [logs, setLogs] = useState<SystemLogItem[]>([]);
  const [isLogsConnected, setIsLogsConnected] = useState<boolean>(false);
  const [logLevelFilter, setLogLevelFilter] = useState<string>('all');
  const [logSearchTerm, setLogSearchTerm] = useState<string>('');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [clearingLogs, setClearingLogs] = useState<boolean>(false);
  const [downloadingLogs, setDownloadingLogs] = useState<boolean>(false);
  const logsContainerRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // ---------------------------------------------------------------------------
  // Queue Handlers
  // ---------------------------------------------------------------------------
  const handleCancel = async (id: string) => {
    if (!confirm('Are you sure you want to cancel and remove this download?')) return;
    setBusyId(id);
    try {
      await cancelItem(id);
    } finally {
      setBusyId(null);
    }
  };

  const handleRetry = async (id: string) => {
    setBusyId(id);
    try {
      await retryItem(id);
    } finally {
      setBusyId(null);
    }
  };

  const handleBacklogClick = async () => {
    setIsTriggeringBacklog(true);
    try {
      await triggerBacklogSearch();
    } finally {
      setIsTriggeringBacklog(false);
    }
  };

  const formatBytes = (bytes?: number) => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  // ---------------------------------------------------------------------------
  // Events Fetching
  // ---------------------------------------------------------------------------
  const fetchEvents = useCallback(async (page: number = 1) => {
    setEventsLoading(true);
    setEventsError(null);
    try {
      const res = await getSystemEvents({
        page,
        page_size: eventsPageSize,
        event_type: eventTypeFilter !== 'all' ? eventTypeFilter : undefined,
        severity: eventSeverityFilter !== 'all' ? eventSeverityFilter : undefined,
        search: activeEventSearch.trim() || undefined,
      });
      setEvents(res.items || []);
      setTotalEvents(res.total || 0);
      setEventsPage(res.page || 1);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch system events';
      setEventsError(msg);
    } finally {
      setEventsLoading(false);
    }
  }, [eventsPageSize, eventTypeFilter, eventSeverityFilter, activeEventSearch]);

  useEffect(() => {
    if (activitySubTab === 'events') {
      fetchEvents(eventsPage);
    }
  }, [activitySubTab, eventsPage, eventTypeFilter, eventSeverityFilter, activeEventSearch, fetchEvents]);

  const handleEventSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setEventsPage(1);
    setActiveEventSearch(eventSearchInput);
  };

  const handleClearEvents = async () => {
    if (!confirm('Are you sure you want to clear all recorded system events?')) return;
    setClearingEvents(true);
    try {
      await clearSystemEvents();
      setEventsPage(1);
      await fetchEvents(1);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to clear system events');
    } finally {
      setClearingEvents(false);
    }
  };

  const totalEventPages = Math.max(1, Math.ceil(totalEvents / eventsPageSize));

  // ---------------------------------------------------------------------------
  // Logs Streaming & Controls
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (activitySubTab !== 'logs') {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
        setIsLogsConnected(false);
      }
      return;
    }

    // 1. Initial snapshot load
    let isSubscribed = true;
    getSystemLogs({ limit: 300 })
      .then((initial) => {
        if (isSubscribed && initial) {
          setLogs(initial);
        }
      })
      .catch((err) => {
        console.warn('Initial system logs load failed:', err);
      });

    // 2. Setup SSE connection
    const token = getAuthToken();
    const streamUrl = token
      ? `/api/system/logs/stream?token=${encodeURIComponent(token)}`
      : '/api/system/logs/stream';

    const es = new EventSource(streamUrl);
    eventSourceRef.current = es;

    es.onopen = () => {
      if (isSubscribed) setIsLogsConnected(true);
    };

    es.onmessage = (event) => {
      if (!isSubscribed) return;
      try {
        const item: SystemLogItem = JSON.parse(event.data);
        if (item && item.message) {
          setLogs((prev) => {
            const next = [...prev, item];
            return next.length > 1000 ? next.slice(next.length - 1000) : next;
          });
        }
      } catch {
        // Ping or non-json frame
      }
    };

    es.onerror = () => {
      if (isSubscribed) setIsLogsConnected(false);
    };

    return () => {
      isSubscribed = false;
      es.close();
      eventSourceRef.current = null;
      setIsLogsConnected(false);
    };
  }, [activitySubTab]);

  // Auto-scroll logic for log terminal
  useEffect(() => {
    if (activitySubTab === 'logs' && autoScroll && logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [logs, autoScroll, activitySubTab]);

  const handleClearLogs = async () => {
    setClearingLogs(true);
    try {
      await clearSystemLogs();
      setLogs([]);
    } catch (err: unknown) {
      console.warn('Failed to clear logs on server, clearing locally:', err);
      setLogs([]);
    } finally {
      setClearingLogs(false);
    }
  };

  const handleDownloadLogs = async () => {
    setDownloadingLogs(true);
    try {
      const token = getAuthToken();
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch('/api/system/logs/download', { headers });
      if (!res.ok) {
        throw new Error(`Download failed with status ${res.status}`);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'trackseerr.log';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to download logs');
    } finally {
      setDownloadingLogs(false);
    }
  };

  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      if (logLevelFilter !== 'all') {
        const lvl = (log.level || '').toLowerCase();
        const target = logLevelFilter.toLowerCase();
        if (target === 'warning' && lvl !== 'warn' && lvl !== 'warning') return false;
        if (target !== 'warning' && lvl !== target) return false;
      }
      if (logSearchTerm.trim()) {
        const s = logSearchTerm.toLowerCase();
        const msg = (log.message || '').toLowerCase();
        const nm = (log.name || '').toLowerCase();
        return msg.includes(s) || nm.includes(s);
      }
      return true;
    });
  }, [logs, logLevelFilter, logSearchTerm]);

  // Event severity badge style helper
  const getSeverityBadge = (severity: string) => {
    const s = (severity || 'info').toLowerCase();
    if (s === 'error') {
      return (
        <span className="px-1.5 py-0.5 rounded-[2px] bg-red-950/80 border border-red-800 text-[10px] font-mono uppercase text-red-300">
          ERROR
        </span>
      );
    }
    if (s === 'warn' || s === 'warning') {
      return (
        <span className="px-1.5 py-0.5 rounded-[2px] bg-amber-950/80 border border-amber-800 text-[10px] font-mono uppercase text-amber-300">
          WARN
        </span>
      );
    }
    return (
      <span className="px-1.5 py-0.5 rounded-[2px] bg-neutral-900 border border-neutral-700 text-[10px] font-mono uppercase text-neutral-300">
        INFO
      </span>
    );
  };

  // Event type badge style helper
  const getEventTypeBadge = (eventType: string) => {
    let colorClasses = 'bg-[#1a1a1a] border-[#2a2a2a] text-[#e5a00d]';
    if (eventType.includes('completed') || eventType.includes('available')) {
      colorClasses = 'bg-emerald-950/50 border-emerald-800/60 text-emerald-400';
    } else if (eventType.includes('failed')) {
      colorClasses = 'bg-red-950/50 border-red-800/60 text-red-400';
    } else if (eventType.includes('sync')) {
      colorClasses = 'bg-sky-950/50 border-sky-800/60 text-sky-400';
    } else if (eventType.includes('sweep')) {
      colorClasses = 'bg-purple-950/50 border-purple-800/60 text-purple-400';
    }

    return (
      <span className={`px-2 py-0.5 rounded-[2px] border text-[10px] font-mono uppercase whitespace-nowrap ${colorClasses}`}>
        {eventType}
      </span>
    );
  };

  return (
    <div className="space-y-6">
      {/* Top Controls & Sub-Tab Navigation Bay */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
        {/* Main 3-Tab Selector */}
        <TapeTransportBay className="flex items-center gap-1.5 p-1 bg-[#0d0d0d] border border-[#222222] rounded-[4px]">
          <TapeDeckButton
            size="sm"
            active={activitySubTab === 'queue'}
            onClick={() => setActivitySubTab('queue')}
            icon={<List className="h-3.5 w-3.5" />}
          >
            Queue {queueItems.length > 0 && `(${queueItems.length})`}
          </TapeDeckButton>
          <TapeDeckButton
            size="sm"
            active={activitySubTab === 'events'}
            onClick={() => setActivitySubTab('events')}
            icon={<Activity className="h-3.5 w-3.5" />}
          >
            Events
          </TapeDeckButton>
          <TapeDeckButton
            size="sm"
            active={activitySubTab === 'logs'}
            onClick={() => setActivitySubTab('logs')}
            icon={<Terminal className="h-3.5 w-3.5" />}
          >
            Logs
          </TapeDeckButton>
        </TapeTransportBay>

        {/* Tab-Specific Action Controls */}
        <div className="flex items-center gap-2">
          {activitySubTab === 'queue' && (
            <TapeTransportBay className="flex items-center gap-2">
              <TapeDeckButton
                size="sm"
                onClick={refreshQueue}
                icon={<RefreshCw className="h-3.5 w-3.5" />}
              >
                Refresh Queue
              </TapeDeckButton>

                <TapeDeckButton
                  size="sm"
                  variant="amber"
                  onClick={handleBacklogClick}
                  disabled={isTriggeringBacklog || backlogStatus?.is_running}
                  icon={
                    isTriggeringBacklog ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="h-3.5 w-3.5" />
                    )
                  }
                >
                  {backlogStatus?.is_running ? 'Backlog Running...' : 'Trigger Backlog Search'}
                </TapeDeckButton>
            </TapeTransportBay>
          )}

          {activitySubTab === 'events' && (
            <TapeTransportBay className="flex items-center gap-2">
              <TapeDeckButton
                size="sm"
                onClick={() => fetchEvents(eventsPage)}
                disabled={eventsLoading}
                icon={<RefreshCw className={`h-3.5 w-3.5 ${eventsLoading ? 'animate-spin' : ''}`} />}
              >
                Refresh
              </TapeDeckButton>

                <TapeDeckButton
                  size="sm"
                  variant="danger"
                  onClick={handleClearEvents}
                  disabled={clearingEvents || totalEvents === 0}
                  icon={clearingEvents ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                >
                  Clear Events
                </TapeDeckButton>
            </TapeTransportBay>
          )}

          {activitySubTab === 'logs' && (
            <TapeTransportBay className="flex items-center gap-2">
              <TapeDeckButton
                size="sm"
                onClick={handleDownloadLogs}
                disabled={downloadingLogs}
                icon={downloadingLogs ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
              >
                Download Log File
              </TapeDeckButton>

              <TapeDeckButton
                size="sm"
                variant="danger"
                onClick={handleClearLogs}
                disabled={clearingLogs || logs.length === 0}
                icon={clearingLogs ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              >
                Clear Logs
              </TapeDeckButton>
            </TapeTransportBay>
          )}
        </div>
      </div>

      {/* =====================================================================
          TAB 1: QUEUE
         ===================================================================== */}
      {activitySubTab === 'queue' && (
        <div className="space-y-6">
          {/* Backlog Worker Status Banner */}
          {backlogStatus && (
            <div className="p-3 bg-[#121212] border border-[#222222] rounded-[4px] flex items-center justify-between text-xs font-mono">
              <div className="flex items-center gap-2">
                <DownloadCloud className="h-4 w-4 text-[#e5a00d]" />
                <span className="text-neutral-300">
                  Backlog Worker: {backlogStatus.total_missing} missing releases tracked, {backlogStatus.in_progress} actively searching
                </span>
              </div>
              {backlogStatus.last_run && (
                <span className="text-neutral-500 text-[10px]">
                  Last run: {new Date(backlogStatus.last_run).toLocaleTimeString()}
                </span>
              )}
            </div>
          )}

          {/* Loading state */}
          {isQueueLoading && (
            <div className="flex flex-col items-center justify-center py-16 gap-3">
              <Loader2 className="h-8 w-8 text-[#e5a00d] animate-spin" />
              <span className="text-xs uppercase tracking-widest text-neutral-400 font-mono">
                Interrogating Download Clients...
              </span>
            </div>
          )}

          {/* Error state */}
          {queueError && !isQueueLoading && (
            <div className="p-4 bg-red-950/40 border border-red-800/50 rounded-[4px] text-xs text-red-300 font-mono flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{queueError}</span>
            </div>
          )}

          {/* Empty state */}
          {!isQueueLoading && queueItems.length === 0 && !queueError && (
            <div className="text-center py-16 text-neutral-500 font-mono text-sm">
              Download queue is currently empty.
            </div>
          )}

          {/* Active Queue cards */}
          {!isQueueLoading && queueItems.length > 0 && (
            <div className="space-y-3">
              {queueItems.map((item) => {
                const isBusy = busyId === item.id;
                const progressVal = item.progress !== undefined ? Math.round(item.progress) : 0;

                return (
                  <MachinedCard key={item.id} className="p-4 space-y-3">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="px-2 py-0.5 rounded-[2px] bg-[#1a1a1a] border border-[#2a2a2a] text-[10px] font-mono uppercase text-[#e5a00d]">
                            {item.protocol || item.download_client || 'Direct'}
                          </span>
                          <span className="text-xs font-mono text-neutral-400 uppercase">
                            {item.status}
                          </span>
                        </div>

                        <h4 className="font-bold text-sm text-white truncate" title={item.title}>
                          {item.title}
                        </h4>

                        {item.artist && (
                          <p className="text-xs text-neutral-400 truncate mt-0.5">
                            {item.artist} {item.album ? `— ${item.album}` : ''}
                          </p>
                        )}

                        {item.error_message && (
                          <p className="text-xs text-red-400 font-mono mt-1">
                            Error: {item.error_message}
                          </p>
                        )}
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <TapeDeckButton
                          size="sm"
                          variant="amber"
                          disabled={isBusy}
                          onClick={() => handleRetry(item.id)}
                          icon={<RotateCcw className="h-3 w-3" />}
                          aria-label="Retry download"
                        />
                        <TapeDeckButton
                          size="sm"
                          variant="danger"
                          disabled={isBusy}
                          onClick={() => handleCancel(item.id)}
                          icon={<X className="h-3 w-3" />}
                          aria-label="Cancel download"
                        />
                      </div>
                    </div>

                    {/* Progress bar */}
                    <div className="space-y-1">
                      <div className="flex justify-between text-[11px] font-mono text-neutral-400">
                        <span>{progressVal}%</span>
                        <span>
                          {item.size ? formatBytes(item.size) : ''}{' '}
                          {item.timeleft ? `· ETA: ${item.timeleft}` : ''}
                        </span>
                      </div>
                      <div className="w-full h-1.5 bg-[#0d0d0d] rounded-full overflow-hidden border border-[#1f1f1f]">
                        <div
                          className="h-full bg-[#e5a00d] transition-all duration-300"
                          style={{ width: `${progressVal}%` }}
                        />
                      </div>
                    </div>
                  </MachinedCard>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* =====================================================================
          TAB 2: EVENTS
         ===================================================================== */}
      {activitySubTab === 'events' && (
        <div className="space-y-4">
          {/* Filters & Search Toolbar */}
          <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 p-3 bg-[#101010] border border-[#222222] rounded-[4px]">
            {/* Search Input */}
            <form onSubmit={handleEventSearchSubmit} className="flex items-center gap-2 flex-1 max-w-md">
              <div className="relative flex-1">
                <Search className="h-3.5 w-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
                <input
                  type="text"
                  placeholder="Filter event message or source..."
                  value={eventSearchInput}
                  onChange={(e) => setEventSearchInput(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 bg-[#171717] border border-[#262626] rounded-[3px] text-xs font-mono text-neutral-200 placeholder-neutral-500 focus:outline-none focus:border-[#e5a00d]"
                />
              </div>
              <TapeDeckButton size="sm" type="submit">
                Search
              </TapeDeckButton>
            </form>

            {/* Severity & Type Selectors */}
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 text-xs font-mono text-neutral-400">
                <span>Severity:</span>
                <select
                  value={eventSeverityFilter}
                  onChange={(e) => {
                    setEventSeverityFilter(e.target.value);
                    setEventsPage(1);
                  }}
                  className="bg-[#171717] border border-[#262626] text-neutral-200 text-xs font-mono rounded-[3px] px-2 py-1 focus:outline-none focus:border-[#e5a00d]"
                >
                  <option value="all">All</option>
                  <option value="info">Info</option>
                  <option value="warn">Warning</option>
                  <option value="error">Error</option>
                </select>
              </div>

              <div className="flex items-center gap-1.5 text-xs font-mono text-neutral-400">
                <span>Type:</span>
                <select
                  value={eventTypeFilter}
                  onChange={(e) => {
                    setEventTypeFilter(e.target.value);
                    setEventsPage(1);
                  }}
                  className="bg-[#171717] border border-[#262626] text-neutral-200 text-xs font-mono rounded-[3px] px-2 py-1 focus:outline-none focus:border-[#e5a00d]"
                >
                  <option value="all">All Types</option>
                  <option value="scan_started">scan_started</option>
                  <option value="scan_completed">scan_completed</option>
                  <option value="download_started">download_started</option>
                  <option value="download_failed">download_failed</option>
                  <option value="item_available">item_available</option>
                  <option value="backlog_sweep">backlog_sweep</option>
                  <option value="rss_synced">rss_synced</option>
                  <option value="sync_completed">sync_completed</option>
                </select>
              </div>
            </div>
          </div>

          {/* Events Error */}
          {eventsError && (
            <div className="p-3 bg-red-950/40 border border-red-800/50 rounded-[4px] text-xs text-red-300 font-mono flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{eventsError}</span>
            </div>
          )}

          {/* Events Table */}
          <MachinedCard className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr className="bg-[#141414] border-b border-[#222222] text-neutral-400 uppercase tracking-wider text-[11px]">
                    <th className="py-2.5 px-3 whitespace-nowrap">Timestamp</th>
                    <th className="py-2.5 px-3">Type</th>
                    <th className="py-2.5 px-3">Severity</th>
                    <th className="py-2.5 px-3">Source</th>
                    <th className="py-2.5 px-3">Message</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1e1e1e]">
                  {eventsLoading && events.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-12 text-center text-neutral-500">
                        <Loader2 className="h-5 w-5 text-[#e5a00d] animate-spin inline-block mr-2" />
                        Loading system events...
                      </td>
                    </tr>
                  )}

                  {!eventsLoading && events.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-12 text-center text-neutral-500">
                        No system lifecycle events recorded matching current filters.
                      </td>
                    </tr>
                  )}

                  {events.map((ev) => (
                    <tr key={ev.id} className="hover:bg-[#151515] transition-colors">
                      <td className="py-2 px-3 text-neutral-400 whitespace-nowrap text-[11px]">
                        {ev.created_at}
                      </td>
                      <td className="py-2 px-3">
                        {getEventTypeBadge(ev.event_type)}
                      </td>
                      <td className="py-2 px-3">
                        {getSeverityBadge(ev.severity)}
                      </td>
                      <td className="py-2 px-3 text-neutral-300 font-bold text-[11px] whitespace-nowrap">
                        {ev.source}
                      </td>
                      <td className="py-2 px-3 text-neutral-200 break-words max-w-xl">
                        {ev.message}
                        {ev.details && Object.keys(ev.details).length > 0 && (
                          <div className="mt-1 text-[10px] text-neutral-400 bg-[#0d0d0d] p-1.5 rounded border border-[#1f1f1f] overflow-x-auto">
                            {JSON.stringify(ev.details)}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination footer */}
            <div className="flex items-center justify-between p-3 bg-[#121212] border-t border-[#222222] text-xs font-mono">
              <span className="text-neutral-400">
                Page {eventsPage} of {totalEventPages} ({totalEvents} total events)
              </span>

              <div className="flex items-center gap-2">
                <TapeDeckButton
                  size="sm"
                  disabled={eventsPage <= 1 || eventsLoading}
                  onClick={() => setEventsPage((p) => Math.max(1, p - 1))}
                  icon={<ChevronLeft className="h-3 w-3" />}
                >
                  Previous
                </TapeDeckButton>

                <TapeDeckButton
                  size="sm"
                  disabled={eventsPage >= totalEventPages || eventsLoading}
                  onClick={() => setEventsPage((p) => p + 1)}
                  icon={<ChevronRight className="h-3 w-3" />}
                >
                  Next
                </TapeDeckButton>
              </div>
            </div>
          </MachinedCard>
        </div>
      )}

      {/* =====================================================================
          TAB 3: LOGS
         ===================================================================== */}
      {activitySubTab === 'logs' && (
        <div className="space-y-4">
          {/* Log Controls Bar */}
          <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 p-3 bg-[#101010] border border-[#222222] rounded-[4px]">
            {/* Level Filter Pills */}
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-xs font-mono text-neutral-400 mr-1">Level:</span>
              {(['all', 'info', 'warning', 'error', 'debug'] as const).map((lvl) => {
                const isSelected = logLevelFilter === lvl;
                return (
                  <button
                    key={lvl}
                    onClick={() => setLogLevelFilter(lvl)}
                    className={`px-2 py-0.5 text-[11px] font-mono uppercase rounded-[2px] transition-colors ${
                      isSelected
                        ? 'bg-[#e5a00d] text-slate-950 font-bold'
                        : 'bg-[#181818] text-neutral-400 hover:text-white border border-[#262626]'
                    }`}
                  >
                    {lvl}
                  </button>
                );
              })}
            </div>

            {/* Search Input & Auto-scroll Toggle */}
            <div className="flex items-center gap-3">
              <div className="relative">
                <Search className="h-3 w-3 absolute left-2.5 top-1/2 -translate-y-1/2 text-neutral-500" />
                <input
                  type="text"
                  placeholder="Filter log stream..."
                  value={logSearchTerm}
                  onChange={(e) => setLogSearchTerm(e.target.value)}
                  className="pl-8 pr-3 py-1 bg-[#171717] border border-[#262626] rounded-[3px] text-xs font-mono text-neutral-200 placeholder-neutral-500 focus:outline-none focus:border-[#e5a00d] w-48"
                />
              </div>

              <label className="flex items-center gap-1.5 text-xs font-mono text-neutral-400 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={autoScroll}
                  onChange={(e) => setAutoScroll(e.target.checked)}
                  className="accent-[#e5a00d] rounded"
                />
                <span>Auto-scroll</span>
              </label>

              {/* Live Connection indicator badge */}
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-[2px] bg-[#141414] border border-[#242424] text-[10px] font-mono">
                <span
                  className={`w-2 h-2 rounded-full ${
                    isLogsConnected ? 'bg-emerald-500 animate-pulse' : 'bg-neutral-600'
                  }`}
                />
                <span className={isLogsConnected ? 'text-emerald-400' : 'text-neutral-500'}>
                  {isLogsConnected ? 'LIVE STREAM' : 'DISCONNECTED'}
                </span>
              </div>
            </div>
          </div>

          {/* Real-time Terminal Display */}
          <MachinedCard className="p-3 bg-[#0a0a0a] border border-[#222222]">
            <div
              ref={logsContainerRef}
              className="h-[550px] overflow-y-auto space-y-1 font-mono text-[11px] leading-relaxed select-text"
            >
              {filteredLogs.length === 0 && (
                <div className="py-20 text-center text-neutral-500">
                  {logs.length === 0
                    ? 'Connecting to live log stream or waiting for incoming events...'
                    : 'No log entries match the active filter.'}
                </div>
              )}

              {filteredLogs.map((log, idx) => {
                const lvl = (log.level || '').toUpperCase();
                let lvlColor = 'text-sky-400';
                if (lvl === 'ERROR') lvlColor = 'text-red-400 font-bold';
                else if (lvl === 'WARN' || lvl === 'WARNING') lvlColor = 'text-amber-400 font-bold';
                else if (lvl === 'DEBUG') lvlColor = 'text-neutral-500';

                return (
                  <div key={log.id || idx} className="hover:bg-[#121212] px-1 py-0.5 rounded flex items-start gap-2">
                    <span className="text-neutral-500 whitespace-nowrap shrink-0">
                      {log.timestamp}
                    </span>
                    <span className={`w-14 text-center shrink-0 uppercase ${lvlColor}`}>
                      [{lvl}]
                    </span>
                    <span className="text-neutral-400 whitespace-nowrap shrink-0">
                      {log.name}:
                    </span>
                    <span className="text-neutral-200 break-all flex-1">
                      {log.message}
                    </span>
                  </div>
                );
              })}
            </div>
          </MachinedCard>
        </div>
      )}
    </div>
  );
};
