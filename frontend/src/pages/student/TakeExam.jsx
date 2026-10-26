import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getExam, startAttempt, submitAttempt } from '../../api/client';
import { buildSubmissionPayload, formatTimer } from './examTaking';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import Modal from '../../components/ui/Modal';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  Clock,
  CheckCircle2,
  AlertTriangle,
  Send,
  ChevronLeft,
  ChevronRight,
  HelpCircle,
  FileText,
  Check,
} from 'lucide-react';

const TakeExam = () => {
  const { id } = useParams();
  const navigate = useNavigate();

  const [exam, setExam] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Attempt tracking
  const [attemptId, setAttemptId] = useState(null);

  // Active question index
  const [currentIndex, setCurrentIndex] = useState(0);

  // Map of answers: index -> string
  const [answers, setAnswers] = useState({});
  const answersRef = useRef(answers);
  useEffect(() => {
    answersRef.current = answers;
  }, [answers]);

  // Timer states
  const [remainingSeconds, setRemainingSeconds] = useState(1800); // 30 minutes default
  const [initialSeconds, setInitialSeconds] = useState(1800);
  const timerRef = useRef(null);
  const startTimeRef = useRef(Date.now());

  // Submit states
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const isSubmittingRef = useRef(false);
  const [submitError, setSubmitError] = useState('');

  const doSubmit = useCallback(async () => {
    if (isSubmittingRef.current) return;
    isSubmittingRef.current = true;
    setSubmitting(true);
    setSubmitError('');

    const elapsedSeconds = Math.round((Date.now() - startTimeRef.current) / 1000);

    // If we have an attempt_id from startAttempt, use it
    // Otherwise, start one now
    let currentAttemptId = attemptId;
    if (!currentAttemptId) {
      try {
        const attemptData = await startAttempt(parseInt(id, 10));
        currentAttemptId = attemptData.attempt_id;
        setAttemptId(currentAttemptId);
      } catch (err) {
        console.error('Failed to start attempt:', err);
        const detail =
          err.response?.data?.detail ||
          err.response?.data?.message ||
          'Could not start an exam attempt. Make sure you are logged in as a student.';
        setSubmitError(typeof detail === 'string' ? detail : JSON.stringify(detail));
        setSubmitting(false);
        isSubmittingRef.current = false;
        return;
      }
    }

    const payload = buildSubmissionPayload({
      attemptId: currentAttemptId,
      questions: exam?.questions || [],
      currentAnswers: answersRef.current || {},
      elapsedSeconds,
    });

    try {
      const response = await submitAttempt(payload);
      setShowConfirmModal(false);
      const resultId = response.id || response.attempt_id || response._id;
      if (resultId) {
        navigate(`/student/attempt/${resultId}`);
      } else {
        navigate('/student/results');
      }
    } catch (err) {
      console.error('Submission error:', err);
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        'Error submitting answers. Please try again.';
      setSubmitError(typeof detail === 'string' ? detail : JSON.stringify(detail));
      setSubmitting(false);
      isSubmittingRef.current = false;
    }
  }, [attemptId, exam, id, navigate]);

  useEffect(() => {
    const fetchExamAndStartAttempt = async () => {
      setLoading(true);
      setError('');
      try {
        const data = await getExam(id);
        setExam(data);
        const qCount = data.questions?.length || 5;
        // Allocate 5 minutes per question
        const allocatedSeconds = Math.max(600, qCount * 300);
        setRemainingSeconds(allocatedSeconds);
        setInitialSeconds(allocatedSeconds);

        // Start an attempt to get an attempt_id
        try {
          const attemptData = await startAttempt(parseInt(id, 10));
          setAttemptId(attemptData.attempt_id);
          startTimeRef.current = Date.now();
        } catch (attemptErr) {
          console.warn('Could not start attempt (may need student role):', attemptErr);
          // Still let them view the exam even if attempt creation fails
          // They can try submitting later
        }
      } catch (err) {
        console.error('Failed to load exam:', err);
        setError('Failed to load this assessment. It may not exist or the backend is offline.');
      } finally {
        setLoading(false);
      }
    };

    if (id) {
      fetchExamAndStartAttempt();
    }
  }, [id]);

  // Live countdown timer
  useEffect(() => {
    if (loading || !exam) return;

    timerRef.current = setInterval(() => {
      setRemainingSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(timerRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [loading, exam]);

  // Handle auto-submit safely when timer reaches zero
  useEffect(() => {
    if (remainingSeconds === 0 && !loading && exam && !isSubmittingRef.current) {
      alert('Time has expired! Submitting your answers automatically now.');
      doSubmit();
    }
  }, [remainingSeconds, loading, exam, doSubmit]);

  const handleSelectAnswer = (index, value) => {
    setAnswers((prev) => ({
      ...prev,
      [index]: value,
    }));
  };

  const answeredCount = Object.values(answers).filter(
    (ans) => typeof ans === 'string' && ans.trim().length > 0
  ).length;

  const totalQuestions = exam?.questions?.length || 0;
  const currentQuestion = exam?.questions ? exam.questions[currentIndex] : null;

  if (loading) {
    return <LoadingSpinner size="lg" message="Preparing assessment and timer..." />;
  }

  if (error || !exam) {
    return (
      <div className="max-w-2xl mx-auto space-y-4">
        <Alert type="error" title="Assessment Unavailable" message={error} />
        <Button onClick={() => navigate('/student/exams')}>Return to Exams List</Button>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Top Bar with Timer and Progress */}
      <div className="sticky top-16 z-20 bg-white/95 backdrop-blur-md border border-gray-200/90 rounded-2xl p-4 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-gray-900 line-clamp-1">
            {exam.title || exam.topic || `Assessment #${id}`}
          </h2>
          <div className="flex items-center gap-3 text-xs text-gray-500 mt-0.5">
            <span>
              Progress: <strong>{answeredCount}</strong> of <strong>{totalQuestions}</strong> answered
            </span>
            <span>&bull;</span>
            <span className="capitalize">{exam.difficulty} difficulty</span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {/* Live Timer Indicator */}
          <div
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl font-mono text-sm font-bold border transition-colors ${
              remainingSeconds < 300
                ? 'bg-rose-50 text-rose-700 border-rose-300 animate-pulse'
                : 'bg-indigo-50 text-indigo-700 border-indigo-200'
            }`}
          >
            <Clock className="w-4 h-4" />
            <span>{formatTimer(remainingSeconds)}</span>
          </div>

          <Button
            variant="success"
            size="md"
            icon={Send}
            onClick={() => setShowConfirmModal(true)}
          >
            Finish &amp; Submit
          </Button>
        </div>
      </div>

      {submitError && <Alert type="error" message={submitError} onClose={() => setSubmitError('')} />}

      {/* Question Navigation Tabs */}
      <div className="bg-white p-3 rounded-xl border border-gray-200/80 flex items-center gap-2 overflow-x-auto">
        {exam.questions?.map((_, idx) => {
          const isAnswered =
            answers[idx] !== undefined && String(answers[idx]).trim().length > 0;
          const isCurrent = idx === currentIndex;

          return (
            <button
              key={idx}
              type="button"
              onClick={() => setCurrentIndex(idx)}
              className={`w-9 h-9 rounded-lg font-bold text-xs flex items-center justify-center transition-all shrink-0 ${
                isCurrent
                  ? 'bg-indigo-600 text-white shadow-md ring-2 ring-indigo-300'
                  : isAnswered
                  ? 'bg-emerald-100 text-emerald-800 border border-emerald-300'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200 border border-transparent'
              }`}
            >
              {idx + 1}
            </button>
          );
        })}
      </div>

      {/* Current Question Body */}
      {currentQuestion && (
        <Card className="p-6 md:p-8 space-y-6">
          {/* Question Header */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 pb-4">
            <div className="flex items-center gap-2.5">
              <span className="w-8 h-8 rounded-lg bg-indigo-600 text-white font-bold text-sm flex items-center justify-center">
                Q{currentIndex + 1}
              </span>
              <Badge type="qtype">{currentQuestion.question_type}</Badge>
              {currentQuestion.bloom_level && (
                <Badge type="bloom">{currentQuestion.bloom_level}</Badge>
              )}
            </div>
            <span className="text-xs font-semibold text-gray-500 bg-gray-50 px-3 py-1 rounded-md border border-gray-200">
              Worth: {currentQuestion.max_score || 1} point(s)
            </span>
          </div>

          {/* Question Prompt */}
          <div className="text-gray-900 text-base md:text-lg font-semibold leading-relaxed">
            {currentQuestion.question}
          </div>

          {/* Answer Input Controls Based on Question Type */}
          <div className="space-y-4 pt-2">
            {/* 1. Multiple Choice (MCQ) */}
            {currentQuestion.question_type === 'mcq' && currentQuestion.options && (
              <div className="space-y-2.5">
                <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
                  Select the best answer:
                </p>
                {currentQuestion.options.map((option, optIdx) => {
                  const letter = String.fromCharCode(65 + optIdx);
                  const isChecked = answers[currentIndex] === letter;

                  return (
                    <label
                      key={optIdx}
                      onClick={() => handleSelectAnswer(currentIndex, letter)}
                      className={`flex items-center gap-3 p-4 rounded-xl border text-sm font-medium cursor-pointer transition-all ${
                        isChecked
                          ? 'border-indigo-600 bg-indigo-50/70 text-indigo-950 shadow-sm ring-1 ring-indigo-500'
                          : 'border-gray-200 hover:border-gray-300 bg-white text-gray-700'
                      }`}
                    >
                      <input
                        type="radio"
                        name={`q-${currentIndex}`}
                        value={letter}
                        checked={isChecked}
                        onChange={() => {}}
                        className="hidden"
                      />
                      <span
                        className={`w-6 h-6 rounded-md flex items-center justify-center text-xs font-bold border transition-colors ${
                          isChecked
                            ? 'bg-indigo-600 border-indigo-600 text-white'
                            : 'border-gray-300 text-gray-600 bg-gray-50'
                        }`}
                      >
                        {letter}
                      </span>
                      <span className="flex-1">{option}</span>
                    </label>
                  );
                })}
              </div>
            )}

            {/* 2. Short Answer */}
            {currentQuestion.question_type === 'short_answer' && (
              <div className="space-y-2">
                <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider">
                  Your Answer (Concise Explanation):
                </label>
                <input
                  type="text"
                  placeholder="Type your response here..."
                  value={answers[currentIndex] || ''}
                  onChange={(e) => handleSelectAnswer(currentIndex, e.target.value)}
                  className="w-full p-3.5 text-sm border border-gray-300 rounded-xl focus:ring-2 focus:ring-indigo-600 focus:border-indigo-600"
                />
              </div>
            )}

            {/* 3. Essay Question */}
            {currentQuestion.question_type === 'essay' && (
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider">
                    Your Essay Answer:
                  </label>
                  <span className="text-[11px] text-gray-400">
                    Supports Markdown formatting
                  </span>
                </div>
                <textarea
                  rows={8}
                  placeholder="Elaborate your explanation here. Cite principles from the curriculum where applicable..."
                  value={answers[currentIndex] || ''}
                  onChange={(e) => handleSelectAnswer(currentIndex, e.target.value)}
                  className="w-full p-4 text-sm border border-gray-300 rounded-xl focus:ring-2 focus:ring-indigo-600 focus:border-indigo-600 font-sans leading-relaxed"
                />
              </div>
            )}
          </div>

          {/* Bottom Pagination Controls */}
          <div className="pt-6 border-t border-gray-100 flex items-center justify-between">
            <Button
              variant="secondary"
              size="md"
              disabled={currentIndex === 0}
              onClick={() => setCurrentIndex((prev) => prev - 1)}
              icon={ChevronLeft}
            >
              Previous
            </Button>

            <span className="text-xs font-medium text-gray-500">
              Question {currentIndex + 1} of {totalQuestions}
            </span>

            {currentIndex < totalQuestions - 1 ? (
              <Button
                variant="primary"
                size="md"
                onClick={() => setCurrentIndex((prev) => prev + 1)}
              >
                Next Question &rarr;
              </Button>
            ) : (
              <Button
                variant="success"
                size="md"
                icon={Send}
                onClick={() => setShowConfirmModal(true)}
              >
                Review &amp; Submit
              </Button>
            )}
          </div>
        </Card>
      )}

      {/* Confirmation Modal */}
      <Modal
        isOpen={showConfirmModal}
        onClose={() => setShowConfirmModal(false)}
        title="Confirm Assessment Submission"
        subtitle="Please review your completion status before finalizing"
        footer={
          <>
            <Button
              variant="primary"
              size="md"
              loading={submitting}
              onClick={doSubmit}
              icon={Send}
            >
              Confirm and Submit
            </Button>
            <Button
              variant="secondary"
              size="md"
              disabled={submitting}
              onClick={() => setShowConfirmModal(false)}
            >
              Continue Exam
            </Button>
          </>
        }
      >
        <div className="space-y-4 text-sm">
          <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-2">
            <div className="flex justify-between">
              <span className="text-gray-600">Total Questions:</span>
              <span className="font-bold text-gray-900">{totalQuestions}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Answered Questions:</span>
              <span className="font-bold text-emerald-600">{answeredCount}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Unanswered Questions:</span>
              <span className="font-bold text-rose-600">
                {totalQuestions - answeredCount}
              </span>
            </div>
            <div className="flex justify-between border-t border-gray-200 pt-2">
              <span className="text-gray-600">Time Remaining:</span>
              <span className="font-mono font-bold text-indigo-600">
                {formatTimer(remainingSeconds)}
              </span>
            </div>
          </div>

          {answeredCount < totalQuestions && (
            <div className="flex items-start gap-2.5 p-3 bg-amber-50 rounded-lg text-amber-800 text-xs border border-amber-200">
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <span>
                You have {totalQuestions - answeredCount} unanswered question(s). You can still submit now, but unattempted questions will receive 0 points.
              </span>
            </div>
          )}

          <p className="text-xs text-gray-500">
            Once submitted, your answers will be evaluated semantically by our AI engine against the rubric criteria.
          </p>
        </div>
      </Modal>
    </div>
  );
};

export default TakeExam;
