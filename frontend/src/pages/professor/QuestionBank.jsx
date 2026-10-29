import React, { useState, useEffect, useCallback } from 'react';
import {
  Database,
  Search,
  Filter,
  Plus,
  Upload,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Eye,
  Edit3,
  Layers,
  Sparkles,
  FileText,
  HelpCircle,
  RefreshCw,
  Award,
} from 'lucide-react';
import {
  getQuestionBank,
  getQuestionBankSummary,
  getLearningReadinessStats,
  classifyQuestion,
  importQuestionBank,
  updateQuestionBankItem,
  approveQuestionBankItem,
  rejectQuestionBankItem,
  getCleanedDataset,
  getCleanedDatasetProvenance,
} from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import Alert from '../../components/ui/Alert';
import Modal from '../../components/ui/Modal';
import LoadingSpinner from '../../components/ui/LoadingSpinner';

const BLOOM_TRANSLATIONS = {
  remember: 'تذكر',
  understand: 'فهم',
  apply: 'تطبيق',
  analyze: 'تحليل',
  evaluate: 'تقييم',
  create: 'ابتكار',
  unknown: 'غير محدد',
};

const DIFFICULTY_TRANSLATIONS = {
  easy: 'سهل',
  medium: 'متوسط',
  hard: 'صعب',
  unknown: 'غير محدد',
};

const STATUS_CONFIGS = {
  approved: { label: 'معتمد', badge: 'success', icon: CheckCircle2, color: 'text-emerald-700 bg-emerald-50 border-emerald-200' },
  needs_review: { label: 'يحتاج مراجعة', badge: 'warning', icon: AlertTriangle, color: 'text-amber-700 bg-amber-50 border-amber-200' },
  pending_review: { label: 'بانتظار المراجعة', badge: 'info', icon: Clock, color: 'text-blue-700 bg-blue-50 border-blue-200' },
  rejected: { label: 'مرفوض', badge: 'danger', icon: XCircle, color: 'text-rose-700 bg-rose-50 border-rose-200' },
};

