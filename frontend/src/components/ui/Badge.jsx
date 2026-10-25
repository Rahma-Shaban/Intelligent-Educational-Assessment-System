import React from 'react';

const Badge = ({
  children,
  variant,
  type, // 'difficulty' | 'bloom' | 'status' | 'qtype'
  size = 'md',
  className = '',
}) => {
  const normalized = String(children || variant || '').trim().toLowerCase();

  let colorClasses = 'bg-gray-100 text-gray-800 border-gray-200';

  if (type === 'difficulty' || ['easy', 'medium', 'hard'].includes(normalized)) {
    switch (normalized) {
      case 'easy':
        colorClasses = 'bg-emerald-50 text-emerald-700 border-emerald-200';
        break;
      case 'medium':
        colorClasses = 'bg-amber-50 text-amber-700 border-amber-200';
        break;
      case 'hard':
        colorClasses = 'bg-rose-50 text-rose-700 border-rose-200';
        break;
      default:
        colorClasses = 'bg-gray-100 text-gray-700 border-gray-200';
    }
  } else if (type === 'bloom' || ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'].includes(normalized)) {
    switch (normalized) {
      case 'remember':
        colorClasses = 'bg-slate-100 text-slate-700 border-slate-200';
        break;
      case 'understand':
        colorClasses = 'bg-sky-50 text-sky-700 border-sky-200';
        break;
      case 'apply':
        colorClasses = 'bg-blue-50 text-blue-700 border-blue-200';
        break;
      case 'analyze':
        colorClasses = 'bg-indigo-50 text-indigo-700 border-indigo-200';
        break;
      case 'evaluate':
        colorClasses = 'bg-purple-50 text-purple-700 border-purple-200';
        break;
      case 'create':
        colorClasses = 'bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200';
        break;
      default:
        colorClasses = 'bg-indigo-50 text-indigo-700 border-indigo-200';
    }
  } else if (type === 'qtype' || ['mcq', 'short_answer', 'essay'].includes(normalized)) {
    switch (normalized) {
      case 'mcq':
        colorClasses = 'bg-violet-50 text-violet-700 border-violet-200';
        break;
      case 'short_answer':
        colorClasses = 'bg-teal-50 text-teal-700 border-teal-200';
        break;
      case 'essay':
        colorClasses = 'bg-blue-50 text-blue-700 border-blue-200';
        break;
      default:
        colorClasses = 'bg-gray-100 text-gray-700 border-gray-200';
    }
  } else if (type === 'cluster' || normalized.includes('intervention') || normalized.includes('proficient') || normalized.includes('advanced')) {
    if (normalized.includes('advanced')) {
      colorClasses = 'bg-purple-50 text-purple-700 border-purple-200';
    } else if (normalized.includes('proficient')) {
      colorClasses = 'bg-blue-50 text-blue-700 border-blue-200';
    } else {
      colorClasses = 'bg-rose-50 text-rose-700 border-rose-200';
    }
  } else {
    // Custom variant
    switch (variant) {
      case 'primary':
        colorClasses = 'bg-indigo-50 text-indigo-700 border-indigo-200';
        break;
      case 'success':
        colorClasses = 'bg-emerald-50 text-emerald-700 border-emerald-200';
        break;
      case 'warning':
        colorClasses = 'bg-amber-50 text-amber-700 border-amber-200';
        break;
      case 'danger':
        colorClasses = 'bg-rose-50 text-rose-700 border-rose-200';
        break;
      case 'info':
        colorClasses = 'bg-cyan-50 text-cyan-700 border-cyan-200';
        break;
      default:
        colorClasses = 'bg-gray-100 text-gray-700 border-gray-200';
    }
  }

  const sizes = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-2.5 py-1 text-xs',
    lg: 'px-3 py-1.5 text-sm',
  };

  const displayText =
    normalized === 'short_answer'
      ? 'Short Answer'
      : normalized === 'mcq'
      ? 'MCQ'
      : typeof children === 'string'
      ? children.charAt(0).toUpperCase() + children.slice(1)
      : children;

  return (
    <span
      className={`inline-flex items-center font-medium rounded-full border ${colorClasses} ${sizes[size] || sizes.md} ${className}`}
    >
      {displayText}
    </span>
  );
};

export default Badge;
