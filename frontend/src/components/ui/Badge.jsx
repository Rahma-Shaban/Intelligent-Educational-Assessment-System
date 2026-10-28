import React from 'react';

const Badge = ({
  children,
  variant,
  type, // 'difficulty' | 'bloom' | 'status' | 'qtype' | 'cluster'
  size = 'md',
  className = '',
}) => {
  const rawChildStr =
    typeof children === 'string' || typeof children === 'number'
      ? String(children)
      : children && typeof children === 'object'
      ? children.cluster_label || children.label || children.name || children.title || ''
      : '';

  const normalized = String(rawChildStr || variant || '').trim().toLowerCase();

  let colorClasses = 'bg-sand text-cocoa-800 border-cocoa-300/50';

  if (type === 'difficulty' || ['easy', 'medium', 'hard'].includes(normalized)) {
    switch (normalized) {
      case 'easy':
        colorClasses = 'bg-teal-50 text-teal-700 border-teal-200';
        break;
      case 'medium':
        colorClasses = 'bg-gold-100 text-gold-700 border-gold-200';
        break;
      case 'hard':
        colorClasses = 'bg-rose-50 text-rose-700 border-rose-200';
        break;
      default:
        colorClasses = 'bg-sand text-cocoa-500 border-cocoa-300/50';
    }
  } else if (type === 'bloom' || ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'].includes(normalized)) {
    switch (normalized) {
      case 'remember':
        colorClasses = 'bg-cocoa-100 text-cocoa-800 border-cocoa-300/50';
        break;
      case 'understand':
        colorClasses = 'bg-sky-50 text-sky-700 border-sky-200';
        break;
      case 'apply':
        colorClasses = 'bg-teal-50 text-teal-700 border-teal-200';
        break;
      case 'analyze':
        colorClasses = 'bg-clay-100 text-clay-800 border-clay-200';
        break;
      case 'evaluate':
        colorClasses = 'bg-violet-50 text-violet-700 border-violet-200';
        break;
      case 'create':
        colorClasses = 'bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200';
        break;
      default:
        colorClasses = 'bg-clay-50 text-clay-700 border-clay-200';
    }
  } else if (type === 'qtype' || ['mcq', 'short_answer', 'essay'].includes(normalized)) {
    switch (normalized) {
      case 'mcq':
        colorClasses = 'bg-clay-100 text-clay-800 border-clay-200';
        break;
      case 'short_answer':
        colorClasses = 'bg-teal-50 text-teal-700 border-teal-200';
        break;
      case 'essay':
        colorClasses = 'bg-violet-50 text-violet-700 border-violet-200';
        break;
      default:
        colorClasses = 'bg-sand text-cocoa-500 border-cocoa-300/50';
    }
  } else if (type === 'cluster' || normalized.includes('intervention') || normalized.includes('proficient') || normalized.includes('advanced')) {
    if (normalized.includes('advanced')) {
      colorClasses = 'bg-clay-100 text-clay-800 border-clay-200';
    } else if (normalized.includes('proficient')) {
      colorClasses = 'bg-teal-50 text-teal-700 border-teal-200';
    } else {
      colorClasses = 'bg-rose-50 text-rose-700 border-rose-200';
    }
  } else {
    // Custom variant
    switch (variant) {
      case 'primary':
        colorClasses = 'bg-clay-100 text-clay-800 border-clay-200';
        break;
      case 'success':
        colorClasses = 'bg-teal-50 text-teal-700 border-teal-200';
        break;
      case 'warning':
        colorClasses = 'bg-gold-100 text-gold-700 border-gold-200';
        break;
      case 'danger':
        colorClasses = 'bg-rose-50 text-rose-700 border-rose-200';
        break;
      case 'info':
        colorClasses = 'bg-sky-50 text-sky-700 border-sky-200';
        break;
      default:
        colorClasses = 'bg-sand text-cocoa-500 border-cocoa-300/50';
    }
  }

  const sizes = {
    sm: 'px-2 py-0.5 text-[10px]',
    md: 'px-2.5 py-1 text-[11px]',
    lg: 'px-3 py-1.5 text-xs',
  };

  const qTypeLabels = {
    mcq: 'اختيار متعدد',
    short_answer: 'إجابة قصيرة',
    essay: 'مقالي',
  };

  const difficultyLabels = {
    easy: 'سهل',
    medium: 'متوسط',
    hard: 'صعب',
  };

  const bloomLabels = {
    remember: 'تذكّر',
    understand: 'فهم',
    apply: 'تطبيق',
    analyze: 'تحليل',
    evaluate: 'تقييم',
    create: 'إبداع',
  };

  const clusterLabels = {
    advanced: 'متقدمين',
    proficient: 'متمكنين',
    needs_intervention: 'محتاجين متابعة',
    at_risk: 'محتاجين متابعة',
  };

  let displayText = rawChildStr;
  if (qTypeLabels[normalized]) {
    displayText = qTypeLabels[normalized];
  } else if (difficultyLabels[normalized] && (type === 'difficulty' || !type)) {
    displayText = difficultyLabels[normalized];
  } else if (bloomLabels[normalized] && (type === 'bloom' || !type)) {
    displayText = bloomLabels[normalized];
  } else if (type === 'cluster') {
    const key = Object.keys(clusterLabels).find((k) => normalized.includes(k));
    displayText = key ? clusterLabels[key] : rawChildStr;
  }

  // Title-case fallback for English content strings (e.g. exam topics)
  if (displayText && displayText === rawChildStr) {
    displayText = displayText.charAt(0).toUpperCase() + displayText.slice(1);
  }

  return (
    <span
      className={`inline-flex items-center font-bold rounded-full border ${colorClasses} ${sizes[size] || sizes.md} ${className}`}
      dir="auto"
    >
      {displayText}
    </span>
  );
};

export default Badge;
