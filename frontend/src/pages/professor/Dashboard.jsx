import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getProfessorDashboard, getExams } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  FileUp,
  Sparkles,
  BookOpen,
  Users,
  Award,
  TrendingUp,
  ArrowRight,
  Clock,
  CheckCircle,
  AlertCircle,
  HelpCircle,
} from 'lucide-react';

const ProfessorDashboard = () => {
  const [dashboardData, setDashboardData] = useState(null);
  const [exams, setExams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError('');
      try {
        const [dashRes, examsRes] = await Promise.allSettled([
          getProfessorDashboard(),
          getExams(),
        ]);

        if (dashRes.status === 'fulfilled') {
          setDashboardData(dashRes.value);
        } else {
          console.warn('Professor dashboard analytics endpoint failed or empty:', dashRes.reason);
        }

        if (examsRes.status === 'fulfilled') {
          setExams(Array.isArray(examsRes.value) ? examsRes.value : examsRes.value?.exams || []);
        } else {
          console.warn('Exams fetch failed:', examsRes.reason);
        }
      } catch (err) {
        console.error('Failed to load dashboard data:', err);
        setError('Could not load some dashboard analytics. Using available data.');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  if (loading) {
    return <LoadingSpinner size="lg" message="Loading instructor dashboard..." />;
  }

  // Derive stats either from dashboard endpoint or exam collection
  const totalExams = dashboardData?.total_exams ?? exams.length;
  const totalStudents = dashboardData?.total_students ?? dashboardData?.student_count ?? 0;
  const avgScore = dashboardData?.average_score !== undefined
    ? `${Math.round(dashboardData.average_score)}%`
    : dashboardData?.avg_score !== undefined
    ? `${Math.round(dashboardData.avg_score)}%`
    : 'N/A';
  const totalAttempts = dashboardData?.total_attempts ?? 0;

  const topicPerformance = dashboardData?.topic_performance || dashboardData?.topic_scores || [];
  const recentExams = exams.slice(0, 5);

  return (
    <div className="space-y-8">
      {/* Welcome Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 bg-gradient-to-r from-indigo-700 via-indigo-600 to-blue-600 rounded-2xl p-6 md:p-8 text-white shadow-lg shadow-indigo-100">
        <div>
          <span className="text-xs uppercase tracking-wider font-semibold text-indigo-200">
            Instructor Control Center
          </span>
          <h1 className="text-2xl md:text-3xl font-extrabold mt-1">
            Welcome back, Professor
          </h1>
          <p className="text-indigo-100 text-sm mt-1 max-w-xl">
            Generate curriculum-grounded exams, monitor student cohort clustering, and view semantic assessment analytics.
          </p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <Link to="/professor/curriculum">
            <Button variant="secondary" size="md" icon={FileUp} className="bg-white/10 hover:bg-white/20 text-white border-white/20">
              Upload Curriculum
            </Button>
          </Link>
          <Link to="/professor/generate">
            <Button variant="secondary" size="md" icon={Sparkles} className="bg-white text-indigo-900 hover:bg-indigo-50 border-none font-semibold">
              Generate Exam
            </Button>
          </Link>
        </div>
      </div>

      {error && <Alert type="warning" message={error} onClose={() => setError('')} />}

      {/* Overview Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <Card className="hover:border-indigo-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                Total Exams
              </p>
              <h3 className="text-3xl font-bold text-gray-900 mt-1">{totalExams}</h3>
              <p className="text-xs text-indigo-600 font-medium mt-1">Active assessments</p>
            </div>
            <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-xl flex items-center justify-center">
              <BookOpen className="w-6 h-6" />
            </div>
          </div>
        </Card>

        <Card className="hover:border-blue-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                Enrolled Students
              </p>
              <h3 className="text-3xl font-bold text-gray-900 mt-1">{totalStudents}</h3>
              <p className="text-xs text-blue-600 font-medium mt-1">Across all cohorts</p>
            </div>
            <div className="w-12 h-12 bg-blue-50 text-blue-600 rounded-xl flex items-center justify-center">
              <Users className="w-6 h-6" />
            </div>
          </div>
        </Card>

        <Card className="hover:border-emerald-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                Average Class Score
              </p>
              <h3 className="text-3xl font-bold text-gray-900 mt-1">{avgScore}</h3>
              <p className="text-xs text-emerald-600 font-medium mt-1">Overall proficiency</p>
            </div>
            <div className="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-xl flex items-center justify-center">
              <Award className="w-6 h-6" />
            </div>
          </div>
        </Card>

        <Card className="hover:border-purple-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                Submissions
              </p>
              <h3 className="text-3xl font-bold text-gray-900 mt-1">{totalAttempts}</h3>
              <p className="text-xs text-purple-600 font-medium mt-1">Completed attempts</p>
            </div>
            <div className="w-12 h-12 bg-purple-50 text-purple-600 rounded-xl flex items-center justify-center">
              <TrendingUp className="w-6 h-6" />
            </div>
          </div>
        </Card>
      </div>

      {/* Two Column Section: Recent Exams & Class Performance */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Recent Exams List (2 cols on large screen) */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-indigo-600" />
              Recent Assessment Exams
            </h2>
            <Link
              to="/professor/exams"
              className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1"
            >
              View All Exams ({exams.length}) <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          {recentExams.length === 0 ? (
            <Card className="text-center py-12">
              <div className="w-12 h-12 bg-indigo-50 text-indigo-500 rounded-full flex items-center justify-center mx-auto mb-3">
                <BookOpen className="w-6 h-6" />
              </div>
              <h4 className="text-base font-semibold text-gray-800">No exams generated yet</h4>
              <p className="text-xs text-gray-500 mt-1 max-w-sm mx-auto">
                Upload your course curriculum and let our AI engine generate grounded questions.
              </p>
              <div className="mt-4">
                <Link to="/professor/generate">
                  <Button size="sm" icon={Sparkles}>
                    Generate First Exam
                  </Button>
                </Link>
              </div>
            </Card>
          ) : (
            <div className="space-y-3">
              {recentExams.map((exam) => {
                const examId = exam.id || exam._id || exam.exam_id;
                const questionCount =
                  exam.questions?.length || exam.question_count || exam.num_questions || 0;
                const totalPoints =
                  exam.total_points ||
                  exam.max_score ||
                  (exam.questions ? exam.questions.reduce((acc, q) => acc + (q.max_score || 1), 0) : 0);

                return (
                  <Card
                    key={examId || Math.random()}
                    className="p-5 hover:border-indigo-300 transition-all cursor-pointer"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <Link
                            to={`/professor/exams/${examId}`}
                            className="font-semibold text-gray-900 hover:text-indigo-600 transition-colors"
                          >
                            {exam.title || exam.topic || `Exam #${examId}`}
                          </Link>
                          {exam.difficulty && (
                            <Badge type="difficulty">{exam.difficulty}</Badge>
                          )}
                          {exam.bloom_level && (
                            <Badge type="bloom">{exam.bloom_level}</Badge>
                          )}
                        </div>
                        <p className="text-xs text-gray-500">
                          {exam.lesson_title || exam.lesson || (exam.topic && `Topic: ${exam.topic}`) || 'Curriculum Assessment'}
                        </p>
                      </div>

                      <div className="flex items-center gap-4 text-xs text-gray-600 shrink-0">
                        <span className="bg-gray-50 px-2.5 py-1 rounded-md border border-gray-100 font-medium">
                          {questionCount} Questions
                        </span>
                        <span className="bg-gray-50 px-2.5 py-1 rounded-md border border-gray-100 font-medium">
                          {totalPoints} Points
                        </span>
                        <Link to={`/professor/exams/${examId}`}>
                          <Button variant="outline" size="sm">
                            Inspect
                          </Button>
                        </Link>
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>

        {/* Class Performance Summary / Quick Analytics (1 col) */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-indigo-600" />
              Class Insights
            </h2>
            <Link
              to="/professor/analytics"
              className="text-xs font-semibold text-indigo-600 hover:text-indigo-800"
            >
              Full Analytics &rarr;
            </Link>
          </div>

          <Card title="Cohort Performance" subtitle="Distribution across proficiency bands">
            {dashboardData?.clusters || dashboardData?.cluster_summary ? (
              <div className="space-y-3 mt-2">
                {Object.entries(dashboardData.clusters || dashboardData.cluster_summary).map(
                  ([name, count]) => (
                    <div key={name} className="flex items-center justify-between text-xs">
                      <span className="font-medium capitalize text-gray-700">{name}</span>
                      <span className="font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-full">
                        {count} students
                      </span>
                    </div>
                  )
                )}
              </div>
            ) : (
              <div className="text-center py-6 text-gray-500 space-y-2">
                <HelpCircle className="w-8 h-8 mx-auto text-gray-300" />
                <p className="text-xs">No clustering run yet for this cohort.</p>
                <Link to="/professor/analytics">
                  <Button variant="outline" size="sm" className="mt-2 text-xs">
                    Run ML Clustering
                  </Button>
                </Link>
              </div>
            )}
          </Card>

          <Card title="Quick Action Guide">
            <ul className="space-y-3 text-xs text-gray-600">
              <li className="flex items-start gap-2.5">
                <span className="w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 font-bold flex items-center justify-center shrink-0 text-[11px]">
                  1
                </span>
                <span>
                  <strong>Upload PDF:</strong> Provide your curriculum text book or lecture slides to vectorize context.
                </span>
              </li>
              <li className="flex items-start gap-2.5">
                <span className="w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 font-bold flex items-center justify-center shrink-0 text-[11px]">
                  2
                </span>
                <span>
                  <strong>Configure Generation:</strong> Choose Bloom's taxonomy level, difficulty, and question breakdown.
                </span>
              </li>
              <li className="flex items-start gap-2.5">
                <span className="w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 font-bold flex items-center justify-center shrink-0 text-[11px]">
                  3
                </span>
                <span>
                  <strong>Analyze Results:</strong> Use semantic clustering to locate struggling students and knowledge gaps.
                </span>
              </li>
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
};

export default ProfessorDashboard;
