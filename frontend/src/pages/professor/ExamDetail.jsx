import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getExam, togglePublishExam, updateExamQuestion } from '../../api/client';
import { Send, Globe } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  ArrowRight,
  BookOpen,
  Calendar,
  Layers,
  Award,
  CheckCircle,
  HelpCircle,
  Quote,
  Check,
  FileText,
  Pencil,
  X,
  Plus,
  Trash2,
} from 'lucide-react';

const DIFFICULTY_OPTIONS = ['easy', 'medium', 'hard'];
const BLOOM_OPTIONS = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'];
const QUESTION_TYPE_OPTIONS = ['mcq', 'short_answer', 'essay'];

const buildDraft = (q) => ({
  question: q.question || '',
  question_type: q.question_type || 'short_answer',
  difficulty: DIFFICULTY_OPTIONS.includes(q.difficulty) ? q.difficulty : 'medium',
  bloom_level: BLOOM_OPTIONS.includes(q.bloom_level) ? q.bloom_level : 'understand',
  options:
    q.question_type === 'mcq' && Array.isArray(q.options)
      ? q.options.slice(0, 4).concat(Array(Math.max(0, 4 - q.options.length)).fill(''))
      : ['', '', '', ''],
  correct_answer:
    q.question_type === 'mcq' && /^[A-D]$/.test(String(q.correct_answer || '').trim())
      ? String(q.correct_answer).trim()
      : 'A',
  reference_answer: q.reference_answer || q.correct_answer || '',
  explanation: q.explanation || '',
  max_score: String(q.max_score ?? 1),
  rubric:
    Array.isArray(q.rubric) && q.rubric.length > 0
      ? q.rubric.map((r) => ({
          criterion: r.criterion || '',
          description: r.description || '',
          points: String(r.points ?? 1),
        }))
      : [{ criterion: '', description: '', points: '1' }],
  bloom_rationale: q.bloom_rationale || '',
});

const rubricPointsSum = (rubric) =>
  rubric.reduce((sum, row) => sum + (Number.parseFloat(row.points) || 0), 0);

const validateDraft = (draft) => {
  if (!draft.question.trim()) return 'نص السؤال مطلوب.';
  if (draft.question_type === 'mcq') {
    if (draft.options.length !== 4 || draft.options.some((o) => !o.trim())) {
      return 'سؤال الاختيار المتعدد لازم يكون فيه ٤ اختيارات مكتوبة.';
    }
    if (new Set(draft.options.map((o) => o.trim())).size !== 4) {
      return 'لازم الاختيارات الأربعة تكون مختلفة عن بعض.';
    }
    if (!/^[A-D]$/.test(draft.correct_answer)) {
      return 'اختار الإجابة الصحيحة (A-D).';
    }
  }
  if (!draft.reference_answer.trim()) return 'الإجابة النموذجية مطلوبة (هي أساس التصحيح الآلي).';
  if (!draft.explanation.trim()) return 'الشرح التعليمي مطلوب.';
  if (draft.rubric.length === 0) return 'لازم معيار تصحيح واحد على الأقل.';
  if (
    draft.rubric.some(
      (r) => !r.criterion.trim() || !r.description.trim() || !(Number.parseFloat(r.points) > 0)
    )
  ) {
    return 'كل معيار في نموذج التصحيح لازم يكون فيه وصف ودرجة أكبر من صفر.';
  }
  const maxScore = Number.parseFloat(draft.max_score);
  if (!(maxScore > 0)) return 'الدرجة الكلية للسؤال لازم تكون أكبر من صفر.';
  const sum = rubricPointsSum(draft.rubric);
  if (Math.abs(sum - maxScore) > 1e-6) {
    return `مجموع درجات المعايير (${sum}) لازم يساوي الدرجة الكلية (${maxScore}).`;
  }
  return '';
};

