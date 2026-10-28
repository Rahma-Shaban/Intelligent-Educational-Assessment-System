import assert from 'node:assert/strict';
import test from 'node:test';
import {
  ANOMALY_REVIEW_NOTE,
  EXAM_RESULTS_EMPTY_MESSAGE,
  EXAM_RESULTS_ERROR_MESSAGE,
  buildStudentResultRows,
  countDistinctSubmittedStudents,
  examResultsErrorMessage,
  formatAnomalyReview,
  formatAttemptDuration,
  formatCompletionTime,
} from './examStudentResults.js';

test('normal and flagged screening labels stay review-oriented', () => {
  const normal = formatAnomalyReview({
    is_suspicious: false,
    anomaly_score: 0.12,
    suspicion_reason: null,
  });
  assert.equal(normal.label, 'Normal');
  assert.equal(normal.kind, 'normal');

  const flagged = formatAnomalyReview({
    is_suspicious: true,
    anomaly_score: -0.4,
    suspicion_reason: 'سلوك شاذ إحصائياً مقارنة بمتوسط التوزيع العام للطلاب',
  });
  assert.equal(flagged.label, 'Suspicious / Flagged for review');
  assert.equal(flagged.kind, 'flagged');
  assert.equal(flagged.reason, 'سلوك شاذ إحصائياً مقارنة بمتوسط التوزيع العام للطلاب');
  assert.match(ANOMALY_REVIEW_NOTE, /ليس إثباتًا/);
});

test('missing model result displays as Not assessed rather than Normal', () => {
  const legacy = formatAnomalyReview({
    is_suspicious: false,
    suspicion_status: 'Normal',
    anomaly_score: null,
    anomaly_assessed: false,
  });
  assert.equal(legacy.label, 'Not assessed');
  assert.equal(legacy.kind, 'unknown');
});

test('student rows group submitted attempts with scores and screening', () => {
  const rows = buildStudentResultRows({
    exam_id: 9,
    exam_title: 'Lesson One',
    students: [
      {
        student_id: 4,
        student_name: 'Alice Johnson',
        submitted_attempt_count: 2,
        unsubmitted_attempt_count: 1,
        attempts: [
          {
            attempt_id: 11,
            score: 8,
            max_possible_score: 10,
            score_percentage: 80,
            submitted_at: '2026-10-29T10:00:00+00:00',
            duration_seconds: 125,
            is_suspicious: false,
            anomaly_score: 0.2,
            anomaly_assessed: true,
          },
          {
            attempt_id: 12,
            score: 10,
            max_possible_score: 10,
            score_percentage: 100,
            submitted_at: '2026-10-29T12:00:00+00:00',
            duration_seconds: 40,
            is_suspicious: true,
            suspicion_reason: 'سرعة حل غير واقعية لأسئلة مقالية (اشتباه قوي)',
            anomaly_score: -0.3,
            anomaly_assessed: true,
          },
        ],
      },
    ],
  });

  assert.equal(rows.length, 1);
  assert.equal(rows[0].name, 'Alice Johnson');
  assert.equal(rows[0].submittedAttemptCount, 2);
  assert.equal(rows[0].attempts.length, 2);
  assert.equal(rows[0].attempts[0].anomaly.label, 'Normal');
  assert.equal(rows[0].attempts[1].anomaly.label, 'Suspicious / Flagged for review');
  assert.equal(rows[0].attempts[0].durationLabel, formatAttemptDuration(125));
});

test('countDistinctSubmittedStudents correctly calculates distinct students with submitted attempts', () => {
  const testPayload = {
    exam_id: 10,
    students: [
      {
        student_id: 1,
        student_name: 'Student One',
        submitted_attempt_count: 3,
        unsubmitted_attempt_count: 0,
      },
      {
        student_id: 2,
        student_name: 'Student Two',
        submitted_attempt_count: 0,
        unsubmitted_attempt_count: 2,
      },
      {
        student_id: 3,
        student_name: 'Student Three',
        submitted_attempt_count: 1,
        unsubmitted_attempt_count: 1,
      },
    ],
  };

  assert.equal(countDistinctSubmittedStudents(testPayload), 2);

  const rows = buildStudentResultRows(testPayload);
  assert.equal(countDistinctSubmittedStudents(rows), 2);

  const duplicateList = [
    { studentId: 5, submittedAttemptCount: 1 },
    { studentId: 5, submittedAttemptCount: 2 },
    { studentId: 6, submittedAttemptCount: 0 },
  ];
  assert.equal(countDistinctSubmittedStudents(duplicateList), 1);

  assert.equal(countDistinctSubmittedStudents(null), 0);
  assert.equal(countDistinctSubmittedStudents({ students: [] }), 0);

  assert.equal(
    countDistinctSubmittedStudents({ distinct_submitted_students_count: 5 }),
    5
  );
});

test('formatCompletionTime formats timestamps according to Egyptian time domain (Africa/Cairo)', () => {
  // 23:13 UTC on 2026-10-28 is 02:13 AM (next day, ص) in Cairo
  const formatted = formatCompletionTime('2026-10-28T23:13:08.179686Z');
  assert.equal(formatted.includes('٢:١٣') || formatted.includes('2:13'), true);
  assert.equal(formatted.includes('ص') || formatted.includes('AM'), true);

  // Naive datetime string without Z is also normalized as UTC and converted to Cairo
  const naiveFormatted = formatCompletionTime('2026-10-28 23:13:08.179686');
  assert.equal(naiveFormatted.includes('٢:١٣') || naiveFormatted.includes('2:13'), true);

  // Empty or invalid returns placeholder
  assert.equal(formatCompletionTime(null), 'غير متوفر');
  assert.equal(formatCompletionTime('invalid-date'), 'غير متوفر');
});

test('empty payload and API errors have clear dashboard copy', () => {
  assert.deepEqual(buildStudentResultRows({ students: [] }), []);
  assert.equal(EXAM_RESULTS_EMPTY_MESSAGE.includes('لا يوجد'), true);
  assert.equal(
    examResultsErrorMessage({ response: { data: { detail: 'Forbidden' } } }),
    'Forbidden'
  );
  assert.equal(examResultsErrorMessage({}), EXAM_RESULTS_ERROR_MESSAGE);
});
