import React from 'react';
import { Loader2 } from 'lucide-react';

const LoadingSpinner = ({
  size = 'md',
  message = 'Loading...',
  fullScreen = false,
  className = '',
}) => {
  const sizeMap = {
    sm: 'w-4 h-4',
    md: 'w-8 h-8',
    lg: 'w-12 h-12',
    xl: 'w-16 h-16',
  };

  const content = (
    <div className={`flex flex-col items-center justify-center p-8 gap-3 text-cocoa-500 ${className}`}>
      <Loader2 className={`${sizeMap[size] || sizeMap.md} animate-spin text-clay-600`} />
      {message && (
        <p className="text-sm font-bold text-cocoa-500 animate-pulse">
          {message}
        </p>
      )}
    </div>
  );

  if (fullScreen) {
    return (
      <div className="fixed inset-0 bg-white/80 backdrop-blur-sm z-50 flex items-center justify-center">
        {content}
      </div>
    );
  }

  return content;
};

export default LoadingSpinner;
