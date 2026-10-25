import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { uploadCurriculum } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Alert from '../../components/ui/Alert';
import Badge from '../../components/ui/Badge';
import {
  UploadCloud,
  FileText,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Trash2,
  Layers,
} from 'lucide-react';

const UploadCurriculum = () => {
  const [file, setFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const fileInputRef = useRef(null);
  const navigate = useNavigate();

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const validateAndSetFile = (selectedFile) => {
    setError('');
    setResult(null);

    if (selectedFile.type !== 'application/pdf' && !selectedFile.name.toLowerCase().endsWith('.pdf')) {
      setError('Please upload a valid PDF document (.pdf).');
      return;
    }

    if (selectedFile.size > 50 * 1024 * 1024) {
      setError('File size exceeds the 50MB maximum limit.');
      return;
    }

    setFile(selectedFile);
  };

  const handleUpload = async () => {
    if (!file) return;

    setUploading(true);
    setError('');
    setResult(null);

    try {
      const response = await uploadCurriculum(file);
      setResult(response);
    } catch (err) {
      console.error('Curriculum upload error:', err);
      const detail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        'Failed to process curriculum file. If this collection was already indexed, try generating an exam directly.';
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setUploading(false);
    }
  };

  const clearSelectedFile = () => {
    setFile(null);
    setResult(null);
    setError('');
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Page Title */}
      <div>
        <h1 className="text-2xl md:text-3xl font-extrabold text-gray-900 tracking-tight">
          Curriculum Ingestion
        </h1>
        <p className="text-sm text-gray-600 mt-1">
          Upload course textbooks, syllabus units, or lecture slide PDFs to vectorize and build a RAG knowledge base.
        </p>
      </div>

      {error && (
        <Alert
          type="error"
          title="Upload Error"
          message={error}
          onClose={() => setError('')}
        />
      )}

      {/* Upload Box */}
      <Card>
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-xl p-8 sm:p-12 text-center transition-all ${
            dragActive
              ? 'border-indigo-600 bg-indigo-50/50 scale-[1.01]'
              : file
              ? 'border-indigo-300 bg-indigo-50/20'
              : 'border-gray-300 hover:border-gray-400 bg-gray-50/50'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,application/pdf"
            onChange={handleFileChange}
            className="hidden"
            id="curriculum-upload-input"
          />

          {!file ? (
            <div className="flex flex-col items-center justify-center space-y-4">
              <div className="w-16 h-16 rounded-2xl bg-indigo-50 text-indigo-600 flex items-center justify-center shadow-inner">
                <UploadCloud className="w-8 h-8" />
              </div>
              <div>
                <p className="text-base font-semibold text-gray-800">
                  Drag & drop your curriculum PDF here
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  Supports course textbooks and lecture PDFs up to 50MB
                </p>
              </div>
              <label
                htmlFor="curriculum-upload-input"
                className="cursor-pointer inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-colors shadow-sm"
              >
                <FileText className="w-4 h-4" />
                Browse Local PDF
              </label>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center space-y-4">
              <div className="w-14 h-14 rounded-2xl bg-emerald-50 text-emerald-600 flex items-center justify-center shadow-inner">
                <FileText className="w-7 h-7" />
              </div>
              <div className="space-y-1">
                <h4 className="text-base font-bold text-gray-900 truncate max-w-md">
                  {file.name}
                </h4>
                <p className="text-xs text-gray-500 font-medium">
                  {(file.size / (1024 * 1024)).toFixed(2)} MB &bull; PDF Document
                </p>
              </div>
              <div className="flex items-center gap-3 pt-2">
                <Button
                  variant="primary"
                  size="md"
                  onClick={handleUpload}
                  loading={uploading}
                  icon={UploadCloud}
                >
                  {uploading ? 'Processing & Indexing...' : 'Index Curriculum'}
                </Button>
                {!uploading && (
                  <Button
                    variant="secondary"
                    size="md"
                    onClick={clearSelectedFile}
                    icon={Trash2}
                  >
                    Remove
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>

        {uploading && (
          <div className="mt-6 p-4 bg-indigo-50/70 border border-indigo-100 rounded-xl space-y-2">
            <div className="flex items-center justify-between text-xs font-semibold text-indigo-900">
              <span className="flex items-center gap-2">
                <Layers className="w-4 h-4 animate-spin text-indigo-600" />
                Extracting chapters, splitting chunks, and computing vector embeddings...
              </span>
              <span>In Progress</span>
            </div>
            <div className="w-full bg-indigo-200 rounded-full h-1.5 overflow-hidden">
              <div className="bg-indigo-600 h-1.5 rounded-full animate-pulse w-3/4"></div>
            </div>
            <p className="text-[11px] text-indigo-600">
              This process indexes every curriculum section to ensure all generated exam questions have verbatim citations.
            </p>
          </div>
        )}
      </Card>

      {/* Success Ingestion Result */}
      {result && (
        <Card className="border-emerald-200 bg-emerald-50/20">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="w-6 h-6 text-emerald-600 shrink-0 mt-0.5" />
            <div className="flex-1 space-y-3">
              <div>
                <h3 className="text-base font-bold text-emerald-900">
                  Curriculum Indexed Successfully!
                </h3>
                <p className="text-xs text-emerald-700 mt-0.5">
                  The document has been chunked and stored in the Chroma vector database.
                </p>
              </div>

              {/* Extracted lessons list */}
              {(result.lessons || result.extracted_lessons || result.sections) && (
                <div className="bg-white p-4 rounded-xl border border-emerald-100 space-y-2">
                  <h4 className="text-xs font-bold text-gray-700 uppercase tracking-wider flex items-center gap-1.5">
                    <BookOpen className="w-3.5 h-3.5 text-indigo-600" />
                    Detected Lessons & Topics (
                    {(result.lessons || result.extracted_lessons || result.sections).length}
                    )
                  </h4>
                  <div className="divide-y divide-gray-100 max-h-56 overflow-y-auto">
                    {(result.lessons || result.extracted_lessons || result.sections).map(
                      (lesson, idx) => (
                        <div
                          key={lesson.id || lesson.lesson_id || idx}
                          className="py-2 flex items-center justify-between text-xs"
                        >
                          <span className="font-medium text-gray-800">
                            {lesson.title || lesson.name || `Lesson ${idx + 1}`}
                          </span>
                          {lesson.chunks_count && (
                            <Badge variant="info" size="sm">
                              {lesson.chunks_count} chunks
                            </Badge>
                          )}
                        </div>
                      )
                    )}
                  </div>
                </div>
              )}

              <div className="pt-2 flex justify-end">
                <Button
                  variant="primary"
                  onClick={() => navigate('/professor/generate')}
                  icon={ArrowRight}
                >
                  Proceed to Generate Exam
                </Button>
              </div>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
};

export default UploadCurriculum;
