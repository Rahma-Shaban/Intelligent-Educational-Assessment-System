import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getLessons, generateExam } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import Alert from '../../components/ui/Alert';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import {
  assertRequestedQuestionCount,
  buildExamPayload,
} from './examGeneration';
import {
  Sparkles,
  BookOpen,
  CheckSquare,
  HelpCircle,
  FileCheck,
  Eye,
  ArrowRight,
  ListOrdered,
  ChevronDown,
  Quote,
} from 'lucide-react';

const GenerateExam = () => {
  const [lessons, setLessons] = useState([]);
  const [loadingLessons, setLoadingLessons] = useState(true);

  // Form states
  const [selectedLesson, setSelectedLesson] = useState('');
  const [topic, setTopic] = useState('');
  const [difficulty, setDifficulty] = useState('medium');
  const [bloomLevel, setBloomLevel] = useState('understand');
  const [questionTypes, setQuestionTypes] = useState({
    mcq: true,
    short_answer: true,
    essay: true,
  });
  const [numQuestions, setNumQuestions] = useState(3);
  const [title, setTitle] = useState('');

  // Generation state
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [generatedExam, setGeneratedExam] = useState(null);
  const [lastRequestedCount, setLastRequestedCount] = useState(null);

  const navigate = useNavigate();
  const selectedLessonDetails = lessons.find(
    (lesson) => String(lesson.lesson_id || lesson.id) === String(selectedLesson)
  );
  const lessonChunkCount = Number.isInteger(selectedLessonDetails?.chunk_count)
    ? selectedLessonDetails.chunk_count
    : null;
  const requestedQuestionCount = Number.parseInt(numQuestions, 10) || 3;
  const generatedQuestions = generatedExam?.questions || [];
  const uniqueQuestionCount = new Set(
    generatedQuestions
      .map((question) => question.question?.trim().toLowerCase())
      .filter(Boolean)
  ).size;
  const uniqueCitedChunkCount = new Set(
    generatedQuestions.flatMap((question) =>
      (question.source_refs || []).map((sourceRef) => sourceRef.chunk_id).filter(Boolean)
    )
  ).size;
  const generationWarnings = generatedExam?.warnings || [];

  useEffect(() => {
    const fetchLessons = async () => {
      setLoadingLessons(true);
      try {
        const data = await getLessons();
        const list = Array.isArray(data) ? data : data?.lessons || [];
        setLessons(list);
        if (list.length > 0) {
          const firstId = list[0].id || list[0].lesson_id || list[0].title || list[0];
          setSelectedLesson(typeof firstId === 'object' ? firstId.id : firstId);
        }
      } catch (err) {
        console.warn('Could not load lessons list:', err);
        // Fallback default sample lessons so professor can still generate
        setLessons([
          { id: 'ch1_intro', title: 'Chapter 1: Introduction to Educational Systems' },
          { id: 'ch2_assessment', title: 'Chapter 2: Formative vs Summative Assessment' },
          { id: 'ch3_taxonomy', title: "Chapter 3: Bloom's Cognitive Taxonomy" },
        ]);
        setSelectedLesson('ch1_intro');
      } finally {
        setLoadingLessons(false);
      }
    };

    fetchLessons();
  }, []);

  const handleTypeChange = (type) => {
    const nextState = { ...questionTypes, [type]: !questionTypes[type] };
    // Ensure at least one type is selected
    if (Object.values(nextState).some(Boolean)) {
      setQuestionTypes(nextState);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    const activeTypes = Object.keys(questionTypes).filter((t) => questionTypes[t]);
    if (activeTypes.length === 0) {
      setError('Please select at least one question type (MCQ, Short Answer, or Essay).');
      return;
    }

    setGenerating(true);
    setGeneratedExam(null);
    setLastRequestedCount(null);

    const requestCount = Number.parseInt(numQuestions, 10) || 3;
    const payload = buildExamPayload({
      title,
      selectedLesson,
      topic,
      difficulty,
      bloomLevel,
      questionTypes: activeTypes,
      numQuestions,
    });

    try {
      const response = await generateExam(payload);
      assertRequestedQuestionCount(response, requestCount);
      setGeneratedExam(response);
      setLastRequestedCount(requestCount);
    } catch (err) {
      console.error('Exam generation failed:', err);
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        'Exam generation failed. Check that the curriculum is indexed and the selected LLM provider is configured.';
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* Title */}
      <div>
        <h1 className="text-2xl md:text-3xl font-extrabold text-gray-900 tracking-tight">
          Generate Curriculum-Grounded Exam
        </h1>
        <p className="text-sm text-gray-600 mt-1">
          Specify lesson, cognitive level, and target topics. Questions are retrieved from verified vector store context with source citations.
        </p>
      </div>

      {error && (
        <Alert
          type="error"
          title="Generation Error"
          message={error}
          onClose={() => setError('')}
        />
      )}

      {/* Main Form */}
      <Card
        title="Exam Specification"
        subtitle="Configure the AI assessment generator"
      >
        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Exam Title (Optional) */}
            <div className="md:col-span-2">
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1.5">
                Assessment Title (Optional)
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g., Midterm Evaluation: Chapter 2 Foundations"
                className="w-full px-3.5 py-2.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-600 focus:border-indigo-600 transition-colors"
              />
            </div>

            {/* Lesson dropdown */}
            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1.5">
                Curriculum Lesson / Chapter
              </label>
              {loadingLessons ? (
                <div className="h-10 bg-gray-100 rounded-lg animate-pulse" />
              ) : (
                <div className="relative">
                  <select
                    value={selectedLesson}
                    onChange={(e) => setSelectedLesson(e.target.value)}
                    className="w-full px-3.5 py-2.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-600 focus:border-indigo-600 appearance-none bg-white pr-10"
                    required
                  >
                    {lessons.map((lesson, idx) => {
                      const val = lesson.id || lesson.lesson_id || lesson.title || lesson;
                      const label = lesson.title || lesson.name || lesson.id || `Lesson ${idx + 1}`;
                      return (
                        <option key={String(val)} value={val}>
                          {label}
                        </option>
                      );
                    })}
                  </select>
                  <ChevronDown className="w-4 h-4 text-gray-400 absolute right-3 top-3 pointer-events-none" />
                </div>
              )}
            </div>

            {/* Target Topic Input */}
            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1.5">
                Target Topic / Focus Keyword
              </label>
              <input
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g., Cognitive taxonomies, formative evaluation"
                className="w-full px-3.5 py-2.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-600 focus:border-indigo-600 transition-colors"
              />
            </div>

            {/* Difficulty select */}
            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1.5">
                Difficulty Level
              </label>
              <select
                value={difficulty}
                onChange={(e) => setDifficulty(e.target.value)}
                className="w-full px-3.5 py-2.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-600 focus:border-indigo-600 bg-white"
              >
                <option value="easy">Easy (Foundational & Definitions)</option>
                <option value="medium">Medium (Application & Explanation)</option>
                <option value="hard">Hard (Critical Analysis & Synthesis)</option>
              </select>
            </div>

            {/* Bloom's Taxonomy Level */}
            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1.5">
                Bloom's Taxonomy Level
              </label>
              <select
                value={bloomLevel}
                onChange={(e) => setBloomLevel(e.target.value)}
                className="w-full px-3.5 py-2.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-600 focus:border-indigo-600 bg-white"
              >
                <option value="remember">Remember (Recall facts and basic concepts)</option>
                <option value="understand">Understand (Explain ideas or concepts)</option>
                <option value="apply">Apply (Use information in new situations)</option>
                <option value="analyze">Analyze (Draw connections among ideas)</option>
                <option value="evaluate">Evaluate (Justify a stance or decision)</option>
                <option value="create">Create (Produce new or original work)</option>
              </select>
            </div>

            {/* Number of Questions */}
            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1.5">
                Number of Questions (1 - 25)
              </label>
              <input
                type="number"
                min="1"
                max="25"
                value={numQuestions}
                onChange={(e) => setNumQuestions(e.target.value)}
                className="w-full px-3.5 py-2.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-600 focus:border-indigo-600 transition-colors"
                required
              />
              <p className="text-xs text-gray-500 mt-1.5">
                {lessonChunkCount === null
                  ? 'Lesson chunk count is unavailable.'
                  : `${lessonChunkCount} curriculum chunks available for this lesson.`}
              </p>
              {lessonChunkCount !== null && requestedQuestionCount > lessonChunkCount && (
                <p className="text-xs text-amber-700 mt-1" role="alert">
                  You requested {requestedQuestionCount} questions, but this lesson has only{' '}
                  {lessonChunkCount} unique chunks. Some questions may need to focus on the same chunk.
                </p>
              )}
            </div>

            {/* Question Types checkboxes */}
            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1.5">
                Allowed Question Types
              </label>
              <div className="flex items-center gap-4 pt-1.5">
                <label className="inline-flex items-center gap-2 cursor-pointer text-sm font-medium text-gray-700">
                  <input
                    type="checkbox"
                    checked={questionTypes.mcq}
                    onChange={() => handleTypeChange('mcq')}
                    className="w-4 h-4 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500"
                  />
                  <span>MCQ</span>
                </label>
                <label className="inline-flex items-center gap-2 cursor-pointer text-sm font-medium text-gray-700">
                  <input
                    type="checkbox"
                    checked={questionTypes.short_answer}
                    onChange={() => handleTypeChange('short_answer')}
                    className="w-4 h-4 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500"
                  />
                  <span>Short Answer</span>
                </label>
                <label className="inline-flex items-center gap-2 cursor-pointer text-sm font-medium text-gray-700">
                  <input
                    type="checkbox"
                    checked={questionTypes.essay}
                    onChange={() => handleTypeChange('essay')}
                    className="w-4 h-4 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500"
                  />
                  <span>Essay</span>
                </label>
              </div>
            </div>
          </div>

          <div className="pt-4 border-t border-gray-100 flex items-center justify-between">
            <p className="text-xs text-gray-500">
              ⚡ Generation typically requires 15–45 seconds as questions undergo grounding verification.
            </p>
            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={generating}
              icon={Sparkles}
            >
              {generating ? 'Generating Grounded Exam...' : 'Generate Exam'}
            </Button>
          </div>
        </form>
      </Card>

      {/* Generation in progress banner */}
      {generating && (
        <Card className="text-center py-10 bg-indigo-50/30 border-indigo-200">
          <LoadingSpinner size="lg" message="Gemini LLM is synthesizing questions from curriculum context..." />
          <p className="text-xs text-indigo-600 mt-2">
            Verifying source quotes &bull; Formulating grading rubrics &bull; Formatting options
          </p>
        </Card>
      )}

      {/* Generated Exam Preview Section */}
      {generatedExam && (
        <div className="space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-5 bg-emerald-50 border border-emerald-200 rounded-xl">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-600 text-white flex items-center justify-center shrink-0">
                <FileCheck className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-base font-bold text-emerald-950">
                  Exam Generated Successfully!
                </h3>
                <p className="text-xs text-emerald-700">
                  Requested: {lastRequestedCount} &bull; Generated: {generatedQuestions.length}{' '}
                  &bull; Total Points: {generatedExam.total_points || 'Calculated'}
                </p>
              </div>
            </div>
            <div className="flex gap-2">
              <Link to="/professor/exams">
                <Button variant="secondary" size="sm">
                  View All Exams
                </Button>
              </Link>
              {generatedExam.id && (
                <Link to={`/professor/exams/${generatedExam.id}`}>
                  <Button variant="primary" size="sm" icon={Eye}>
                    Inspect Full Details
                  </Button>
                </Link>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-700">
            <p>
              Unique question texts: {uniqueQuestionCount} &bull; Unique cited chunk IDs:{' '}
              {uniqueCitedChunkCount}
            </p>
            {generationWarnings.length > 0 && (
              <ul className="mt-2 list-disc pl-5 text-amber-800" role="status">
                {generationWarnings.map((warning, index) => (
                  <li key={`${index}-${warning}`}>{warning}</li>
                ))}
              </ul>
            )}
          </div>

          {/* Render Question Previews */}
          <div className="space-y-4">
            <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
              <ListOrdered className="w-5 h-5 text-indigo-600" />
              Generated Questions Preview
            </h3>

            {generatedQuestions.map((q, idx) => (
              <Card key={idx} className="p-6 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 pb-3">
                  <div className="flex items-center gap-2">
                    <span className="w-6 h-6 rounded-md bg-indigo-600 text-white font-bold text-xs flex items-center justify-center">
                      Q{idx + 1}
                    </span>
                    <Badge type="qtype">{q.question_type}</Badge>
                    <Badge type="difficulty">{q.difficulty || difficulty}</Badge>
                    <Badge type="bloom">{q.bloom_level || bloomLevel}</Badge>
                  </div>
                  <span className="text-xs font-semibold text-gray-600 bg-gray-100 px-2.5 py-1 rounded-md">
                    Max Score: {q.max_score || 1} pt(s)
                  </span>
                </div>

                {/* Question Prompt */}
                <div>
                  <h4 className="text-sm font-bold text-gray-900 leading-relaxed">
                    {q.question}
                  </h4>
                  {q.bloom_rationale && (
                    <p className="text-xs text-gray-500 italic mt-1">
                      Rationale: {q.bloom_rationale}
                    </p>
                  )}
                </div>

                {/* MCQ Options */}
                {q.question_type === 'mcq' && q.options && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                    {q.options.map((opt, optIdx) => {
                      const letter = String.fromCharCode(65 + optIdx);
                      const isCorrect =
                        q.correct_answer === letter ||
                        q.correct_answer === String(optIdx + 1) ||
                        opt.startsWith(`${letter}.`) ||
                        opt.startsWith(`${letter})`);

                      return (
                        <div
                          key={optIdx}
                          className={`p-3 rounded-lg border text-xs font-medium flex items-start gap-2.5 ${
                            isCorrect
                              ? 'bg-emerald-50 border-emerald-300 text-emerald-900 font-semibold'
                              : 'bg-gray-50 border-gray-200 text-gray-700'
                          }`}
                        >
                          <span
                            className={`w-5 h-5 rounded flex items-center justify-center shrink-0 text-[11px] font-bold ${
                              isCorrect
                                ? 'bg-emerald-600 text-white'
                                : 'bg-gray-200 text-gray-700'
                            }`}
                          >
                            {letter}
                          </span>
                          <span className="flex-1">{opt}</span>
                          {isCorrect && (
                            <span className="text-[10px] uppercase font-bold text-emerald-700 bg-emerald-100 px-1.5 py-0.5 rounded">
                              Correct
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Reference Answer & Explanation */}
                <div className="p-3 bg-slate-50 rounded-lg text-xs space-y-1.5 border border-slate-100">
                  <div>
                    <span className="font-semibold text-gray-700">Reference Answer: </span>
                    <span className="text-gray-900">{q.reference_answer || q.correct_answer}</span>
                  </div>
                  {q.explanation && (
                    <div>
                      <span className="font-semibold text-gray-700">Explanation: </span>
                      <span className="text-gray-600">{q.explanation}</span>
                    </div>
                  )}
                </div>

                {/* Rubric Table if short_answer or essay */}
                {q.rubric && Array.isArray(q.rubric) && q.rubric.length > 0 && (
                  <div className="text-xs space-y-1.5">
                    <span className="font-semibold text-gray-700 uppercase tracking-wider text-[11px]">
                      Grading Rubric
                    </span>
                    <div className="border border-gray-200 rounded-lg overflow-hidden">
                      <table className="w-full divide-y divide-gray-200 text-left">
                        <thead className="bg-gray-50">
                          <tr>
                            <th className="px-3 py-2 text-[11px] font-semibold text-gray-600">
                              Criterion
                            </th>
                            <th className="px-3 py-2 text-[11px] font-semibold text-gray-600">
                              Description
                            </th>
                            <th className="px-3 py-2 text-[11px] font-semibold text-gray-600 text-right">
                              Points
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100 bg-white">
                          {q.rubric.map((r, rIdx) => (
                            <tr key={rIdx}>
                              <td className="px-3 py-2 font-medium text-gray-900">
                                {r.criterion}
                              </td>
                              <td className="px-3 py-2 text-gray-600">{r.description}</td>
                              <td className="px-3 py-2 text-right font-bold text-indigo-600">
                                {r.points}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Source Citations */}
                {q.source_refs && q.source_refs.length > 0 && (
                  <div className="text-xs text-gray-500 pt-1 flex items-start gap-1.5">
                    <Quote className="w-3.5 h-3.5 text-indigo-500 shrink-0 mt-0.5" />
                    <div>
                      <span className="font-medium text-gray-700">Curriculum Grounding: </span>
                      {q.source_refs.map((ref, refIdx) => (
                        <span key={refIdx} className="italic">
                          "{ref.evidence_quote || ref.source || 'Curriculum Chunk'}"{' '}
                          {ref.chunk_id && `[Chunk: ${ref.chunk_id}]`}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default GenerateExam;
