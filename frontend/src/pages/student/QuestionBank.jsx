import React, { useState, useEffect, useCallback } from 'react';
import {
  Database,
  Search,
  Filter,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  HelpCircle,
  Layers,
  Sparkles,
  Check,
  RotateCcw,
  PenLine,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Send,
} from 'lucide-react';
import { getQuestionBank, submitQuestionBankPractice } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import Alert from '../../components/ui/Alert';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import {
  BLOOM_TRANSLATIONS,
  DIFFICULTY_TRANSLATIONS,
  TYPE_TRANSLATIONS,
  saveStudentDraft,
  loadStudentDraft,
  clearStudentDraft,
} from './questionBankUtils';

const StudentQuestionBank = () => {
  const [questions, setQuestions] = useState([]);
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Filters
  const [search, setSearch] = useState('');
  const [difficultyFilter, setDifficultyFilter] = useState('');
  const [bloomFilter, setBloomFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  // Local interactive practice state: student can test their answer selection
  const [selectedAnswers, setSelectedAnswers] = useState({});

  // Graded practice results keyed by question_id: { is_correct, score, max_score, correct_option, correct_answer, explanation, feedback_message, status, requires_teacher_review }
  const [gradedSubmissions, setGradedSubmissions] = useState({});
  const [submittingQuestion, setSubmittingQuestion] = useState({});
  const [submissionErrors, setSubmissionErrors] = useState({});

  // Local self-practice draft answers for essay & short-answer questions
  const [drafts, setDrafts] = useState({});
  const [draftStatus, setDraftStatus] = useState({});

  const fetchQuestions = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = {
        page,
        page_size: pageSize,
      };
      if (search.trim()) params.search = search.trim();
      if (difficultyFilter) params.difficulty = difficultyFilter;
      if (bloomFilter) params.bloom_level = bloomFilter;
      if (typeFilter) params.question_type = typeFilter;

      const data = await getQuestionBank(params);
      const items = data.items || [];
      setQuestions(items);
      setTotalQuestions(data.total || 0);
      setTotalPages(data.total_pages || 1);

      // Preload saved local drafts for non-MCQ questions
      const initialDrafts = {};
      items.forEach((item) => {
        if (item.question_type !== 'mcq' && item.question_id) {
          const saved = loadStudentDraft(item.question_id);
          if (saved) {
            initialDrafts[item.question_id] = saved;
          }
        }
      });
      setDrafts((prev) => ({ ...initialDrafts, ...prev }));
    } catch (err) {
      console.error('Failed to load student question bank:', err);
      setError('فشل تحميل بنك الأسئلة. يرجى المحاولة مرة أخرى.');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search, difficultyFilter, bloomFilter, typeFilter]);

  useEffect(() => {
    fetchQuestions();
  }, [fetchQuestions]);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setPage(1);
    fetchQuestions();
  };

  const handleClearFilters = () => {
    setSearch('');
    setDifficultyFilter('');
    setBloomFilter('');
    setTypeFilter('');
    setPage(1);
  };

  const handleSelectOption = (questionId, optionIndex) => {
    setSelectedAnswers((prev) => ({
      ...prev,
      [questionId]: prev[questionId] === optionIndex ? null : optionIndex,
    }));
  };

  const handleDraftChange = (questionId, value) => {
    setDrafts((prev) => ({
      ...prev,
      [questionId]: value,
    }));
    if (draftStatus[questionId]?.type === 'error') {
      setDraftStatus((prev) => ({
        ...prev,
        [questionId]: null,
      }));
    }
  };

  const handleSaveDraft = (questionId) => {
    const text = drafts[questionId] || '';
    const result = saveStudentDraft(questionId, text);
    if (!result.success) {
      setDraftStatus((prev) => ({
        ...prev,
        [questionId]: {
          type: 'error',
          message: result.error,
        },
      }));
    } else {
      setDraftStatus((prev) => ({
        ...prev,
        [questionId]: {
          type: 'success',
          message: 'تم حفظ الإجابة بنجاح',
          savedAt: new Date().toLocaleTimeString('ar-EG', {
            hour: '2-digit',
            minute: '2-digit',
          }),
        },
      }));
    }
  };

  const handleClearDraft = (questionId) => {
    clearStudentDraft(questionId);
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[questionId];
      return next;
    });
    setDraftStatus((prev) => ({
      ...prev,
      [questionId]: null,
    }));
  };

  const handleSubmitMcqPractice = async (questionId) => {
    const selectedIdx = selectedAnswers[questionId];
    if (selectedIdx === undefined || selectedIdx === null) {
      setSubmissionErrors((prev) => ({
        ...prev,
        [questionId]: 'يرجى اختيار أحد الخيارات أولاً قبل تأكيد الإجابة.',
      }));
      return;
    }
    const q = questions.find((item) => (item.question_id || item.id) === questionId);
    const selectedLetter = ['A', 'B', 'C', 'D'][selectedIdx] || String(selectedIdx);
    const selectedText = q?.options?.[selectedIdx] || '';

    setSubmittingQuestion((prev) => ({ ...prev, [questionId]: true }));
    setSubmissionErrors((prev) => ({ ...prev, [questionId]: '' }));

    try {
      const res = await submitQuestionBankPractice(questionId, {
        selected_option: selectedLetter,
        answer_text: selectedText,
      });
      setGradedSubmissions((prev) => ({ ...prev, [questionId]: res }));
    } catch (err) {
      console.error('Failed to submit practice answer:', err);
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : 'تعذر التحقق من الإجابة في الوقت الحالي. يرجى المحاولة مرة أخرى.';
      setSubmissionErrors((prev) => ({ ...prev, [questionId]: msg }));
    } finally {
      setSubmittingQuestion((prev) => ({ ...prev, [questionId]: false }));
    }
  };

  const handleResetPractice = (questionId) => {
    setSelectedAnswers((prev) => {
      const updated = { ...prev };
      delete updated[questionId];
      return updated;
    });
    setGradedSubmissions((prev) => {
      const updated = { ...prev };
      delete updated[questionId];
      return updated;
    });
    setSubmissionErrors((prev) => {
      const updated = { ...prev };
      delete updated[questionId];
      return updated;
    });
  };

  const handleSubmitEssayReview = async (questionId) => {
    const text = drafts[questionId]?.trim() || '';
    if (!text) {
      setSubmissionErrors((prev) => ({
        ...prev,
        [questionId]: 'يرجى كتابة مسودة الإجابة أولاً قبل إرسالها للمراجعة.',
      }));
      return;
    }

    setSubmittingQuestion((prev) => ({ ...prev, [questionId]: true }));
    setSubmissionErrors((prev) => ({ ...prev, [questionId]: '' }));

    try {
      const res = await submitQuestionBankPractice(questionId, {
        answer_text: text,
      });
      setGradedSubmissions((prev) => ({ ...prev, [questionId]: res }));
      saveStudentDraft(questionId, text);
    } catch (err) {
      console.error('Failed to submit essay for review:', err);
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : 'تعذر تسجيل الإجابة لمراجعة المعلم. يرجى المحاولة مرة أخرى.';
      setSubmissionErrors((prev) => ({ ...prev, [questionId]: msg }));
    } finally {
      setSubmittingQuestion((prev) => ({ ...prev, [questionId]: false }));
    }
  };

  const hasActiveFilters = Boolean(search || difficultyFilter || bloomFilter || typeFilter);

  return (
    <div className="space-y-6 max-w-6xl mx-auto" dir="rtl">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-sand">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-teal-50 text-teal-700 flex items-center justify-center font-bold shrink-0">
            <Database className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-display text-2xl md:text-3xl text-ink">بنك الأسئلة</h1>
            <p className="text-xs text-cocoa-500 mt-0.5">
              استعراض الأسئلة المعتمدة للتدريب والمذاكرة الذاتية
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <Button
            variant="outline"
            size="sm"
            icon={RotateCcw}
            onClick={fetchQuestions}
            loading={loading}
            title="تحديث بنك الأسئلة"
          >
            تحديث
          </Button>
          <span className="text-xs font-semibold px-3 py-1.5 rounded-xl bg-white border border-sand text-cocoa-700 shadow-sm">
            {totalQuestions} سؤال متاح
          </span>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <Alert type="error" message={error} onClose={() => setError('')} />
      )}

      {/* Search and Filters */}
      <Card className="p-4 bg-white border-sand">
        <form onSubmit={handleSearchSubmit} className="flex flex-col md:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute right-3 top-3 text-cocoa-300 pointer-events-none" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="البحث في نص السؤال أو الدرس..."
              className="w-full pr-9 pl-4 py-2 border border-sand rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/20 focus:border-teal-600 transition"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              value={difficultyFilter}
              onChange={(e) => {
                setDifficultyFilter(e.target.value);
                setPage(1);
              }}
              className="px-3 py-2 border border-sand rounded-xl text-xs bg-white text-cocoa-800 focus:outline-none focus:ring-2 focus:ring-teal-500/20"
            >
              <option value="">جميع مستويات الصعوبة</option>
              <option value="easy">سهل</option>
              <option value="medium">متوسط</option>
              <option value="hard">صعب</option>
            </select>

            <select
              value={bloomFilter}
              onChange={(e) => {
                setBloomFilter(e.target.value);
                setPage(1);
              }}
              className="px-3 py-2 border border-sand rounded-xl text-xs bg-white text-cocoa-800 focus:outline-none focus:ring-2 focus:ring-teal-500/20"
            >
              <option value="">جميع المستويات الإدراكية</option>
              <option value="remember">تذكر</option>
              <option value="understand">فهم</option>
              <option value="apply">تطبيق</option>
              <option value="analyze">تحليل</option>
              <option value="evaluate">تقييم</option>
              <option value="create">ابتكار</option>
            </select>

            <select
              value={typeFilter}
              onChange={(e) => {
                setTypeFilter(e.target.value);
                setPage(1);
              }}
              className="px-3 py-2 border border-sand rounded-xl text-xs bg-white text-cocoa-800 focus:outline-none focus:ring-2 focus:ring-teal-500/20"
            >
              <option value="">جميع أنواع الأسئلة</option>
              <option value="mcq">اختيار من متعدد</option>
              <option value="short_answer">إجابة قصيرة</option>
              <option value="essay">سؤال مقالي</option>
            </select>

            <Button type="submit" variant="primary" size="sm">
              بحث
            </Button>

            {hasActiveFilters && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleClearFilters}
                className="text-xs text-cocoa-500 hover:text-ink"
              >
                مسح التصفية
              </Button>
            )}
          </div>
        </form>
      </Card>

      {/* Questions Listing */}
      <div className="space-y-4">
        {loading ? (
          <div className="py-16 flex justify-center">
            <LoadingSpinner size="lg" message="جاري استعلام بنك الأسئلة..." />
          </div>
        ) : questions.length === 0 ? (
          <Card className="p-12 text-center bg-white border-dashed border-sand">
            <div className="w-12 h-12 rounded-2xl bg-sand text-cocoa-500 flex items-center justify-center mx-auto mb-3">
              <Database className="w-6 h-6" />
            </div>
            <h3 className="text-base font-bold text-ink mb-1">لا توجد أسئلة تطابق البحث</h3>
            <p className="text-xs text-cocoa-500 max-w-sm mx-auto mb-4">
              {hasActiveFilters
                ? 'جرّب تعديل كلمات البحث أو مسح عوامل التصفية لعرض مزيد من الأسئلة.'
                : 'لم يتم اعتماد أسئلة في بنك الأسئلة بعد. ستظهر الأسئلة المعتمدة هنا فور مراجعتها.'}
            </p>
            {hasActiveFilters && (
              <Button size="sm" variant="outline" onClick={handleClearFilters}>
                إلغاء التصفية
              </Button>
            )}
          </Card>
        ) : (
          questions.map((q, idx) => {
            const itemNumber = (page - 1) * pageSize + idx + 1;
            const chosenOpt = selectedAnswers[q.question_id];

            return (
              <Card
                key={q.question_id || q.id}
                className="p-5 bg-white border-sand hover:border-gold-300 transition-all shadow-sm"
              >
                <div className="space-y-3">
                  {/* Meta Badges */}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-bold font-code text-cocoa-700 bg-sand px-2 py-0.5 rounded-lg">
                      #{itemNumber}
                    </span>
                    <span className="text-xs text-cocoa-600 bg-sand/60 px-2 py-0.5 rounded-lg">
                      {TYPE_TRANSLATIONS[q.question_type] || q.question_type}
                    </span>
                    {q.difficulty && (
                      <Badge type="difficulty">
                        {DIFFICULTY_TRANSLATIONS[q.difficulty.toLowerCase()] || q.difficulty}
                      </Badge>
                    )}
                    {q.bloom_level && (
                      <Badge type="bloom">
                        {BLOOM_TRANSLATIONS[q.bloom_level.toLowerCase()] || q.bloom_level}
                      </Badge>
                    )}
                    {q.lesson && (
                      <span className="text-xs text-cocoa-600 flex items-center gap-1 bg-cream px-2 py-0.5 rounded-lg border border-sand">
                        <BookOpen className="w-3 h-3 text-cocoa-400" />
                        {q.lesson}
                      </span>
                    )}
                  </div>

                  {/* Question Stem */}
                  <div className="text-sm md:text-base font-bold text-ink leading-relaxed">
                    {q.question_text}
                  </div>

                  {/* Multiple Choice Options with Authoritative Grading & Feedback */}
                  {q.question_type === 'mcq' && q.options && q.options.length > 0 && (() => {
                    const graded = gradedSubmissions[q.question_id];
                    const isSubmitting = submittingQuestion[q.question_id];
                    const submissionError = submissionErrors[q.question_id];

                    return (
                      <div className="space-y-3 pt-1">
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          {q.options.map((opt, optIdx) => {
                            const letter = ['A', 'B', 'C', 'D'][optIdx] || String(optIdx + 1);
                            const isSelected = chosenOpt === optIdx;

                            // Calculate styling when graded vs unsubmitted
                            let btnStyle = 'bg-cream/40 border-sand text-cocoa-800 hover:bg-cream hover:border-cocoa-300';
                            let badgeStyle = 'bg-sand text-cocoa-700';
                            let statusLabel = null;

                            if (!graded) {
                              if (isSelected) {
                                btnStyle = 'bg-teal-50 border-teal-500 font-bold text-teal-950 shadow-sm ring-1 ring-teal-500';
                                badgeStyle = 'bg-teal-600 text-white';
                              }
                            } else {
                              const isCorrectOpt =
                                letter === graded.correct_option ||
                                (graded.correct_answer && opt.trim().toLowerCase() === graded.correct_answer.trim().toLowerCase());

                              if (graded.is_correct === true) {
                                if (isSelected) {
                                  btnStyle = 'bg-emerald-50 border-emerald-500 font-bold text-emerald-950 shadow-sm ring-2 ring-emerald-500';
                                  badgeStyle = 'bg-emerald-600 text-white';
                                  statusLabel = 'إجابتك الصحيحة ✓';
                                } else {
                                  btnStyle = 'bg-cream/20 border-sand/60 text-cocoa-400 opacity-60';
                                }
                              } else if (graded.is_correct === false) {
                                if (isSelected) {
                                  btnStyle = 'bg-rose-50 border-rose-500 font-bold text-rose-950 shadow-sm ring-2 ring-rose-500';
                                  badgeStyle = 'bg-rose-600 text-white';
                                  statusLabel = 'إجابتك المختارة ✗';
                                } else if (isCorrectOpt) {
                                  btnStyle = 'bg-emerald-50 border-emerald-500 font-bold text-emerald-950 shadow-sm ring-2 ring-emerald-500';
                                  badgeStyle = 'bg-emerald-600 text-white';
                                  statusLabel = 'الإجابة الصحيحة ✓';
                                } else {
                                  btnStyle = 'bg-cream/20 border-sand/60 text-cocoa-400 opacity-60';
                                }
                              } else {
                                // Missing key or pending
                                if (isSelected) {
                                  btnStyle = 'bg-amber-50 border-amber-500 font-bold text-amber-950 ring-1 ring-amber-500';
                                  badgeStyle = 'bg-amber-600 text-white';
                                }
                              }
                            }

                            return (
                              <button
                                type="button"
                                key={optIdx}
                                disabled={Boolean(graded) || isSubmitting}
                                onClick={() => handleSelectOption(q.question_id, optIdx)}
                                className={`p-3 rounded-xl border text-xs sm:text-sm text-right flex items-center gap-2.5 transition-all ${btnStyle}`}
                              >
                                <span
                                  className={`w-6 h-6 rounded-lg text-xs font-bold flex items-center justify-center shrink-0 ${badgeStyle}`}
                                >
                                  {letter}
                                </span>
                                <span className="flex-1 leading-normal">{opt}</span>
                                {statusLabel && (
                                  <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-white/90 shadow-xs">
                                    {statusLabel}
                                  </span>
                                )}
                                {!graded && isSelected && <Check className="w-4 h-4 text-teal-600 shrink-0" />}
                              </button>
                            );
                          })}
                        </div>

                        {/* Interactive Practice Action Bar (Unsubmitted state) */}
                        {!graded && (
                          <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-sand/60">
                            <div className="flex items-center gap-2">
                              <Button
                                type="button"
                                variant="primary"
                                size="sm"
                                disabled={chosenOpt === undefined || isSubmitting}
                                loading={isSubmitting}
                                onClick={() => handleSubmitMcqPractice(q.question_id)}
                                className="flex items-center gap-1.5 text-xs shadow-sm"
                              >
                                <Check className="w-3.5 h-3.5" />
                                <span>تأكيد الإجابة والتحقق</span>
                              </Button>

                              {chosenOpt !== undefined && !isSubmitting && (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => handleResetPractice(q.question_id)}
                                  className="text-xs text-cocoa-500 hover:text-cocoa-800"
                                >
                                  إلغاء التحديد
                                </Button>
                              )}
                            </div>

                            {submissionError && (
                              <div className="text-xs text-rose-600 flex items-center gap-1 font-medium">
                                <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                                <span>{submissionError}</span>
                              </div>
                            )}
                          </div>
                        )}

                        {/* Authoritative Grading Result Card (Immediate Post-submission feedback) */}
                        {graded && (
                          <div className="space-y-2 pt-1">
                            {/* Correct Banner */}
                            {graded.is_correct === true && (
                              <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-950 space-y-2 animate-fadeIn">
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-2 font-bold text-sm text-emerald-900">
                                    <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
                                    <span>إجابة صحيحة! أحسنت 🎉</span>
                                  </div>
                                  <span className="text-xs font-bold bg-emerald-200/80 text-emerald-900 px-2.5 py-0.5 rounded-full">
                                    الدرجة: {graded.score} / {graded.max_score}
                                  </span>
                                </div>
                                <p className="text-xs text-emerald-800 leading-relaxed font-medium">
                                  {graded.feedback_message}
                                </p>
                                {graded.explanation && (
                                  <div className="pt-2 border-t border-emerald-200/70 text-xs text-emerald-900 leading-relaxed">
                                    <span className="font-bold text-emerald-950">💡 التفسير والشرح: </span>
                                    <span>{graded.explanation}</span>
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Incorrect Banner */}
                            {graded.is_correct === false && (
                              <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-950 space-y-2 animate-fadeIn">
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-2 font-bold text-sm text-rose-900">
                                    <XCircle className="w-5 h-5 text-rose-600 shrink-0" />
                                    <span>إجابة غير صحيحة</span>
                                  </div>
                                  <span className="text-xs font-bold bg-rose-200/80 text-rose-900 px-2.5 py-0.5 rounded-full">
                                    الدرجة: 0 / {graded.max_score}
                                  </span>
                                </div>
                                <p className="text-xs text-rose-800 leading-relaxed font-medium">
                                  {graded.feedback_message}
                                </p>
                                <div className="p-2.5 bg-white/80 rounded-lg border border-rose-200 text-xs text-rose-950 flex flex-wrap items-center gap-2">
                                  <span className="font-bold text-cocoa-700">الإجابة الصحيحة المعتمدة:</span>
                                  <span className="font-bold text-emerald-800 bg-emerald-100 px-2 py-0.5 rounded">
                                    {graded.correct_option ? `(${graded.correct_option}) ` : ''}
                                    {graded.correct_answer || 'محددة في الخيارات'}
                                  </span>
                                </div>
                                {graded.explanation && (
                                  <div className="pt-2 border-t border-rose-200/70 text-xs text-rose-900 leading-relaxed">
                                    <span className="font-bold text-rose-950">💡 التفسير والشرح: </span>
                                    <span>{graded.explanation}</span>
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Unverified Answer Key Banner */}
                            {graded.status === 'unverified_key' && (
                              <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-950 space-y-1.5 animate-fadeIn">
                                <div className="flex items-center gap-2 font-bold text-sm text-amber-900">
                                  <AlertCircle className="w-5 h-5 text-amber-600 shrink-0" />
                                  <span>مفتاح الإجابة قيد المراجعة</span>
                                </div>
                                <p className="text-xs text-amber-800 leading-relaxed font-medium">
                                  {graded.feedback_message}
                                </p>
                              </div>
                            )}

                            {/* Reset Button to Practice Again */}
                            <div className="flex justify-end pt-1">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => handleResetPractice(q.question_id)}
                                className="flex items-center gap-1.5 text-xs text-cocoa-700 hover:text-ink"
                              >
                                <RotateCcw className="w-3.5 h-3.5 text-cocoa-500" />
                                <span>إعادة المحاولة للتدريب</span>
                              </Button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })()}

                  {/* Essay & Short-Answer Student Practice Input Area */}
                  {q.question_type !== 'mcq' && (() => {
                    const graded = gradedSubmissions[q.question_id];
                    const isSubmitting = submittingQuestion[q.question_id];
                    const submissionError = submissionErrors[q.question_id];

                    return (
                      <div className="pt-2 space-y-2 border-t border-sand/60 mt-2">
                        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 text-xs">
                          <div className="flex items-center gap-1.5 text-cocoa-700 font-medium">
                            <PenLine className="w-3.5 h-3.5 text-teal-600" />
                            <span>تدريب ذاتي: فكّر في الإجابة واكتب مسودتك لمراجعة استيعابك للمفهوم.</span>
                          </div>
                          <span className="text-[11px] text-cocoa-400 bg-sand/40 px-2 py-0.5 rounded">
                            مسودة محلية (محفوظة على هذا المتصفح للمذاكرة)
                          </span>
                        </div>

                        <div className="relative">
                          <textarea
                            dir="rtl"
                            rows={3}
                            value={drafts[q.question_id] ?? ''}
                            onChange={(e) => handleDraftChange(q.question_id, e.target.value)}
                            placeholder="اكتب إجابتك هنا..."
                            aria-label="مسودة الإجابة"
                            className="w-full p-3 border border-sand rounded-xl text-xs sm:text-sm text-ink placeholder:text-cocoa-400 focus:outline-none focus:ring-2 focus:ring-teal-500/20 focus:border-teal-600 transition resize-y bg-cream/20 hover:bg-white focus:bg-white leading-relaxed"
                          />
                        </div>

                        <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5">
                          <div className="flex items-center gap-2">
                            <Button
                              type="button"
                              variant="primary"
                              size="sm"
                              onClick={() => handleSaveDraft(q.question_id)}
                              className="flex items-center gap-1.5 text-xs shadow-sm"
                            >
                              <Check className="w-3.5 h-3.5" />
                              <span>حفظ الإجابة</span>
                            </Button>

                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={isSubmitting || !drafts[q.question_id]?.trim()}
                              loading={isSubmitting}
                              onClick={() => handleSubmitEssayReview(q.question_id)}
                              className="flex items-center gap-1.5 text-xs shadow-sm text-teal-700 border-teal-300 hover:bg-teal-50"
                            >
                              <Send className="w-3.5 h-3.5" />
                              <span>إرسال للمراجعة</span>
                            </Button>

                            {Boolean(drafts[q.question_id]?.trim()) && (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => handleClearDraft(q.question_id)}
                                className="text-xs text-cocoa-500 hover:text-rose-600 flex items-center gap-1"
                              >
                                <RotateCcw className="w-3.5 h-3.5" />
                                <span>مسح المسودة</span>
                              </Button>
                            )}
                          </div>

                          {/* Feedback message indicator for local drafts */}
                          {draftStatus[q.question_id] && (
                            <div
                              className={`text-xs px-2.5 py-1 rounded-lg flex items-center gap-1.5 font-medium transition-all ${
                                draftStatus[q.question_id].type === 'success'
                                  ? 'bg-teal-50 text-teal-800 border border-teal-200'
                                  : 'bg-rose-50 text-rose-700 border border-rose-200'
                              }`}
                            >
                              {draftStatus[q.question_id].type === 'success' ? (
                                <Check className="w-3.5 h-3.5 text-teal-600 shrink-0" />
                              ) : (
                                <AlertCircle className="w-3.5 h-3.5 text-rose-600 shrink-0" />
                              )}
                              <span>{draftStatus[q.question_id].message}</span>
                              {draftStatus[q.question_id].savedAt && (
                                <span className="text-[10px] text-teal-700/70 font-mono mr-1">
                                  ({draftStatus[q.question_id].savedAt})
                                </span>
                              )}
                            </div>
                          )}

                          {submissionError && (
                            <div className="text-xs text-rose-600 flex items-center gap-1 font-medium">
                              <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                              <span>{submissionError}</span>
                            </div>
                          )}
                        </div>

                        {/* Authoritative Teacher Review Status Card */}
                        {graded && graded.requires_teacher_review && (
                          <div className="p-4 rounded-xl bg-sky-50 border border-sky-200 text-sky-950 space-y-2 mt-2 animate-fadeIn">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2 font-bold text-sm text-sky-900">
                                <Sparkles className="w-4 h-4 text-sky-600 shrink-0" />
                                <span>تم تسجيل الإجابة بنجاح - بانتظار مراجعة المعلم</span>
                              </div>
                              <span className="text-xs font-bold bg-amber-100 text-amber-800 border border-amber-300 px-2.5 py-0.5 rounded-full">
                                قيد مراجعة المعلم
                              </span>
                            </div>
                            <p className="text-xs text-sky-800 leading-relaxed">
                              {graded.feedback_message}
                            </p>
                            {graded.correct_answer && (
                              <div className="p-3 bg-white/90 rounded-lg border border-sky-200 text-xs space-y-1">
                                <div className="font-bold text-cocoa-900">الإجابة النموذجية المرجعية:</div>
                                <div className="text-cocoa-800 leading-relaxed font-sans">{graded.correct_answer}</div>
                              </div>
                            )}
                            {graded.explanation && (
                              <div className="text-xs text-sky-900 leading-relaxed pt-1 border-t border-sky-200/60">
                                <span className="font-bold">💡 توجيهات التقييم والشرح: </span>
                                <span>{graded.explanation}</span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
              </Card>
            );
          })
        )}
      </div>

      {/* Pagination Controls */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-4 border-t border-sand">
          <p className="text-xs text-cocoa-500">
            صفحة <span className="font-bold text-ink">{page}</span> من{' '}
            <span className="font-bold text-ink">{totalPages}</span>
          </p>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="flex items-center gap-1 text-xs"
            >
              <ChevronRight className="w-4 h-4" />
              <span>السابق</span>
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="flex items-center gap-1 text-xs"
            >
              <span>التالي</span>
              <ChevronLeft className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

export default StudentQuestionBank;
