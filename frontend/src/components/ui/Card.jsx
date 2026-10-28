import React from 'react';

const Card = ({
  title,
  subtitle,
  action,
  children,
  className = '',
  bodyClassName = 'p-6',
  headerClassName = 'px-6 py-4 border-b border-sand',
  footer,
  footerClassName = 'px-6 py-4 bg-cream border-t border-sand rounded-b-2xl',
  ...props
}) => {
  return (
    <div
      className={`bg-paper rounded-2xl border border-cocoa-300/40 shadow-warm hover:shadow-pop transition-shadow overflow-hidden ${className}`}
      {...props}
    >
      {(title || subtitle || action) && (
        <div className={`flex items-center justify-between ${headerClassName}`}>
          <div>
            {title && (
              <h3 className="text-base font-bold text-ink leading-tight">
                {title}
              </h3>
            )}
            {subtitle && (
              <p className="text-xs text-cocoa-500 mt-1">{subtitle}</p>
            )}
          </div>
          {action && <div className="ms-4">{action}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
      {footer && <div className={footerClassName}>{footer}</div>}
    </div>
  );
};

export default Card;
