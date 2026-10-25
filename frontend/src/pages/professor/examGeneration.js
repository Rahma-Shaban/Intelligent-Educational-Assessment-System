export const buildExamPayload = ({
  title,
  selectedLesson,
  topic,
  difficulty,
  bloomLevel,
  questionTypes,
  numQuestions,
  lessonTitle,
}) => {
  const resolvedTopic =
    (topic && typeof topic === 'string' && topic.trim()) ||
    (lessonTitle && typeof lessonTitle === 'string' && lessonTitle.trim()) ||
    (selectedLesson ? `Lesson ${selectedLesson}` : 'General Curriculum');

  return {
    title: (title && typeof title === 'string' && title.trim()) || undefined,
    lesson_id: selectedLesson,
    lesson: selectedLesson,
    topic: resolvedTopic,
    difficulty,
    bloom_level: bloomLevel,
    question_types: questionTypes,
    number_of_questions: Number.parseInt(numQuestions, 10) || 3,
  };
};

export const assertRequestedQuestionCount = (exam, requestedCount) => {
  const generatedCount = Array.isArray(exam?.questions) ? exam.questions.length : 0;
  if (generatedCount !== requestedCount) {
    throw new Error(
      `Generation returned ${generatedCount} of ${requestedCount} requested questions.`
    );
  }
};
