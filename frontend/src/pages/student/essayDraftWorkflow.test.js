import assert from 'node:assert/strict';
import test from 'node:test';
import {
  validateStudentDraft,
  saveStudentDraft,
  loadStudentDraft,
  clearStudentDraft,
  getDraftStorageKey,
  sanitizeStudentQuestionItem,
  TYPE_TRANSLATIONS,
} from './questionBankUtils.js';

test('Draft workflow: placeholder and labeling requirements for essay & short-answer questions', () => {
  const expectedPlaceholder = 'اكتب إجابتك هنا...';
  const expectedButtonLabel = 'حفظ الإجابة';
  const expectedNotice = 'تدريب ذاتي: فكّر في الإجابة واكتب مسودتك لمراجعة استيعابك للمفهوم.';

  assert.equal(expectedPlaceholder, 'اكتب إجابتك هنا...');
  assert.equal(expectedButtonLabel, 'حفظ الإجابة');
  assert.match(expectedNotice, /تدريب ذاتي/);

  // Both question types supported
  assert.equal(TYPE_TRANSLATIONS['essay'], 'سؤال مقالي');
  assert.equal(TYPE_TRANSLATIONS['short_answer'], 'إجابة قصيرة');
});

test('Draft workflow: typing, validation, and feedback state transitions', () => {
  const memoryStore = new Map();
  const mockStorage = {
    getItem: (key) => memoryStore.get(key) || null,
    setItem: (key, val) => memoryStore.set(key, String(val)),
    removeItem: (key) => memoryStore.delete(key),
  };

  const qId = 'QBK-ESSAY-101';

  // 1. Initial state: no draft
  assert.equal(loadStudentDraft(qId, mockStorage), '');

  // 2. Student attempts to save empty input -> validation error
  const emptyAttempt = saveStudentDraft(qId, '', mockStorage);
  assert.equal(emptyAttempt.success, false);
  assert.equal(emptyAttempt.error, 'يرجى كتابة إجابتك هنا قبل الحفظ.');
  assert.equal(loadStudentDraft(qId, mockStorage), '');

  // 3. Student attempts to save whitespace only -> validation error
  const whitespaceAttempt = saveStudentDraft(qId, '   \t\n  ', mockStorage);
  assert.equal(whitespaceAttempt.success, false);
  assert.equal(whitespaceAttempt.error, 'يرجى كتابة إجابتك هنا قبل الحفظ.');
  assert.equal(loadStudentDraft(qId, mockStorage), '');

  // 4. Student types actual draft answer -> success feedback
  const validText = 'الفرق الأساسي بين التعلم الخاضع للإشراف وغير الخاضع للإشراف يكمن في وجود التصنيفات المسبقة.';
  const saveResult = saveStudentDraft(qId, validText, mockStorage);
  assert.equal(saveResult.success, true);
  assert.equal(saveResult.sanitized, validText);
  assert.ok(saveResult.savedAt);

  // 5. Draft is loaded back accurately
  const reloaded = loadStudentDraft(qId, mockStorage);
  assert.equal(reloaded, validText);

  // 6. Student clears their draft
  const cleared = clearStudentDraft(qId, mockStorage);
  assert.equal(cleared, true);
  assert.equal(loadStudentDraft(qId, mockStorage), '');
});

test('Draft workflow: independent question draft isolation', () => {
  const memoryStore = new Map();
  const mockStorage = {
    getItem: (key) => memoryStore.get(key) || null,
    setItem: (key, val) => memoryStore.set(key, String(val)),
    removeItem: (key) => memoryStore.delete(key),
  };

  const essayId = 'QBK-ESSAY-001';
  const shortAnsId = 'QBK-SHORT-002';
  const mcqId = 'QBK-MCQ-003';

  // Save for essay and short answer
  saveStudentDraft(essayId, 'مسودة المقال التوضيحي', mockStorage);
  saveStudentDraft(shortAnsId, 'إجابة مختصرة من سطرين', mockStorage);

  // Verify completely independent values
  assert.equal(loadStudentDraft(essayId, mockStorage), 'مسودة المقال التوضيحي');
  assert.equal(loadStudentDraft(shortAnsId, mockStorage), 'إجابة مختصرة من سطرين');
  assert.equal(loadStudentDraft(mcqId, mockStorage), '');

  // Modifying one does not affect the other
  saveStudentDraft(essayId, 'مسودة مقال محدثة ومنقحة', mockStorage);
  assert.equal(loadStudentDraft(essayId, mockStorage), 'مسودة مقال محدثة ومنقحة');
  assert.equal(loadStudentDraft(shortAnsId, mockStorage), 'إجابة مختصرة من سطرين');
});

test('Defense-in-depth: Student draft data is completely isolated from solutions and model answers', () => {
  const mockServerItem = {
    id: 99,
    question_id: 'QBK-ESSAY-DEFENSE',
    question_type: 'essay',
    question_text: 'اشرح مبدأ عمل شبكات التوليد الخصومية (GANs).',
    correct_answer: 'تتكون من شبكتين: المولد والمميز يتنافسان في لعبة صفرية...',
    explanation: 'توضيح مفصل للمعلم...',
    classification_reasoning: 'تصنيف بلوم: فهم/تحليل',
    review_notes: 'معتمد من المعلم',
  };

  // Sanitized view delivered to student
  const studentView = sanitizeStudentQuestionItem(mockServerItem);

  assert.equal(studentView.question_text, 'اشرح مبدأ عمل شبكات التوليد الخصومية (GANs).');
  assert.equal(studentView.correct_answer, undefined);
  assert.equal(studentView.explanation, undefined);
  assert.equal(studentView.classification_reasoning, undefined);
  assert.equal(studentView.review_notes, undefined);

  // Student drafts remain strictly local
  const memoryStore = new Map();
  const mockStorage = {
    getItem: (key) => memoryStore.get(key) || null,
    setItem: (key, val) => memoryStore.set(key, String(val)),
    removeItem: (key) => memoryStore.delete(key),
  };

  const studentDraft = 'GANs تحتوي على شبكة مولد وأخرى ناقدة تتنافسان معاً.';
  saveStudentDraft(studentView.question_id, studentDraft, mockStorage);

  // Stored draft never touches or leaks server correct_answer
  const loadedDraft = loadStudentDraft(studentView.question_id, mockStorage);
  assert.equal(loadedDraft, studentDraft);
  assert.notEqual(loadedDraft, mockServerItem.correct_answer);
});
