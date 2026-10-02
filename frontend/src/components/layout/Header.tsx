import React from 'react';
import { Menu, X, LogIn, LogOut, Shield } from 'lucide-react';
import type { User, UserQuota } from '@/types/models';
import { TapeDeckButton, QuotaBadge } from '@/components/ui';

export interface HeaderProps {
  user: User | null;
  quota: UserQuota | null;
  isMobileMenuOpen: boolean;
  onToggleMobileMenu: () => void;
  onLogin: () => void;
  onLogout: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  user,
  quota,
  isMobileMenuOpen,
  onToggleMobileMenu,
  onLogin,
  onLogout,
}) => {
  return (
    <header className="sticky top-0 z-40 w-full bg-[#0a0a0a]/90 backdrop-blur-md border-b border-[#1f1f1f] pt-safe">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
        {/* Brand / Logo */}
        <div className="flex items-center gap-3 select-none">
          <img
            src="/trackseerr-logo.svg"
            alt="TrackSeerr"
            className="h-8 w-8 object-contain"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).src = '/static/trackseerr-logo.svg';
            }}
          />
          <div className="flex flex-col">
            <span className="text-base sm:text-lg font-black tracking-wider uppercase text-white font-mono leading-none">
              Track<span className="text-[#e5a00d]">Seerr</span>
            </span>
            <span className="text-[10px] text-neutral-400 font-mono tracking-widest uppercase">
              Analog Precision Sync
            </span>
          </div>
        </div>

        {/* User Status / Actions */}
        <div className="flex items-center gap-3">
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

          {/* Mobile Menu Toggle */}
          <button
            type="button"
            onClick={onToggleMobileMenu}
            className="sm:hidden flex items-center justify-center min-h-[44px] min-w-[44px] text-neutral-300 hover:text-white"
            aria-label="Toggle navigation menu"
          >
            {isMobileMenuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
          </button>
        </div>
      </div>
    </header>
  );
};
