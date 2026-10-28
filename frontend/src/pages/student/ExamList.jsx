import React, { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getExams } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import ProfessorPicker from '../../components/ProfessorPicker';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  BookOpen,
  Play,
  Search,
  Filter,
  Layers,
  Award,
  Clock,
  Sparkles,
  GraduationCap,
} from 'lucide-react';

const StudentExamList = () => {
  const { user } = useAuth();
  const hasProfessor = Boolean(user?.selected_professor_id);
  const [exams, setExams] = useState([]);
  const [loading, setLoading] = useState(hasProfessor);
  const [error, setError] = useState('');
  const [startingId, setStartingId] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterDifficulty, setFilterDifficulty] = useState('all');

  const navigate = useNavigate();

  const fetchExams = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getExams();
      const list = Array.isArray(data) ? data : data?.exams || [];
      setExams(list);
    } catch (err) {
      console.error('Failed to load available exams:', err);
      setError('فشل تحميل الامتحانات المتاحة.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // The backend scopes the exam list to the student's selected professor;
    // only fetch (or refetch) once a professor is chosen.
    if (hasProfessor) {
      fetchExams();
    } else {
      setExams([]);
      setLoading(false);
    }
  }, [hasProfessor, fetchExams]);

  const handleStartExam = (examId) => {
    navigate(`/student/exam/${examId}`);
  };

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
      <div className="relative">
        <span className="code-chip absolute -top-3 end-0 rotate-2 hidden md:inline-block">exams.filter(available)</span>
        <h1 className="font-display text-3xl md:text-4xl text-ink">الامتحانات المتاحة 🗺️</h1>
        <p className="text-sm text-cocoa-500 mt-1">
          اختار امتحان واختبر نفسك — كل الأسئلة مبنية على منهجك ومتولّدة بالإنجليزي.
        </p>
      </div>

      {error && <Alert type="error" message={error} onClose={() => setError('')} />}

      {/* Professor selection — persisted on the account, exams are scoped to it */}
      <ProfessorPicker onSaved={fetchExams} />

      {/* Search and Filters (only meaningful once a professor is selected) */}
      {hasProfessor && (
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
      )}

      {/* Grid of Exams */}
      {!hasProfessor ? (
        <Card className="text-center py-16">
          <div className="w-14 h-14 bg-gold-100 text-gold-700 rounded-2xl rounded-br-md flex items-center justify-center mx-auto mb-3 -rotate-3">
            <GraduationCap className="w-8 h-8" />
          </div>
          <h3 className="text-lg font-extrabold text-ink">اختار أستاذك الأول</h3>
          <p className="text-sm text-cocoa-500 mt-1 max-w-md mx-auto leading-relaxed">
            امتحانات المنصة بتظهر حسب الأستاذ اللي بتدرس معاه. اختار أستاذك من الخانة اللي فوق
            وهتظهر لك كل امتحاناته المنشورة هنا فوراً.
          </p>
        </Card>
      ) : filteredExams.length === 0 ? (
        <Card className="text-center py-16">
          <div className="w-14 h-14 bg-teal-50 text-teal-700 rounded-2xl rounded-br-md flex items-center justify-center mx-auto mb-3 -rotate-3 text-2xl">
            🦉
          </div>
          <h3 className="text-lg font-extrabold text-ink">
            {exams.length === 0 ? 'لسه مفيش امتحانات متاحة' : 'مفيش نتائج مطابقة'}
          </h3>
          <p className="text-sm text-cocoa-500 mt-1 max-w-md mx-auto">
            {exams.length === 0
              ? 'الأستاذ لسه م publish اش امتحانات — عاّد بعد شوية!'
              : 'جرّب تغيّر البحث أو الفلتر.'}
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredExams.map((exam, idx) => {
            const examId = exam.id || exam._id || exam.exam_id;
            const qCount =
              exam.questions?.length || exam.question_count || exam.num_questions || 0;
            const totalPoints =
              exam.total_points ||
              exam.max_score ||
              (exam.questions ? exam.questions.reduce((a, b) => a + (b.max_score || 1), 0) : 0);
            const estMinutes = Math.max(10, qCount * 5);
            const covers = [
              'from-clay-600 to-clay-900',
              'from-teal-500 to-teal-800',
              'from-gold-500 to-clay-800',
            ];
            const cover = covers[idx % covers.length];

            return (
              <Card
                key={examId || Math.random()}
                className="flex flex-col justify-between overflow-hidden !p-0 hover:border-gold-400 hover:-translate-y-1 hover:rotate-[-0.4deg] transition-all"
              >
                <div className={`relative bg-gradient-to-bl ${cover} p-5 pb-4 text-white`}>
                  <span className="absolute top-2 start-4 font-display text-4xl opacity-25">
                    {idx + 1}
                  </span>
                  <h3 className="font-extrabold text-[15px] leading-snug relative" dir="auto">
                    {exam.title || exam.topic || `Assessment #${examId}`}
                  </h3>
                  <p className="text-[11px] text-white/80 mt-1 relative line-clamp-1" dir="auto">
                    {exam.lesson_title || exam.lesson || (exam.topic && `Topic: ${exam.topic}`) || 'امتحان من المنهج'}
                  </p>
                </div>

                <div className="space-y-3 p-4 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-bold text-cocoa-300 flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5" />
                      ~{estMinutes} دقيقة
                    </span>
                    <div className="flex items-center gap-1.5">
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

                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-sand text-xs text-cocoa-500">
                    <div className="flex items-center gap-1.5">
                      <Layers className="w-3.5 h-3.5 text-clay-500" />
                      <span>{qCount} سؤال</span>
                    </div>
                    <div className="flex items-center gap-1.5 justify-end">
                      <Award className="w-3.5 h-3.5 text-gold-600" />
                      <span className="font-bold text-cocoa-800">{totalPoints} درجة</span>
                    </div>
                  </div>
                </div>

                <div className="p-4 pt-0">
                  <Button
                    variant="primary"
                    size="md"
                    className="w-full btn-cut"
                    icon={Play}
                    loading={startingId === examId}
                    onClick={() => handleStartExam(examId)}
                  >
                    ابدأ الامتحان 🚀
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default StudentExamList;
