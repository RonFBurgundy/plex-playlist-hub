import React from 'react';
import { Compass, Inbox, Library, ListMusic, Activity, Settings, X } from 'lucide-react';
import type { MainTab } from './Navigation';
import type { User, UserQuota } from '@/types/models';
import { TapeDeckButton, QuotaBadge } from '@/components/ui';

export interface MobileDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  activeTab: MainTab;
  onTabChange: (tab: MainTab) => void;
  user: User | null;
  quota: UserQuota | null;
  isAdmin?: boolean;
}

export const MobileDrawer: React.FC<MobileDrawerProps> = ({
  isOpen,
  onClose,
  activeTab,
  onTabChange,
  user,
  quota,
  isAdmin = false,
}) => {
  if (!isOpen) return null;

  const navItems: Array<{ id: MainTab; label: string; icon: React.ReactNode; adminOnly?: boolean }> = [
    { id: 'discover', label: 'Discover', icon: <Compass className="h-5 w-5" /> },
    { id: 'requests', label: 'Requests', icon: <Inbox className="h-5 w-5" /> },
    { id: 'library', label: 'Library', icon: <Library className="h-5 w-5" /> },
    { id: 'playlists', label: 'Playlists', icon: <ListMusic className="h-5 w-5" /> },
    { id: 'activity', label: 'Activity', icon: <Activity className="h-5 w-5" /> },
    { id: 'settings', label: 'Settings', icon: <Settings className="h-5 w-5" />, adminOnly: true },
  ];

  return (
    <div className="fixed inset-0 z-50 sm:hidden bg-black/90 backdrop-blur-md flex flex-col pt-safe pb-safe">
      {/* Top Header inside Drawer */}
      <div className="flex items-center justify-between px-4 py-4 border-b border-[#222222]">
        <div className="flex items-center gap-2">
          <img src="/trackseerr-logo.svg" alt="TrackSeerr" className="h-6 w-6" />
          <span className="text-sm font-bold uppercase font-mono text-white">Menu</span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="min-h-[44px] min-w-[44px] flex items-center justify-center text-neutral-400 hover:text-white"
          aria-label="Close menu"
        >
          <X className="h-6 w-6" />
        </button>
      </div>

      {/* Quota for user */}
      {user && (
        <div className="px-4 py-3 bg-[#121212] border-b border-[#1f1f1f]">
          <QuotaBadge quota={quota} className="w-full justify-between" />
        </div>
      )}

      {/* Navigation Keys */}
      <div className="flex-1 p-4 flex flex-col gap-2.5 overflow-y-auto">
        {navItems
          .filter((item) => !item.adminOnly || isAdmin)
          .map((item) => {
            const isActive = activeTab === item.id;
            return (
              <TapeDeckButton
                key={item.id}
                size="lg"
                active={isActive}
                onClick={() => {
                  onTabChange(item.id);
                  onClose();
                }}
                icon={item.icon}
                className="w-full justify-start px-4 text-sm"
              >
                {item.label}
              </TapeDeckButton>
            );
          })}
      </div>
    </div>
  );
};
