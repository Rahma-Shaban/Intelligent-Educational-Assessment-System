/**
 * Utility helpers for exam taking and response submission formatting.
 */

export const buildAnswersDict = (questionsList, currentAnswers) => {
  const answersDict = {};
  const list = Array.isArray(questionsList) ? questionsList : [];
  const answers = currentAnswers || {};

  list.forEach((q, idx) => {
    const questionId = q.question_id || q.id || `Q${String(idx + 1).padStart(2, '0')}`;
    answersDict[questionId] = answers[idx] !== undefined ? String(answers[idx]) : '';
  });

  return answersDict;
};

export const buildSubmissionPayload = ({
  attemptId,
  questions,
  currentAnswers,
  elapsedSeconds,
}) => {
  if (!attemptId) {
    throw new Error('attemptId is required for exam submission.');
  }

  return {
    attempt_id: attemptId,
    answers: buildAnswersDict(questions, currentAnswers),
    duration_seconds: Math.max(0, elapsedSeconds || 0),
  };
};

export const formatTimer = (seconds) => {
  const total = Math.max(0, Number(seconds) || 0);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
};
