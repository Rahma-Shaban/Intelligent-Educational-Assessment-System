import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { uploadCurriculum, getDocuments } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Alert from '../../components/ui/Alert';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import {
  UploadCloud,
  FileText,
  CheckCircle2,
  ArrowLeft,
  BookOpen,
  Trash2,
  Layers,
  Library,
  Calendar,
  ChevronDown,
  Sparkles,
  AlertTriangle,
} from 'lucide-react';

const SELECTED_DOC_KEY = 'iqyas.selectedCurriculumId';

const formatArabicDate = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('ar-EG', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return iso;
  }
};

const DocumentLibrary = () => {
  const [documents, setDocuments] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [docsError, setDocsError] = useState('');

  const [file, setFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [uploadError, setUploadError] = useState('');
  const fileInputRef = useRef(null);

  const [expandedId, setExpandedId] = useState(null);
  const [selectedDocId, setSelectedDocId] = useState(() => {
    const saved = localStorage.getItem(SELECTED_DOC_KEY);
    return saved ? Number(saved) : null;
  });

  const refreshDocuments = useCallback(async () => {
    setLoadingDocs(true);
    setDocsError('');
    try {
      const data = await getDocuments();
      setDocuments(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Failed to load document library:', err);
      setDocsError('فشل تحميل مكتبة المناهج. تأكد إن السيرفر شغال وحاول تاني.');
    } finally {
      setLoadingDocs(false);
    }
  }, []);

  useEffect(() => {
    refreshDocuments();
  }, [refreshDocuments]);

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') setDragActive(true);
    else if (e.type === 'dragleave') setDragActive(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const validateAndSetFile = (selectedFile) => {
    setUploadError('');
    setUploadResult(null);
    if (!selectedFile.name.toLowerCase().endsWith('.pdf')) {
      setUploadError('لازم ترفع ملف PDF صحيح.');
      return;
    }
    if (selectedFile.size > 50 * 1024 * 1024) {
      setUploadError('حجم الملف أكبر من الحد الأقصى (٥٠ ميجابايت).');
      return;
    }
    setFile(selectedFile);
  };

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setUploadError('');
    setUploadResult(null);
    try {
      const response = await uploadCurriculum(file);
      setUploadResult(response);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      await refreshDocuments();
    } catch (err) {
      console.error('Curriculum upload error:', err);
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        'فشل رفع وفهرسة ملف المنهج. حاول تاني.';
      setUploadError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setUploading(false);
    }
  };

  const clearSelectedFile = () => {
    setFile(null);
    setUploadResult(null);
    setUploadError('');
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleMarkSelected = (docId) => {
    const next = selectedDocId === docId ? null : docId;
    setSelectedDocId(next);
    if (next) localStorage.setItem(SELECTED_DOC_KEY, String(next));
    else localStorage.removeItem(SELECTED_DOC_KEY);
  };

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* Page header */}
      <div className="relative">
        <span className="code-chip absolute -top-3 end-0 rotate-2 hidden md:inline-block">
          library.list(documents)
        </span>
        <h1 className="font-display text-3xl md:text-4xl text-ink">مكتبة المناهج 📚</h1>
        <p className="text-sm text-cocoa-500 mt-1 leading-relaxed">
          كل الكتب والمذكرات اللي رفعتها في مكان واحد. اختار الكتاب اللي هيكون مصدر
          الامتحانات، وارفع كتب جديدة وقت ما تحب.
        </p>
      </div>

      {/* Step 1: existing documents first */}
      <section className="space-y-4" aria-label="الكتب المرفوعة">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-extrabold text-ink flex items-center gap-2">
            <Library className="w-5 h-5 text-clay-600" />
            الكتب المرفوعة ({documents.length})
          </h2>
          <Link
            to="/professor/generate"
            className="text-xs font-bold text-clay-700 hover:text-clay-600 flex items-center gap-1"
          >
            ولّد امتحان من كتاب <Sparkles className="w-3.5 h-3.5" />
          </Link>
        </div>

        {loadingDocs ? (
          <Card className="py-8">
            <LoadingSpinner size="md" message="جاري تحميل المكتبة..." />
          </Card>
        ) : docsError ? (
          <Alert type="error" title="خطأ في تحميل المكتبة" message={docsError} />
        ) : documents.length === 0 ? (
          <Card className="text-center py-12">
            <div className="w-14 h-14 bg-clay-100 text-clay-600 rounded-2xl rounded-br-md flex items-center justify-center mx-auto mb-3 -rotate-3">
              <Library className="w-7 h-7" />
            </div>
            <h3 className="text-lg font-extrabold text-ink">المكتبة فاضية لسه</h3>
            <p className="text-sm text-cocoa-500 mt-1 max-w-md mx-auto">
              ارفع أول كتاب من الأسفل، وبعد الفهرسة هيظهر هنا بقائمة دروسه.
            </p>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {documents.map((doc) => {
              const isSelected = selectedDocId === doc.id;
              const isExpanded = expandedId === doc.id;
              return (
                <Card
                  key={doc.id}
                  className={`flex flex-col justify-between ${
                    isSelected
                      ? '!border-gold-400 ring-2 ring-gold-300 shadow-pop'
                      : 'hover:border-clay-300'
                  }`}
                >
                  <div className="space-y-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-3 min-w-0">
                        <div
                          className={`w-11 h-11 rounded-2xl rounded-br-sm flex items-center justify-center shrink-0 ${
                            isSelected
                              ? 'bg-gold-400 text-clay-950'
                              : 'bg-clay-100 text-clay-700'
                          }`}
                        >
                          <FileText className="w-5 h-5" />
                        </div>
                        <div className="min-w-0">
                          <h3
                            className="text-sm font-extrabold text-ink truncate font-code"
                            dir="ltr"
                            title={doc.filename}
                          >
                            {doc.filename}
                          </h3>
                          <p className="text-[11px] text-cocoa-500 flex items-center gap-1 mt-0.5">
                            <Calendar className="w-3 h-3" />
                            {formatArabicDate(doc.uploaded_at)}
                          </p>
                        </div>
                      </div>
                      {isSelected ? (
                        <span className="sticker !text-[10px] !py-0.5 !px-2.5 text-gold-700 shrink-0">
                          ✦ مصدر الامتحانات
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => handleMarkSelected(doc.id)}
                          className="text-[11px] font-bold text-cocoa-500 hover:text-clay-700 underline underline-offset-2 shrink-0"
                        >
                          اجعله مصدر الامتحانات
                        </button>
                      )}
                    </div>

                    <div className="flex items-center gap-2 text-xs text-cocoa-500">
                      <span className="bg-cream px-2.5 py-1 rounded-lg border border-sand font-bold flex items-center gap-1.5">
                        <Layers className="w-3.5 h-3.5 text-clay-500" />
                        {doc.lesson_count} درس
                      </span>
                      <button
                        type="button"
                        onClick={() => setExpandedId(isExpanded ? null : doc.id)}
                        className="flex items-center gap-1 font-bold text-clay-700 hover:text-clay-600"
                        aria-expanded={isExpanded}
                      >
                        <BookOpen className="w-3.5 h-3.5" />
                        {isExpanded ? 'إخفاء الدروس' : 'عرض الدروس'}
                        <ChevronDown
                          className={`w-3.5 h-3.5 transition-transform ${
                            isExpanded ? 'rotate-180' : ''
                          }`}
                        />
                      </button>
                    </div>

                    {isExpanded && (
                      <div className="border border-sand rounded-xl divide-y divide-sand max-h-44 overflow-y-auto bg-cream/60">
                        {doc.lessons.length === 0 ? (
                          <p className="text-xs text-cocoa-500 p-3 text-center">
                            مفيش دروس مسجّلة لهذا الكتاب.
                          </p>
                        ) : (
                          doc.lessons.map((lesson, idx) => (
                            <div
                              key={lesson.lesson_id || idx}
                              className="px-3 py-2 text-xs flex items-center gap-2"
                            >
                              <span className="w-5 h-5 rounded-md rounded-br-sm bg-sand text-cocoa-800 font-bold flex items-center justify-center text-[10px] shrink-0">
                                {idx + 1}
                              </span>
                              <span className="font-bold text-cocoa-800 truncate" dir="auto">
                                {lesson.lesson_title || lesson.title || lesson.lesson_id}
                              </span>
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </section>

      {/* Step 2: upload area */}
      <section className="space-y-4" aria-label="رفع كتاب جديد">
        <h2 className="text-lg font-extrabold text-ink flex items-center gap-2">
          <UploadCloud className="w-5 h-5 text-clay-600" />
          رفع كتاب جديد
        </h2>

        {uploadError && (
          <Alert
            type="error"
            title="مشكلة في الرفع"
            message={uploadError}
            onClose={() => setUploadError('')}
          />
        )}

        {uploadResult && (
          <Alert
            type="success"
            title="الكتاب اتفهرس بنجاح!"
            message={`تمت فهرسة ${uploadResult.lesson_count} درس من «${uploadResult.filename}» وهو دلوقتي ظاهر في مكتبتك.`}
            onClose={() => setUploadResult(null)}
          />
        )}

        <Card>
          <div
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            className={`border-2 border-dashed rounded-2xl p-8 text-center transition-all ${
              dragActive
                ? 'border-gold-500 bg-gold-100/40 scale-[1.01]'
                : file
                ? 'border-clay-300 bg-clay-50/30'
                : 'border-cocoa-300/60 hover:border-gold-400 bg-cream/60'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              onChange={(e) => e.target.files?.[0] && validateAndSetFile(e.target.files[0])}
              className="hidden"
              id="curriculum-upload-input"
            />

            {!file ? (
              <div className="flex flex-col items-center justify-center space-y-4">
                <div className="w-16 h-16 rounded-2xl rounded-br-md bg-clay-100 text-clay-600 flex items-center justify-center shadow-inner -rotate-3">
                  <UploadCloud className="w-8 h-8" />
                </div>
                <div>
                  <p className="text-base font-bold text-cocoa-800">اسحب ملف الكتاب وحطه هنا</p>
                  <p className="text-xs text-cocoa-500 mt-1">كتب ومحاضرات PDF — لحد ٥٠ ميجابايت</p>
                </div>
                <label
                  htmlFor="curriculum-upload-input"
                  className="cursor-pointer inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-b from-clay-600 to-clay-800 hover:from-clay-500 text-white rounded-xl text-sm font-bold transition-all shadow-warm btn-cut"
                >
                  <FileText className="w-4 h-4" />
                  اختار الملف من جهازك
                </label>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center space-y-4">
                <div className="w-14 h-14 rounded-2xl rounded-br-md bg-teal-50 text-teal-700 flex items-center justify-center shadow-inner rotate-2">
                  <FileText className="w-7 h-7" />
                </div>
                <div className="space-y-1">
                  <h4 className="text-base font-bold text-ink truncate max-w-md font-code" dir="ltr">
                    {file.name}
                  </h4>
                  <p className="text-xs text-cocoa-500 font-bold">
                    {(file.size / (1024 * 1024)).toFixed(2)} MB • ملف PDF
                  </p>
                </div>
                <div className="flex items-center gap-3 pt-2">
                  <Button
                    variant="primary"
                    size="md"
                    onClick={handleUpload}
                    loading={uploading}
                    icon={UploadCloud}
                    className="btn-cut"
                  >
                    {uploading ? 'جاري الفهرسة...' : 'فهرس الكتاب'}
                  </Button>
                  {!uploading && (
                    <Button variant="secondary" size="md" onClick={clearSelectedFile} icon={Trash2}>
                      شيله
                    </Button>
                  )}
                </div>
              </div>
            )}
          </div>

          {uploading && (
            <div className="mt-6 p-4 bg-gold-50 border border-gold-200 rounded-2xl space-y-2">
              <div className="flex items-center justify-between text-xs font-bold text-gold-700">
                <span className="flex items-center gap-2">
                  <Layers className="w-4 h-4 animate-spin text-gold-600" />
                  بنستخرج الفصول ونقسّم المحتوى ونحسب الـ embeddings...
                </span>
                <span>جاري التنفيذ</span>
              </div>
              <div className="w-full bg-gold-200 rounded-full h-1.5 overflow-hidden">
                <div className="bg-gradient-to-l from-gold-400 to-clay-600 h-1.5 rounded-full animate-pulse w-3/4" />
              </div>
            </div>
          )}
        </Card>

        <div className="flex items-start gap-2.5 p-3 bg-cream rounded-xl text-xs text-cocoa-500 border border-sand">
          <AlertTriangle className="w-4 h-4 text-gold-600 shrink-0 mt-0.5" />
          <span>
            كل كتاب بياخد مجموعة بحث منفصلة خاصة بيه، فامتحانات كل كتاب بتطلع من محتواه هو بالظبط.
          </span>
        </div>
      </section>
    </div>
  );
};

export default DocumentLibrary;
