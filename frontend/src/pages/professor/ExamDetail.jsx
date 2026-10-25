import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getExam } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  ArrowLeft,
  BookOpen,
  Calendar,
  Layers,
  Award,
  CheckCircle,
  HelpCircle,
  Quote,
  Check,
  FileText,
} from 'lucide-react';

const ExamDetail = () => {
  const { id } = useParams();
  const [exam, setExam] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchExam = async () => {
      setLoading(true);
      setError('');
      try {
        const data = await getExam(id);
        setExam(data);
      } catch (err) {
        console.error('Failed to load exam details:', err);
        setError('Failed to fetch exam details. Please ensure the backend is running.');
      } finally {
        setLoading(false);
      }
    };

    if (id) {
      fetchExam();
    }
  }, [id]);

  if (loading) {
    return <LoadingSpinner size="lg" message="Loading exam assessment details..." />;
  }

  if (error || !exam) {
    return (
      <div className="space-y-4 max-w-4xl mx-auto">
        <Link to="/professor/exams">
          <Button variant="ghost" size="sm" icon={ArrowLeft}>
            Back to Exams
          </Button>
        </Link>
        <Alert type="error" title="Error" message={error || 'Exam not found.'} />
      </div>
    );
  }

  const questions = exam.questions || [];
  const totalScore =
    exam.total_points ||
    exam.max_score ||
    questions.reduce((sum, q) => sum + (q.max_score || 1), 0);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Back button and breadcrumbs */}
      <div className="flex items-center justify-between">
        <Link to="/professor/exams">
          <Button variant="ghost" size="sm" icon={ArrowLeft}>
            Back to All Exams
          </Button>
        </Link>
        <span className="text-xs font-mono text-gray-400">Exam ID: {id}</span>
      </div>

      {/* Exam Header Banner */}
      <Card className="bg-gradient-to-r from-slate-900 to-indigo-950 text-white p-6 md:p-8">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              {exam.difficulty && (
                <Badge type="difficulty" size="sm">
                  {exam.difficulty}
                </Badge>
              )}
              {exam.bloom_level && (
                <Badge type="bloom" size="sm">
                  {exam.bloom_level}
                </Badge>
              )}
              <span className="text-xs text-indigo-200 bg-indigo-900/60 px-2.5 py-0.5 rounded-full border border-indigo-700/50">
                Grounding: Chroma RAG
              </span>
            </div>
            <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight text-white">
              {exam.title || exam.topic || `Assessment #${id}`}
            </h1>
            <p className="text-sm text-indigo-200">
              Lesson: {exam.lesson_title || exam.lesson || 'Standard Curriculum'}{' '}
              {exam.topic && `• Topic: ${exam.topic}`}
            </p>
          </div>

          <div className="flex items-center gap-4 bg-white/10 p-4 rounded-xl backdrop-blur-sm border border-white/10 shrink-0">
            <div className="text-center px-3 border-r border-white/10">
              <p className="text-[11px] uppercase tracking-wider text-indigo-200">Questions</p>
              <p className="text-2xl font-bold">{questions.length}</p>
            </div>
            <div className="text-center px-3">
              <p className="text-[11px] uppercase tracking-wider text-indigo-200">Total Points</p>
              <p className="text-2xl font-bold text-amber-300">{totalScore}</p>
            </div>
          </div>
        </div>
      </Card>

      {/* Questions list */}
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
            <Layers className="w-5 h-5 text-indigo-600" />
            Questions, Model Answers & Rubrics ({questions.length})
          </h2>
        </div>

        {questions.length === 0 ? (
          <Card className="text-center py-10">
            <p className="text-sm text-gray-500">No questions found in this assessment.</p>
          </Card>
        ) : (
          questions.map((q, idx) => (
            <Card key={idx} className="p-6 space-y-4">
              {/* Question metadata header */}
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 pb-3">
                <div className="flex items-center gap-2">
                  <span className="w-7 h-7 rounded-lg bg-indigo-600 text-white font-bold text-xs flex items-center justify-center">
                    {idx + 1}
                  </span>
                  <Badge type="qtype">{q.question_type}</Badge>
                  {q.difficulty && <Badge type="difficulty">{q.difficulty}</Badge>}
                  {q.bloom_level && <Badge type="bloom">{q.bloom_level}</Badge>}
                </div>
                <span className="text-xs font-semibold text-gray-700 bg-gray-100 px-3 py-1 rounded-md">
                  Point Value: {q.max_score || 1} pt(s)
                </span>
              </div>

              {/* Question statement */}
              <div>
                <h3 className="text-base font-bold text-gray-900 leading-snug">
                  {q.question}
                </h3>
                {q.bloom_rationale && (
                  <p className="text-xs text-gray-500 italic mt-1.5 bg-slate-50 p-2 rounded border border-slate-100">
                    <span className="font-semibold text-gray-700">Taxonomy Rationale:</span>{' '}
                    {q.bloom_rationale}
                  </p>
                )}
              </div>

              {/* Multiple Choice Options */}
              {q.question_type === 'mcq' && q.options && (
                <div className="space-y-2 pt-1">
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Options:
                  </p>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {q.options.map((option, optIdx) => {
                      const letter = String.fromCharCode(65 + optIdx);
                      const isCorrect =
                        q.correct_answer === letter ||
                        q.correct_answer === String(optIdx + 1) ||
                        option.startsWith(`${letter}.`) ||
                        option.startsWith(`${letter})`);

                      return (
                        <div
                          key={optIdx}
                          className={`p-3 rounded-lg border text-xs font-medium flex items-start gap-3 transition-colors ${
                            isCorrect
                              ? 'bg-emerald-50 border-emerald-300 text-emerald-950 font-semibold'
                              : 'bg-white border-gray-200 text-gray-700'
                          }`}
                        >
                          <span
                            className={`w-5 h-5 rounded-md flex items-center justify-center shrink-0 text-xs font-bold ${
                              isCorrect
                                ? 'bg-emerald-600 text-white'
                                : 'bg-gray-100 text-gray-600'
                            }`}
                          >
                            {letter}
                          </span>
                          <span className="flex-1">{option}</span>
                          {isCorrect && (
                            <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-700 bg-emerald-100 px-1.5 py-0.5 rounded flex items-center gap-1">
                              <Check className="w-3 h-3" /> Correct Key
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Model / Reference Answer & Explanation */}
              <div className="p-4 bg-slate-50/80 rounded-xl border border-slate-200/80 space-y-2 text-xs">
                <div>
                  <span className="font-bold text-gray-800">Model / Reference Answer:</span>
                  <p className="text-gray-900 mt-0.5 leading-relaxed font-mono whitespace-pre-wrap bg-white p-2.5 rounded border border-gray-200">
                    {q.reference_answer || q.correct_answer || 'None provided'}
                  </p>
                </div>
                {q.explanation && (
                  <div>
                    <span className="font-bold text-gray-800">Pedagogical Explanation:</span>
                    <p className="text-gray-600 mt-0.5 leading-relaxed">{q.explanation}</p>
                  </div>
                )}
              </div>

              {/* Rubric Criteria Table */}
              {q.rubric && Array.isArray(q.rubric) && q.rubric.length > 0 && (
                <div className="space-y-2">
                  <span className="text-xs font-bold text-gray-700 uppercase tracking-wider">
                    Semantic Evaluation Rubric ({q.rubric.length} Criteria)
                  </span>
                  <div className="border border-gray-200 rounded-lg overflow-hidden">
                    <table className="w-full text-xs text-left divide-y divide-gray-200">
                      <thead className="bg-gray-50 text-gray-600 uppercase tracking-wider text-[10px] font-semibold">
                        <tr>
                          <th className="px-3.5 py-2">Evaluation Criterion</th>
                          <th className="px-3.5 py-2">Target Evidence & Expectations</th>
                          <th className="px-3.5 py-2 text-right">Points</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 bg-white">
                        {q.rubric.map((item, rIdx) => (
                          <tr key={rIdx} className="hover:bg-slate-50">
                            <td className="px-3.5 py-2.5 font-semibold text-gray-900">
                              {item.criterion}
                            </td>
                            <td className="px-3.5 py-2.5 text-gray-600 leading-relaxed">
                              {item.description}
                            </td>
                            <td className="px-3.5 py-2.5 text-right font-bold text-indigo-600">
                              {item.points}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Grounded Source Citations */}
              {q.source_refs && q.source_refs.length > 0 && (
                <div className="p-3 bg-amber-50/50 border border-amber-200/60 rounded-lg text-xs space-y-1">
                  <div className="flex items-center gap-1.5 font-semibold text-amber-900">
                    <Quote className="w-3.5 h-3.5 text-amber-600" />
                    <span>Curriculum Source Grounding Quote</span>
                  </div>
                  {q.source_refs.map((ref, refIdx) => (
                    <div key={refIdx} className="text-amber-800 italic pl-5">
                      "{ref.evidence_quote || ref.source}"
                      {ref.chunk_id && (
                        <span className="text-amber-600 not-italic ml-2 font-mono text-[11px]">
                          [{ref.chunk_id}]
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          ))
        )}
      </div>
    </div>
  );
};

export default ExamDetail;
