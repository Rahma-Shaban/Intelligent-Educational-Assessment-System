import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import Markdown from 'react-markdown';
import { getAttempt } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  CheckCircle2,
  XCircle,
  Award,
  ArrowLeft,
  Clock,
  Sparkles,
  Layers,
  ChevronRight,
  TrendingUp,
  FileText,
  ThumbsUp,
  AlertTriangle,
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
        setError('Failed to load assessment results. Please check your submission ID.');
      } finally {
        setLoading(false);
      }
    };

    if (id) {
      fetchAttempt();
    }
  }, [id]);

  if (loading) {
    return <LoadingSpinner size="lg" message="Retrieving semantic evaluation score and rubric analysis..." />;
  }

  if (error || !attempt) {
    return (
      <div className="max-w-2xl mx-auto space-y-4">
        <Link to="/student/dashboard">
          <Button variant="ghost" size="sm" icon={ArrowLeft}>
            Back to Dashboard
          </Button>
        </Link>
        <Alert type="error" title="Results Not Found" message={error} />
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
          <Button variant="ghost" size="sm" icon={ArrowLeft}>
            Back to Student Dashboard
          </Button>
        </Link>
        <span className="text-xs font-mono text-gray-400">Submission ID: {id}</span>
      </div>

      {/* Hero Score Banner */}
      <Card
        className={`p-6 md:p-8 border-2 ${
          passed ? 'bg-gradient-to-r from-emerald-900 to-indigo-950 text-white border-emerald-400/30' : 'bg-gradient-to-r from-slate-900 to-rose-950 text-white border-rose-400/30'
        }`}
      >
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span
                className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider ${
                  passed
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                    : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                }`}
              >
                {passed ? 'Assessment Passed' : 'Needs Review'}
              </span>
              {attempt.cluster && (
                <span className="px-3 py-1 rounded-full text-xs font-semibold bg-white/10 text-indigo-200">
                  Cluster: {attempt.cluster}
                </span>
              )}
            </div>

            <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight">
              {attempt.exam_title || attempt.title || `Assessment Results`}
            </h1>
            <p className="text-sm text-gray-300">
              Submitted on{' '}
              {attempt.submitted_at
                ? new Date(attempt.submitted_at).toLocaleString()
                : 'Just now'}{' '}
              &bull; Time spent: {attempt.duration_seconds ? `${Math.round(attempt.duration_seconds / 60)} min` : 'Completed'}
            </p>
          </div>

          {/* Big Score Box */}
          <div className="bg-white/10 backdrop-blur-md p-5 rounded-2xl border border-white/10 flex items-center gap-5 shrink-0">
            <div className="text-center">
              <p className="text-[11px] font-bold uppercase tracking-wider text-gray-300">
                Total Score
              </p>
              <div className="text-3xl md:text-4xl font-extrabold mt-0.5">
                {score} <span className="text-lg font-normal text-gray-300">/ {maxScore}</span>
              </div>
            </div>
            <div className="h-10 w-px bg-white/20" />
            <div className="text-center">
              <p className="text-[11px] font-bold uppercase tracking-wider text-gray-300">
                Percentage
              </p>
              <div
                className={`text-3xl md:text-4xl font-extrabold mt-0.5 ${
                  passed ? 'text-emerald-300' : 'text-rose-300'
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
        <Card className="border-indigo-100 bg-indigo-50/40 p-5">
          <div className="flex items-start gap-3">
            <Sparkles className="w-5 h-5 text-indigo-600 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h3 className="text-sm font-bold text-indigo-950">Overall AI Diagnostic Feedback</h3>
              <p className="text-xs text-indigo-900 leading-relaxed">
                {attempt.overall_feedback || attempt.feedback}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Per-Question Breakdown */}
      <div className="space-y-6">
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
          <Layers className="w-5 h-5 text-indigo-600" />
          Question-by-Question Evaluation Breakdown
        </h2>

        {questions.length === 0 ? (
          <Card className="text-center py-8 text-gray-500 text-sm">
            Detailed per-question breakdown is not available for this record.
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
                className={`p-6 space-y-4 border ${
                  q.question_type === 'mcq'
                    ? isCorrect
                      ? 'border-emerald-200 bg-emerald-50/10'
                      : 'border-rose-200 bg-rose-50/10'
                    : 'border-gray-200'
                }`}
              >
                {/* Header */}
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 pb-3">
                  <div className="flex items-center gap-2">
                    <span className="w-7 h-7 rounded-lg bg-indigo-600 text-white font-bold text-xs flex items-center justify-center">
                      Q{idx + 1}
                    </span>
                    <Badge type="qtype">{q.question_type}</Badge>
                    {q.bloom_level && <Badge type="bloom">{q.bloom_level}</Badge>}
                  </div>

                  <div className="flex items-center gap-2">
                    {q.question_type === 'mcq' && (
                      <span
                        className={`inline-flex items-center gap-1 text-xs font-bold px-2.5 py-1 rounded-md ${
                          isCorrect
                            ? 'bg-emerald-100 text-emerald-800'
                            : 'bg-rose-100 text-rose-800'
                        }`}
                      >
                        {isCorrect ? (
                          <>
                            <CheckCircle2 className="w-3.5 h-3.5" /> Correct
                          </>
                        ) : (
                          <>
                            <XCircle className="w-3.5 h-3.5" /> Incorrect
                          </>
                        )}
                      </span>
                    )}

                    <span className="text-xs font-bold text-gray-700 bg-gray-100 px-3 py-1 rounded-md">
                      Score: {qScore} / {qMax} pts
                    </span>
                  </div>
                </div>

                {/* Question Text */}
                <h4 className="text-base font-semibold text-gray-900 leading-snug">
                  {q.question}
                </h4>

                {/* Student's Answer */}
                <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/80 space-y-1 text-xs">
                  <p className="font-bold text-gray-600 uppercase tracking-wider text-[10px]">
                    Your Submitted Answer:
                  </p>
                  <div className="text-gray-900 font-medium whitespace-pre-wrap">
                    {q.student_answer || q.answer || '(No response provided)'}
                  </div>
                </div>

                {/* For MCQ: Correct Answer and Explanation */}
                {q.question_type === 'mcq' && (
                  <div className="p-3.5 rounded-xl bg-emerald-50/70 border border-emerald-200 space-y-1 text-xs">
                    <p className="font-bold text-emerald-800 uppercase tracking-wider text-[10px]">
                      Correct Answer Key:
                    </p>
                    <p className="text-emerald-950 font-semibold">
                      Option {q.correct_answer || q.reference_answer}
                    </p>
                    {q.explanation && (
                      <p className="text-emerald-800 mt-1 italic leading-relaxed">
                        Explanation: {q.explanation}
                      </p>
                    )}
                  </div>
                )}

                {/* For Essay / Short Answer: Rubric Criteria, Model Answer & Semantic Feedback */}
                {(q.question_type === 'essay' || q.question_type === 'short_answer') && (
                  <div className="space-y-4 pt-1">
                    {/* Reference / Model Answer */}
                    {(q.reference_answer || q.model_answer) && (
                      <div className="p-3.5 rounded-xl bg-indigo-50/70 border border-indigo-200 space-y-1 text-xs">
                        <p className="font-bold text-indigo-800 uppercase tracking-wider text-[10px]">
                          Model / Reference Answer:
                        </p>
                        <div className="text-indigo-950 font-medium whitespace-pre-wrap">
                          {q.reference_answer || q.model_answer}
                        </div>
                      </div>
                    )}

                    {/* Rubric Breakdown */}
                    {(q.rubric_breakdown || q.rubric_evaluation || q.rubric_scores || q.rubric) && (
                      <div className="space-y-2">
                        <span className="text-xs font-bold text-gray-700 uppercase tracking-wider">
                          Rubric Criterion Evaluation:
                        </span>
                        <div className="border border-gray-200 rounded-lg overflow-hidden text-xs">
                          <table className="w-full divide-y divide-gray-200 text-left">
                            <thead className="bg-gray-50 text-[10px] text-gray-500 uppercase font-semibold">
                              <tr>
                                <th className="px-3.5 py-2">Rubric Criterion</th>
                                <th className="px-3.5 py-2">Evaluator Remarks</th>
                                <th className="px-3.5 py-2 text-right">Points Earned</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100 bg-white">
                              {(q.rubric_breakdown || q.rubric_evaluation || q.rubric_scores || q.rubric).map(
                                (r, rIdx) => (
                                  <tr key={rIdx} className="hover:bg-slate-50">
                                    <td className="px-3.5 py-2.5 font-semibold text-gray-900">
                                      {r.criterion}
                                    </td>
                                    <td className="px-3.5 py-2.5 text-gray-600">
                                      {r.feedback || r.comment || r.remarks || r.description || 'Evaluated'}
                                    </td>
                                    <td className="px-3.5 py-2.5 text-right font-bold text-indigo-600">
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
                          <div className="p-3 bg-emerald-50 rounded-xl border border-emerald-200/80 space-y-1">
                            <span className="font-bold text-emerald-800 flex items-center gap-1.5 uppercase text-[10px] tracking-wider">
                              <ThumbsUp className="w-3.5 h-3.5 text-emerald-600" /> Strengths & Observations
                            </span>
                            <div className="text-emerald-950 leading-relaxed">
                              {Array.isArray(q.strengths) ? (
                                <ul className="list-disc pl-4 space-y-0.5">
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
                          <div className="p-3 bg-amber-50 rounded-xl border border-amber-200/80 space-y-1">
                            <span className="font-bold text-amber-800 flex items-center gap-1.5 uppercase text-[10px] tracking-wider">
                              <AlertTriangle className="w-3.5 h-3.5 text-amber-600" /> Areas for Improvement
                            </span>
                            <div className="text-amber-950 leading-relaxed">
                              {Array.isArray(q.weaknesses || q.learning_gaps) ? (
                                <ul className="list-disc pl-4 space-y-0.5">
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

      <div className="flex justify-end gap-3 pt-4">
        <Link to="/student/dashboard">
          <Button variant="secondary">Go to Dashboard</Button>
        </Link>
        <Link to="/student/exams">
          <Button variant="primary">Take Another Assessment</Button>
        </Link>
      </div>
    </div>
  );
};

export default AttemptResult;
