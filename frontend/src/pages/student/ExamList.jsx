import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getExams } from '../../api/client';
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
} from 'lucide-react';

const StudentExamList = () => {
  const [exams, setExams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [startingId, setStartingId] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterDifficulty, setFilterDifficulty] = useState('all');

  const navigate = useNavigate();

  useEffect(() => {
    const fetchExams = async () => {
      setLoading(true);
      setError('');
      try {
        const data = await getExams();
        const list = Array.isArray(data) ? data : data?.exams || [];
        setExams(list);
      } catch (err) {
        console.error('Failed to load available exams:', err);
        setError('Failed to fetch available assessments.');
      } finally {
        setLoading(false);
      }
    };

    fetchExams();
  }, []);

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
    return <LoadingSpinner size="lg" message="Loading available assessments..." />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl md:text-3xl font-extrabold text-gray-900 tracking-tight">
          Available Assessment Exams
        </h1>
        <p className="text-sm text-gray-600 mt-1">
          Select an assessment to test your understanding. All questions are dynamically validated against course materials.
        </p>
      </div>

      {error && <Alert type="error" message={error} onClose={() => setError('')} />}

      {/* Search and Filters */}
      <Card className="p-4">
        <div className="flex flex-col sm:flex-row gap-4 items-center justify-between">
          <div className="relative w-full sm:w-80">
            <Search className="w-4 h-4 text-gray-400 absolute left-3 top-3 pointer-events-none" />
            <input
              type="text"
              placeholder="Search by topic, lesson, or keyword..."
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

      {/* Grid of Exams */}
      {filteredExams.length === 0 ? (
        <Card className="text-center py-16">
          <div className="w-14 h-14 bg-indigo-50 text-indigo-600 rounded-full flex items-center justify-center mx-auto mb-3">
            <BookOpen className="w-7 h-7" />
          </div>
          <h3 className="text-lg font-bold text-gray-900">
            {exams.length === 0 ? 'No Assessments Available' : 'No Matching Exams'}
          </h3>
          <p className="text-sm text-gray-500 mt-1 max-w-md mx-auto">
            {exams.length === 0
              ? 'Your instructor has not published any assessments yet. Please check back later.'
              : 'Try adjusting your search criteria.'}
          </p>
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
            const estMinutes = Math.max(10, qCount * 5);

            return (
              <Card
                key={examId || Math.random()}
                className="flex flex-col justify-between hover:border-indigo-300 transition-all shadow-sm hover:shadow"
              >
                <div className="space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5" />
                      ~{estMinutes} Mins
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

                  <div>
                    <h3 className="text-base font-bold text-gray-900 line-clamp-2">
                      {exam.title || exam.topic || `Assessment #${examId}`}
                    </h3>
                    <p className="text-xs text-gray-500 mt-1 line-clamp-1">
                      {exam.lesson_title || exam.lesson || (exam.topic && `Topic: ${exam.topic}`) || 'Curriculum Assessment'}
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-gray-100 text-xs text-gray-600">
                    <div className="flex items-center gap-1.5">
                      <Layers className="w-3.5 h-3.5 text-indigo-500" />
                      <span>{qCount} Questions</span>
                    </div>
                    <div className="flex items-center gap-1.5 justify-end">
                      <Award className="w-3.5 h-3.5 text-emerald-500" />
                      <span className="font-semibold text-gray-800">{totalPoints} Points</span>
                    </div>
                  </div>
                </div>

                <div className="pt-4 mt-3 border-t border-gray-100">
                  <Button
                    variant="primary"
                    size="md"
                    className="w-full"
                    icon={Play}
                    loading={startingId === examId}
                    onClick={() => handleStartExam(examId)}
                  >
                    Start Exam
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
