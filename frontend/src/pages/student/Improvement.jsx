import React, { useState, useEffect } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { getImprovement, createPracticeExam } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import Modal from '../../components/ui/Modal';
import {
  Target,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  Sparkles,
  ChevronDown,
  ChevronUp,
  BookOpen,
  Layers,
  Award,
} from 'lucide-react';

const DIFFICULTY_LABELS = {
  easy: 'سهل',
  medium: 'متوسط',
  hard: 'صعب',
};

const BLOOM_LABELS = {
  remember: 'تذكّر',
  understand: 'فهم',
  apply: 'تطبيق',
  analyze: 'تحليل',
  evaluate: 'تقييم',
  create: 'إبداع',
};

const Improvement = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const targetLessonParam = searchParams.get('lesson');

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Expanded collapsible for wrong questions per lesson
  const [expandedLessons, setExpandedLessons] = useState({});

  // Practice modal state
  const [selectedLesson, setSelectedLesson] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState('');
  const [questionCount, setQuestionCount] = useState(5);

  const fetchImprovementData = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getImprovement();
      setData(res);
      // Auto-open modal if targetLessonParam is provided in URL
      if (targetLessonParam && res?.lessons) {
        const found = res.lessons.find((l) => l.lesson_id === targetLessonParam);
        if (found) {
          setSelectedLesson(found);
          setQuestionCount(found.suggested_practice?.number_of_questions || 5);
        }
      }
    } catch (err) {
      console.error('Failed to load improvement diagnosis:', err);
      setError(
        err.response?.data?.detail ||
          'تعذر تحميل تشخيص التحسين. يرجى التأكد من تسليم امتحان واحد على الأقل.'
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchImprovementData();
  }, [targetLessonParam]);

  const toggleExpand = (lessonId) => {
    setExpandedLessons((prev) => ({
      ...prev,
      [lessonId]: !prev[lessonId],
    }));
  };

  const handleOpenPracticeModal = (lesson) => {
    setSelectedLesson(lesson);
    setGenerateError('');
    setQuestionCount(lesson.suggested_practice?.number_of_questions || 5);
  };

  const handleStartPractice = async () => {
    if (!selectedLesson || generating) return;
    setGenerating(true);
    setGenerateError('');

    try {
      const payload = {
        lesson_id: selectedLesson.lesson_id,
        number_of_questions: parseInt(questionCount, 10) || 5,
      };
      const exam = await createPracticeExam(payload);
      // Navigate to the take exam screen
      navigate(`/student/exam/${exam.id}`);
    } catch (err) {
      console.error('Practice exam generation failed:', err);
      const detail =
        err.response?.data?.detail ||
        err.message ||
        'تعذر إنشاء امتحان التدريب. يرجى المحاولة مرة أخرى.';
      setGenerateError(detail);
      setGenerating(false);
    }
  };

  const renderTrendBadge = (trend) => {
    switch (trend) {
      case 'improving':
        return (
          <span className="inline-flex items-center gap-1 text-xs font-bold text-teal-700 bg-teal-50 px-2 py-0.5 rounded-full border border-teal-200">
            <TrendingUp className="w-3.5 h-3.5" /> يتحسن
          </span>
        );
      case 'declining':
        return (
          <span className="inline-flex items-center gap-1 text-xs font-bold text-rose-600 bg-rose-50 px-2 py-0.5 rounded-full border border-rose-200">
            <TrendingDown className="w-3.5 h-3.5" /> يتراجع
          </span>
        );
      case 'stable':
        return (
          <span className="inline-flex items-center gap-1 text-xs font-bold text-cocoa-600 bg-cocoa-50 px-2 py-0.5 rounded-full border border-cocoa-200">
            <Minus className="w-3.5 h-3.5" /> مستقر
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-cocoa-500 bg-sand/60 px-2 py-0.5 rounded-full border border-cocoa-200">
            <HelpCircle className="w-3.5 h-3.5" /> جديد
          </span>
        );
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case 'weak':
        return <Badge variant="danger">يحتاج إلى تحسين (&lt;60%)</Badge>;
      case 'developing':
        return <Badge variant="warning">قيد التطور (60-80%)</Badge>;
      case 'strong':
        return <Badge variant="success">متقن (80%+)</Badge>;
      default:
        return <Badge variant="info">بيانات غير كافية</Badge>;
    }
  };

  const getProgressBarColor = (status, pct) => {
    if (status === 'weak' || pct < 60) return 'bg-rose-500';
    if (status === 'developing' || pct < 80) return 'bg-gold-500';
    return 'bg-teal-600';
  };

  if (loading) {
    return <LoadingSpinner size="lg" message="جارٍ تحليل أدائك في الامتحانات السابقة..." />;
  }

  const lessons = data?.lessons || [];
  const practiceHistory = data?.practice_history || [];
  const hasNoData = !data || (lessons.length === 0 && data.real_attempts_count === 0);

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="relative overflow-hidden flex flex-col md:flex-row md:items-center justify-between gap-6 bg-gradient-to-l from-clay-900 via-cocoa-950 to-teal-950 p-6 md:p-8 rounded-3xl text-white shadow-pop">
        <div className="space-y-2 relative z-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 text-gold-300 text-xs font-bold">
            <Target className="w-4 h-4" />
            <span>تدريب موجه لتطوير المهارات</span>
          </div>
          <h1 className="font-display text-2xl md:text-3xl text-white">
            خطة تحسين مستوى الطالب 🎯
          </h1>
          <p className="text-xs md:text-sm text-sand/85 max-w-xl leading-relaxed">
            تشخيص ذكي لأدائك في الامتحانات السابقة؛ حدد الدروس التي تحتاج إلى تركيز،
            وتدرب على أسئلة مخصصة لمستواك لرفع كفاءتك وتطوير فهمك.
          </p>
        </div>

        {/* High-level stats banner */}
        <div className="flex items-center gap-4 bg-white/10 border border-white/15 p-4 rounded-2xl backdrop-blur-md shrink-0 relative z-10">
          <div className="text-center px-4 border-e border-white/20">
            <p className="text-[11px] text-cocoa-300 font-semibold tracking-wide">
              المستوى الحالي
            </p>
            <div className="mt-1.5">
              <Badge type="cluster" size="md">
                {data?.student_level || 'قيد التقييم'}
              </Badge>
            </div>
          </div>
          <div className="text-center px-4">
            <p className="text-[11px] text-cocoa-300 font-semibold tracking-wide">
              الدقة الإجمالية
            </p>
            <p className="text-2xl font-extrabold text-gold-300 mt-0.5">
              {data?.overall_accuracy !== null && data?.overall_accuracy !== undefined
                ? `${data.overall_accuracy}%`
                : '—'}
            </p>
          </div>
        </div>
      </div>

      {error && <Alert type="error" message={error} onClose={() => setError('')} />}

      {/* Empty State: student has not completed any exams yet */}
      {hasNoData ? (
        <Card className="text-center py-16">
          <div className="w-16 h-16 bg-gold-100 text-gold-700 rounded-3xl flex items-center justify-center mx-auto mb-4 -rotate-3 text-3xl">
            🎯
          </div>
          <h3 className="text-lg font-bold text-ink">لا توجد امتحانات سابقة بعد</h3>
          <p className="text-sm text-cocoa-500 max-w-md mx-auto mt-2 leading-relaxed">
            ابدأ بحل وتسليم امتحان واحد على الأقل ليتمكن الذكاء الاصطناعي من تحليل نقاط قوتك وضعفك،
            وفتح جلسات تدريبية مخصصة لمستواك.
          </p>
          <div className="mt-6">
            <Link to="/student/exams">
              <Button icon={BookOpen} variant="primary" className="btn-cut">
                استعرض الامتحانات المتاحة
              </Button>
            </Link>
          </div>
        </Card>
      ) : (
        <>
          {/* Lessons Diagnosis List */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-extrabold text-ink flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-gold-600" />
                  تشخيص دروس المنهج
                </h2>
                <p className="text-xs text-cocoa-500 mt-0.5">
                  مرتبة بحيث تظهر الدروس الأكثر احتياجاً للتحسين أولاً لتركز على ما يهمك.
                </p>
              </div>
              <span className="text-xs font-semibold text-cocoa-500">
                {lessons.length} {lessons.length === 1 ? 'درس تم تقييمه' : 'دروس تم تقييمها'}
              </span>
            </div>

            <div className="grid grid-cols-1 gap-4">
              {lessons.map((lesson) => {
                const isWeak = lesson.status === 'weak';
                const isDeveloping = lesson.status === 'developing';
                const isExpanded = !!expandedLessons[lesson.lesson_id];
                const wrongCount = lesson.questions_wrong;
                const totalCount = lesson.total_questions;
                const sampleQuestions = lesson.sample_wrong_questions || [];

                return (
                  <Card
                    key={lesson.lesson_id}
                    className={`transition-all ${
                      isWeak
                        ? 'border-rose-300 bg-rose-50/20'
                        : isDeveloping
                        ? 'border-gold-300 bg-gold-50/20'
                        : 'border-cocoa-200'
                    }`}
                  >
                    <div className="p-5 space-y-4">
                      {/* Top Row: Title, Badges, Practice Button */}
                      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                        <div className="space-y-1.5 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-cocoa-100 text-cocoa-800">
                              الدرس {lesson.lesson_id}
                            </span>
                            {getStatusBadge(lesson.status)}
                            {renderTrendBadge(lesson.trend)}
                          </div>
                          <h3
                            className="font-bold text-base md:text-lg text-ink"
                            dir="auto"
                          >
                            {lesson.lesson_title}
                          </h3>
                        </div>

                        {/* Practice Trigger */}
                        <div className="shrink-0">
                          <Button
                            variant={isWeak || isDeveloping ? 'primary' : 'outline'}
                            size="sm"
                            icon={Target}
                            onClick={() => handleOpenPracticeModal(lesson)}
                            disabled={!lesson.practice_available}
                            title={lesson.practice_unavailable_reason || 'ابدأ تدريباً على هذا الدرس'}
                          >
                            تدرب على هذا الدرس
                          </Button>
                        </div>
                      </div>

                      {/* Accuracy Progress Bar & Stats */}
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between text-xs font-bold">
                          <span className="text-cocoa-700">
                            نسبة الدقة:{' '}
                            <span className="font-extrabold text-ink">
                              {lesson.accuracy_pct}%
                            </span>
                          </span>
                          <span className="text-cocoa-500 font-normal">
                            الأسئلة الخاطئة:{' '}
                            <strong className="text-rose-600 font-bold">{wrongCount}</strong> من أصل{' '}
                            {totalCount} سؤال ({lesson.attempts_count}{' '}
                            {lesson.attempts_count === 1 ? 'محاولة' : 'محاولات'})
                          </span>
                        </div>
                        <div className="w-full h-2.5 bg-sand rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-500 ${getProgressBarColor(
                              lesson.status,
                              lesson.accuracy_pct
                            )}`}
                            style={{ width: `${Math.max(4, Math.min(100, lesson.accuracy_pct))}%` }}
                          />
                        </div>
                      </div>

                      {/* Practice Unavailable note if store missing */}
                      {!lesson.practice_available && lesson.practice_unavailable_reason && (
                        <p className="text-[11px] text-cocoa-500 italic">
                          ⚠️ {lesson.practice_unavailable_reason}
                        </p>
                      )}

                      {/* Collapsible: Missed Questions */}
                      {sampleQuestions.length > 0 && (
                        <div className="border-t border-sand/60 pt-3">
                          <button
                            type="button"
                            onClick={() => toggleExpand(lesson.lesson_id)}
                            className="flex items-center gap-1.5 text-xs font-bold text-clay-700 hover:text-clay-900 transition-colors"
                          >
                            {isExpanded ? (
                              <ChevronUp className="w-4 h-4" />
                            ) : (
                              <ChevronDown className="w-4 h-4" />
                            )}
                            <span>
                              {isExpanded ? 'إخفاء' : 'مراجعة'} الأسئلة التي أخطأت فيها ({sampleQuestions.length})
                            </span>
                          </button>

                          {isExpanded && (
                            <div className="mt-3 space-y-2.5">
                              {sampleQuestions.map((q, idx) => (
                                <div
                                  key={idx}
                                  className="p-3.5 rounded-xl bg-white border border-cocoa-200/80 text-xs space-y-2"
                                >
                                  <div className="flex items-start justify-between gap-2">
                                    <p
                                      className="font-bold text-ink leading-relaxed flex-1"
                                      dir="auto"
                                    >
                                      {idx + 1}. {q.question}
                                    </p>
                                    <span className="shrink-0 text-[10px] font-mono px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200">
                                      الدرجة: {q.score} / {q.max_score}
                                    </span>
                                  </div>
                                  {q.skipped ? (
                                    <p className="text-[11px] text-rose-600 font-semibold">
                                      تم التخطي تلقائياً (رصد مغادرة شاشة الاختبار).
                                    </p>
                                  ) : q.student_answer ? (
                                    <div className="text-[11px] text-cocoa-600 bg-sand/40 p-2.5 rounded-lg border border-sand">
                                      <span className="font-bold text-cocoa-800">إجابتك:{' '}</span>
                                      <span dir="auto">{q.student_answer}</span>
                                    </div>
                                  ) : (
                                    <p className="text-[11px] text-cocoa-400 italic">لم يتم تقديم إجابة.</p>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </Card>
                );
              })}
            </div>
          </div>

          {/* Practice History Section */}
          {practiceHistory.length > 0 && (
            <div className="space-y-4 pt-4 border-t border-sand">
              <div>
                <h2 className="text-lg font-extrabold text-ink flex items-center gap-2">
                  <Award className="w-5 h-5 text-teal-700" />
                  تقدم التدريب وسجل الدرجات
                </h2>
                <p className="text-xs text-cocoa-500 mt-0.5">
                  تابع تطور درجاتك بعد خوض جلسات التدريب المخصصة لكل درس.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {practiceHistory.map((item) => (
                  <Card key={item.lesson_id} className="p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <h4 className="font-bold text-sm text-ink" dir="auto">
                          {item.lesson_title}
                        </h4>
                        <p className="text-[11px] text-cocoa-500">
                          {item.practice_count}{' '}
                          {item.practice_count === 1 ? 'جلسة تدريبية' : 'جلسات تدريبية'}
                        </p>
                      </div>
                      <div className="text-end">
                        <span className="text-xs font-bold text-teal-700 block">
                          آخر محاولة: {item.latest_percentage}%
                        </span>
                        <div className="text-[10px] text-cocoa-500 font-semibold">
                          أعلى درجة: {item.best_percentage}%
                        </div>
                      </div>
                    </div>

                    {/* Progress bars sparkline */}
                    <div className="space-y-1.5 pt-1">
                      <div className="flex items-end gap-1.5 h-14 bg-sand/30 p-2 rounded-xl">
                        {item.scores.map((s, idx) => {
                          const heightPct = Math.max(10, Math.min(100, Math.round(s.percentage)));
                          const isHigh = s.percentage >= 80;
                          const isMid = s.percentage >= 60;
                          const diffLabel = DIFFICULTY_LABELS[s.difficulty] || s.difficulty || 'متوسط';
                          return (
                            <div
                              key={idx}
                              className="flex-1 flex flex-col items-center justify-end h-full group relative"
                            >
                              <div
                                className={`w-full rounded-t transition-all ${
                                  isHigh
                                    ? 'bg-teal-600'
                                    : isMid
                                    ? 'bg-gold-500'
                                    : 'bg-rose-500'
                                }`}
                                style={{ height: `${heightPct}%` }}
                              />
                              {/* Hover Tooltip */}
                              <div className="absolute bottom-full mb-1 hidden group-hover:block bg-cocoa-950 text-white text-[10px] py-1 px-2 rounded shadow-lg whitespace-nowrap z-10">
                                محاولة #{s.attempt_id}: {s.percentage}% ({diffLabel})
                              </div>
                            </div>
                          );
                        })}
                      </div>
                      <div className="flex items-center justify-between text-[10px] text-cocoa-400 px-1">
                        <span>أول تدريب</span>
                        <span>أحدث تدريب</span>
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Practice Modal */}
      {selectedLesson && (
        <Modal
          isOpen={!!selectedLesson}
          onClose={() => !generating && setSelectedLesson(null)}
          title={`تدريب: ${selectedLesson.lesson_title}`}
          subtitle={`جلسة تدريبية مخصصة لمنهج الدرس ${selectedLesson.lesson_id}`}
          maxWidth="max-w-lg"
          footer={
            <div className="flex items-center justify-end gap-3 w-full">
              <Button
                variant="ghost"
                onClick={() => setSelectedLesson(null)}
                disabled={generating}
              >
                إلغاء
              </Button>
              <Button
                variant="primary"
                onClick={handleStartPractice}
                loading={generating}
                loadingText="جارٍ إنشاء الأسئلة..."
                disabled={generating}
                icon={Target}
                className="btn-cut"
              >
                ابدأ التدريب
              </Button>
            </div>
          }
        >
          <div className="space-y-4 text-xs">
            {generateError && (
              <Alert type="error" message={generateError} onClose={() => setGenerateError('')} />
            )}

            {generating ? (
              <div className="py-6">
                <LoadingSpinner
                  size="lg"
                  message="جارٍ إنشاء أسئلة تدريبية مخصصة لمستواك من المنهج..."
                />
              </div>
            ) : (
              <>
                <div className="p-3.5 rounded-xl bg-teal-50 border border-teal-200 text-teal-900 leading-relaxed font-semibold">
                  <p dir="auto">
                    سيقوم الذكاء الاصطناعي باستخراج مفاهيم من{' '}
                    <strong>{selectedLesson.lesson_title}</strong> والتركيز على النقاط التي واجهت
                    صعوبة فيها في الامتحانات السابقة.
                  </p>
                </div>

                <div className="space-y-3 bg-white p-4 rounded-xl border border-sand">
                  <h4 className="font-extrabold text-cocoa-800 text-sm">
                    الإعدادات الموصى بها لمستواك:
                  </h4>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="p-2.5 rounded-lg bg-sand/40 border border-sand">
                      <span className="text-[10px] text-cocoa-500 font-bold block mb-0.5">
                        مستوى الصعوبة
                      </span>
                      <span className="font-extrabold text-sm text-ink">
                        {DIFFICULTY_LABELS[selectedLesson.suggested_practice?.difficulty] ||
                          selectedLesson.suggested_practice?.difficulty ||
                          'متوسط'}
                      </span>
                    </div>

                    <div className="p-2.5 rounded-lg bg-sand/40 border border-sand">
                      <span className="text-[10px] text-cocoa-500 font-bold block mb-0.5">
                        المستوى المعرفي (بلوم)
                      </span>
                      <span className="font-extrabold text-sm text-ink">
                        {BLOOM_LABELS[selectedLesson.suggested_practice?.bloom_level] ||
                          selectedLesson.suggested_practice?.bloom_level ||
                          'فهم'}
                      </span>
                    </div>
                  </div>

                  <div>
                    <span className="text-[11px] text-cocoa-600 font-bold block mb-1">
                      عدد الأسئلة:
                    </span>
                    <div className="flex items-center gap-2">
                      {[3, 5, 8, 10].map((num) => (
                        <button
                          key={num}
                          type="button"
                          onClick={() => setQuestionCount(num)}
                          className={`px-3 py-1.5 rounded-lg font-bold text-xs transition-colors border ${
                            questionCount === num
                              ? 'bg-clay-800 text-white border-clay-900 shadow-sm'
                              : 'bg-white text-cocoa-700 border-cocoa-300 hover:bg-sand'
                          }`}
                        >
                          {num} أسئلة
                        </button>
                      ))}
                    </div>
                  </div>

                  <p className="text-[11px] text-cocoa-500 pt-1">
                    أنواع الأسئلة: اختيار من متعدد وإجابة قصيرة (مخصصة للتقييم الفوري بالذكاء الاصطناعي).
                  </p>
                </div>
              </>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
};

export default Improvement;
