import React from 'react';
import { Loader2 } from 'lucide-react';

const Button = ({
  children,
  type = 'button',
  variant = 'primary',
  size = 'md',
  loading = false,
  loadingText = 'جاري التحميل...',
  disabled = false,
  className = '',
  onClick,
  icon: Icon,
  ...props
}) => {
  const baseStyles = 'inline-flex items-center justify-center font-bold rounded-xl transition-all focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-60 disabled:cursor-not-allowed select-none';

  const variants = {
    primary: 'bg-gradient-to-b from-clay-600 to-clay-800 text-white hover:from-clay-500 hover:to-clay-700 focus:ring-clay-500 shadow-warm',
    secondary: 'bg-sand text-cocoa-800 hover:bg-cocoa-100 focus:ring-cocoa-300 border border-cocoa-300/50',
    danger: 'bg-rose-600 text-white hover:bg-rose-700 focus:ring-rose-500 shadow-sm',
    success: 'bg-teal-700 text-white hover:bg-teal-800 focus:ring-teal-600 shadow-sm',
    outline: 'border-2 border-clay-200 text-clay-700 hover:bg-clay-50 focus:ring-clay-300 bg-white',
    ghost: 'text-cocoa-500 hover:text-ink hover:bg-sand focus:ring-cocoa-300',
  };

  const sizes = {
    sm: 'px-3 py-1.5 text-xs gap-1.5',
    md: 'px-4 py-2 text-sm gap-2',
    lg: 'px-5 py-2.5 text-base gap-2.5',
  };

  return (
    <button
      type={type}
      disabled={disabled || loading}
      onClick={onClick}
      className={`${baseStyles} ${variants[variant] || variants.primary} ${sizes[size] || sizes.md} ${className}`}
      {...props}
    >
      {loading ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin" />
          <span>{loadingText}</span>
        </>
      ) : (
        <>
          {Icon && <Icon className="w-4 h-4" />}
          {children}
        </>
      )}
    </button>
  );
};

export default Button;
