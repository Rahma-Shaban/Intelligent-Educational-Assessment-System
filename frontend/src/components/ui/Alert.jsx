import React from 'react';
import { CheckCircle2, AlertCircle, AlertTriangle, Info, X } from 'lucide-react';

const Alert = ({
  type = 'info',
  title,
  children,
  message,
  onClose,
  className = '',
}) => {
  const config = {
    success: {
      bg: 'bg-teal-50 border-teal-200 text-teal-800',
      icon: CheckCircle2,
      iconColor: 'text-teal-500',
    },
    error: {
      bg: 'bg-rose-50 border-rose-200 text-rose-800',
      icon: AlertCircle,
      iconColor: 'text-rose-500',
    },
    warning: {
      bg: 'bg-gold-50 border-gold-200 text-gold-800',
      icon: AlertTriangle,
      iconColor: 'text-gold-500',
    },
    info: {
      bg: 'bg-clay-50 border-clay-200 text-clay-800',
      icon: Info,
      iconColor: 'text-clay-500',
    },
  };

  const current = config[type] || config.info;
  const Icon = current.icon;

  return (
    <div
      className={`rounded-lg border p-4 flex items-start gap-3 transition-all ${current.bg} ${className}`}
      role="alert"
    >
      <Icon className={`w-5 h-5 flex-shrink-0 mt-0.5 ${current.iconColor}`} />
      <div className="flex-1 text-sm">
        {title && <h4 className="font-semibold mb-1 leading-none">{title}</h4>}
        <div className="leading-relaxed">{children || message}</div>
      </div>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          className="text-cocoa-300 hover:text-ink rounded-md p-0.5 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-cocoa-300"
          aria-label="Dismiss alert"
        >
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  );
};

export default Alert;
