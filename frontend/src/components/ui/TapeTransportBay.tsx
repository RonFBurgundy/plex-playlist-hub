import React from 'react';

export interface TapeTransportBayProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
}

export const TapeTransportBay: React.FC<TapeTransportBayProps> = ({
  children,
  className = '',
  ...props
}) => {
  return (
    <div
      className={`tape-transport-bay bg-[#0d0d0d] border border-[#1f1f1f] shadow-transport-bay rounded-[4px] p-[3px] ${className}`}
      {...props}
    >
      {children}
    </div>
  );
};
