import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildAnswersDict,
  buildSubmissionPayload,
  formatTimer,
} from './examTaking.js';

test('buildAnswersDict correctly maps question IDs to student answer strings', () => {
  const questions = [
    { question_id: 'Q01', question: 'What is AI?' },
    { question_id: 'Q02', question: 'Explain ML.' },
    { id: 'custom-id', question: 'Explain DL.' },
    { question: 'Fallback ID question.' },
  ];

  const answers = {
    0: 'Option A',
    1: 'Machine learning learns from data.',
    2: 'Deep learning uses neural networks.',
  };

  const dict = buildAnswersDict(questions, answers);

  assert.equal(dict['Q01'], 'Option A');
  assert.equal(dict['Q02'], 'Machine learning learns from data.');
  assert.equal(dict['custom-id'], 'Deep learning uses neural networks.');
  assert.equal(dict['Q04'], ''); // unanswered maps to empty string
});

test('buildSubmissionPayload throws when attemptId is missing', () => {
  assert.throws(
    () => buildSubmissionPayload({ attemptId: null, questions: [], currentAnswers: {} }),
    /attemptId is required/
  );
});

test('buildSubmissionPayload produces valid payload shape for API', () => {
  const questions = [
    { question_id: 'Q01', question: 'Test question' },
  ];
  const answers = { 0: 'Selected Choice' };

  const payload = buildSubmissionPayload({
    attemptId: 42,
    questions,
    currentAnswers: answers,
    elapsedSeconds: 155,
  });

  assert.equal(payload.attempt_id, 42);
  assert.equal(payload.duration_seconds, 155);
  assert.deepEqual(payload.answers, { Q01: 'Selected Choice' });
});

test('formatTimer formats minutes and seconds with zero padding', () => {
  assert.equal(formatTimer(0), '00:00');
  assert.equal(formatTimer(59), '00:59');
  assert.equal(formatTimer(60), '01:00');
  assert.equal(formatTimer(125), '02:05');
  assert.equal(formatTimer(1800), '30:00');
});
