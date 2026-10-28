/**
 * Display helpers for professor exam student results.
 * Screening labels are review indicators, not findings of misconduct.
 */

export const EXAM_RESULTS_EMPTY_MESSAGE = 'لا يوجد طلاب سلّموا هذا الامتحان بعد.';
export const EXAM_RESULTS_ERROR_MESSAGE = 'فشل تحميل نتائج الطلاب. حاول تاني.';
export const ANOMALY_REVIEW_NOTE =
  'مؤشر سلوك غير معتاد للمراجعة من المدرّس، وليس إثباتًا على الغش أو سوء السلوك.';

export function formatAnomalyReview(attempt) {
  const assessed =
    attempt?.anomaly_assessed === true ||
    (attempt?.anomaly_score !== null && attempt?.anomaly_score !== undefined);

  if (!assessed) {
    return {
      label: 'Not assessed',
      kind: 'unknown',
      reason: null,
    };
  }

  if (attempt?.is_suspicious) {
    return {
      label: 'Suspicious / Flagged for review',
      kind: 'flagged',
      reason: attempt.suspicion_reason || null,
    };
  }

  return {
    label: 'Normal',
    kind: 'normal',
    reason: attempt.suspicion_reason || null,
  };
}

export function formatAttemptDuration(durationSeconds) {
  if (durationSeconds === null || durationSeconds === undefined || durationSeconds < 0) {
    return 'غير متوفر';
  }
  const total = Math.floor(Number(durationSeconds) || 0);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  if (minutes === 0) {
    return `${seconds} ث`;
  }
  return `${minutes} د ${String(seconds).padStart(2, '0')} ث`;
}

export function formatCompletionTime(isoString) {
  if (!isoString) return 'غير متوفر';
  let dateStr = String(isoString).trim();
  // Ensure date strings without explicit timezone offsets are treated as UTC
  if (!dateStr.endsWith('Z') && !/[+-]\d{2}(?::?\d{2})?$/.test(dateStr)) {
    dateStr = dateStr.replace(' ', 'T') + 'Z';
  }
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return 'غير متوفر';
  return date.toLocaleString('ar-EG', {
    timeZone: 'Africa/Cairo',
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

export function examResultsErrorMessage(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }
  return EXAM_RESULTS_ERROR_MESSAGE;
}

export function buildStudentResultRows(payload) {
  const students = Array.isArray(payload?.students) ? payload.students : [];
  return students.map((student) => ({
    studentId: student.student_id,
    name: student.student_name || `Student #${student.student_id}`,
    submittedAttemptCount: student.submitted_attempt_count ?? 0,
    unsubmittedAttemptCount: student.unsubmitted_attempt_count ?? 0,
    attempts: (student.attempts || []).map((attempt) => ({
      attemptId: attempt.attempt_id,
      score: attempt.score,
      maxPossibleScore: attempt.max_possible_score,
      scorePercentage: attempt.score_percentage,
      submittedAt: attempt.submitted_at,
      durationSeconds: attempt.duration_seconds,
      durationLabel: formatAttemptDuration(attempt.duration_seconds),
      completionLabel: formatCompletionTime(attempt.submitted_at),
      anomaly: formatAnomalyReview(attempt),
    })),
  }));
}

/**
 * Computes the number of distinct students with at least one submitted attempt.
 * Excludes students with only unsubmitted attempts and avoids double-counting
 * students who submitted multiple attempts.
 */
export function countDistinctSubmittedStudents(payloadOrRows) {
  if (!payloadOrRows) return 0;
  if (
    typeof payloadOrRows === 'object' &&
    typeof payloadOrRows.distinct_submitted_students_count === 'number'
  ) {
    return payloadOrRows.distinct_submitted_students_count;
  }
  const list = Array.isArray(payloadOrRows)
    ? payloadOrRows
    : Array.isArray(payloadOrRows.students)
    ? payloadOrRows.students
    : [];

  const distinctIds = new Set();
  for (const item of list) {
    const studentId = item.studentId ?? item.student_id;
    if (studentId == null) continue;

    const count =
      item.submittedAttemptCount ??
      item.submitted_attempt_count ??
      (Array.isArray(item.attempts)
        ? item.attempts.filter((a) => a.submittedAt || a.submitted_at).length
        : 0);

    if (count > 0) {
      distinctIds.add(studentId);
    }
  }
  return distinctIds.size;
}
