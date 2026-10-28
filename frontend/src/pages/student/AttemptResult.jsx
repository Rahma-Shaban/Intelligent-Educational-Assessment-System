import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import Markdown from 'react-markdown';
import { getAttempt } from '../../api/client';

import { formatCompletionTime, formatAttemptDuration } from '../professor/examStudentResults';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  CheckCircle2,
  XCircle,
  Award,
  ArrowRight,
  Clock,
  Sparkles,
  Layers,
  ChevronLeft,
  TrendingUp,
  FileText,
  ThumbsUp,
  AlertTriangle,
  Target,
} from 'lucide-react';

const AttemptResult = () => {
  const { id } = useParams();
  const [attempt, setAttempt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchAttempt = async () => {
      setLoading(true);
      setError('');
      try {
        const data = await getAttempt(id);
        setAttempt(data);
      } catch (err) {
        console.error('Failed to load attempt result:', err);
        setError('فشل تحميل النتيجة. راجع رقم المحاولة.');
      } finally {
        setLoading(false);
      }
    };

    if (id) {
      fetchAttempt();
    }
  }, [id]);

  if (loading) {
    return <LoadingSpinner size="lg" message="جاري تجيب نتيجتك وتحليلها..." />;
  }

  if (error || !attempt) {
    return (
      <div className="max-w-2xl mx-auto space-y-4">
        <Link to="/student/dashboard">
          <Button variant="ghost" size="sm" icon={ArrowRight}>
            ارجع للرئيسية
          </Button>
        </Link>
        <Alert type="error" title="النتيجة مش موجودة" message={error} />
      </div>
    );
  }

  const score = attempt.total_score ?? attempt.score ?? 0;
  const maxScore = attempt.max_possible_score ?? attempt.max_score ?? attempt.total_points ?? 100;
  const percentage =
    attempt.percentage !== undefined && attempt.percentage !== null
      ? Math.round(attempt.percentage)
      : maxScore > 0
      ? Math.round((score / maxScore) * 100)
      : 0;

  const passed = attempt.passed !== undefined ? attempt.passed : percentage >= 60;
  const questions = Array.isArray(attempt.graded_answers)
    ? attempt.graded_answers
    : attempt.questions || attempt.evaluations || attempt.answers || [];

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* Back button */}
      <div className="flex items-center justify-between">
        <Link to="/student/dashboard">
          <Button variant="ghost" size="sm" icon={ArrowRight}>
            ارجع للرئيسية
          </Button>
        </Link>
        <span className="text-xs font-code text-cocoa-300" dir="ltr">Submission ID: {id}</span>
      </div>

      {/* Hero Score Banner */}
      <Card
        className={`p-6 md:p-8 border-none shadow-pop ${
          passed ? 'bg-gradient-to-bl from-teal-700 to-cocoa-950 text-white' : 'bg-gradient-to-bl from-cocoa-900 to-clay-950 text-white'
        }`}
      >
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className={`sticker !bg-transparent !text-[11px] ${
                  passed ? 'text-gold-300' : 'text-rose-300'
                }`}
                style={{ borderWidth: 1.5 }}
              >
                {passed ? '🎉 نجحت' : 'محتاج مراجعة'}
              </span>
              {attempt.cluster && (
                <span className="text-xs font-bold bg-white/10 text-teal-100 px-3 py-1 rounded-full">
                  المجموعة: {attempt.cluster}
                </span>
              )}
            </div>

            <h1 className="font-display text-3xl md:text-4xl leading-snug" dir="auto">
              {attempt.exam_title || attempt.title || 'نتيجة الامتحان'}
            </h1>
            <p className="text-sm text-white/70">
              اتسلّم في{' '}
              {attempt.submitted_at
                ? formatCompletionTime(attempt.submitted_at)
                : 'دلوقتي'}{' '}
              &bull; الوقت المستغرق: {attempt.duration_seconds ? formatAttemptDuration(attempt.duration_seconds) : 'مكتمل'}
            </p>
          </div>

          {/* Big Score Box */}
          <div className="bg-white/10 backdrop-blur-md p-5 rounded-2xl border border-white/10 flex items-center gap-5 shrink-0">
            <div className="text-center">
              <p className="text-[11px] font-bold text-white/60">الدرجة</p>
              <div className="font-display text-4xl mt-0.5 text-gold-300">
                {score} <span className="text-base text-white/60">/ {maxScore}</span>
              </div>
            </div>
            <div className="h-10 w-px bg-white/20" />
            <div className="text-center">
              <p className="text-[11px] font-bold text-white/60">النسبة</p>
              <div
                className={`font-display text-4xl mt-0.5 ${
                  passed ? 'text-gold-300' : 'text-rose-300'
                }`}
              >
                {percentage}%
              </div>
            </div>
          </div>
        </div>
      </Card>

      {/* Global AI Feedback Banner if present */}
      {(attempt.overall_feedback || attempt.feedback) && (
        <Card className="border-gold-200 bg-gold-50/50 p-5">
          <div className="flex items-start gap-3">
            <Sparkles className="w-5 h-5 text-gold-600 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h3 className="text-sm font-extrabold text-gold-800">تقييم الذكاء الاصطناعي العام</h3>
              <p className="text-xs text-gold-900 leading-relaxed" dir="auto">
                {attempt.overall_feedback || attempt.feedback}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Per-Question Breakdown */}
      <div className="space-y-6">
        <h2 className="text-xl font-extrabold text-ink flex items-center gap-2">
          <Layers className="w-5 h-5 text-clay-600" />
          تقييم سؤال بسؤال
        </h2>

        {questions.length === 0 ? (
          <Card className="text-center py-8 text-cocoa-500 text-sm">
            التفاصيل دي مش متاحة للسجل ده.
          </Card>
        ) : (
          questions.map((q, idx) => {
            const isCorrect =
              q.is_correct !== undefined
                ? q.is_correct
                : q.passed !== undefined
                ? q.passed
                : q.earned_score !== undefined && q.max_score !== undefined
                ? q.earned_score === q.max_score
                : q.score !== undefined && q.max_score !== undefined
                ? q.score === q.max_score
                : true;

            const qScore = q.earned_score ?? q.score ?? (isCorrect ? (q.max_score || 1) : 0);
            const qMax = q.max_score ?? 1;

            return (
              <Card
                key={idx}
                className={`p-6 space-y-4 border-2 ${
                  q.question_type === 'mcq'
                    ? isCorrect
                      ? 'border-teal-200 bg-teal-50/10'
                      : 'border-rose-200 bg-rose-50/10'
                    : 'border-sand'
                }`}
              >
                {/* Header */}
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-sand pb-3">
                  <div className="flex items-center gap-2">
                    <span className="w-7 h-7 rounded-lg rounded-br-sm bg-gradient-to-b from-clay-600 to-clay-800 text-white font-bold text-xs flex items-center justify-center">
                      Q{idx + 1}
                    </span>
                    <Badge type="qtype">{q.question_type}</Badge>
                    {q.bloom_level && <Badge type="bloom">{q.bloom_level}</Badge>}
                  </div>

                  <div className="flex items-center gap-2">
                    {q.question_type === 'mcq' && (
                      <span
                        className={`inline-flex items-center gap-1 text-xs font-bold px-2.5 py-1 rounded-lg ${
                          isCorrect
                            ? 'bg-teal-100 text-teal-800'
                            : 'bg-rose-100 text-rose-800'
                        }`}
                      >
                        {isCorrect ? (
                          <>
                            <CheckCircle2 className="w-3.5 h-3.5" /> صح
                          </>
                        ) : (
                          <>
                            <XCircle className="w-3.5 h-3.5" /> غلط
                          </>
                        )}
                      </span>
                    )}

                    <span className="text-xs font-bold text-cocoa-800 bg-cream px-3 py-1 rounded-lg border border-sand">
                      {qScore} / {qMax} درجة
                    </span>
                  </div>
                </div>

                {/* Question Text */}
                <h4 className="text-base font-bold text-ink leading-snug" dir="auto">
                  {q.question}
                </h4>

                {/* Student's Answer */}
                <div className="p-3.5 rounded-2xl bg-cream border border-sand space-y-1 text-xs">
                  <p className="font-bold text-cocoa-500 text-[11px]">
                    إجابتك:
                  </p>
                  <div className="text-ink font-bold whitespace-pre-wrap" dir="auto">
                    {q.student_answer || q.answer || '(مفيش إجابة)'}
                  </div>
                </div>

                {/* For MCQ: Correct Answer and Explanation */}
                {q.question_type === 'mcq' && (
                  <div className="p-3.5 rounded-2xl bg-teal-50/70 border border-teal-200 space-y-1 text-xs">
                    <p className="font-bold text-teal-800 text-[11px]">
                      الإجابة الصحيحة:
                    </p>
                    <p className="text-teal-900 font-bold" dir="auto">
                      الاختيار {q.correct_answer || q.reference_answer}
                    </p>
                    {q.explanation && (
                      <p className="text-teal-800 mt-1 italic leading-relaxed" dir="auto">
                        الشرح: {q.explanation}
                      </p>
                    )}
                  </div>
                )}

                {/* For Essay / Short Answer: Rubric Criteria, Model Answer & Semantic Feedback */}
                {(q.question_type === 'essay' || q.question_type === 'short_answer') && (
                  <div className="space-y-4 pt-1">
                    {/* Reference / Model Answer */}
                    {(q.reference_answer || q.model_answer) && (
                      <div className="p-3.5 rounded-2xl bg-clay-50/70 border border-clay-200 space-y-1 text-xs">
                        <p className="font-bold text-clay-800 text-[11px]">
                          الإجابة النموذجية:
                        </p>
                        <div className="text-clay-950 font-bold whitespace-pre-wrap" dir="auto">
                          {q.reference_answer || q.model_answer}
                        </div>
                      </div>
                    )}

                    {/* Rubric Breakdown */}
                    {(q.rubric_breakdown || q.rubric_evaluation || q.rubric_scores || q.rubric) && (
                      <div className="space-y-2">
                        <span className="text-xs font-bold text-cocoa-800">
                          تقييم معايير التصحيح:
                        </span>
                        <div className="border border-sand rounded-xl overflow-hidden text-xs">
                          <table className="w-full divide-y divide-sand text-right">
                            <thead className="bg-cream text-[11px] text-cocoa-500 font-bold">
                              <tr>
                                <th className="px-3.5 py-2">المعيار</th>
                                <th className="px-3.5 py-2">ملاحظات المقيّم</th>
                                <th className="px-3.5 py-2">الدرجة</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-sand bg-paper">
                              {(q.rubric_breakdown || q.rubric_evaluation || q.rubric_scores || q.rubric).map(
                                (r, rIdx) => (
                                  <tr key={rIdx} className="hover:bg-cream/60 transition-colors">
                                    <td className="px-3.5 py-2.5 font-bold text-ink" dir="auto">
                                      {r.criterion}
                                    </td>
                                    <td className="px-3.5 py-2.5 text-cocoa-500" dir="auto">
                                      {r.feedback || r.comment || r.remarks || r.description || 'تم التقييم'}
                                    </td>
                                    <td className="px-3.5 py-2.5 font-bold text-clay-700">
                                      {r.earned_points ?? r.score ?? r.points ?? '-'} /{' '}
                                      {r.max_points ?? r.max_score ?? r.points ?? '-'}
                                    </td>
                                  </tr>
                                )
                              )}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                    {/* Feedback and Strengths / Weaknesses */}
                    {(q.feedback || q.strengths || q.weaknesses || q.learning_gaps) && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                        {(q.strengths || q.feedback) && (
                          <div className="p-3 bg-teal-50 rounded-2xl border border-teal-200/80 space-y-1">
                            <span className="font-bold text-teal-800 flex items-center gap-1.5 text-[11px]">
                              <ThumbsUp className="w-3.5 h-3.5 text-teal-600" /> نقاط القوة
                            </span>
                            <div className="text-teal-900 leading-relaxed" dir="auto">
                              {Array.isArray(q.strengths) ? (
                                <ul className="list-disc ps-4 space-y-0.5">
                                  {q.strengths.map((str, sIdx) => (
                                    <li key={sIdx}>{str}</li>
                                  ))}
                                </ul>
                              ) : (
                                <p>{q.strengths || q.feedback}</p>
                              )}
                            </div>
                          </div>
                        )}

                        {(q.weaknesses || q.learning_gaps) && (
                          <div className="p-3 bg-gold-50 rounded-2xl border border-gold-200/80 space-y-1">
                            <span className="font-bold text-gold-800 flex items-center gap-1.5 text-[11px]">
                              <AlertTriangle className="w-3.5 h-3.5 text-gold-600" /> حاجات تتحسّن
                            </span>
                            <div className="text-gold-900 leading-relaxed" dir="auto">
                              {Array.isArray(q.weaknesses || q.learning_gaps) ? (
                                <ul className="list-disc ps-4 space-y-0.5">
                                  {(q.weaknesses || q.learning_gaps).map((w, wIdx) => (
                                    <li key={wIdx}>{w}</li>
                                  ))}
                                </ul>
                              ) : (
                                <p>{q.weaknesses || q.learning_gaps}</p>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </Card>
            );
          })
        )}
      </div>

      <div className="flex justify-end gap-3 pt-4 flex-wrap">
        {/* Student Improvement shortcut: practice the same lesson again */}
        {attempt?.lesson_id && (
          <Link to={`/student/improvement?lesson=${encodeURIComponent(attempt.lesson_id)}`}>
            <Button variant="outline" icon={Target}>
              تدرب على هذا الدرس
            </Button>
          </Link>
        )}
        <Link to="/student/dashboard">
          <Button variant="secondary">الرئيسية</Button>
        </Link>
        <Link to="/student/exams">
          <Button variant="primary" className="btn-cut">امتحن تاني 🚀</Button>
        </Link>
      </div>
    </div>
  );
};

export default AttemptResult;
