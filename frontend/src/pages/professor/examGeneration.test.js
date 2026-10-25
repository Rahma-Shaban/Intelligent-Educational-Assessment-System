import assert from 'node:assert/strict';
import test from 'node:test';
import {
  assertRequestedQuestionCount,
  buildExamPayload,
} from './examGeneration.js';

test('exam payload uses the backend question-count field', () => {
  const payload = buildExamPayload({
    title: '',
    selectedLesson: '1-1',
    topic: 'Lesson One',
    difficulty: 'medium',
    bloomLevel: 'apply',
    questionTypes: ['mcq'],
    numQuestions: '20',
  });

  assert.equal(payload.number_of_questions, 20);
  assert.equal('num_questions' in payload, false);
});

test('complete responses pass and silent partial responses fail', () => {
  assert.doesNotThrow(() =>
    assertRequestedQuestionCount({ questions: Array(20).fill({}) }, 20)
  );
  assert.throws(
    () => assertRequestedQuestionCount({ questions: Array(5).fill({}) }, 20),
    /Generation returned 5 of 20 requested questions/
  );
});
