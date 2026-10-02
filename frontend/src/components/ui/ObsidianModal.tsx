import React, { useEffect } from 'react';
import { X } from 'lucide-react';
import { TapeDeckButton } from './TapeDeckButton';

export interface ObsidianModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  maxWidth?: string;
}

export const ObsidianModal: React.FC<ObsidianModalProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  footer,
  maxWidth = 'sm:max-w-2xl',
}) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    if (isOpen) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', handleKeyDown);
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-[2px] p-0 sm:p-4 overflow-hidden"
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`relative flex flex-col w-full h-full sm:h-auto sm:max-h-[90dvh] bg-[#121212] border-0 sm:border sm:border-[#2a2a2a] rounded-none sm:rounded-[4px] shadow-2xl pt-safe pb-safe ${maxWidth}`}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#222222] px-4 py-3 sm:px-5 sm:py-3.5 bg-[#181818]/80 shrink-0">
          <div>
            <h3 className="text-sm sm:text-base font-bold tracking-wider uppercase text-white">
              {title}
            </h3>
            {subtitle && (
              <p className="text-xs text-neutral-400 mt-0.5">{subtitle}</p>
            )}
          </div>
          <TapeDeckButton
            size="sm"
            onClick={onClose}
            aria-label="Close dialog"
            icon={<X className="h-4 w-4" />}
          />
        </div>

        {/* Scrollable Body */}
        <div className="modal-body-scroll flex-1 p-4 sm:p-5 text-neutral-200">
          {children}
        </div>

        {/* Footer */}
        {footer && (
          <div className="flex items-center justify-end gap-3 border-t border-[#222222] px-4 py-3 sm:px-5 bg-[#0e0e0e] shrink-0">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
};
