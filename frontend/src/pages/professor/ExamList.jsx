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
  ArrowRight,
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
      setError('Could not update publication status. Please try again.');
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
        setError('Failed to load exams list. Please try again.');
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
    return <LoadingSpinner size="lg" message="Loading generated exams..." />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-extrabold text-gray-900 tracking-tight">
            Generated Assessments
          </h1>
          <p className="text-sm text-gray-600 mt-1">
            Review and inspect active exams, answer keys, rubrics, and source citations.
          </p>
        </div>
        <Link to="/professor/generate">
          <Button variant="primary" size="md" icon={Sparkles}>
            Generate New Exam
          </Button>
        </Link>
      </div>

      {error && <Alert type="error" message={error} onClose={() => setError('')} />}

      {/* Filter and Search Bar */}
      <Card className="p-4">
        <div className="flex flex-col sm:flex-row gap-4 items-center justify-between">
          <div className="relative w-full sm:w-80">
            <Search className="w-4 h-4 text-gray-400 absolute left-3 top-3 pointer-events-none" />
            <input
              type="text"
              placeholder="Search by title, topic, or lesson..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-600 focus:border-indigo-600"
            />
          </div>

          <div className="flex items-center gap-3 w-full sm:w-auto">
            <Filter className="w-4 h-4 text-gray-400 shrink-0" />
            <select
              value={filterDifficulty}
              onChange={(e) => setFilterDifficulty(e.target.value)}
              className="w-full sm:w-44 px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-600 focus:border-indigo-600 bg-white"
            >
              <option value="all">All Difficulties</option>
              <option value="easy">Easy</option>
              <option value="medium">Medium</option>
              <option value="hard">Hard</option>
            </select>
          </div>
        </div>
      </Card>

      {/* Exam Table / Cards */}
      {filteredExams.length === 0 ? (
        <Card className="text-center py-16">
          <div className="w-14 h-14 bg-indigo-50 text-indigo-600 rounded-full flex items-center justify-center mx-auto mb-3">
            <BookOpen className="w-7 h-7" />
          </div>
          <h3 className="text-lg font-bold text-gray-900">
            {exams.length === 0 ? 'No Exams Created Yet' : 'No Matching Exams Found'}
          </h3>
          <p className="text-sm text-gray-500 mt-1 max-w-md mx-auto">
            {exams.length === 0
              ? 'Start by uploading your curriculum PDF and using the AI generator to create your first grounded assessment.'
              : 'Try clearing your search or difficulty filter.'}
          </p>
          {exams.length === 0 && (
            <div className="mt-5">
              <Link to="/professor/generate">
                <Button icon={Sparkles}>Generate Assessment Now</Button>
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
              ? new Date(exam.created_at).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                })
              : 'Recent';

            return (
              <Card
                key={examId || Math.random()}
                className="flex flex-col justify-between hover:border-indigo-300 transition-all shadow-sm hover:shadow"
              >
                <div className="space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5" />
                      {dateStr}
                    </span>
                    <div className="flex items-center gap-1.5 flex-wrap justify-end">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                          exam.is_published
                            ? 'bg-emerald-100 text-emerald-800 border border-emerald-300'
                            : 'bg-amber-100 text-amber-800 border border-amber-300'
                        }`}
                      >
                        {exam.is_published ? '● Published' : '○ Draft'}
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
                    <h3 className="text-base font-bold text-gray-900 line-clamp-2 hover:text-indigo-600 transition-colors">
                      <Link to={`/professor/exams/${examId}`}>
                        {exam.title || exam.topic || `Exam #${examId}`}
                      </Link>
                    </h3>
                    <p className="text-xs text-gray-500 mt-1 line-clamp-1">
                      {exam.lesson_title || exam.lesson || (exam.topic && `Topic: ${exam.topic}`) || 'Curriculum Assessment'}
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-gray-100 text-xs">
                    <div className="flex items-center gap-1.5 text-gray-600">
                      <Layers className="w-3.5 h-3.5 text-indigo-500" />
                      <span>{qCount} Questions</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-gray-600 justify-end">
                      <Award className="w-3.5 h-3.5 text-emerald-500" />
                      <span className="font-semibold text-gray-800">{totalPoints} Pts</span>
                    </div>
                  </div>
                </div>

                <div className="pt-4 mt-3 border-t border-gray-100 flex items-center justify-between gap-2">
                  <Button
                    variant={exam.is_published ? 'ghost' : 'primary'}
                    size="sm"
                    loading={togglingId === examId}
                    onClick={() => handleTogglePublish(examId, exam.is_published)}
                  >
                    {exam.is_published ? 'Unpublish' : 'Publish to Students'}
                  </Button>
                  <Link to={`/professor/exams/${examId}`}>
                    <Button variant="outline" size="sm" icon={Eye}>
                      Inspect
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