const QuestionEditor = ({ examId, index, question, onSaved, onCancel }) => {
  const [draft, setDraft] = useState(() => buildDraft(question));
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState('');

  const updateField = (field, value) => setDraft((prev) => ({ ...prev, [field]: value }));

  const updateRubricRow = (rowIdx, field, value) =>
    setDraft((prev) => ({
      ...prev,
      rubric: prev.rubric.map((row, i) => (i === rowIdx ? { ...row, [field]: value } : row)),
    }));

  const addRubricRow = () =>
    setDraft((prev) => ({
      ...prev,
      rubric: [...prev.rubric, { criterion: '', description: '', points: '1' }],
    }));

  const removeRubricRow = (rowIdx) =>
    setDraft((prev) => ({
      ...prev,
      rubric: prev.rubric.filter((_, i) => i !== rowIdx),
    }));

  const handleSave = async () => {
    setEditError('');
    const validationMessage = validateDraft(draft);
    if (validationMessage) {
      setEditError(validationMessage);
      return;
    }

    setSaving(true);
    try {
      const payload = {
        question: draft.question.trim(),
        question_type: draft.question_type,
        difficulty: draft.difficulty,
        bloom_level: draft.bloom_level,
        options: draft.question_type === 'mcq' ? draft.options.map((o) => o.trim()) : [],
        correct_answer: draft.question_type === 'mcq' ? draft.correct_answer : '',
        reference_answer: draft.reference_answer.trim(),
        explanation: draft.explanation.trim(),
        max_score: Number.parseFloat(draft.max_score),
        rubric: draft.rubric.map((row) => ({
          criterion: row.criterion.trim(),
          description: row.description.trim(),
          points: Number.parseFloat(row.points),
        })),
        bloom_rationale: draft.bloom_rationale.trim() || undefined,
      };
      const updated = await updateExamQuestion(examId, index, payload);
      onSaved(updated);
    } catch (err) {
      console.error('Failed to save question edit:', err);
      const detail = err.response?.data?.detail || err.message || 'فشل حفظ التعديل.';
      setEditError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setSaving(false);
    }
  };

  const inputClass =
    'w-full px-3 py-2 text-sm bg-white border-2 border-cocoa-300/60 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 transition outline-none';

  const rubricSum = rubricPointsSum(draft.rubric);
  const maxScoreValue = Number.parseFloat(draft.max_score) || 0;
  const scoreMismatch = Math.abs(rubricSum - maxScoreValue) > 1e-6;

  return (
    <div className="mt-4 p-4 bg-gold-50/50 border-2 border-gold-300 rounded-2xl space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-extrabold text-cocoa-800 flex items-center gap-2">
          <Pencil className="w-4 h-4 text-gold-700" />
          تعديل السؤال رقم {index + 1}
        </h4>
        <Button variant="ghost" size="sm" icon={X} onClick={onCancel}>
          إلغاء
        </Button>
      </div>

      {editError && (
        <Alert type="error" title="التعديل مرفوض" message={editError} onClose={() => setEditError('')} />
      )}

      <div>
        <label className="block text-xs font-bold text-cocoa-800 mb-1">نص السؤال</label>
        <textarea
          value={draft.question}
          onChange={(e) => updateField('question', e.target.value)}
          rows={2}
          dir="auto"
          className={inputClass}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-bold text-cocoa-800 mb-1">نوع السؤال</label>
          <select
            value={draft.question_type}
            onChange={(e) => updateField('question_type', e.target.value)}
            className={inputClass}
          >
            {QUESTION_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-bold text-cocoa-800 mb-1">الصعوبة</label>
          <select
            value={draft.difficulty}
            onChange={(e) => updateField('difficulty', e.target.value)}
            className={inputClass}
          >
            {DIFFICULTY_OPTIONS.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-bold text-cocoa-800 mb-1">مستوى بلوم</label>
          <select
            value={draft.bloom_level}
            onChange={(e) => updateField('bloom_level', e.target.value)}
            className={inputClass}
          >
            {BLOOM_OPTIONS.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </div>
      </div>

      {draft.question_type === 'mcq' && (
        <div className="space-y-2">
          <label className="block text-xs font-bold text-cocoa-800">الاختيارات الأربعة</label>
          {draft.options.map((opt, optIdx) => {
            const letter = String.fromCharCode(65 + optIdx);
            return (
              <div key={optIdx} className="flex items-center gap-2">
                <span className="w-6 h-6 rounded-md bg-sand text-cocoa-800 text-xs font-bold flex items-center justify-center shrink-0">
                  {letter}
                </span>
                <input
                  type="text"
                  value={opt}
                  onChange={(e) =>
                    setDraft((prev) => ({
                      ...prev,
                      options: prev.options.map((o, i) => (i === optIdx ? e.target.value : o)),
                    }))
                  }
                  dir="auto"
                  className={`${inputClass} flex-1`}
                />
                <label className="inline-flex items-center gap-1 text-xs font-bold text-cocoa-800 cursor-pointer shrink-0">
                  <input
                    type="radio"
                    name={`correct-answer-${index}`}
                    checked={draft.correct_answer === letter}
                    onChange={() => updateField('correct_answer', letter)}
                    className="w-4 h-4 accent-teal-700"
                  />
                  صح
                </label>
              </div>
            );
          })}
        </div>
      )}

      <div>
        <label className="block text-xs font-bold text-cocoa-800 mb-1">الإجابة النموذجية (أساس التصحيح)</label>
        <textarea
          value={draft.reference_answer}
          onChange={(e) => updateField('reference_answer', e.target.value)}
          rows={2}
          dir="auto"
          className={inputClass}
        />
      </div>

      <div>
        <label className="block text-xs font-bold text-cocoa-800 mb-1">الشرح التعليمي</label>
        <textarea
          value={draft.explanation}
          onChange={(e) => updateField('explanation', e.target.value)}
          rows={2}
          dir="auto"
          className={inputClass}
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-xs font-bold text-cocoa-800">نموذج التصحيح (المعايير والدرجات)</label>
          <Button variant="ghost" size="sm" icon={Plus} onClick={addRubricRow}>
            معيار جديد
          </Button>
        </div>
        {draft.rubric.map((row, rowIdx) => (
          <div key={rowIdx} className="flex flex-col sm:flex-row gap-2 bg-paper border border-sand rounded-xl p-2">
            <input
              type="text"
              value={row.criterion}
              onChange={(e) => updateRubricRow(rowIdx, 'criterion', e.target.value)}
              placeholder="المعيار"
              dir="auto"
              className={`${inputClass} sm:w-44 shrink-0`}
            />
            <input
              type="text"
              value={row.description}
              onChange={(e) => updateRubricRow(rowIdx, 'description', e.target.value)}
              placeholder="الوصف والمتوقع في الإجابة"
              dir="auto"
              className={`${inputClass} flex-1`}
            />
            <input
              type="number"
              min="0.5"
              step="0.5"
              value={row.points}
              onChange={(e) => updateRubricRow(rowIdx, 'points', e.target.value)}
              className={`${inputClass} sm:w-20 shrink-0`}
            />
            <Button
              variant="ghost"
              size="sm"
              icon={Trash2}
              onClick={() => removeRubricRow(rowIdx)}
              disabled={draft.rubric.length === 1}
              className="text-red-600 shrink-0"
              aria-label="حذف المعيار"
            />
          </div>
        ))}
        <div className="flex items-center justify-between text-xs font-bold">
          <span className="text-cocoa-500">
            مجموع درجات المعايير: {rubricSum}
          </span>
          <div className="flex items-center gap-2">
            <label className="text-cocoa-800">الدرجة الكلية:</label>
            <input
              type="number"
              min="0.5"
              step="0.5"
              value={draft.max_score}
              onChange={(e) => updateField('max_score', e.target.value)}
              className="w-20 px-2 py-1 text-sm bg-white border-2 border-cocoa-300/60 rounded-lg focus:ring-2 focus:ring-gold-400/20 focus:border-gold-500 outline-none"
            />
          </div>
        </div>
        {scoreMismatch && (
          <p className="text-xs text-gold-700 font-bold" role="alert">
            ⚠️ مجموع درجات المعايير لازم يساوي الدرجة الكلية عشان التصحيح الآلي يشتغل صح.
          </p>
        )}
      </div>

      <div className="flex items-center justify-end gap-2 pt-2 border-t border-gold-200">
        <Button variant="secondary" size="sm" onClick={onCancel}>
          إلغاء
        </Button>
        <Button
          variant="primary"
          size="sm"
          icon={Check}
          loading={saving}
          onClick={handleSave}
          className="btn-cut"
        >
          تأكيد وحفظ التعديل
        </Button>
      </div>
    </div>
  );
};

const ExamDetail = () => {
  const { id } = useParams();
  const [exam, setExam] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [publishing, setPublishing] = useState(false);
  const [editingIndex, setEditingIndex] = useState(null);
  const [saveNotice, setSaveNotice] = useState('');

  const handleTogglePublish = async () => {
    if (!exam) return;
    setPublishing(true);
    try {
      const nextStatus = !exam.is_published;
      const updated = await togglePublishExam(id, nextStatus);
      setExam((prev) => ({ ...prev, is_published: updated.is_published }));
    } catch (err) {
      console.error('Failed to toggle publish status:', err);
      setError('معرفناش نغيّر حالة النشر، حاول تاني.');
    } finally {
      setPublishing(false);
    }
  };

  const handleQuestionSaved = (updatedExam) => {
    setExam((prev) => ({
      ...prev,
      ...updatedExam,
      is_published: prev?.is_published ?? updatedExam.is_published,
    }));
    setEditingIndex(null);
    setSaveNotice('✓ السؤال اتعدل واتأكد — نموذج التصحيح الجديد هيتستخدم في التصحيح الآلي.');
  };

  useEffect(() => {
    const fetchExam = async () => {
      setLoading(true);
      setError('');
      try {
        const data = await getExam(id);
        setExam(data);
      } catch (err) {
        console.error('Failed to load exam details:', err);
        setError('فشل تحميل تفاصيل الامتحان. تأكد إن السيرفر شغال.');
      } finally {
        setLoading(false);
      }
    };

    if (id) {
      fetchExam();
    }
  }, [id]);

  if (loading) {
    return <LoadingSpinner size="lg" message="جاري تحميل تفاصيل الامتحان..." />;
  }

  if (error || !exam) {
    return (
      <div className="space-y-4 max-w-4xl mx-auto">
        <Link to="/professor/exams">
          <Button variant="ghost" size="sm" icon={ArrowRight}>
            رجوع للامتحانات
          </Button>
        </Link>
        <Alert type="error" title="خطأ" message={error || 'الامتحان مش موجود.'} />
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
          <Button variant="ghost" size="sm" icon={ArrowRight}>
            رجوع لكل الامتحانات
          </Button>
        </Link>
        <span className="text-xs font-code text-cocoa-300" dir="ltr">Exam ID: {id}</span>
      </div>

      {/* Exam Header Banner */}
      <Card className="bg-gradient-to-bl from-cocoa-900 to-cocoa-950 text-white p-6 md:p-8 border-none shadow-pop relative overflow-hidden">
        <span className="code-chip-light absolute top-4 end-5 rotate-2 hidden md:inline-block">exam.publish()</span>
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 relative z-10">
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
              <span className="code-chip-light">Grounding: RAG</span>
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight text-white" dir="auto">
                {exam.title || exam.topic || `Assessment #${id}`}
              </h1>
              <span
                className={`sticker !text-[11px] ${
                  exam.is_published ? 'text-teal-300 !bg-transparent' : 'text-gold-300 !bg-transparent'
                }`}
                style={{ borderWidth: 1.5 }}
              >
                {exam.is_published ? '🟢 منشور للطلبة' : '✏️ مسودة (مش ظاهرة)'}
              </span>
            </div>
            <p className="text-sm text-cocoa-300" dir="auto">
              الدرس: {exam.lesson_title || exam.lesson || 'المنهج الأساسي'}{' '}
              {exam.topic && `• Topic: ${exam.topic}`}
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-center gap-4 shrink-0">
            <div className="flex items-center gap-4 bg-white/10 p-4 rounded-2xl backdrop-blur-sm border border-white/10">
              <div className="text-center px-3 border-e border-white/10">
                <p className="text-[11px] text-cocoa-300 font-bold">أسئلة</p>
                <p className="font-display text-2xl text-gold-300">{questions.length}</p>
              </div>
              <div className="text-center px-3">
                <p className="text-[11px] text-cocoa-300 font-bold">إجمالي الدرجات</p>
                <p className="font-display text-2xl text-gold-300">{totalScore}</p>
              </div>
            </div>
            <Button
              variant={exam.is_published ? "secondary" : "primary"}
              size="lg"
              loading={publishing}
              icon={exam.is_published ? Globe : Send}
              onClick={handleTogglePublish}
              className={exam.is_published ? "bg-white/20 text-white hover:bg-white/30 border-white/20" : "bg-gold-400 hover:bg-gold-300 text-clay-950 shadow-pop !bg-gradient-to-b !from-gold-400 !to-gold-500"}
            >
              {exam.is_published ? "إلغاء النشر" : "انشر للطلبة"}
            </Button>
          </div>
        </div>
      </Card>

      {/* Questions list */}
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-extrabold text-ink flex items-center gap-2">
            <Layers className="w-5 h-5 text-clay-600" />
            الأسئلة والإجابات النموذجية ونماذج التصحيح ({questions.length})
          </h2>
        </div>

        {saveNotice && (
          <Alert
            type="success"
            title="تم الحفظ"
            message={saveNotice}
            onClose={() => setSaveNotice('')}
          />
        )}

        {questions.length === 0 ? (
          <Card className="text-center py-10">
            <p className="text-sm text-cocoa-500">مفيش أسئلة في الامتحان ده.</p>
          </Card>
        ) : (
          questions.map((q, idx) => (
            <Card key={idx} className="p-6 space-y-4">
              {/* Question metadata header */}
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-sand pb-3">
                <div className="flex items-center gap-2">
                  <span className="w-7 h-7 rounded-lg rounded-br-sm bg-gradient-to-b from-clay-600 to-clay-800 text-white font-bold text-xs flex items-center justify-center">
                    {idx + 1}
                  </span>
                  <Badge type="qtype">{q.question_type}</Badge>
                  {q.difficulty && <Badge type="difficulty">{q.difficulty}</Badge>}
                  {q.bloom_level && <Badge type="bloom">{q.bloom_level}</Badge>}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-cocoa-800 bg-cream px-3 py-1 rounded-lg border border-sand">
                    الدرجة: {q.max_score || 1}
                  </span>
                  {editingIndex !== idx && (
                    <Button
                      variant="outline"
                      size="sm"
                      icon={Pencil}
                      onClick={() => {
                        setSaveNotice('');
                        setEditingIndex(idx);
                      }}
                    >
                      تعديل
                    </Button>
                  )}
                </div>
              </div>

              {editingIndex === idx ? (
                <QuestionEditor
                  examId={id}
                  index={idx}
                  question={q}
                  onSaved={handleQuestionSaved}
                  onCancel={() => setEditingIndex(null)}
                />
              ) : (
                <>
                  {/* Question statement */}
                  <div>
                    <h3 className="text-base font-bold text-ink leading-snug" dir="auto">
                      {q.question}
                    </h3>
                    {q.bloom_rationale && (
                      <p className="text-xs text-cocoa-500 italic mt-1.5 bg-cream p-2 rounded-lg border border-sand" dir="auto">
                        <span className="font-bold text-cocoa-800">مبرر التصنيف المعرفي:</span>{' '}
                        {q.bloom_rationale}
                      </p>
                    )}
                  </div>

                  {/* Multiple Choice Options */}
                  {q.question_type === 'mcq' && q.options && (
                    <div className="space-y-2 pt-1">
                      <p className="text-xs font-bold text-cocoa-500">الاختيارات:</p>
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
                              className={`p-3 rounded-xl border text-xs font-bold flex items-start gap-3 transition-colors ${
                                isCorrect
                                  ? 'bg-teal-50 border-teal-300 text-teal-900'
                                  : 'bg-paper border-sand text-cocoa-800'
                              }`}
                              dir="auto"
                            >
                              <span
                                className={`w-5 h-5 rounded-md flex items-center justify-center shrink-0 text-xs font-bold ${
                                  isCorrect
                                    ? 'bg-teal-700 text-white'
                                    : 'bg-sand text-cocoa-800'
                                }`}
                              >
                                {letter}
                              </span>
                              <span className="flex-1">{option}</span>
                              {isCorrect && (
                                <span className="text-[10px] font-bold text-teal-700 bg-teal-100 px-1.5 py-0.5 rounded flex items-center gap-1">
                                  <Check className="w-3 h-3" /> الإجابة
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Model / Reference Answer & Explanation */}
                  <div className="p-4 bg-cream/80 rounded-2xl border border-sand space-y-2 text-xs">
                    <div>
                      <span className="font-bold text-cocoa-800">الإجابة النموذجية:</span>
                      <p className="text-ink mt-0.5 leading-relaxed font-code whitespace-pre-wrap bg-paper p-2.5 rounded-lg border border-sand" dir="auto">
                        {q.reference_answer || q.correct_answer || 'غير متوفر'}
                      </p>
                    </div>
                    {q.explanation && (
                      <div>
                        <span className="font-bold text-cocoa-800">الشرح التعليمي:</span>
                        <p className="text-cocoa-500 mt-0.5 leading-relaxed" dir="auto">{q.explanation}</p>
                      </div>
                    )}
                  </div>

                  {/* Rubric Criteria Table */}
                  {q.rubric && Array.isArray(q.rubric) && q.rubric.length > 0 && (
                    <div className="space-y-2">
                      <span className="text-xs font-bold text-cocoa-800">
                        نموذج التصحيح ({q.rubric.length} معايير)
                      </span>
                      <div className="border border-sand rounded-xl overflow-hidden">
                        <table className="w-full text-xs text-right divide-y divide-sand">
                          <thead className="bg-cream text-cocoa-500 text-[11px] font-bold">
                            <tr>
                              <th className="px-3.5 py-2">المعيار</th>
                              <th className="px-3.5 py-2">الوصف والمتوقع</th>
                              <th className="px-3.5 py-2">الدرجة</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-sand bg-paper">
                            {q.rubric.map((item, rIdx) => (
                              <tr key={rIdx} className="hover:bg-cream/60 transition-colors">
                                <td className="px-3.5 py-2.5 font-bold text-ink" dir="auto">
                                  {item.criterion}
                                </td>
                                <td className="px-3.5 py-2.5 text-cocoa-500 leading-relaxed" dir="auto">
                                  {item.description}
                                </td>
                                <td className="px-3.5 py-2.5 font-bold text-clay-700">
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
                    <div className="p-3 bg-gold-50/60 border border-gold-200 rounded-xl text-xs space-y-1">
                      <div className="flex items-center gap-1.5 font-bold text-gold-700">
                        <Quote className="w-3.5 h-3.5 text-gold-600" />
                        <span>اقتباس من مصدر المنهج</span>
                      </div>
                      {q.source_refs.map((ref, refIdx) => (
                        <div key={refIdx} className="text-gold-800 italic ps-5" dir="auto">
                          "{ref.evidence_quote || ref.source}"
                          {ref.chunk_id && (
                            <span className="text-gold-600 not-italic ms-2 font-code text-[11px]">
                              [{ref.chunk_id}]
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </Card>
          ))
        )}
      </div>
    </div>
  );
};

export default ExamDetail;
