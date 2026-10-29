import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildQuestionBankParams,
  sanitizeStudentQuestionItem,
  validateStudentDraft,
  getDraftStorageKey,
  loadStudentDraft,
  saveStudentDraft,
  clearStudentDraft,
  BLOOM_TRANSLATIONS,
  DIFFICULTY_TRANSLATIONS,
  TYPE_TRANSLATIONS,
} from './questionBankUtils.js';

test('buildQuestionBankParams correctly formats and excludes empty filter strings', () => {
  const params = buildQuestionBankParams({
    page: 2,
    pageSize: 15,
    search: '  recursion  ',
    difficulty: 'MEDIUM',
    bloomLevel: 'Understand',
    questionType: '',
  });

  assert.equal(params.page, 2);
  assert.equal(params.page_size, 15);
  assert.equal(params.search, 'recursion');
  assert.equal(params.difficulty, 'medium');
  assert.equal(params.bloom_level, 'understand');
  assert.equal('question_type' in params, false);
});

test('buildQuestionBankParams handles edge-case numbers and clamps page_size', () => {
  const params = buildQuestionBankParams({
    page: -5,
    pageSize: 500,
  });

  assert.equal(params.page, 1);
  assert.equal(params.page_size, 100);
});

test('sanitizeStudentQuestionItem strictly excludes sensitive answers and teacher metadata', () => {
  const rawWithSecrets = {
    id: 42,
    question_id: 'QBK-LEAK-TEST',
    question_type: 'mcq',
    question_text: 'What is polymorphism?',
    options: ['Ability to take multiple forms', 'A compiler', 'A loop', 'A syntax error'],
    correct_option: 'A',
    correct_answer: 'Ability to take multiple forms',
    explanation: 'Teacher solution explanation',
    classification_reasoning: 'Internal AI rationale',
    review_notes: 'Reviewed by Prof',
    teacher_corrections: { bloom_level: 'Apply' },
  };

  const safeItem = sanitizeStudentQuestionItem(rawWithSecrets);

  assert.equal(safeItem.id, 42);
  assert.equal(safeItem.question_id, 'QBK-LEAK-TEST');
  assert.equal(safeItem.question_text, 'What is polymorphism?');
  assert.equal(safeItem.options.length, 4);

  // Verify none of the leaked fields are present
  assert.equal('correct_option' in safeItem, false);
  assert.equal('correct_answer' in safeItem, false);
  assert.equal('explanation' in safeItem, false);
  assert.equal('classification_reasoning' in safeItem, false);
  assert.equal('review_notes' in safeItem, false);
  assert.equal('teacher_corrections' in safeItem, false);
});

test('validateStudentDraft rejects empty, whitespace, and non-string values', () => {
  const emptyRes = validateStudentDraft('');
  assert.equal(emptyRes.isValid, false);
  assert.match(emptyRes.error, /يرجى كتابة إجابتك/);

  const spaceRes = validateStudentDraft('    \n\t  ');
  assert.equal(spaceRes.isValid, false);
  assert.match(spaceRes.error, /يرجى كتابة إجابتك/);

  const nullRes = validateStudentDraft(null);
  assert.equal(nullRes.isValid, false);

  const validRes = validateStudentDraft('  هذه مسودة إجابة تجريبية  ');
  assert.equal(validRes.isValid, true);
  assert.equal(validRes.sanitized, 'هذه مسودة إجابة تجريبية');
  assert.equal(validRes.error, null);
});

test('getDraftStorageKey produces distinct keys per question', () => {
  const key1 = getDraftStorageKey('Q-001');
  const key2 = getDraftStorageKey('Q-002');
  assert.equal(key1, 'student_qb_draft_Q-001');
  assert.equal(key2, 'student_qb_draft_Q-002');
  assert.notEqual(key1, key2);
});

test('saveStudentDraft and loadStudentDraft persist independent drafts per question in storage', () => {
  const memoryStore = new Map();
  const mockStorage = {
    getItem: (k) => memoryStore.get(k) || null,
    setItem: (k, v) => memoryStore.set(k, String(v)),
    removeItem: (k) => memoryStore.delete(k),
  };

  // Save for Question 1
  const save1 = saveStudentDraft('QBK-ESSAY-01', 'إجابة السؤال الأول عن الخوارزميات', mockStorage);
  assert.equal(save1.success, true);
  assert.equal(save1.sanitized, 'إجابة السؤال الأول عن الخوارزميات');

  // Save for Question 2
  const save2 = saveStudentDraft('QBK-SHORT-02', 'إجابة السؤال الثاني عن قواعد البيانات', mockStorage);
  assert.equal(save2.success, true);

  // Load Question 1 and 2 independently
  const loaded1 = loadStudentDraft('QBK-ESSAY-01', mockStorage);
  const loaded2 = loadStudentDraft('QBK-SHORT-02', mockStorage);
  assert.equal(loaded1, 'إجابة السؤال الأول عن الخوارزميات');
  assert.equal(loaded2, 'إجابة السؤال الثاني عن قواعد البيانات');

  // Verify questions do not collide or leak into each other
  assert.notEqual(loaded1, loaded2);

  // Clear Question 1
  const cleared = clearStudentDraft('QBK-ESSAY-01', mockStorage);
  assert.equal(cleared, true);
  assert.equal(loadStudentDraft('QBK-ESSAY-01', mockStorage), '');
  assert.equal(loadStudentDraft('QBK-SHORT-02', mockStorage), 'إجابة السؤال الثاني عن قواعد البيانات');
});

test('saveStudentDraft fails with validation message when input is blank', () => {
  const memoryStore = new Map();
  const mockStorage = {
    getItem: (k) => memoryStore.get(k) || null,
    setItem: (k, v) => memoryStore.set(k, String(v)),
    removeItem: (k) => memoryStore.delete(k),
  };

  const res = saveStudentDraft('QBK-ESSAY-01', '   ', mockStorage);
  assert.equal(res.success, false);
  assert.match(res.error, /يرجى كتابة إجابتك/);
  assert.equal(memoryStore.size, 0);
});

test('translations map key educational levels correctly', () => {
  assert.equal(BLOOM_TRANSLATIONS['understand'], 'فهم');
  assert.equal(BLOOM_TRANSLATIONS['apply'], 'تطبيق');
  assert.equal(DIFFICULTY_TRANSLATIONS['easy'], 'سهل');
  assert.equal(DIFFICULTY_TRANSLATIONS['hard'], 'صعب');
  assert.equal(TYPE_TRANSLATIONS['essay'], 'سؤال مقالي');
  assert.equal(TYPE_TRANSLATIONS['short_answer'], 'إجابة قصيرة');
});