const QuestionBank = () => {
  // State: Listing & Pagination
  const [questions, setQuestions] = useState([]);
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(15);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [learningStats, setLearningStats] = useState(null);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  // Filters
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [difficultyFilter, setDifficultyFilter] = useState('');
  const [bloomFilter, setBloomFilter] = useState('');

  // Modals
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [selectedQuestion, setSelectedQuestion] = useState(null);

  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importFile, setImportFile] = useState(null);
  const [autoClassifyOnImport, setAutoClassifyOnImport] = useState(true);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);

  const [addModalOpen, setAddModalOpen] = useState(false);
  const [modalError, setModalError] = useState(null);
  const [manualQuestion, setManualQuestion] = useState({
    question_text: '',
    question_type: 'mcq',
    options: ['', '', '', ''],
    correct_option: '',
    correct_answer: '',
    explanation: '',
  });
  const [classifying, setClassifying] = useState(false);
  const [previewClassification, setPreviewClassification] = useState(null);

  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewAction, setReviewAction] = useState('approve'); // 'approve' | 'reject' | 'edit'
  const [reviewNotes, setReviewNotes] = useState('');
  const [editFormData, setEditFormData] = useState({
    bloom_level: '',
    difficulty: '',
    lesson: '',
    correct_answer: '',
  });

  // Active View Tab: 'production' | 'cleaned_dataset'
  const [activeTab, setActiveTab] = useState('production');

  // Cleaned Dataset State
  const [cleanedQuestions, setCleanedQuestions] = useState([]);
  const [cleanedProvenance, setCleanedProvenance] = useState(null);
  const [cleanedFiltersAvailable, setCleanedFiltersAvailable] = useState({});
  const [cleanedLoading, setCleanedLoading] = useState(false);
  const [cleanedError, setCleanedError] = useState(null);
  const [cleanedPage, setCleanedPage] = useState(1);
  const [cleanedPageSize] = useState(15);
  const [cleanedTotal, setCleanedTotal] = useState(0);
  const [cleanedTotalPages, setCleanedTotalPages] = useState(1);
  const [cleanedLoadedOnce, setCleanedLoadedOnce] = useState(false);

  // Cleaned Dataset Filters
  const [cleanedSearch, setCleanedSearch] = useState('');
  const [cleanedTypeFilter, setCleanedTypeFilter] = useState('');
  const [cleanedChapterFilter, setCleanedChapterFilter] = useState('');
  const [cleanedLessonFilter, setCleanedLessonFilter] = useState('');
  const [cleanedVerificationFilter, setCleanedVerificationFilter] = useState('');

  // Cleaned Question Detail Modal & UI State
  const [selectedCleanedQuestion, setSelectedCleanedQuestion] = useState(null);
  const [cleanedDetailModalOpen, setCleanedDetailModalOpen] = useState(false);
  const [copiedHash, setCopiedHash] = useState(false);

  // Fetch Questions
  const fetchQuestions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {
        page,
        page_size: pageSize,
      };
      if (search.trim()) params.search = search.trim();
      if (statusFilter) params.status = statusFilter;
      if (difficultyFilter) params.difficulty = difficultyFilter;
      if (bloomFilter) params.bloom_level = bloomFilter;

      const data = await getQuestionBank(params);
      setQuestions(data.items || []);
      setTotalQuestions(data.total || 0);
      setTotalPages(data.total_pages || 1);
    } catch (err) {
      setError(err?.response?.data?.detail || 'فشل في تحميل بنك الأسئلة.');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search, statusFilter, difficultyFilter, bloomFilter]);

  // Fetch Statistics
  const fetchStats = async () => {
    try {
      const [s, l] = await Promise.all([
        getQuestionBankSummary(),
        getLearningReadinessStats(),
      ]);
      setStats(s);
      setLearningStats(l);
    } catch (err) {
      console.error('Failed to load stats:', err);
    }
  };

  useEffect(() => {
    fetchQuestions();
  }, [fetchQuestions]);

  useEffect(() => {
    fetchStats();
  }, []);

  // Fetch Cleaned Dataset (Read-only, Isolated)
  const fetchCleanedDataset = useCallback(async () => {
    setCleanedLoading(true);
    setCleanedError(null);
    try {
      const params = {
        page: cleanedPage,
        page_size: cleanedPageSize,
      };
      if (cleanedSearch.trim()) params.search = cleanedSearch.trim();
      if (cleanedTypeFilter) params.question_type = cleanedTypeFilter;
      if (cleanedChapterFilter) params.chapter = cleanedChapterFilter;
      if (cleanedLessonFilter) params.lesson = cleanedLessonFilter;
      if (cleanedVerificationFilter) params.verification_status = cleanedVerificationFilter;

      const data = await getCleanedDataset(params);
      setCleanedQuestions(data.items || []);
      setCleanedProvenance(data.provenance || null);
      setCleanedFiltersAvailable(data.filters_available || {});
      setCleanedTotal(data.total || 0);
      setCleanedTotalPages(data.total_pages || 1);
      setCleanedLoadedOnce(true);
    } catch (err) {
      setCleanedError(err?.response?.data?.detail || 'فشل في تحميل مجموعة البيانات المنقحة.');
    } finally {
      setCleanedLoading(false);
    }
  }, [cleanedPage, cleanedPageSize, cleanedSearch, cleanedTypeFilter, cleanedChapterFilter, cleanedLessonFilter, cleanedVerificationFilter]);

  useEffect(() => {
    if (activeTab === 'cleaned_dataset') {
      fetchCleanedDataset();
    }
  }, [activeTab, fetchCleanedDataset]);

  const handleCleanedSearchSubmit = (e) => {
    e.preventDefault();
    setCleanedPage(1);
    fetchCleanedDataset();
  };

  const handleCopyHash = (hash) => {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(hash);
      setCopiedHash(true);
      setTimeout(() => setCopiedHash(false), 2000);
    }
  };


  // Handle Search submit
  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setPage(1);
    fetchQuestions();
  };

  // Handle Review: Approve
  const handleApprove = async (question) => {
    setSelectedQuestion(question);
    setEditFormData({
      bloom_level: question.bloom_level || 'Understand',
      difficulty: question.difficulty || 'Medium',
      lesson: question.lesson || '',
      correct_answer: question.correct_answer || '',
    });
    setReviewAction('approve');
    setReviewNotes('');
    setReviewModalOpen(true);
  };

  // Handle Review: Reject
  const handleReject = async (question) => {
    setSelectedQuestion(question);
    setReviewAction('reject');
    setReviewNotes('');
    setReviewModalOpen(true);
  };

  // Submit Review Modal
  const submitReviewDecision = async () => {
    if (!selectedQuestion) return;
    setError(null);
    try {
      if (reviewAction === 'approve') {
        const corrections = {
          bloom_level: editFormData.bloom_level,
          difficulty: editFormData.difficulty,
          lesson: editFormData.lesson,
          correct_answer: editFormData.correct_answer,
        };
        await approveQuestionBankItem(selectedQuestion.question_id, {
          corrections,
          notes: reviewNotes,
        });
        setSuccessMsg(`تم اعتماد السؤال ${selectedQuestion.question_id} بنجاح وحفظ التصحيحات.`);
      } else if (reviewAction === 'reject') {
        await rejectQuestionBankItem(selectedQuestion.question_id, {
          notes: reviewNotes,
        });
        setSuccessMsg(`تم رفض السؤال ${selectedQuestion.question_id}.`);
      } else if (reviewAction === 'edit') {
        await updateQuestionBankItem(selectedQuestion.question_id, {
          ...editFormData,
        });
        setSuccessMsg(`تم تحديث بيانات السؤال ${selectedQuestion.question_id}.`);
      }

      setReviewModalOpen(false);
      fetchQuestions();
      fetchStats();
    } catch (err) {
      setError(err?.response?.data?.detail || 'فشلت عملية المراجعة.');
    }
  };

  // Handle Import
  const handleImportSubmit = async (e) => {
    e.preventDefault();
    if (!importFile) return;
    setImporting(true);
    setImportResult(null);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file', importFile);
      formData.append('auto_classify', autoClassifyOnImport ? 'true' : 'false');
      formData.append('skip_embedding', 'false');

      const res = await importQuestionBank(formData);
      setImportResult(res);
      setSuccessMsg(`تم استيراد ${res.valid_count || 0} سؤالاً بنجاح.`);
      fetchQuestions();
      fetchStats();
    } catch (err) {
      setError(err?.response?.data?.detail || 'فشل استيراد الملف.');
    } finally {
      setImporting(false);
    }
  };

  // Handle Manual Question On-demand classification
  const handleClassifyManual = async () => {
    setModalError(null);
    if (!manualQuestion.question_text.trim()) {
      setModalError('يرجى إدخال نص السؤال أولاً.');
      return;
    }
    let derivedOpt = manualQuestion.correct_option;
    let derivedAns = manualQuestion.correct_answer.trim();

    if (manualQuestion.question_type === 'mcq') {
      const filledOptions = (manualQuestion.options || []).map((o) => o.trim()).filter(Boolean);
      if (filledOptions.length !== 4) {
        setModalError('سؤال الاختيار من متعدد يتطلب إدخال 4 خيارات إجابة كاملة.');
        return;
      }
      // If correct option wasn't explicitly clicked, see if correct_answer matches an option
      if (!derivedOpt && derivedAns) {
        const found = filledOptions.findIndex(o => o.toLowerCase() === derivedAns.toLowerCase());
        if (found >= 0) {
          derivedOpt = ['A', 'B', 'C', 'D'][found];
        }
      }
      // If correct option was clicked, sync answer text
      if (derivedOpt && !derivedAns) {
        const optIdx = ['A', 'B', 'C', 'D'].indexOf(derivedOpt);
        if (optIdx >= 0 && manualQuestion.options[optIdx]) {
          derivedAns = manualQuestion.options[optIdx].trim();
        }
      }
    }
    setClassifying(true);
    try {
      const payload = {
        question_text: manualQuestion.question_text.trim(),
        question_type: manualQuestion.question_type,
        options: manualQuestion.question_type === 'mcq' ? manualQuestion.options.map((o) => o.trim()) : [],
        correct_option: manualQuestion.question_type === 'mcq' ? (derivedOpt || null) : null,
        correct_answer: derivedAns,
        explanation: manualQuestion.explanation ? manualQuestion.explanation.trim() : null,
        persist: false,
      };
      const res = await classifyQuestion(payload);
      setPreviewClassification(res);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
        ? detail.map((d) => d.msg || d.detail || JSON.stringify(d)).join(', ')
        : 'فشل التحليل والتصنيف التلقائي للسؤال.';
      setModalError(msg);
    } finally {
      setClassifying(false);
    }
  };

  // Save Manual Question
  const handleSaveManualQuestion = async () => {
    setModalError(null);
    if (!manualQuestion.question_text.trim()) {
      setModalError('نص السؤال مطلوب.');
      return;
    }
    if (manualQuestion.question_type === 'mcq') {
      const filledOptions = (manualQuestion.options || []).map((o) => o.trim()).filter(Boolean);
      if (filledOptions.length !== 4) {
        setModalError('سؤال الاختيار من متعدد يتطلب إدخال 4 خيارات إجابة كاملة.');
        return;
      }
      if (!manualQuestion.correct_option) {
        setModalError('يرجى تحديد الخيار الصحيح (A, B, C, أو D) صراحة قبل حفظ السؤال.');
        return;
      }
    } else {
      if (!manualQuestion.correct_answer.trim()) {
        setModalError('يرجى إدخال الإجابة النموذجية للسؤال قبل الحفظ.');
        return;
      }
    }
    setLoading(true);
    try {
      const optIdx = ['A', 'B', 'C', 'D'].indexOf(manualQuestion.correct_option);
      const derivedCorrectAnswer = manualQuestion.question_type === 'mcq'
        ? (optIdx >= 0 ? manualQuestion.options[optIdx]?.trim() : '')
        : manualQuestion.correct_answer.trim();

      if (manualQuestion.question_type === 'mcq' && !derivedCorrectAnswer) {
        setModalError('نص الخيار الصحيح المحدد فارغ. يرجى كتابة نص الخيار.');
        setLoading(false);
        return;
      }

      const payload = {
        question_text: manualQuestion.question_text.trim(),
        question_type: manualQuestion.question_type,
        options: manualQuestion.question_type === 'mcq' ? manualQuestion.options.map((o) => o.trim()) : [],
        correct_option: manualQuestion.question_type === 'mcq' ? manualQuestion.correct_option : null,
        correct_answer: derivedCorrectAnswer,
        explanation: manualQuestion.explanation ? manualQuestion.explanation.trim() : null,
        persist: true,
      };
      await classifyQuestion(payload);
      setSuccessMsg('تم حفظ وتصنيف السؤال بنجاح في بنك الأسئلة.');
      setAddModalOpen(false);
      setManualQuestion({
        question_text: '',
        question_type: 'mcq',
        options: ['', '', '', ''],
        correct_option: '',
        correct_answer: '',
        explanation: '',
      });
      setPreviewClassification(null);
      fetchQuestions();
      fetchStats();
    } catch (err) {
      setModalError(err?.response?.data?.detail || 'فشل حفظ السؤال في بنك الأسئلة.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto px-4 sm:px-6 py-6" dir="rtl">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-cocoa-100">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gold-500/10 text-gold-600 flex items-center justify-center font-bold">
              <Database className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-2xl font-bold font-display text-cocoa-900">بنك الأسئلة الذكي</h1>
              <p className="text-sm text-cocoa-600">
                تصنيف آلي مبني على المنهج، مراجعة دقيقة، وتعلّم مستمر من اعتمادات المدرس
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <Button
            variant="outline"
            className="flex items-center gap-2"
            onClick={() => setImportModalOpen(true)}
          >
            <Upload className="w-4 h-4" />
            <span>استيراد ملف أسئلة</span>
          </Button>
          <Button
            variant="primary"
            className="flex items-center gap-2 shadow-warm"
            onClick={() => {
              setPreviewClassification(null);
              setAddModalOpen(true);
            }}
          >
            <Plus className="w-4 h-4" />
            <span>إضافة سؤال يدوياً</span>
          </Button>
        </div>
      </div>

      {/* View Switcher: Production Question Bank vs Cleaned Dataset */}
      <div className="flex border-b border-cocoa-200">
        <button
          type="button"
          onClick={() => setActiveTab('production')}
          className={`flex items-center gap-2 px-5 py-3 border-b-2 font-medium text-sm transition-colors ${
            activeTab === 'production'
              ? 'border-gold-500 text-cocoa-900 font-bold bg-gold-50/40'
              : 'border-transparent text-cocoa-500 hover:text-cocoa-700 hover:border-cocoa-300'
          }`}
        >
          <Database className="w-4 h-4" />
          <span>بنك الأسئلة المعتمد (الإنتاجي)</span>
          {stats && (
            <span className="px-2 py-0.5 text-xs rounded-full bg-cocoa-100 text-cocoa-700 font-semibold">
              {stats.total_questions || 0}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => {
            setActiveTab('cleaned_dataset');
            if (!cleanedLoadedOnce) {
              fetchCleanedDataset();
            }
          }}
          className={`flex items-center gap-2 px-5 py-3 border-b-2 font-medium text-sm transition-colors ${
            activeTab === 'cleaned_dataset'
              ? 'border-gold-500 text-cocoa-900 font-bold bg-gold-50/40'
              : 'border-transparent text-cocoa-500 hover:text-cocoa-700 hover:border-cocoa-300'
          }`}
        >
          <FileText className="w-4 h-4" />
          <span>مجموعة البيانات المنقحة (Cleaned Dataset)</span>
          <span className="px-2 py-0.5 text-xs rounded-full bg-emerald-100 text-emerald-800 font-semibold">
            {cleanedProvenance ? `${cleanedProvenance.valid_rows} سؤال` : '317 سؤال'}
          </span>
        </button>
      </div>

      {/* Alerts */}
      {error && (
        <Alert variant="danger" dismissible onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}
      {successMsg && (
        <Alert variant="success" dismissible onDismiss={() => setSuccessMsg(null)}>
          {successMsg}
        </Alert>
      )}

{activeTab === 'production' && (
        <>
      {/* Statistics Cards */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5">
          <Card className="p-3.5 bg-white border-cocoa-100 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-cocoa-100/60 text-cocoa-700 flex items-center justify-center">
              <Layers className="w-4 h-4" />
            </div>
            <div>
              <div className="text-xs text-cocoa-500 font-medium">إجمالي الأسئلة</div>
              <div className="text-xl font-bold font-display text-cocoa-900">
                {stats.total_questions || 0}
              </div>
            </div>
          </Card>

          <Card
            className={`p-3.5 bg-white border-cocoa-100 flex items-center gap-3 cursor-pointer transition hover:border-emerald-300 ${
              statusFilter === 'approved' ? 'ring-2 ring-emerald-500' : ''
            }`}
            onClick={() => setStatusFilter(statusFilter === 'approved' ? '' : 'approved')}
          >
            <div className="w-9 h-9 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center">
              <CheckCircle2 className="w-4 h-4" />
            </div>
            <div>
              <div className="text-xs text-cocoa-500 font-medium">معتمدة</div>
              <div className="text-xl font-bold font-display text-emerald-700">
                {stats.approved_count || 0}
              </div>
            </div>
          </Card>

          <Card
            className={`p-3.5 bg-white border-cocoa-100 flex items-center gap-3 cursor-pointer transition hover:border-amber-300 ${
              statusFilter === 'needs_review' ? 'ring-2 ring-amber-500' : ''
            }`}
            onClick={() => setStatusFilter(statusFilter === 'needs_review' ? '' : 'needs_review')}
          >
            <div className="w-9 h-9 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center">
              <AlertTriangle className="w-4 h-4" />
            </div>
            <div>
              <div className="text-xs text-cocoa-500 font-medium">تحتاج مراجعة</div>
              <div className="text-xl font-bold font-display text-amber-700">
                {stats.needs_review_count || 0}
              </div>
            </div>
          </Card>

          <Card
            className={`p-3.5 bg-white border-cocoa-100 flex items-center gap-3 cursor-pointer transition hover:border-blue-300 ${
              statusFilter === 'pending_review' ? 'ring-2 ring-blue-500' : ''
            }`}
            onClick={() => setStatusFilter(statusFilter === 'pending_review' ? '' : 'pending_review')}
          >
            <div className="w-9 h-9 rounded-lg bg-blue-100 text-blue-700 flex items-center justify-center">
              <Clock className="w-4 h-4" />
            </div>
            <div>
              <div className="text-xs text-cocoa-500 font-medium">بانتظار المراجعة</div>
              <div className="text-xl font-bold font-display text-blue-700">
                {stats.pending_review_count || 0}
              </div>
            </div>
          </Card>

          <Card
            className={`p-3.5 bg-white border-cocoa-100 flex items-center gap-3 cursor-pointer transition hover:border-rose-300 ${
              statusFilter === 'rejected' ? 'ring-2 ring-rose-500' : ''
            }`}
            onClick={() => setStatusFilter(statusFilter === 'rejected' ? '' : 'rejected')}
          >
            <div className="w-9 h-9 rounded-lg bg-rose-100 text-rose-700 flex items-center justify-center">
              <XCircle className="w-4 h-4" />
            </div>
            <div>
              <div className="text-xs text-cocoa-500 font-medium">مرفوضة</div>
              <div className="text-xl font-bold font-display text-rose-700">
                {stats.rejected_count || 0}
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* Incremental Learning Status Pill */}
      {learningStats && (
        <div className="bg-gradient-to-r from-cocoa-900 via-cocoa-950 to-cocoa-900 text-white rounded-xl p-3.5 flex flex-col md:flex-row items-start md:items-center justify-between gap-3 shadow-warm">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gold-400/20 text-gold-400 rounded-lg">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-gold-400">
                التعلم من قرارات التدريس (In-Context Exemplars)
              </span>
              <p className="text-xs text-cocoa-200 mt-0.5">
                {learningStats.guidance}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 self-end md:self-auto shrink-0">
            <span className="text-xs px-2.5 py-1 rounded-full bg-white/10 font-code text-gold-300">
              {learningStats.approved_sample_count} / {learningStats.required_total_samples} عينة معتمدة
            </span>
            <Badge variant={learningStats.is_ready_for_supervised_training ? 'success' : 'neutral'}>
              {learningStats.is_ready_for_supervised_training ? 'جاهز لتدريب مصنف مستقل' : 'النشط: RAG + LLM'}
            </Badge>
          </div>
        </div>
      )}

      {/* Filter and Search Bar */}
      <Card className="p-4 bg-white border-cocoa-100">
        <form onSubmit={handleSearchSubmit} className="flex flex-col md:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute right-3 top-3 text-cocoa-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="ابحث بنص السؤال، المعرف، أو الإجابة النموذجية..."
              className="w-full pr-9 pl-4 py-2 border border-cocoa-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-gold-500"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className="px-3 py-2 border border-cocoa-200 rounded-lg text-xs bg-white text-cocoa-800"
            >
              <option value="">جميع الحالات</option>
              <option value="pending_review">بانتظار المراجعة</option>
              <option value="needs_review">تحتاج مراجعة</option>
              <option value="approved">معتمدة</option>
              <option value="rejected">مرفوضة</option>
            </select>

            <select
              value={difficultyFilter}
              onChange={(e) => {
                setDifficultyFilter(e.target.value);
                setPage(1);
              }}
              className="px-3 py-2 border border-cocoa-200 rounded-lg text-xs bg-white text-cocoa-800"
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
              className="px-3 py-2 border border-cocoa-200 rounded-lg text-xs bg-white text-cocoa-800"
            >
              <option value="">جميع مستويات بلوم</option>
              <option value="remember">تذكر</option>
              <option value="understand">فهم</option>
              <option value="apply">تطبيق</option>
              <option value="analyze">تحليل</option>
              <option value="evaluate">تقييم</option>
              <option value="create">ابتكار</option>
            </select>

            <Button type="submit" variant="secondary" size="sm">
              بحث
            </Button>
            {(search || statusFilter || difficultyFilter || bloomFilter) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSearch('');
                  setStatusFilter('');
                  setDifficultyFilter('');
                  setBloomFilter('');
                  setPage(1);
                }}
              >
                مسح التصفية
              </Button>
            )}
          </div>
        </form>
      </Card>

      {/* Questions List */}
      <div className="space-y-3">
        {loading ? (
          <div className="py-12 flex justify-center">
            <LoadingSpinner message="جاري استعلام بنك الأسئلة..." />
          </div>
        ) : questions.length === 0 ? (
          <Card className="p-12 text-center bg-white border-dashed border-cocoa-200">
            <div className="w-12 h-12 rounded-full bg-cocoa-100 flex items-center justify-center mx-auto text-cocoa-500 mb-3">
              <Database className="w-6 h-6" />
            </div>
            <h3 className="text-base font-bold text-cocoa-900 mb-1">لا توجد أسئلة تطابق البحث</h3>
            <p className="text-xs text-cocoa-500 max-w-sm mx-auto mb-4">
              يمكنك استيراد أسئلة من ملف (PDF, DOCX, XLSX, JSON) أو إضافة سؤال جديد يدوياً.
            </p>
            <div className="flex justify-center gap-2">
              <Button size="sm" variant="outline" onClick={() => setImportModalOpen(true)}>
                استيراد ملف
              </Button>
              <Button size="sm" variant="primary" onClick={() => setAddModalOpen(true)}>
                إضافة سؤال
              </Button>
            </div>
          </Card>
        ) : (
          questions.map((q) => {
            const statusCfg = STATUS_CONFIGS[q.classification_status] || STATUS_CONFIGS.pending_review;
            const StatusIcon = statusCfg.icon;

            return (
              <Card
                key={q.question_id}
                className="p-4 bg-white border-cocoa-100 hover:border-gold-300 transition shadow-sm"
              >
                <div className="flex flex-col md:flex-row md:items-start justify-between gap-3">
                  <div className="flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-code text-xs font-bold text-cocoa-700 bg-cocoa-100 px-2 py-0.5 rounded">
                        {q.question_id}
                      </span>
                      <span className="text-xs text-cocoa-600 bg-cocoa-50 border border-cocoa-200 px-2 py-0.5 rounded">
                        {q.question_type === 'mcq' ? 'اختيار من متعدد' : 'سؤال مقالي'}
                      </span>
                      {q.difficulty && (
                        <span className="text-xs font-medium text-cocoa-700 bg-cocoa-100/70 px-2 py-0.5 rounded">
                          الصعوبة: {DIFFICULTY_TRANSLATIONS[q.difficulty.toLowerCase()] || q.difficulty}
                        </span>
                      )}
                      {q.bloom_level && (
                        <span className="text-xs font-medium text-gold-900 bg-gold-100/70 px-2 py-0.5 rounded">
                          بلوم: {BLOOM_TRANSLATIONS[q.bloom_level.toLowerCase()] || q.bloom_level}
                        </span>
                      )}
                      {q.lesson && (
                        <span className="text-xs text-cocoa-600 flex items-center gap-1">
                          <BookOpen className="w-3 h-3 text-cocoa-400" />
                          {q.lesson}
                        </span>
                      )}
                    </div>

                    <div className="text-sm font-semibold text-cocoa-900 leading-relaxed">
                      {q.question_text}
                    </div>

                    {q.options && q.options.length > 0 && (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 pt-1 text-xs text-cocoa-700">
                        {q.options.map((opt, i) => {
                          const letter = ['A', 'B', 'C', 'D'][i];
                          const isCorrect = q.correct_option === letter || q.correct_answer === opt;
                          return (
                            <div
                              key={i}
                              className={`p-1.5 rounded border text-xs flex items-center gap-1.5 ${
                                isCorrect
                                  ? 'bg-emerald-50 border-emerald-300 font-medium text-emerald-900'
                                  : 'bg-cocoa-50/50 border-cocoa-200'
                              }`}
                            >
                              <span className="font-bold text-cocoa-500">{letter}:</span>
                              <span className="truncate">{opt}</span>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Evidence & Confidence Snippet */}
                    <div className="flex flex-wrap items-center gap-3 pt-1 text-xs text-cocoa-500">
                      {q.classification_confidence !== null && (
                        <div className="flex items-center gap-1.5">
                          <span>نسبة الثقة:</span>
                          <span className="font-code font-bold text-cocoa-800">
                            {(q.classification_confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      )}
                      {q.source_chunk_ids && q.source_chunk_ids.length > 0 && (
                        <div className="flex items-center gap-1">
                          <span>المقاطع المدعومة:</span>
                          <span className="font-code text-gold-800">
                            {q.source_chunk_ids.join(', ')}
                          </span>
                        </div>
                      )}
                      {q.reviewed_by && (
                        <div className="text-cocoa-600">
                          راجعه: <span className="font-medium">{q.reviewed_by}</span>
                        </div>
                      )}
                    </div>

                    {/* Review warning message if needs review */}
                    {q.needs_teacher_review && q.review_reasons && q.review_reasons.length > 0 && (
                      <div className="p-2 rounded bg-amber-50 border border-amber-200 text-amber-800 text-xs flex items-start gap-1.5 mt-1">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-amber-600" />
                        <div>
                          <span className="font-bold">أسباب المراجعة: </span>
                          <span>{q.review_reasons.join(' | ')}</span>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Actions & Status Badge */}
                  <div className="flex flex-row md:flex-col items-center md:items-end justify-between gap-2.5 shrink-0 pt-2 md:pt-0 border-t md:border-t-0 border-cocoa-100">
                    <div className={`px-2.5 py-1 rounded-full border text-xs font-medium flex items-center gap-1.5 ${statusCfg.color}`}>
                      <StatusIcon className="w-3.5 h-3.5" />
                      <span>{statusCfg.label}</span>
                    </div>

                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => {
                          setSelectedQuestion(q);
                          setDetailModalOpen(true);
                        }}
                        className="p-1.5 rounded-lg border border-cocoa-200 text-cocoa-600 hover:bg-cocoa-100 transition"
                        title="عرض الأدلة والتفاصيل"
                      >
                        <Eye className="w-4 h-4" />
                      </button>

                      {q.classification_status !== 'approved' && (
                        <button
                          onClick={() => handleApprove(q)}
                          className="p-1.5 rounded-lg bg-emerald-50 border border-emerald-300 text-emerald-700 hover:bg-emerald-100 transition"
                          title="اعتماد السؤال"
                        >
                          <CheckCircle2 className="w-4 h-4" />
                        </button>
                      )}

                      {q.classification_status !== 'rejected' && (
                        <button
                          onClick={() => handleReject(q)}
                          className="p-1.5 rounded-lg bg-rose-50 border border-rose-300 text-rose-700 hover:bg-rose-100 transition"
                          title="رفض السؤال"
                        >
                          <XCircle className="w-4 h-4" />
                        </button>
                      )}

                      <button
                        onClick={() => {
                          setSelectedQuestion(q);
                          setEditFormData({
                            bloom_level: q.bloom_level || 'Understand',
                            difficulty: q.difficulty || 'Medium',
                            lesson: q.lesson || '',
                            correct_answer: q.correct_answer || '',
                          });
                          setReviewAction('edit');
                          setReviewNotes('');
                          setReviewModalOpen(true);
                        }}
                        className="p-1.5 rounded-lg border border-cocoa-200 text-cocoa-600 hover:bg-cocoa-100 transition"
                        title="تعديل السؤال"
                      >
                        <Edit3 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              </Card>
            );
          })
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-4 border-t border-cocoa-200">
          <div className="text-xs text-cocoa-500">
            عرض صفحة {page} من {totalPages} (إجمالي {totalQuestions} سؤال)
          </div>
          <div className="flex items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              <ChevronRight className="w-4 h-4 ml-1" /> السابق
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              التالي <ChevronLeft className="w-4 h-4 mr-1" />
            </Button>
          </div>
        </div>
      )}

        </>
      )}

      {/* =========================================================================
          VIEW 2: CLEANED QUESTION BANK DATASET (READ-ONLY)
         ========================================================================= */}
      {activeTab === 'cleaned_dataset' && (
        <div className="space-y-4">
          {/* Provenance & Cryptographic Audit Banner */}
          <Card className="p-4 bg-gradient-to-br from-white via-cocoa-50/30 to-gold-50/20 border-cocoa-200 shadow-sm">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-3 border-b border-cocoa-100">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-xl bg-emerald-100 text-emerald-800 flex items-center justify-center shrink-0">
                  <FileText className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-bold font-display text-cocoa-900">
                      مجموعة بيانات بنك الأسئلة المنقحة والمحققة
                    </h2>
                    <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200">
                      بيانات موثوقة (317 سؤالاً)
                    </span>
                    <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-cocoa-100 text-cocoa-700">
                      للقراءة فقط (Read-Only)
                    </span>
                  </div>
                  <p className="text-xs text-cocoa-600 mt-0.5">
                    مجموعة أسئلة تم تنقيحها والتحقق من صحة صياغتها وإجاباتها عبر مرحلة إعداد البيانات، معزولة تماماً عن قاعدة البيانات الإنتاجية.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={fetchCleanedDataset}
                  loading={cleanedLoading}
                  className="flex items-center gap-1.5"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>تحديث العرض</span>
                </Button>
              </div>
            </div>

            {/* Provenance Metadata Grid */}
            {cleanedProvenance && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-3">
                <div className="p-2.5 rounded-lg bg-white border border-cocoa-100">
                  <div className="text-[11px] text-cocoa-500 font-medium">ملف البيانات ومساره</div>
                  <div className="text-xs font-bold font-code text-cocoa-900 truncate mt-0.5" title={cleanedProvenance.file_path}>
                    {cleanedProvenance.file_path.split('\\').pop() || cleanedProvenance.file_path}
                  </div>
                  <div className="text-[10px] text-cocoa-400 mt-0.5">
                    الحجم: {(cleanedProvenance.file_size_bytes / 1024).toFixed(1)} ك.ب | الورقة: {cleanedProvenance.sheet_name}
                  </div>
                </div>

                <div className="p-2.5 rounded-lg bg-white border border-cocoa-100">
                  <div className="text-[11px] text-cocoa-500 font-medium">البصمة الرقمية (SHA-256)</div>
                  <div className="flex items-center justify-between gap-1 mt-0.5">
                    <span className="text-xs font-code font-bold text-cocoa-800 truncate" title={cleanedProvenance.sha256_hash}>
                      {cleanedProvenance.sha256_hash.substring(0, 16)}...
                    </span>
                    <button
                      type="button"
                      onClick={() => handleCopyHash(cleanedProvenance.sha256_hash)}
                      className="p-1 text-cocoa-400 hover:text-gold-600 transition shrink-0"
                      title="نسخ البصمة كاملة"
                    >
                      {copiedHash ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <Eye className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                  <div className="text-[10px] text-cocoa-400 mt-0.5">
                    {copiedHash ? 'تم نسخ التجزئة للحافظة' : 'للتحقق من سلامة البيانات'}
                  </div>
                </div>

                <div className="p-2.5 rounded-lg bg-white border border-cocoa-100">
                  <div className="text-[11px] text-cocoa-500 font-medium">إحصائيات الأسئلة</div>
                  <div className="text-xs font-bold text-cocoa-900 mt-0.5">
                    {cleanedProvenance.valid_rows} سؤال صالح (0 تالف)
                  </div>
                  <div className="text-[10px] text-cocoa-500 mt-0.5">
                    168 اختيار من متعدد + 149 مقالي
                  </div>
                </div>

                <div className="p-2.5 rounded-lg bg-white border border-cocoa-100">
                  <div className="text-[11px] text-cocoa-500 font-medium">تصنيفات الصعوبة وبلوم</div>
                  <div className="text-xs font-bold text-amber-700 mt-0.5 flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3 shrink-0" />
                    <span>غير مدرجة (غير مصطنعة)</span>
                  </div>
                  <div className="text-[10px] text-cocoa-400 mt-0.5">
                    النشط للأسئلة الجديدة: RAG + LLM
                  </div>
                </div>
              </div>
            )}

            {/* Clarification Alert */}
            <div className="mt-3 p-2.5 rounded-lg bg-amber-50/70 border border-amber-200 text-amber-900 text-xs flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-bold">سياسة الموثوقية وعدم اصطناع التسميات: </span>
                مجموعة البيانات المنقحة تحتوي على صياغات الأسئلة، الخيارات، والإجابات النموذجية المحققة، ولكنها لا تحتوي على تسميات مسبقة للصعوبة أو مستويات بلوم. لا يقوم النظام باختلاق أي تصنيفات وهمية لتدريب نموذج مراقب غير دقيق، ويبقى تصنيف RAG/LLM هو المعتمد. التصفح هنا للقراءة فقط ولا يُعدّل قاعدة البيانات.
              </div>
            </div>
          </Card>

          {/* Cleaned Dataset Filters */}
          <Card className="p-4 bg-white border-cocoa-100">
            <form onSubmit={handleCleanedSearchSubmit} className="flex flex-col md:flex-row gap-3">
              <div className="relative flex-1">
                <Search className="w-4 h-4 absolute right-3 top-3 text-cocoa-400" />
                <input
                  type="text"
                  value={cleanedSearch}
                  onChange={(e) => setCleanedSearch(e.target.value)}
                  placeholder="ابحث في نص السؤال، الإجابة، أو المعرف الأصلي..."
                  className="w-full pr-9 pl-4 py-2 border border-cocoa-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-gold-500"
                />
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={cleanedTypeFilter}
                  onChange={(e) => {
                    setCleanedTypeFilter(e.target.value);
                    setCleanedPage(1);
                  }}
                  className="px-3 py-2 border border-cocoa-200 rounded-lg text-xs bg-white text-cocoa-800"
                >
                  <option value="">جميع أنواع الأسئلة</option>
                  <option value="mcq">اختيار من متعدد (MCQ)</option>
                  <option value="essay">سؤال مقالي (Essay)</option>
                </select>

                <select
                  value={cleanedChapterFilter}
                  onChange={(e) => {
                    setCleanedChapterFilter(e.target.value);
                    setCleanedPage(1);
                  }}
                  className="px-3 py-2 border border-cocoa-200 rounded-lg text-xs bg-white text-cocoa-800 max-w-[160px]"
                >
                  <option value="">جميع الفصول</option>
                  {(cleanedFiltersAvailable.chapters || []).map((ch) => (
                    <option key={ch} value={ch}>
                      {ch}
                    </option>
                  ))}
                </select>

                <select
                  value={cleanedLessonFilter}
                  onChange={(e) => {
                    setCleanedLessonFilter(e.target.value);
                    setCleanedPage(1);
                  }}
                  className="px-3 py-2 border border-cocoa-200 rounded-lg text-xs bg-white text-cocoa-800 max-w-[160px]"
                >
                  <option value="">جميع الدروس</option>
                  {(cleanedFiltersAvailable.lessons || []).map((ls) => (
                    <option key={ls} value={ls}>
                      {ls}
                    </option>
                  ))}
                </select>

                <select
                  value={cleanedVerificationFilter}
                  onChange={(e) => {
                    setCleanedVerificationFilter(e.target.value);
                    setCleanedPage(1);
                  }}
                  className="px-3 py-2 border border-cocoa-200 rounded-lg text-xs bg-white text-cocoa-800"
                >
                  <option value="">حالة التحقق</option>
                  {(cleanedFiltersAvailable.verification_statuses || []).map((v) => (
                    <option key={v} value={v}>
                      {v === 'verified' ? 'متحقق منه (verified)' : v}
                    </option>
                  ))}
                </select>

                <Button type="submit" variant="secondary" size="sm">
                  بحث
                </Button>

                {(cleanedSearch || cleanedTypeFilter || cleanedChapterFilter || cleanedLessonFilter || cleanedVerificationFilter) && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setCleanedSearch('');
                      setCleanedTypeFilter('');
                      setCleanedChapterFilter('');
                      setCleanedLessonFilter('');
                      setCleanedVerificationFilter('');
                      setCleanedPage(1);
                    }}
                  >
                    مسح التصفية
                  </Button>
                )}
              </div>
            </form>
          </Card>

          {/* Cleaned Dataset Question List */}
          <div className="space-y-3">
            {cleanedLoading ? (
              <div className="py-12 flex justify-center">
                <LoadingSpinner message="جاري استعلام مجموعة البيانات المنقحة..." />
              </div>
            ) : cleanedError ? (
              <Alert variant="danger">{cleanedError}</Alert>
            ) : cleanedQuestions.length === 0 ? (
              <Card className="p-12 text-center bg-white border-dashed border-cocoa-200">
                <div className="w-12 h-12 rounded-full bg-cocoa-100 flex items-center justify-center mx-auto text-cocoa-500 mb-3">
                  <FileText className="w-6 h-6" />
                </div>
                <h3 className="text-base font-bold text-cocoa-900 mb-1">لا توجد أسئلة تطابق معايير التصفية</h3>
                <p className="text-xs text-cocoa-500 max-w-sm mx-auto mb-4">
                  جرب تغيير نص البحث أو إزالة بعض خيارات التصفية لعرض أسئلة المجموعة المنقحة.
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setCleanedSearch('');
                    setCleanedTypeFilter('');
                    setCleanedChapterFilter('');
                    setCleanedLessonFilter('');
                    setCleanedVerificationFilter('');
                    setCleanedPage(1);
                  }}
                >
                  إعادة ضبط التصفية
                </Button>
              </Card>
            ) : (
              cleanedQuestions.map((q) => (
                <Card
                  key={q.question_id}
                  className="p-4 bg-white border-cocoa-100 hover:border-emerald-300 transition shadow-sm"
                >
                  <div className="flex flex-col md:flex-row md:items-start justify-between gap-3">
                    <div className="flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-code text-xs font-bold text-emerald-800 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded">
                          {q.question_id}
                        </span>
                        {q.original_question_id && q.original_question_id !== q.question_id && (
                          <span className="font-code text-xs text-cocoa-500 bg-cocoa-100 px-2 py-0.5 rounded" title="المعرف الأصلي قبل التنقيح">
                            أصل: {q.original_question_id}
                          </span>
                        )}
                        <span className="text-xs font-medium text-cocoa-700 bg-cocoa-50 border border-cocoa-200 px-2 py-0.5 rounded">
                          {q.question_type === 'mcq' ? 'اختيار من متعدد' : 'سؤال مقالي'}
                        </span>
                        {q.verification_status && (
                          <span className="text-xs font-medium text-emerald-800 bg-emerald-50 px-2 py-0.5 rounded flex items-center gap-1 border border-emerald-200">
                            <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                            {q.verification_status === 'verified' ? 'متحقق منه' : q.verification_status}
                          </span>
                        )}
                        {q.chapter && (
                          <span className="text-xs text-cocoa-700 bg-cocoa-100/70 px-2 py-0.5 rounded">
                            {q.chapter}
                          </span>
                        )}
                        {q.lesson && (
                          <span className="text-xs text-cocoa-600 flex items-center gap-1">
                            <BookOpen className="w-3 h-3 text-cocoa-400" />
                            {q.lesson}
                          </span>
                        )}
                        {q.page_number && (
                          <span className="text-xs text-cocoa-500">
                            ص {q.page_number}
                          </span>
                        )}
                      </div>

                      <div className="text-sm font-semibold text-cocoa-900 leading-relaxed" dir="auto">
                        {q.question_text}
                      </div>

                      {/* Options for MCQ */}
                      {q.question_type === 'mcq' && q.options && q.options.length > 0 && (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 pt-1 text-xs text-cocoa-700">
                          {q.options.map((opt, i) => {
                            const letter = ['A', 'B', 'C', 'D'][i];
                            const isCorrect = q.correct_option === letter || q.correct_answer === opt;
                            return (
                              <div
                                key={i}
                                className={`p-2 rounded border text-xs flex items-center gap-2 ${
                                  isCorrect
                                    ? 'bg-emerald-50 border-emerald-300 font-semibold text-emerald-950 shadow-sm'
                                    : 'bg-cocoa-50/40 border-cocoa-200'
                                }`}
                              >
                                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${
                                  isCorrect ? 'bg-emerald-600 text-white' : 'bg-cocoa-200 text-cocoa-700'
                                }`}>
                                  {letter}
                                </span>
                                <span className="truncate" dir="auto">{opt}</span>
                                {isCorrect && (
                                  <span className="mr-auto text-[11px] text-emerald-700 font-bold flex items-center gap-0.5">
                                    <CheckCircle2 className="w-3.5 h-3.5" />
                                    <span>صحيح</span>
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {/* Essay Model Answer */}
                      {q.question_type !== 'mcq' && q.correct_answer && (
                        <div className="mt-2 p-2.5 rounded-lg bg-emerald-50/60 border border-emerald-200 text-xs">
                          <span className="font-bold text-emerald-900 block mb-1">الإجابة النموذجية المعتمدة:</span>
                          <div className="text-emerald-950 font-medium leading-relaxed" dir="auto">
                            {q.correct_answer}
                          </div>
                        </div>
                      )}

                      {/* Metadata Footer */}
                      <div className="flex flex-wrap items-center gap-3 pt-1 text-xs text-cocoa-500">
                        {q.source_file && (
                          <div className="flex items-center gap-1">
                            <span>الملف المصدري:</span>
                            <span className="font-code text-cocoa-700">{q.source_file}</span>
                          </div>
                        )}
                        {q.answer_source && (
                          <div className="flex items-center gap-1">
                            <span>مصدر الإجابة:</span>
                            <span className="text-cocoa-700 font-medium">{q.answer_source}</span>
                          </div>
                        )}
                        {q.Source && (
                          <div className="text-cocoa-500">
                            المصدر: <span className="font-medium text-cocoa-700">{q.Source}</span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* View Details Button */}
                    <div className="flex md:flex-col items-center md:items-end justify-end shrink-0 pt-2 md:pt-0">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setSelectedCleanedQuestion(q);
                          setCleanedDetailModalOpen(true);
                        }}
                        className="flex items-center gap-1 text-xs"
                      >
                        <Eye className="w-3.5 h-3.5" />
                        <span>التفاصيل الكاملة</span>
                      </Button>
                    </div>
                  </div>
                </Card>
              ))
            )}
          </div>

          {/* Cleaned Dataset Pagination */}
          {cleanedTotalPages > 1 && (
            <div className="flex items-center justify-between pt-4 border-t border-cocoa-200">
              <div className="text-xs text-cocoa-500">
                عرض صفحة {cleanedPage} من {cleanedTotalPages} (إجمالي {cleanedTotal} سؤالاً)
              </div>
              <div className="flex items-center gap-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={cleanedPage <= 1}
                  onClick={() => setCleanedPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronRight className="w-4 h-4 ml-1" /> السابق
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={cleanedPage >= cleanedTotalPages}
                  onClick={() => setCleanedPage((p) => Math.min(cleanedTotalPages, p + 1))}
                >
                  التالي <ChevronLeft className="w-4 h-4 mr-1" />
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* =========================================================================
          MODAL 1: Detail & Grounding Evidence Modal
         ========================================================================= */}
      {detailModalOpen && selectedQuestion && (
        <Modal
          isOpen={detailModalOpen}
          onClose={() => setDetailModalOpen(false)}
          title={`تفاصيل وتأصيل السؤال: ${selectedQuestion.question_id}`}
          size="lg"
        >
          <div className="space-y-4 text-cocoa-900 text-sm" dir="rtl">
            <div>
              <div className="text-xs text-cocoa-500 font-medium mb-1">نص السؤال:</div>
              <div className="p-3 bg-cocoa-50 rounded-lg font-medium text-cocoa-900 border border-cocoa-200">
                {selectedQuestion.question_text}
              </div>
            </div>

            {selectedQuestion.options && selectedQuestion.options.length > 0 && (
              <div>
                <div className="text-xs text-cocoa-500 font-medium mb-1">الخيارات:</div>
                <div className="grid grid-cols-2 gap-2">
                  {selectedQuestion.options.map((opt, i) => (
                    <div key={i} className="p-2 rounded border border-cocoa-200 bg-white text-xs">
                      <span className="font-bold text-cocoa-500">{['A', 'B', 'C', 'D'][i]}:</span> {opt}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <div className="text-xs text-cocoa-500 font-medium mb-1">الإجابة النموذجية:</div>
              <div className="p-2.5 bg-emerald-50 text-emerald-950 rounded-lg border border-emerald-200 text-xs">
                {selectedQuestion.correct_answer}
              </div>
            </div>

            {selectedQuestion.explanation && (
              <div>
                <div className="text-xs text-cocoa-500 font-medium mb-1">التفسير التعليمي:</div>
                <div className="p-2.5 bg-cocoa-50 rounded-lg border border-cocoa-200 text-xs">
                  {selectedQuestion.explanation}
                </div>
              </div>
            )}

            {/* Curriculum Grounding Evidence Section */}
            <div className="border-t border-cocoa-200 pt-3">
              <div className="flex items-center gap-1.5 font-bold text-cocoa-900 mb-2">
                <BookOpen className="w-4 h-4 text-gold-600" />
                <span>التأصيل المنهجي والأدلة المسترجعة</span>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
                <div className="p-2 bg-cocoa-50 rounded border border-cocoa-200 text-xs">
                  <div className="text-cocoa-500">المادة/الموضوع:</div>
                  <div className="font-bold">{selectedQuestion.subject || 'غير محدد'}</div>
                </div>
                <div className="p-2 bg-cocoa-50 rounded border border-cocoa-200 text-xs">
                  <div className="text-cocoa-500">الوحدة:</div>
                  <div className="font-bold">{selectedQuestion.unit || 'غير محدد'}</div>
                </div>
                <div className="p-2 bg-cocoa-50 rounded border border-cocoa-200 text-xs">
                  <div className="text-cocoa-500">الدرس:</div>
                  <div className="font-bold">{selectedQuestion.lesson || 'غير محدد'}</div>
                </div>
                <div className="p-2 bg-cocoa-50 rounded border border-cocoa-200 text-xs">
                  <div className="text-cocoa-500">الصفحة:</div>
                  <div className="font-bold">{selectedQuestion.page_number || 'غير محدد'}</div>
                </div>
              </div>

              {selectedQuestion.source_evidence && (
                <div className="mb-3">
                  <div className="text-xs text-cocoa-500 mb-1">الشاهد المقتبس من المنهج:</div>
                  <div className="p-2.5 bg-gold-50 border border-gold-200 text-gold-950 rounded text-xs leading-relaxed italic">
                    "{selectedQuestion.source_evidence}"
                  </div>
                </div>
              )}

              {selectedQuestion.classification_reasoning && (
                <div className="mb-3">
                  <div className="text-xs text-cocoa-500 mb-1">تحليل الصعوبة ومستوى بلوم:</div>
                  <div className="p-2.5 bg-cocoa-50 border border-cocoa-200 rounded text-xs text-cocoa-800">
                    {selectedQuestion.classification_reasoning}
                  </div>
                </div>
              )}

              {selectedQuestion.teacher_corrections && (
                <div className="mb-3 p-2.5 bg-blue-50 border border-blue-200 rounded text-xs text-blue-900">
                  <div className="font-bold mb-1">سجل تصحيحات المعلم:</div>
                  <pre className="text-xs font-code overflow-x-auto">
                    {JSON.stringify(selectedQuestion.teacher_corrections, null, 2)}
                  </pre>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-cocoa-200">
              <Button variant="secondary" onClick={() => setDetailModalOpen(false)}>
                إغلاق
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* =========================================================================
          MODAL 2: Review / Approve / Reject Modal
         ========================================================================= */}
      {reviewModalOpen && selectedQuestion && (
        <Modal
          isOpen={reviewModalOpen}
          onClose={() => setReviewModalOpen(false)}
          title={
            reviewAction === 'approve'
              ? `اعتماد وتصنيف السؤال: ${selectedQuestion.question_id}`
              : reviewAction === 'reject'
              ? `رفض السؤال: ${selectedQuestion.question_id}`
              : `تعديل السؤال: ${selectedQuestion.question_id}`
          }
          size="md"
        >
          <div className="space-y-4 text-sm" dir="rtl">
            <div className="p-2.5 bg-cocoa-50 rounded border border-cocoa-200 text-xs">
              <span className="font-bold">السؤال: </span>
              {selectedQuestion.question_text}
            </div>

            {reviewAction !== 'reject' && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-cocoa-700 mb-1">
                    مستوى بلوم:
                  </label>
                  <select
                    value={editFormData.bloom_level}
                    onChange={(e) => setEditFormData({ ...editFormData, bloom_level: e.target.value })}
                    className="w-full p-2 border border-cocoa-200 rounded-lg text-xs"
                  >
                    <option value="Remember">تذكر (Remember)</option>
                    <option value="Understand">فهم (Understand)</option>
                    <option value="Apply">تطبيق (Apply)</option>
                    <option value="Analyze">تحليل (Analyze)</option>
                    <option value="Evaluate">تقييم (Evaluate)</option>
                    <option value="Create">ابتكار (Create)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-cocoa-700 mb-1">
                    درجة الصعوبة:
                  </label>
                  <select
                    value={editFormData.difficulty}
                    onChange={(e) => setEditFormData({ ...editFormData, difficulty: e.target.value })}
                    className="w-full p-2 border border-cocoa-200 rounded-lg text-xs"
                  >
                    <option value="Easy">سهل (Easy)</option>
                    <option value="Medium">متوسط (Medium)</option>
                    <option value="Hard">صعب (Hard)</option>
                  </select>
                </div>

                <div className="col-span-2">
                  <label className="block text-xs font-medium text-cocoa-700 mb-1">
                    الدرس / المفهوم المنهجي:
                  </label>
                  <input
                    type="text"
                    value={editFormData.lesson}
                    onChange={(e) => setEditFormData({ ...editFormData, lesson: e.target.value })}
                    className="w-full p-2 border border-cocoa-200 rounded-lg text-xs"
                    placeholder="اسم الدرس أو الموضوع..."
                  />
                </div>
              </div>
            )}

            <div>
              <label className="block text-xs font-medium text-cocoa-700 mb-1">
                {reviewAction === 'reject' ? 'سبب الرفض (مطلوب):' : 'ملاحظات المعلم / مبرر التعديل:'}
              </label>
              <textarea
                rows={3}
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
                placeholder={
                  reviewAction === 'reject'
                    ? 'اكتب سبب رفض السؤال...'
                    : 'اختياري: اكتب سبب تعديل التصنيف أو أي ملاحظات...'
                }
                className="w-full p-2 border border-cocoa-200 rounded-lg text-xs focus:ring-2 focus:ring-gold-500"
              />
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-cocoa-200">
              <Button variant="ghost" onClick={() => setReviewModalOpen(false)}>
                إلغاء
              </Button>
              <Button
                variant={reviewAction === 'reject' ? 'danger' : 'primary'}
                onClick={submitReviewDecision}
              >
                {reviewAction === 'approve'
                  ? 'تأكيد الاعتماد'
                  : reviewAction === 'reject'
                  ? 'تأكيد الرفض'
                  : 'حفظ التعديلات'}
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* =========================================================================
          MODAL 3: Import Questions File
         ========================================================================= */}
      {importModalOpen && (
        <Modal
          isOpen={importModalOpen}
          onClose={() => setImportModalOpen(false)}
          title="استيراد بنك أسئلة من ملف"
          size="md"
        >
          <form onSubmit={handleImportSubmit} className="space-y-4 text-sm" dir="rtl">
            <div className="p-3 bg-cocoa-50 rounded-lg border border-cocoa-200 text-xs text-cocoa-700">
              <div className="font-bold mb-1">الصيغ المدعومة:</div>
              <div>PDF, DOCX (Word), XLSX / XLS (Excel), CSV, JSON</div>
            </div>

            <div>
              <label className="block text-xs font-medium text-cocoa-700 mb-1.5">
                اختر ملف الأسئلة:
              </label>
              <input
                type="file"
                accept=".pdf,.docx,.xlsx,.xls,.csv,.json"
                onChange={(e) => setImportFile(e.target.files?.[0] || null)}
                className="w-full text-xs text-cocoa-700 file:mr-0 file:ml-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-cocoa-900 file:text-gold-400 hover:file:bg-cocoa-800"
              />
            </div>

            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="autoClassify"
                checked={autoClassifyOnImport}
                onChange={(e) => setAutoClassifyOnImport(e.target.checked)}
                className="w-4 h-4 text-gold-600 rounded border-cocoa-300 focus:ring-gold-500"
              />
              <label htmlFor="autoClassify" className="text-xs text-cocoa-800 cursor-pointer">
                تفعيل التصنيف والتأصيل المنهجي التلقائي بواسطة RAG
              </label>
            </div>

            {importResult && (
              <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-xs space-y-1 text-emerald-950">
                <div className="font-bold">نتيجة الاستيراد:</div>
                <div>تم استخراج {importResult.total_extracted} سؤالاً.</div>
                <div>الأسئلة الصحيحة والمدرجة: {importResult.inserted} سؤالاً.</div>
                {importResult.duplicate_count > 0 && (
                  <div className="text-amber-800">
                    الأسئلة المتشابهة المرصودة: {importResult.duplicate_count} (لم يتم حذفها، فقط وسمها).
                  </div>
                )}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-3 border-t border-cocoa-200">
              <Button variant="ghost" onClick={() => setImportModalOpen(false)}>
                إغلاق
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={!importFile || importing}
                loading={importing}
              >
                بدء الاستيراد
              </Button>
            </div>
          </form>
        </Modal>
      )}

      {/* =========================================================================
          MODAL 4: Manual Add & Instant Classification
         ========================================================================= */}
      {addModalOpen && (
        <Modal
          isOpen={addModalOpen}
          onClose={() => setAddModalOpen(false)}
          title="إضافة سؤال يدوي وتصنيفه منهجياً"
          size="lg"
        >
          <div className="space-y-4 text-sm" dir="rtl">
            {modalError && (
              <Alert variant="danger" dismissible onDismiss={() => setModalError(null)}>
                {modalError}
              </Alert>
            )}

            <div>
              <label className="block text-xs font-medium text-cocoa-700 mb-1">
                نص السؤال:
              </label>
              <textarea
                rows={3}
                value={manualQuestion.question_text}
                onChange={(e) => setManualQuestion({ ...manualQuestion, question_text: e.target.value })}
                placeholder="اكتب منطوق السؤال التعليمي..."
                className="w-full p-2.5 border border-cocoa-200 rounded-lg text-xs focus:ring-2 focus:ring-gold-500"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-cocoa-700 mb-1">
                  نوع السؤال:
                </label>
                <select
                  value={manualQuestion.question_type}
                  onChange={(e) => setManualQuestion({ ...manualQuestion, question_type: e.target.value })}
                  className="w-full p-2 border border-cocoa-200 rounded-lg text-xs"
                >
                  <option value="mcq">اختيار من متعدد (MCQ)</option>
                  <option value="essay">سؤال مقالي (Essay)</option>
                  <option value="short_answer">إجابة قصيرة (Short Answer)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-cocoa-700 mb-1">
                  {manualQuestion.question_type === 'mcq' ? 'الإجابة الصحيحة المحددة:' : 'الإجابة النموذجية:'}
                </label>
                <input
                  type="text"
                  value={manualQuestion.correct_answer}
                  onChange={(e) => setManualQuestion({ ...manualQuestion, correct_answer: e.target.value })}
                  placeholder="الإجابة الصحيحة أو النموذجية..."
                  className="w-full p-2 border border-cocoa-200 rounded-lg text-xs"
                />
              </div>
            </div>

            {manualQuestion.question_type === 'mcq' && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="block text-xs font-medium text-cocoa-700">
                    خيارات الإجابة (انقر الحرف لتحديده كإجابة صحيحة):
                  </label>
                  <span className={`text-[11px] font-bold ${manualQuestion.correct_option ? 'text-emerald-700' : 'text-amber-700'}`}>
                    {manualQuestion.correct_option
                      ? `الخيار الصحيح المحدد: ${manualQuestion.correct_option}`
                      : 'لم يتم تحديد الخيار الصحيح بعد (مطلوب)'}
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {['A', 'B', 'C', 'D'].map((letter, i) => {
                    const isSelected = manualQuestion.correct_option === letter;
                    return (
                      <div key={i} className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => {
                            const optText = manualQuestion.options[i] || '';
                            setManualQuestion({
                              ...manualQuestion,
                              correct_option: letter,
                              correct_answer: optText,
                            });
                          }}
                          className={`w-6 h-6 rounded flex items-center justify-center font-bold text-xs transition-colors ${
                            isSelected
                              ? 'bg-emerald-600 text-white shadow-sm'
                              : 'bg-cocoa-100 text-cocoa-700 hover:bg-cocoa-200'
                          }`}
                          title={`تحديد ${letter} كإجابة صحيحة`}
                        >
                          {letter}
                        </button>
                        <input
                          type="text"
                          value={manualQuestion.options[i] || ''}
                          onChange={(e) => {
                            const newOpts = [...manualQuestion.options];
                            newOpts[i] = e.target.value;
                            const updateObj = { ...manualQuestion, options: newOpts };
                            if (manualQuestion.correct_option === letter) {
                              updateObj.correct_answer = e.target.value;
                            }
                            setManualQuestion(updateObj);
                          }}
                          placeholder={`الخيار ${letter}`}
                          className={`flex-1 p-2 border rounded-lg text-xs ${
                            isSelected ? 'border-emerald-500 bg-emerald-50/20' : 'border-cocoa-200'
                          }`}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Instant Classification Action */}
            <div className="p-3 bg-cocoa-50 rounded-lg border border-cocoa-200 flex items-center justify-between">
              <div>
                <div className="text-xs font-bold text-cocoa-900">تحليل وتأصيل المنهج الفوري</div>
                <div className="text-xs text-cocoa-500">
                  استرجاع الأدلة من Chroma واقتراح الصعوبة ومستوى بلوم وتأصيل المنهج
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleClassifyManual}
                loading={classifying}
              >
                <Sparkles className="w-3.5 h-3.5 ml-1 text-gold-600" />
                تحليل وتصنيف
              </Button>
            </div>

            {/* Preview Box */}
            {previewClassification && (
              <div className="p-3 bg-white border border-gold-300 rounded-lg text-xs space-y-2">
                <div className="font-bold text-cocoa-900 flex items-center justify-between">
                  <span>نتائج التصنيف المقترح:</span>
                  <Badge variant={previewClassification.classification_status === 'approved' ? 'success' : 'warning'}>
                    {previewClassification.classification_status === 'needs_review' ? 'تحتاج مراجعة' : 'بانتظار المراجعة'}
                  </Badge>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <div>
                    <span className="text-cocoa-500">مستوى بلوم: </span>
                    <span className="font-bold">{previewClassification.bloom_level}</span>
                  </div>
                  <div>
                    <span className="text-cocoa-500">الصعوبة: </span>
                    <span className="font-bold">{previewClassification.difficulty}</span>
                  </div>
                  <div>
                    <span className="text-cocoa-500">ثقة التصنيف: </span>
                    <span className="font-bold">
                      {previewClassification.classification_confidence !== null && previewClassification.classification_confidence !== undefined
                        ? `${(previewClassification.classification_confidence * 100).toFixed(0)}%`
                        : 'غير متاحة'}
                    </span>
                  </div>
                  <div>
                    <span className="text-cocoa-500">توثيق المنهج: </span>
                    <span className={`font-bold ${previewClassification.grounding_confidence > 0 ? 'text-emerald-700' : 'text-amber-600'}`}>
                      {previewClassification.grounding_confidence !== null && previewClassification.grounding_confidence !== undefined
                        ? (previewClassification.grounding_confidence > 0 ? `${(previewClassification.grounding_confidence * 100).toFixed(0)}%` : 'غير موثق')
                        : 'قيد التحقق'}
                    </span>
                  </div>
                </div>

                {(previewClassification.subject || previewClassification.lesson) && (
                  <div className="text-cocoa-700 bg-cocoa-50 p-2 rounded border border-cocoa-200 flex gap-4 text-[11px]">
                    {previewClassification.subject && (
                      <div>
                        <span className="text-cocoa-500">المادة: </span>
                        <span className="font-semibold">{previewClassification.subject}</span>
                      </div>
                    )}
                    {previewClassification.lesson && (
                      <div>
                        <span className="text-cocoa-500">الدرس: </span>
                        <span className="font-semibold">{previewClassification.lesson}</span>
                      </div>
                    )}
                  </div>
                )}

                {previewClassification.source_evidence && (
                  <div className="text-cocoa-700 bg-gold-50/50 p-2 rounded border border-gold-200">
                    <span className="font-bold">الشاهد المنهجي: </span>
                    "{previewClassification.source_evidence}"
                  </div>
                )}

                {previewClassification.classification_reasoning && (
                  <div className="text-cocoa-600 text-[11px] bg-slate-50 p-2 rounded border border-slate-200">
                    <span className="font-bold">تعليل التصنيف: </span>
                    {previewClassification.classification_reasoning}
                  </div>
                )}

                {previewClassification.review_reasons && previewClassification.review_reasons.length > 0 && (
                  <div className="text-amber-800 text-[11px] bg-amber-50 p-2 rounded border border-amber-200 space-y-1">
                    <span className="font-bold">تنبيهات المراجعة المطلوبة:</span>
                    <ul className="list-disc list-inside space-y-0.5">
                      {previewClassification.review_reasons.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-3 border-t border-cocoa-200">
              <Button variant="ghost" onClick={() => { setAddModalOpen(false); setModalError(null); }}>
                إلغاء
              </Button>
              <Button variant="primary" onClick={handleSaveManualQuestion} loading={loading}>
                حفظ في بنك الأسئلة
              </Button>
            </div>
          </div>
        </Modal>
      )}
      {/* =========================================================================
          MODAL: Cleaned Question Full Details
         ========================================================================= */}
      {cleanedDetailModalOpen && selectedCleanedQuestion && (
        <Modal
          isOpen={cleanedDetailModalOpen}
          onClose={() => setCleanedDetailModalOpen(false)}
          title={`تفاصيل السؤال من المجموعة المنقحة: ${selectedCleanedQuestion.question_id}`}
          size="lg"
        >
          <div className="space-y-4 text-cocoa-900 text-sm" dir="rtl">
            <div>
              <div className="text-xs text-cocoa-500 font-medium mb-1">نص السؤال:</div>
              <div className="p-3 bg-cocoa-50 rounded-lg font-medium text-cocoa-900 border border-cocoa-200 leading-relaxed" dir="auto">
                {selectedCleanedQuestion.question_text}
              </div>
            </div>

            {selectedCleanedQuestion.question_type === 'mcq' && (
              <div>
                <div className="text-xs text-cocoa-500 font-medium mb-1.5">خيارات الإجابة:</div>
                <div className="space-y-1.5">
                  {['option_A', 'option_B', 'option_C', 'option_D'].map((optKey, idx) => {
                    const letter = ['A', 'B', 'C', 'D'][idx];
                    const optVal = selectedCleanedQuestion[optKey];
                    const isCorrect = selectedCleanedQuestion.correct_option === letter;
                    if (!optVal) return null;
                    return (
                      <div
                        key={letter}
                        className={`p-2.5 rounded-lg border text-xs flex items-center justify-between ${
                          isCorrect
                            ? 'bg-emerald-50 border-emerald-300 font-bold text-emerald-900'
                            : 'bg-white border-cocoa-200 text-cocoa-800'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${
                            isCorrect ? 'bg-emerald-600 text-white' : 'bg-cocoa-200 text-cocoa-700'
                          }`}>
                            {letter}
                          </span>
                          <span dir="auto">{optVal}</span>
                        </div>
                        {isCorrect && (
                          <span className="text-xs font-bold text-emerald-700 flex items-center gap-1">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            الخيار الصحيح
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div>
              <div className="text-xs text-cocoa-500 font-medium mb-1">الإجابة النموذجية المعتمدة:</div>
              <div className="p-3 bg-emerald-50/60 rounded-lg font-medium text-emerald-950 border border-emerald-200 leading-relaxed" dir="auto">
                {selectedCleanedQuestion.correct_answer || 'غير متوفرة'}
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5 pt-2 border-t border-cocoa-100 text-xs">
              <div className="p-2 rounded bg-cocoa-50/60 border border-cocoa-200">
                <span className="text-cocoa-500 block">المعرف الأصلي:</span>
                <span className="font-code font-bold text-cocoa-800">{selectedCleanedQuestion.original_question_id || 'غير متوفر'}</span>
              </div>
              <div className="p-2 rounded bg-cocoa-50/60 border border-cocoa-200">
                <span className="text-cocoa-500 block">نوع السؤال:</span>
                <span className="font-bold text-cocoa-800">{selectedCleanedQuestion.question_type === 'mcq' ? 'اختيار من متعدد' : 'سؤال مقالي'}</span>
              </div>
              <div className="p-2 rounded bg-cocoa-50/60 border border-cocoa-200">
                <span className="text-cocoa-500 block">حالة التحقق:</span>
                <span className="font-bold text-emerald-700">{selectedCleanedQuestion.verification_status || 'verified'}</span>
              </div>
              <div className="p-2 rounded bg-cocoa-50/60 border border-cocoa-200">
                <span className="text-cocoa-500 block">الفصل:</span>
                <span className="font-bold text-cocoa-800">{selectedCleanedQuestion.chapter || 'غير محدد'}</span>
              </div>
              <div className="p-2 rounded bg-cocoa-50/60 border border-cocoa-200">
                <span className="text-cocoa-500 block">الدرس:</span>
                <span className="font-bold text-cocoa-800">{selectedCleanedQuestion.lesson || 'غير محدد'}</span>
              </div>
              <div className="p-2 rounded bg-cocoa-50/60 border border-cocoa-200">
                <span className="text-cocoa-500 block">رقم الصفحة:</span>
                <span className="font-bold text-cocoa-800">{selectedCleanedQuestion.page_number || 'غير متوفر'}</span>
              </div>
              <div className="p-2 rounded bg-cocoa-50/60 border border-cocoa-200">
                <span className="text-cocoa-500 block">الملف المصدري:</span>
                <span className="font-code font-bold text-cocoa-800 truncate block">{selectedCleanedQuestion.source_file || 'غير متوفر'}</span>
              </div>
              <div className="p-2 rounded bg-cocoa-50/60 border border-cocoa-200">
                <span className="text-cocoa-500 block">مصدر الإجابة:</span>
                <span className="font-bold text-cocoa-800">{selectedCleanedQuestion.answer_source || 'غير متوفر'}</span>
              </div>
              <div className="p-2 rounded bg-cocoa-50/60 border border-cocoa-200">
                <span className="text-cocoa-500 block">المصدر:</span>
                <span className="font-bold text-cocoa-800">{selectedCleanedQuestion.Source || 'غير متوفر'}</span>
              </div>
            </div>

            <div className="p-2.5 rounded bg-amber-50 border border-amber-200 text-amber-800 text-xs">
              <span className="font-bold">ملاحظة: </span>
              هذا السجل مسترجع مباشرة من مجموعة البيانات المنقحة (ملف الإكسل الأصلي الموثق) دون أي إدراج في قاعدة بيانات النظام الإنتاجية أو تعديل.
            </div>

            <div className="flex justify-end pt-2 border-t border-cocoa-200">
              <Button variant="outline" size="sm" onClick={() => setCleanedDetailModalOpen(false)}>
                إغلاق
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};

export default QuestionBank;

