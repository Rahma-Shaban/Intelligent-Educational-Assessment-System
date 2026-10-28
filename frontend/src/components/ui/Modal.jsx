import React, { useEffect } from 'react';
import { X } from 'lucide-react';

const Modal = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  footer,
  maxWidth = 'max-w-lg',
}) => {
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    if (isOpen) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.body.style.overflow = 'unset';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Dialog container */}
      <div className="flex min-h-full items-center justify-center p-4 text-center sm:p-0">
        <div
          className={`relative transform overflow-hidden rounded-2xl bg-paper text-right shadow-2xl transition-all sm:my-8 w-full ${maxWidth} border border-cocoa-300/40`}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          {(title || subtitle) && (
            <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-sand">
              <div>
                {title && (
                  <h3 className="text-lg font-bold text-ink leading-6">
                    {title}
                  </h3>
                )}
                {subtitle && (
                  <p className="mt-1 text-xs text-cocoa-500">{subtitle}</p>
                )}
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg p-1 text-cocoa-300 hover:text-ink hover:bg-sand transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          )}

          {/* Body */}
          <div className="px-6 py-5">{children}</div>

          {/* Footer */}
          {footer && (
            <div className="bg-cream px-6 py-4 flex flex-row-reverse gap-3 border-t border-sand">
              {footer}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Modal;
