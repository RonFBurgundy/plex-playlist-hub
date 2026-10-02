import React from 'react';

export interface MachinedCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
  interactive?: boolean;
}

export const MachinedCard: React.FC<MachinedCardProps> = ({
  children,
  className = '',
  interactive = false,
  ...props
}) => {
  return (
    <div
      className={`bg-[#141414] border border-[#222222] rounded-[4px] transition-all duration-150 ${
        interactive
          ? 'hover:border-[#2a2a2a] hover:bg-[#1c1c1c] hover:shadow-[0_4px_12px_rgba(0,0,0,0.5)] cursor-pointer'
          : ''
      } ${className}`}
      {...props}
    >
      {children}
    </div>
  );
};
