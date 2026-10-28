import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  getDocuments,
  getDocumentLessons,
  generateExam,
  togglePublishExam,
} from '../../api/client';
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
  FileCheck,
  Eye,
  ListOrdered,
  ChevronDown,
  Quote,
  Library,
  AlertTriangle,
} from 'lucide-react';

const SELECTED_DOC_KEY = 'iqyas.selectedCurriculumId';

const readSelectedDocId = () => {
  const saved = localStorage.getItem(SELECTED_DOC_KEY);
  const parsed = saved ? Number.parseInt(saved, 10) : NaN;
  return Number.isInteger(parsed) ? parsed : null;
};

const GenerateExam = () => {
  // Textbook (document) state — must be selected first
  const [documents, setDocuments] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [docsError, setDocsError] = useState('');
  const [selectedCurriculum, setSelectedCurriculum] = useState('');

  // Lessons of the selected textbook
  const [lessons, setLessons] = useState([]);
  const [loadingLessons, setLoadingLessons] = useState(false);
  const [lessonsError, setLessonsError] = useState('');

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
  const [isPublished, setIsPublished] = useState(false);
  const [publishing, setPublishing] = useState(false);

  const handleQuickPublish = async () => {
    if (!generatedExam?.id) return;
    setPublishing(true);
    try {
      const res = await togglePublishExam(generatedExam.id, true);
      setIsPublished(res.is_published);
    } catch (err) {
      console.error('Failed to publish exam:', err);
      setError('فشل نشر الامتحان. حاول تاني.');
    } finally {
      setPublishing(false);
    }
  };

  const selectedCurriculumId = Number.parseInt(selectedCurriculum, 10);
  const selectedDocument = documents.find(
    (doc) => doc.id === selectedCurriculumId
  );
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
  const canGenerate = Boolean(selectedCurriculum && selectedLesson);

  // Load the professor's document library once; preselect the document that
  // is already marked as the exams source in the Document Library page.
  useEffect(() => {
    const fetchDocuments = async () => {
      setLoadingDocs(true);
      setDocsError('');
      try {
        const data = await getDocuments();
        const list = Array.isArray(data) ? data : [];
        setDocuments(list);
        const savedId = readSelectedDocId();
        if (savedId && list.some((doc) => doc.id === savedId)) {
          setSelectedCurriculum(String(savedId));
        } else if (list.length === 1) {
          setSelectedCurriculum(String(list[0].id));
        }
      } catch (err) {
        console.error('Failed to load document library:', err);
        setDocsError('فشل تحميل قائمة الكتب. تأكد إن السيرفر شغال وحاول تاني.');
      } finally {
        setLoadingDocs(false);
      }
    };

    fetchDocuments();
  }, []);

  // Whenever the textbook changes, drop any stale lesson selection and load
  // only the lessons that belong to the newly selected document.
  useEffect(() => {
    if (!selectedCurriculum) {
      setLessons([]);
      setSelectedLesson('');
      setLessonsError('');
      return;
    }

    let cancelled = false;
    const fetchLessons = async () => {
      setLoadingLessons(true);
      setLessonsError('');
      setSelectedLesson('');
      try {
        const data = await getDocumentLessons(selectedCurriculumId);
        const list = Array.isArray(data) ? data : data?.lessons || [];
        if (cancelled) return;
        setLessons(list);
        if (list.length > 0) {
          const first = list[0];
          const firstId = first.lesson_id || first.id || first.title;
          setSelectedLesson(String(firstId));
        }
      } catch (err) {
        console.error('Failed to load lessons for document:', err);
        if (cancelled) return;
        setLessons([]);
        setSelectedLesson('');
        setLessonsError(
          'فشل تحميل دروس الكتاب المختار. حاول تغيير الكتاب أو إعادة المحاولة.'
        );
      } finally {
        if (!cancelled) setLoadingLessons(false);
      }
    };

    fetchLessons();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCurriculum]);

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

    if (!selectedCurriculum || !selectedLesson) {
      setError('لازم تختار الكتاب والدرس الأول قبل توليد الامتحان.');
      return;
    }

    const activeTypes = Object.keys(questionTypes).filter((t) => questionTypes[t]);
    if (activeTypes.length === 0) {
      setError('اختار نوع سؤال واحد على الأقل (اختياري / إجابة قصيرة / مقالي).');
      return;
    }

    setGenerating(true);
    setGeneratedExam(null);
    setLastRequestedCount(null);

    const requestCount = Number.parseInt(numQuestions, 10) || 3;
    const payload = buildExamPayload({
      curriculumId: selectedCurriculumId,
      title,
      selectedLesson,
      topic,
      difficulty,
      bloomLevel,
      questionTypes: activeTypes,
      numQuestions,
      lessonTitle:
        selectedLessonDetails?.title ||
        selectedLessonDetails?.lesson_title ||
        selectedLessonDetails?.name,
    });

    try {
      const response = await generateExam(payload);
      assertRequestedQuestionCount(response, requestCount);
      setGeneratedExam(response);
      setLastRequestedCount(requestCount);
      setIsPublished(Boolean(response.is_published));
    } catch (err) {
      console.error('Exam generation failed:', err);
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        'فشل توليد الامتحان. تأكد إن المنهج متفهرس وأن مزوّد الذكاء الاصطناعي متظبوط.';
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* Title */}
      <div className="relative">
        <span className="code-chip absolute -top-3 end-0 rotate-2 hidden md:inline-block">def generate_exam(): ✨</span>
        <h1 className="font-display text-3xl md:text-4xl text-ink">إنشاء امتحان ✨</h1>
        <p className="text-sm text-cocoa-500 mt-1 leading-relaxed">
          اختار الكتاب الأول، وبعدين الدرس والمستوى — الأسئلة بتتولّد بالإنجليزي من محتوى الكتاب المختار بس.
        </p>
      </div>

      {error && (
        <Alert
          type="error"
          title="مشكلة في التوليد"
          message={error}
          onClose={() => setError('')}
        />
      )}

      {/* Main Form */}
      <Card
        title="مواصفات الامتحان"
        subtitle="اضبط مولّد الأسئلة الذكي"
      >
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Step 1: Textbook selection (required before lessons) */}
          <div className="p-4 bg-gold-50/60 border-2 border-gold-300/70 rounded-2xl">
            <div className="flex items-center gap-2 mb-2">
              <span className="w-6 h-6 rounded-lg bg-gold-500 text-ink text-xs font-extrabold flex items-center justify-center">١</span>
              <label className="block text-[13px] font-bold text-cocoa-800">
                الكتاب المختار (مصدر الامتحان)
              </label>
            </div>
            {loadingDocs ? (
              <div className="h-10 bg-sand rounded-xl animate-pulse" />
            ) : docsError ? (
              <Alert type="error" title="خطأ في تحميل الكتب" message={docsError} />
            ) : documents.length === 0 ? (
              <div className="flex items-start gap-3 p-3 bg-cream rounded-xl border border-sand">
                <AlertTriangle className="w-5 h-5 text-gold-700 shrink-0 mt-0.5" />
                <div className="text-sm">
                  <p className="font-bold text-cocoa-800">مفيش كتب في مكتبتك لسه.</p>
                  <p className="text-xs text-cocoa-500 mt-1">
                    ارفع منهج PDF الأول من{' '}
                    <Link to="/professor/curriculum" className="font-bold text-clay-700 underline">
                      مكتبة المناهج
                    </Link>{' '}
                    وبعدين ارجع هنا لتوليد الامتحان.
                  </p>
                </div>
              </div>
            ) : (
              <div className="relative">
                <select
                  value={selectedCurriculum}
                  onChange={(e) => setSelectedCurriculum(e.target.value)}
                  className="w-full px-3.5 py-2.5 text-sm font-bold bg-white border-2 border-gold-400 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 appearance-none pe-10 outline-none transition"
                  required
                >
                  <option value="">— اختار الكتاب —</option>
                  {documents.map((doc) => (
                    <option key={doc.id} value={String(doc.id)}>
                      {doc.filename}
                    </option>
                  ))}
                </select>
                <Library className="w-4 h-4 text-gold-600 absolute left-3 top-3 pointer-events-none" />
              </div>
            )}
            {selectedDocument && (
              <p className="text-xs text-gold-700 mt-2 font-bold flex items-center gap-1.5">
                <BookOpen className="w-3.5 h-3.5" />
                مصدر الامتحانات الحالي: {selectedDocument.filename}
                {Number.isInteger(selectedDocument.lesson_count) &&
                  ` • ${selectedDocument.lesson_count} درس`}
              </p>
            )}
          </div>

          {/* Step 2: Lesson selection (scoped to the selected textbook) */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="md:col-span-2">
              <div className="flex items-center gap-2 mb-1.5">
                <span className="w-6 h-6 rounded-lg bg-clay-700 text-white text-xs font-extrabold flex items-center justify-center">٢</span>
                <label className="block text-[13px] font-bold text-cocoa-800">
                  الدرس / الفصل من الكتاب المختار
                </label>
              </div>
              {!selectedCurriculum ? (
                <p className="text-xs text-cocoa-500 bg-cream border border-sand rounded-xl px-3.5 py-2.5">
                  اختار الكتاب الأول وهتظهر دروسه هنا.
                </p>
              ) : loadingLessons ? (
                <div className="h-10 bg-sand rounded-xl animate-pulse" />
              ) : lessonsError ? (
                <Alert type="error" title="خطأ في تحميل الدروس" message={lessonsError} />
              ) : lessons.length === 0 ? (
                <p className="text-xs text-cocoa-500 bg-cream border border-sand rounded-xl px-3.5 py-2.5">
                  مفيش دروس متفهرسة في الكتاب ده. جرّب كتاب تاني أو أعد رفع الملف.
                </p>
              ) : (
                <div className="relative">
                  <select
                    value={selectedLesson}
                    onChange={(e) => setSelectedLesson(e.target.value)}
                    className="w-full px-3.5 py-2.5 text-sm bg-white border-2 border-cocoa-300/60 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 appearance-none pe-10 outline-none transition"
                    required
                  >
                    {lessons.map((lesson, idx) => {
                      const val = lesson.lesson_id || lesson.id;
                      const label = lesson.lesson_title || lesson.title || lesson.lesson_id || `درس ${idx + 1}`;
                      return (
                        <option key={String(val)} value={String(val)}>
                          {label}
                        </option>
                      );
                    })}
                  </select>
                  <ChevronDown className="w-4 h-4 text-cocoa-300 absolute left-3 top-3 pointer-events-none" />
                </div>
              )}
            </div>

            {/* Exam Title (Optional) */}
            <div className="md:col-span-2">
              <label className="block text-[13px] font-bold text-cocoa-800 mb-1.5">
                عنوان الامتحان (اختياري)
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="مثال: Midterm — Chapter 2 Foundations"
                className="w-full px-3.5 py-2.5 text-sm bg-white border-2 border-cocoa-300/60 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 transition outline-none"
              />
            </div>

            {/* Target Topic Input */}
            <div>
              <label className="block text-[13px] font-bold text-cocoa-800 mb-1.5">
                الموضوع المستهدف (اختياري)
              </label>
              <input
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="مثال: Loops & Conditionals"
                className="w-full px-3.5 py-2.5 text-sm bg-white border-2 border-cocoa-300/60 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 transition outline-none"
              />
            </div>

            {/* Difficulty select */}
            <div>
              <label className="block text-[13px] font-bold text-cocoa-800 mb-1.5">
                مستوى الصعوبة
              </label>
              <select
                value={difficulty}
                onChange={(e) => setDifficulty(e.target.value)}
                className="w-full px-3.5 py-2.5 text-sm bg-white border-2 border-cocoa-300/60 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 transition outline-none"
              >
                <option value="easy">سهل (مفاهيم أساسية وتعريفات)</option>
                <option value="medium">متوسط (تطبيق وشرح)</option>
                <option value="hard">صعب (تحليل وتركيب نقدي)</option>
              </select>
            </div>

            {/* Bloom's Taxonomy Level */}
            <div>
              <label className="block text-[13px] font-bold text-cocoa-800 mb-1.5">
                مستوى بلوم المعرفي
              </label>
              <select
                value={bloomLevel}
                onChange={(e) => setBloomLevel(e.target.value)}
                className="w-full px-3.5 py-2.5 text-sm bg-white border-2 border-cocoa-300/60 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 transition outline-none"
              >
                <option value="remember">تذكّر (استرجاع الحقائق)</option>
                <option value="understand">فهم (شرح الأفكار والمفاهيم)</option>
                <option value="apply">تطبيق (استخدام المعلومة في مواقف جديدة)</option>
                <option value="analyze">تحليل (ربط الأفكار ببعضها)</option>
                <option value="evaluate">تقييم (إبداء الرأي والدفاع عنه)</option>
                <option value="create">إبداع (إنتاج عمل جديد)</option>
              </select>
            </div>

            {/* Number of Questions */}
            <div>
              <label className="block text-[13px] font-bold text-cocoa-800 mb-1.5">
                عدد الأسئلة (١ - ٢٥)
              </label>
              <input
                type="number"
                min="1"
                max="25"
                value={numQuestions}
                onChange={(e) => setNumQuestions(e.target.value)}
                className="w-full px-3.5 py-2.5 text-sm bg-white border-2 border-cocoa-300/60 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 transition outline-none"
                required
              />
              <p className="text-xs text-cocoa-500 mt-1.5">
                {lessonChunkCount === null
                  ? 'عدد أجزاء الدرس غير متاح.'
                  : `الدرس فيه ${lessonChunkCount} جزء متاح للتوليد.`}
              </p>
              {lessonChunkCount !== null && requestedQuestionCount > lessonChunkCount && (
                <p className="text-xs text-gold-700 mt-1" role="alert">
                  طلبت {requestedQuestionCount} سؤال، لكن الدرس فيه {lessonChunkCount} جزء بس — ممكن تكرر نفس الجزء في أكتر من سؤال.
                </p>
              )}
            </div>

            {/* Question Types checkboxes */}
            <div>
              <label className="block text-[13px] font-bold text-cocoa-800 mb-1.5">
                أنواع الأسئلة المسموحة
              </label>
              <div className="flex items-center gap-4 pt-1.5 flex-wrap">
                <label className="inline-flex items-center gap-2 cursor-pointer text-sm font-bold text-cocoa-800">
                  <input
                    type="checkbox"
                    checked={questionTypes.mcq}
                    onChange={() => handleTypeChange('mcq')}
                    className="w-4 h-4 accent-clay-700 rounded"
                  />
                  <span>اختيار متعدد</span>
                </label>
                <label className="inline-flex items-center gap-2 cursor-pointer text-sm font-bold text-cocoa-800">
                  <input
                    type="checkbox"
                    checked={questionTypes.short_answer}
                    onChange={() => handleTypeChange('short_answer')}
                    className="w-4 h-4 accent-clay-700 rounded"
                  />
                  <span>إجابة قصيرة</span>
                </label>
                <label className="inline-flex items-center gap-2 cursor-pointer text-sm font-bold text-cocoa-800">
                  <input
                    type="checkbox"
                    checked={questionTypes.essay}
                    onChange={() => handleTypeChange('essay')}
                    className="w-4 h-4 accent-clay-700 rounded"
                  />
                  <span>مقالي</span>
                </label>
              </div>
            </div>
          </div>

          <div className="pt-4 border-t border-sand flex items-center justify-between gap-4">
            <p className="text-xs text-cocoa-500">
              ⚡ التوليد بياخد من ١٥ لـ ٤٥ ثانية لأن الأسئلة بتتراجع ضد مصادر المنهج.
            </p>
            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={generating}
              icon={Sparkles}
              disabled={!canGenerate}
              className="btn-cut shrink-0"
            >
              {generating ? 'جاري التوليد...' : 'ولّد الامتحان'}
            </Button>
          </div>
        </form>
      </Card>

      {/* Generation in progress banner */}
      {generating && (
        <Card className="text-center py-10 bg-gold-50/50 border-gold-200">
          <LoadingSpinner size="lg" message="الذكاء الاصطناعي بيصيغ الأسئلة من محتوى المنهج..." />
          <p className="text-xs text-gold-700 mt-2">
            التحقق من المصادر &bull; صياغة نماذج التصحيح &bull; ترتيب الاختيارات
          </p>
        </Card>
      )}

      {/* Generated Exam Preview Section */}
      {generatedExam && (
        <div className="space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-5 bg-teal-50 border-2 border-teal-200 rounded-2xl">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl rounded-br-sm bg-teal-700 text-white flex items-center justify-center shrink-0 rotate-3">
                <FileCheck className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-base font-extrabold text-teal-900">
                  الامتحان اتولّد بنجاح! 🎉
                </h3>
                <p className="text-xs text-teal-700">
                  طلبت: {lastRequestedCount} &bull; اتولّد: {generatedQuestions.length}{' '}
                  &bull; إجمالي الدرجات: {generatedExam.total_points || '—'}
                </p>
                {selectedDocument && (
                  <p className="text-xs text-teal-800 font-bold mt-0.5 flex items-center gap-1">
                    <BookOpen className="w-3.5 h-3.5" />
                    الكتاب: {selectedDocument.filename}
                    {selectedLessonDetails && (
                      <>
                        {' '}• الدرس:{' '}
                        {selectedLessonDetails.lesson_title ||
                          selectedLessonDetails.title ||
                          selectedLesson}
                      </>
                    )}
                  </p>
                )}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {generatedExam.id && (
                <Button
                  variant={isPublished ? "outline" : "primary"}
                  size="sm"
                  loading={publishing}
                  onClick={handleQuickPublish}
                  className={!isPublished ? "bg-teal-700 hover:bg-teal-800 text-white shadow-sm" : ""}
                >
                  {isPublished ? "✓ منشور للطلبة" : "انشر للطلبة دلوقتي"}
                </Button>
              )}
              <Link to="/professor/exams">
                <Button variant="secondary" size="sm">
                  كل الامتحانات
                </Button>
              </Link>
              {generatedExam.id && (
                <Link to={`/professor/exams/${generatedExam.id}`}>
                  <Button variant="outline" size="sm" icon={Eye}>
                    التفاصيل
                  </Button>
                </Link>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-sand bg-paper p-4 text-sm text-cocoa-800">
            <p>
              نصوص أسئلة فريدة: {uniqueQuestionCount} &bull; أجزاء مصدر فريدة:{' '}
              {uniqueCitedChunkCount}
            </p>
            {generationWarnings.length > 0 && (
              <ul className="mt-2 list-disc ps-5 text-gold-700" role="status">
                {generationWarnings.map((warning, index) => (
                  <li key={`${index}-${warning}`}>{warning}</li>
                ))}
              </ul>
            )}
          </div>

          {/* Render Question Previews */}
          <div className="space-y-4">
            <h3 className="text-lg font-extrabold text-ink flex items-center gap-2">
              <ListOrdered className="w-5 h-5 text-clay-600" />
              معاينة الأسئلة المتولّدة
            </h3>

            {generatedQuestions.map((q, idx) => (
              <Card key={idx} className="p-6 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-sand pb-3">
                  <div className="flex items-center gap-2">
                    <span className="w-7 h-7 rounded-lg rounded-br-sm bg-gradient-to-b from-clay-600 to-clay-800 text-white font-bold text-xs flex items-center justify-center">
                      Q{idx + 1}
                    </span>
                    <Badge type="qtype">{q.question_type}</Badge>
                    <Badge type="difficulty">{q.difficulty || difficulty}</Badge>
                    <Badge type="bloom">{q.bloom_level || bloomLevel}</Badge>
                  </div>
                  <span className="text-xs font-bold text-cocoa-800 bg-cream px-2.5 py-1 rounded-lg border border-sand">
                    الدرجة: {q.max_score || 1}
                  </span>
                </div>

                {/* Question Prompt */}
                <div>
                  <h4 className="text-sm font-bold text-ink leading-relaxed" dir="auto">
                    {q.question}
                  </h4>
                  {q.bloom_rationale && (
                    <p className="text-xs text-cocoa-500 italic mt-1" dir="auto">
                      السبب: {q.bloom_rationale}
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
                          className={`p-3 rounded-xl border text-xs font-bold flex items-start gap-2.5 ${
                            isCorrect
                              ? 'bg-teal-50 border-teal-300 text-teal-900'
                              : 'bg-cream border-sand text-cocoa-800'
                          }`}
                          dir="auto"
                        >
                          <span
                            className={`w-5 h-5 rounded-md flex items-center justify-center shrink-0 text-[11px] font-bold ${
                              isCorrect
                                ? 'bg-teal-700 text-white'
                                : 'bg-sand text-cocoa-800'
                            }`}
                          >
                            {letter}
                          </span>
                          <span className="flex-1">{opt}</span>
                          {isCorrect && (
                            <span className="text-[10px] font-bold text-teal-700 bg-teal-100 px-1.5 py-0.5 rounded">
                              الإجابة ✓
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Reference Answer & Explanation */}
                <div className="p-3 bg-cream rounded-xl text-xs space-y-1.5 border border-sand">
                  <div>
                    <span className="font-bold text-cocoa-800">الإجابة النموذجية: </span>
                    <span className="text-ink" dir="auto">{q.reference_answer || q.correct_answer}</span>
                  </div>
                  {q.explanation && (
                    <div>
                      <span className="font-bold text-cocoa-800">الشرح: </span>
                      <span className="text-cocoa-500" dir="auto">{q.explanation}</span>
                    </div>
                  )}
                </div>

                {/* Rubric Table if short_answer or essay */}
                {q.rubric && Array.isArray(q.rubric) && q.rubric.length > 0 && (
                  <div className="text-xs space-y-1.5">
                    <span className="font-bold text-cocoa-800 text-[12px]">
                      نموذج التصحيح
                    </span>
                    <div className="border border-sand rounded-xl overflow-hidden">
                      <table className="w-full divide-y divide-sand text-right">
                        <thead className="bg-cream">
                          <tr>
                            <th className="px-3 py-2 text-[11px] font-bold text-cocoa-500">
                              المعيار
                            </th>
                            <th className="px-3 py-2 text-[11px] font-bold text-cocoa-500">
                              الوصف
                            </th>
                            <th className="px-3 py-2 text-[11px] font-bold text-cocoa-500">
                              الدرجات
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-sand bg-paper">
                          {q.rubric.map((r, rIdx) => (
                            <tr key={rIdx}>
                              <td className="px-3 py-2 font-bold text-ink" dir="auto">
                                {r.criterion}
                              </td>
                              <td className="px-3 py-2 text-cocoa-500" dir="auto">{r.description}</td>
                              <td className="px-3 py-2 font-bold text-clay-700">
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
                  <div className="text-xs text-cocoa-500 pt-1 flex items-start gap-1.5">
                    <Quote className="w-3.5 h-3.5 text-gold-600 shrink-0 mt-0.5" />
                    <div>
                      <span className="font-bold text-cocoa-800">مصدر من المنهج: </span>
                      {q.source_refs.map((ref, refIdx) => (
                        <span key={refIdx} className="italic" dir="auto">
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
