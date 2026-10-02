import React from 'react';
import {
  Compass,
  Inbox,
  Library,
  ListMusic,
  Activity,
  Settings,
  LogIn,
  LogOut,
  Shield,
} from 'lucide-react';
import type { User, UserQuota } from '@/types/models';
import type { MainTab } from './Navigation';
import { TapeDeckButton, TapeTransportBay, QuotaBadge } from '@/components/ui';

export interface HeaderProps {
  user: User | null;
  quota: UserQuota | null;
  isMobileMenuOpen?: boolean;
  onToggleMobileMenu?: () => void;
  onLogin: () => void;
  onLogout: () => void;
  activeTab?: MainTab;
  onTabChange?: (tab: MainTab) => void;
  isAdmin?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  user,
  quota,
  onLogin,
  onLogout,
  activeTab,
  onTabChange,
  isAdmin = false,
}) => {
  const navItems: Array<{ id: MainTab; label: string; icon: React.ReactNode; adminOnly?: boolean }> = [
    { id: 'discover', label: 'Discover', icon: <Compass className="h-4 w-4" /> },
    { id: 'requests', label: 'Requests', icon: <Inbox className="h-4 w-4" /> },
    { id: 'library', label: 'Library', icon: <Library className="h-4 w-4" /> },
    { id: 'playlists', label: 'Playlists', icon: <ListMusic className="h-4 w-4" /> },
    { id: 'activity', label: 'Activity', icon: <Activity className="h-4 w-4" /> },
    { id: 'settings', label: 'Settings', icon: <Settings className="h-4 w-4" />, adminOnly: true },
  ];

  return (
    <header className="sticky top-0 z-40 w-full flex-shrink-0 bg-[#0a0a0a]/95 backdrop-blur-md border-b border-[#1f1f1f] pt-safe">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
        {/* Brand / Logo */}
        <div className="flex items-center gap-3 select-none flex-shrink-0">
          <img
            src="/trackseerr-logo.svg"
            alt="TrackSeerr"
            className="h-8 w-8 object-contain"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).src = '/static/trackseerr-logo.svg';
            }}
          />
          <span className="text-base sm:text-lg font-black tracking-wider uppercase text-white font-mono leading-none">
            Track<span className="text-[#e5a00d]">Seerr</span>
          </span>
        </div>

        {/* Desktop Sticky Navigation Buttons */}
        {user && activeTab && onTabChange && (
          <div className="hidden md:flex items-center gap-1">
            <TapeTransportBay className="p-1">
              <div className="flex items-center gap-1">
                {navItems
                  .filter((item) => !item.adminOnly || isAdmin)
                  .map((item) => {
                    const isActive = activeTab === item.id;
                    return (
                      <TapeDeckButton
                        key={item.id}
                        size="sm"
                        active={isActive}
                        onClick={() => onTabChange(item.id)}
                        icon={item.icon}
                        className="rounded-[3px]"
                      >
                        {item.label}
                      </TapeDeckButton>
                    );
                  })}
              </div>
            </TapeTransportBay>
          </div>
        )}

        {/* User Status / Actions */}
        <div className="flex items-center gap-3 flex-shrink-0">
          {user && <QuotaBadge quota={quota} className="hidden sm:inline-flex" />}

          {user ? (
            <div className="flex items-center gap-2">
              <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-[#141414] border border-[#222222] rounded-[3px]">
                {user.is_admin && <Shield className="h-3.5 w-3.5 text-[#e5a00d]" />}
                <span className="text-xs font-mono font-medium text-neutral-200">
                  {user.plex_username}
                </span>
              </div>
              <TapeDeckButton
                size="sm"
                variant="default"
                onClick={onLogout}
                title="Sign Out"
                icon={<LogOut className="h-4 w-4 text-neutral-400" />}
              >
                <span className="hidden sm:inline">Logout</span>
              </TapeDeckButton>
            </div>
          ) : (
            <TapeDeckButton
              size="sm"
              variant="amber"
              onClick={onLogin}
              icon={<LogIn className="h-4 w-4" />}
            >
              Sign In
            </TapeDeckButton>
          )}
        </div>
      </div>

      {/* Mobile Sticky Horizontal Button Carousel */}
      {user && activeTab && onTabChange && (
        <div className="md:hidden overflow-x-auto no-scrollbar py-1.5 px-3 border-t border-[#181818] bg-[#0a0a0a]/95 flex items-center gap-1.5">
          {navItems
            .filter((item) => !item.adminOnly || isAdmin)
            .map((item) => {
              const isActive = activeTab === item.id;
              return (
                <TapeDeckButton
                  key={item.id}
                  size="sm"
                  active={isActive}
                  onClick={() => onTabChange(item.id)}
                  icon={item.icon}
                  className="flex-shrink-0 text-xs rounded-none"
                >
                  {item.label}
                </TapeDeckButton>
              );
            })}
        </div>
      )}
    </header>
  );
};

