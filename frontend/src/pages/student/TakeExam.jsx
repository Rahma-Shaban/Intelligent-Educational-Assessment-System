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
  ChevronRight,
  ChevronLeft,
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
          'معرفناش نبدأ محاولة. تأكد إنك مسجّل دخول كطالب.';
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
        'حصلت مشكلة في التسليم، حاول تاني.';
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
        setError('معرفناش نحمّل الامتحان ده. يمكن مش موجود أو السيرفر واقف.');
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
      alert('خلص الوقت! بنسلّم إجاباتك تلقائياً دلوقتي.');
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
    return <LoadingSpinner size="lg" message="بنجهّز الامتحان والمؤقّت..." />;
  }

  if (error || !exam) {
    return (
      <div className="max-w-2xl mx-auto space-y-4">
        <Alert type="error" title="الامتحان غير متاح" message={error} />
        <Button onClick={() => navigate('/student/exams')} className="btn-cut">ارجع لقائمة الامتحانات</Button>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Top Bar with Timer and Progress */}
      <div className="sticky top-16 z-20 bg-paper/95 backdrop-blur-md border border-sand rounded-2xl p-4 shadow-warm flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-extrabold text-ink line-clamp-1" dir="auto">
            {exam.title || exam.topic || `Assessment #${id}`}
          </h2>
          <div className="flex items-center gap-3 text-xs text-cocoa-500 mt-0.5">
            <span>
              جاوبت على <strong className="text-teal-700">{answeredCount}</strong> من{' '}
              <strong>{totalQuestions}</strong>
            </span>
            <span>&bull;</span>
            <span className="font-bold">
              {exam.difficulty === 'easy' ? 'سهل' : exam.difficulty === 'hard' ? 'صعب' : 'متوسط'}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Live Timer Indicator */}
          <div
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl font-code text-sm font-bold border-2 transition-colors ${
              remainingSeconds < 300
                ? 'bg-rose-50 text-rose-700 border-rose-300 animate-pulse'
                : 'bg-gold-50 text-gold-700 border-gold-300'
            }`}
          >
            <Clock className="w-4 h-4" />
            <span dir="ltr">{formatTimer(remainingSeconds)}</span>
          </div>

          <Button
            variant="success"
            size="md"
            icon={Send}
            onClick={() => setShowConfirmModal(true)}
            className="btn-cut"
          >
            سلّم الامتحان
          </Button>
        </div>
      </div>

      {submitError && <Alert type="error" message={submitError} onClose={() => setSubmitError('')} />}

      {/* Question Navigation Tabs */}
      <div className="bg-paper p-3 rounded-2xl border border-sand flex items-center gap-2 overflow-x-auto">
        {exam.questions?.map((_, idx) => {
          const isAnswered =
            answers[idx] !== undefined && String(answers[idx]).trim().length > 0;
          const isCurrent = idx === currentIndex;

          return (
            <button
              key={idx}
              type="button"
              onClick={() => setCurrentIndex(idx)}
              className={`w-9 h-9 rounded-xl font-bold text-xs flex items-center justify-center transition-all shrink-0 ${
                isCurrent
                  ? 'bg-gradient-to-b from-clay-600 to-clay-800 text-white shadow-warm ring-2 ring-gold-300 -rotate-3'
                  : isAnswered
                  ? 'bg-teal-100 text-teal-800 border border-teal-300'
                  : 'bg-sand text-cocoa-500 hover:bg-cocoa-100 border border-transparent'
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
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-sand pb-4">
            <div className="flex items-center gap-2.5">
              <span className="w-9 h-9 rounded-xl rounded-br-sm bg-gradient-to-b from-clay-600 to-clay-800 text-gold-300 font-display text-sm flex items-center justify-center">
                Q{currentIndex + 1}
              </span>
              <Badge type="qtype">{currentQuestion.question_type}</Badge>
              {currentQuestion.bloom_level && (
                <Badge type="bloom">{currentQuestion.bloom_level}</Badge>
              )}
            </div>
            <span className="text-xs font-bold text-cocoa-800 bg-cream px-3 py-1 rounded-lg border border-sand">
              الدرجة: {currentQuestion.max_score || 1}
            </span>
          </div>

          {/* Question Prompt */}
          <div className="text-ink text-base md:text-lg font-bold leading-relaxed" dir="auto">
            {currentQuestion.question}
          </div>

          {/* Answer Input Controls Based on Question Type */}
          <div className="space-y-4 pt-2">
            {/* 1. Multiple Choice (MCQ) */}
            {currentQuestion.question_type === 'mcq' && currentQuestion.options && (
              <div className="space-y-2.5">
                <p className="text-xs font-bold text-cocoa-500 mb-2">
                  اختار الإجابة الصح:
                </p>
                {currentQuestion.options.map((option, optIdx) => {
                  const letter = String.fromCharCode(65 + optIdx);
                  const isChecked = answers[currentIndex] === letter;

                  return (
                    <label
                      key={optIdx}
                      onClick={() => handleSelectAnswer(currentIndex, letter)}
                      className={`flex items-center gap-3 p-4 rounded-2xl border-2 text-sm font-bold cursor-pointer transition-all ${
                        isChecked
                          ? 'border-clay-600 bg-clay-50 text-clay-950 shadow-warm ring-1 ring-gold-400'
                          : 'border-sand hover:border-cocoa-300 bg-paper text-cocoa-800'
                      }`}
                      dir="auto"
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
                        className={`w-7 h-7 rounded-lg rounded-br-sm flex items-center justify-center text-xs font-bold border transition-colors ${
                          isChecked
                            ? 'bg-gradient-to-b from-clay-600 to-clay-800 border-clay-700 text-white'
                            : 'border-cocoa-300/60 text-cocoa-500 bg-cream'
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
                <label className="block text-xs font-bold text-cocoa-500">
                  إجابتك (شرح مختصر):
                </label>
                <input
                  type="text"
                  placeholder="اكتب إجابتك هنا..."
                  value={answers[currentIndex] || ''}
                  onChange={(e) => handleSelectAnswer(currentIndex, e.target.value)}
                  className="w-full p-3.5 text-sm bg-white border-2 border-cocoa-300/60 rounded-2xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 outline-none transition"
                  dir="auto"
                />
              </div>
            )}

            {/* 3. Essay Question */}
            {currentQuestion.question_type === 'essay' && (
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <label className="block text-xs font-bold text-cocoa-500">
                    إجابتك المقالية:
                  </label>
                  <span className="text-[11px] text-cocoa-300">
                    يدعم تنسيق Markdown
                  </span>
                </div>
                <textarea
                  rows={8}
                  placeholder="اشرح إجابتك بالتفصيل، واستشهد بمفاهيم من المنهج لو أمكن..."
                  value={answers[currentIndex] || ''}
                  onChange={(e) => handleSelectAnswer(currentIndex, e.target.value)}
                  className="w-full p-4 text-sm bg-white border-2 border-cocoa-300/60 rounded-2xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 outline-none leading-relaxed transition"
                  dir="auto"
                />
              </div>
            )}
          </div>

          {/* Bottom Pagination Controls */}
          <div className="pt-6 border-t border-sand flex items-center justify-between">
            <Button
              variant="secondary"
              size="md"
              disabled={currentIndex === 0}
              onClick={() => setCurrentIndex((prev) => prev - 1)}
              icon={ChevronRight}
            >
              السابق
            </Button>

            <span className="text-xs font-bold text-cocoa-500">
              سؤال {currentIndex + 1} من {totalQuestions}
            </span>

            {currentIndex < totalQuestions - 1 ? (
              <Button
                variant="primary"
                size="md"
                onClick={() => setCurrentIndex((prev) => prev + 1)}
                className="btn-cut"
              >
                السؤال اللي بعده
              </Button>
            ) : (
              <Button
                variant="success"
                size="md"
                icon={Send}
                onClick={() => setShowConfirmModal(true)}
                className="btn-cut"
              >
                راجع وسلّم
              </Button>
            )}
          </div>
        </Card>
      )}

      {/* Confirmation Modal */}
      <Modal
        isOpen={showConfirmModal}
        onClose={() => setShowConfirmModal(false)}
        title="تأكيد تسليم الامتحان"
        subtitle="راجع حالة إجاباتك قبل ما تسلّم نهائياً"
        footer={
          <>
            <Button
              variant="primary"
              size="md"
              loading={submitting}
              onClick={doSubmit}
              icon={Send}
              className="btn-cut"
            >
              أكيد، سلّم
            </Button>
            <Button
              variant="secondary"
              size="md"
              disabled={submitting}
              onClick={() => setShowConfirmModal(false)}
            >
              كمّل امتحان
            </Button>
          </>
        }
      >
        <div className="space-y-4 text-sm">
          <div className="p-4 bg-cream rounded-2xl border border-sand space-y-2">
            <div className="flex justify-between">
              <span className="text-cocoa-500 font-bold">إجمالي الأسئلة:</span>
              <span className="font-bold text-ink">{totalQuestions}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-cocoa-500 font-bold">إجابت عليها:</span>
              <span className="font-bold text-teal-700">{answeredCount}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-cocoa-500 font-bold">لسه فاضل:</span>
              <span className="font-bold text-rose-600">
                {totalQuestions - answeredCount}
              </span>
            </div>
            <div className="flex justify-between border-t border-sand pt-2">
              <span className="text-cocoa-500 font-bold">الوقت المتبقي:</span>
              <span className="font-code font-bold text-clay-700" dir="ltr">
                {formatTimer(remainingSeconds)}
              </span>
            </div>
          </div>

          {answeredCount < totalQuestions && (
            <div className="flex items-start gap-2.5 p-3 bg-gold-50 rounded-xl text-gold-800 text-xs border border-gold-200">
              <AlertTriangle className="w-4 h-4 text-gold-600 shrink-0 mt-0.5" />
              <span>
                عندك {totalQuestions - answeredCount} سؤال لسه فاضي. تقدر تسلّم دلوقتي، لكن الأسئلة الفاضية هتاخد صفر.
              </span>
            </div>
          )}

          <p className="text-xs text-cocoa-500">
            بعد التسليم، إجاباتك هتتقيّم ذكائياً حسب معايير التصحيح — والنتيجة تظهر فوراً.
          </p>
        </div>
      </Modal>
    </div>
  );
};

export default TakeExam;
