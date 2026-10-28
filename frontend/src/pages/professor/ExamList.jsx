import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { getExams, togglePublishExam } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  BookOpen,
  Sparkles,
  Search,
  Filter,
  Eye,
  Calendar,
  Layers,
  Award,
  ArrowLeft,
  Code2,
} from 'lucide-react';

const ExamList = () => {
  const [exams, setExams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [filterDifficulty, setFilterDifficulty] = useState('all');
  const [togglingId, setTogglingId] = useState(null);

  const handleTogglePublish = async (examId, currentStatus) => {
    setTogglingId(examId);
    try {
      const updated = await togglePublishExam(examId, !currentStatus);
      setExams((prev) =>
        prev.map((ex) => (ex.id === examId ? { ...ex, is_published: updated.is_published } : ex))
      );
    } catch (err) {
      console.error('Failed to toggle publish status:', err);
      setError('معرفناش نغيّر حالة النشر، حاول تاني.');
    } finally {
      setTogglingId(null);
    }
  };

  useEffect(() => {
    const fetchExams = async () => {
      setLoading(true);
      setError('');
      try {
        const data = await getExams();
        const list = Array.isArray(data) ? data : data?.exams || [];
        setExams(list);
      } catch (err) {
        console.error('Failed to fetch exams:', err);
        setError('فشل تحميل قائمة الامتحانات، حاول تاني.');
      } finally {
        setLoading(false);
      }
    };

    fetchExams();
  }, []);

  const filteredExams = exams.filter((exam) => {
    const title = (exam.title || exam.topic || `Exam #${exam.id}`).toLowerCase();
    const topic = (exam.topic || '').toLowerCase();
    const lesson = (exam.lesson_title || exam.lesson || '').toLowerCase();
    const matchesSearch =
      title.includes(searchQuery.toLowerCase()) ||
      topic.includes(searchQuery.toLowerCase()) ||
      lesson.includes(searchQuery.toLowerCase());

    const matchesDiff =
      filterDifficulty === 'all' ||
      (exam.difficulty && exam.difficulty.toLowerCase() === filterDifficulty.toLowerCase());

    return matchesSearch && matchesDiff;
  });

  if (loading) {
    return <LoadingSpinner size="lg" message="جاري تحميل الامتحانات..." />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="relative">
          <span className="code-chip absolute -top-3 end-0 rotate-2 hidden md:inline-block">exams.filter(status)</span>
          <h1 className="font-display text-3xl md:text-4xl text-ink">قائمة الامتحانات 📚</h1>
          <p className="text-sm text-cocoa-500 mt-1">
            راجع الامتحانات ومفاتيح الإجابة ونماذج التصحيح والمصادر.
          </p>
        </div>
        <Link to="/professor/generate">
          <Button variant="primary" size="md" icon={Sparkles} className="btn-cut">
            إنشاء امتحان جديد
          </Button>
        </Link>
      </div>

      {error && <Alert type="error" message={error} onClose={() => setError('')} />}

      {/* Filter and Search Bar */}
      <Card className="p-4">
        <div className="flex flex-col sm:flex-row gap-4 items-center justify-between">
          <div className="relative w-full sm:w-80">
            <Search className="w-4 h-4 text-cocoa-300 absolute start-3 top-3 pointer-events-none" />
            <input
              type="text"
              placeholder="دوّر بالعنوان أو الموضوع..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full ps-10 pe-3 py-2 text-sm bg-white border-2 border-cocoa-300/60 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 outline-none transition"
            />
          </div>

          <div className="flex items-center gap-3 w-full sm:w-auto">
            <Filter className="w-4 h-4 text-cocoa-300 shrink-0" />
            <select
              value={filterDifficulty}
              onChange={(e) => setFilterDifficulty(e.target.value)}
              className="w-full sm:w-44 px-3 py-2 text-sm bg-white border-2 border-cocoa-300/60 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 outline-none transition"
            >
              <option value="all">كل المستويات</option>
              <option value="easy">سهل</option>
              <option value="medium">متوسط</option>
              <option value="hard">صعب</option>
            </select>
          </div>
        </div>
      </Card>

      {/* Exam Cards */}
      {filteredExams.length === 0 ? (
        <Card className="text-center py-16">
          <div className="w-14 h-14 bg-clay-100 text-clay-600 rounded-2xl rounded-br-md flex items-center justify-center mx-auto mb-3 -rotate-3">
            <Code2 className="w-7 h-7" />
          </div>
          <h3 className="text-lg font-extrabold text-ink">
            {exams.length === 0 ? 'لسه مفيش امتحانات' : 'مفيش نتائج مطابقة'}
          </h3>
          <p className="text-sm text-cocoa-500 mt-1 max-w-md mx-auto">
            {exams.length === 0
              ? 'ابدأ برفع ملف المنهج وولّد أول امتحان ذكي.'
              : 'جرّب تغيّر البحث أو الفلتر.'}
          </p>
          {exams.length === 0 && (
            <div className="mt-5">
              <Link to="/professor/generate">
                <Button icon={Sparkles} className="btn-cut">ولّد امتحان دلوقتي</Button>
              </Link>
            </div>
          )}
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredExams.map((exam) => {
            const examId = exam.id || exam._id || exam.exam_id;
            const qCount =
              exam.questions?.length || exam.question_count || exam.num_questions || 0;
            const totalPoints =
              exam.total_points ||
              exam.max_score ||
              (exam.questions ? exam.questions.reduce((a, b) => a + (b.max_score || 1), 0) : 0);
            const dateStr = exam.created_at
              ? new Date(exam.created_at).toLocaleDateString('ar-EG', {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                })
              : 'حديثاً';

            return (
              <Card
                key={examId || Math.random()}
                className="flex flex-col justify-between hover:border-gold-400 transition-all"
              >
                <div className="space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-bold text-cocoa-300 flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5" />
                      {dateStr}
                    </span>
                    <div className="flex items-center gap-1.5 flex-wrap justify-end">
                      <span
                        className={`sticker !text-[10px] !py-0.5 !px-2.5 ${
                          exam.is_published ? 'text-teal-700' : 'text-gold-600'
                        }`}
                        style={{ borderWidth: 1.5 }}
                      >
                        {exam.is_published ? '🟢 منشور' : '✏️ مسودة'}
                      </span>
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
                    </div>
                  </div>

                  <div>
                    <h3 className="text-base font-extrabold text-ink line-clamp-2 hover:text-clay-600 transition-colors">
                      <Link to={`/professor/exams/${examId}`} dir="auto">
                        {exam.title || exam.topic || `Exam #${examId}`}
                      </Link>
                    </h3>
                    <p className="text-xs text-cocoa-500 mt-1 line-clamp-1" dir="auto">
                      {exam.lesson_title || exam.lesson || (exam.topic && `Topic: ${exam.topic}`) || 'امتحان من المنهج'}
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-sand text-xs">
                    <div className="flex items-center gap-1.5 text-cocoa-500">
                      <Layers className="w-3.5 h-3.5 text-clay-500" />
                      <span>{qCount} سؤال</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-cocoa-500 justify-end">
                      <Award className="w-3.5 h-3.5 text-gold-600" />
                      <span className="font-bold text-cocoa-800">{totalPoints} درجة</span>
                    </div>
                  </div>
                </div>

                <div className="pt-4 mt-3 border-t border-sand flex items-center justify-between gap-2">
                  <Button
                    variant={exam.is_published ? 'ghost' : 'primary'}
                    size="sm"
                    loading={togglingId === examId}
                    onClick={() => handleTogglePublish(examId, exam.is_published)}
                  >
                    {exam.is_published ? 'إلغاء النشر' : 'انشر للطلبة'}
                  </Button>
                  <Link to={`/professor/exams/${examId}`}>
                    <Button variant="outline" size="sm" icon={Eye}>
                      التفاصيل
                    </Button>
                  </Link>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default ExamList;
