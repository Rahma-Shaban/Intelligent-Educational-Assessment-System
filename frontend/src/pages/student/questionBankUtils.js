/**
 * Utilities for student question bank search, filtering, safe display formatting,
 * and local self-practice draft answer management.
 */

export const BLOOM_TRANSLATIONS = {
  remember: 'تذكر',
  understand: 'فهم',
  apply: 'تطبيق',
  analyze: 'تحليل',
  evaluate: 'تقييم',
  create: 'ابتكار',
};

export const DIFFICULTY_TRANSLATIONS = {
  easy: 'سهل',
  medium: 'متوسط',
  hard: 'صعب',
};

export const TYPE_TRANSLATIONS = {
  mcq: 'اختيار من متعدد',
  short_answer: 'إجابة قصيرة',
  essay: 'سؤال مقالي',
};

/**
 * Builds API query parameters for question bank listing.
 * Strips empty strings and enforces minimum page index.
 */
export function buildQuestionBankParams({
  page = 1,
  pageSize = 10,
  search = '',
  difficulty = '',
  bloomLevel = '',
  questionType = '',
} = {}) {
  const params = {
    page: Math.max(1, Number.parseInt(page, 10) || 1),
    page_size: Math.max(1, Math.min(100, Number.parseInt(pageSize, 10) || 10)),
  };

  const s = String(search || '').trim();
  if (s) params.search = s;

  const diff = String(difficulty || '').trim().toLowerCase();
  if (diff) params.difficulty = diff;

  const bloom = String(bloomLevel || '').trim().toLowerCase();
  if (bloom) params.bloom_level = bloom;

  const qtype = String(questionType || '').trim().toLowerCase();
  if (qtype) params.question_type = qtype;

  return params;
}

/**
 * Defense-in-depth sanitization: ensures question items displayed to students
 * never contain answers, model solutions, or internal evaluation notes.
 */
export function sanitizeStudentQuestionItem(rawItem) {
  if (!rawItem || typeof rawItem !== 'object') return null;

  const sanitized = {
    id: rawItem.id,
    question_id: rawItem.question_id || `QBK-${rawItem.id}`,
    question_type: rawItem.question_type || 'mcq',
    question_text: rawItem.question_text || '',
    options: Array.isArray(rawItem.options) ? rawItem.options : [],
    difficulty: rawItem.difficulty || null,
    bloom_level: rawItem.bloom_level || null,
    lesson: rawItem.lesson || null,
    subject: rawItem.subject || null,
  };

  return sanitized;
}

/**
 * Validates a student's typed practice answer.
 * Enforces non-empty and non-whitespace content.
 */
export function validateStudentDraft(text) {
  const trimmed = typeof text === 'string' ? text.trim() : '';
  if (!trimmed) {
    return {
      isValid: false,
      error: 'يرجى كتابة إجابتك هنا قبل الحفظ.',
      sanitized: '',
    };
  }
  return {
    isValid: true,
    error: null,
    sanitized: trimmed,
  };
}

/**
 * Generates an isolated storage key scoped to the specific question ID.
 */
export function getDraftStorageKey(questionId) {
  return `student_qb_draft_${String(questionId || '').trim()}`;
}

/**
 * Retrieves a saved student draft from local storage safely.
 */
export function loadStudentDraft(
  questionId,
  storage = typeof window !== 'undefined' ? window.localStorage : null
) {
  if (!storage || !questionId) return '';
  try {
    const raw = storage.getItem(getDraftStorageKey(questionId));
    if (!raw) return '';
    try {
      const parsed = JSON.parse(raw);
      return typeof parsed.text === 'string' ? parsed.text : raw;
    } catch {
      return raw;
    }
  } catch {
    return '';
  }
}

/**
 * Saves a validated student draft to local storage.
 */
export function saveStudentDraft(
  questionId,
  draftText,
  storage = typeof window !== 'undefined' ? window.localStorage : null
) {
  const validation = validateStudentDraft(draftText);
  if (!validation.isValid) {
    return {
      success: false,
      error: validation.error,
      sanitized: '',
      savedAt: null,
    };
  }
  if (!storage || !questionId) {
    return {
      success: false,
      error: 'مساحة التخزين غير متاحة في المتصفح.',
      sanitized: '',
      savedAt: null,
    };
  }
  try {
    const nowIso = new Date().toISOString();
    const payload = JSON.stringify({
      text: validation.sanitized,
      savedAt: nowIso,
    });
    storage.setItem(getDraftStorageKey(questionId), payload);
    return {
      success: true,
      error: null,
      sanitized: validation.sanitized,
      savedAt: nowIso,
    };
  } catch (err) {
    return {
      success: false,
      error: 'فشل حفظ المسودة في الذاكرة المحلية.',
      sanitized: '',
      savedAt: null,
    };
  }
}

/**
 * Clears a student draft from local storage.
 */
export function clearStudentDraft(
  questionId,
  storage = typeof window !== 'undefined' ? window.localStorage : null
) {
  if (!storage || !questionId) return false;
  try {
    storage.removeItem(getDraftStorageKey(questionId));
    return true;
  } catch {
    return false;
  }
}
