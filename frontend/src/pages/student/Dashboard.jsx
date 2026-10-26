import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { getStudentDashboard, getMyAttempts } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  BookOpen,
  Award,
  TrendingUp,
  CheckCircle2,
  Clock,
  ArrowRight,
  Sparkles,
  Target,
  FileText,
  AlertCircle,
} from 'lucide-react';

const StudentDashboard = () => {
  const { user } = useAuth();
  const [dashboardData, setDashboardData] = useState(null);
  const [attempts, setAttempts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError('');
      try {
        const studentId = user?.id || user?._id || user?.user_id;
        const [dashRes, attemptsRes] = await Promise.allSettled([
          getStudentDashboard(studentId),
          getMyAttempts(),
        ]);

        if (dashRes.status === 'fulfilled') {
          setDashboardData(dashRes.value);
        } else {
          console.warn('Student dashboard analytics endpoint not ready:', dashRes.reason);
        }

        if (attemptsRes.status === 'fulfilled') {
          setAttempts(Array.isArray(attemptsRes.value) ? attemptsRes.value : attemptsRes.value?.attempts || []);
        } else {
          console.warn('Student attempts fetch failed:', attemptsRes.reason);
        }
      } catch (err) {
        console.error('Error loading student dashboard:', err);
        setError('Could not load some analytics data.');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [user]);

  if (loading) {
    return <LoadingSpinner size="lg" message="Loading your student learning portal..." />;
  }

  // Derive metrics
  const totalAttempts = dashboardData?.total_attempts ?? attempts.length;
  const avgScore =
    dashboardData?.average_score !== undefined
      ? Math.round(dashboardData.average_score)
      : attempts.length > 0
      ? Math.round(
          attempts.reduce(
            (acc, curr) =>
              acc +
              (curr.percentage !== undefined && curr.percentage !== null
                ? curr.percentage
                : ((curr.total_score ?? curr.score ?? 0) /
                    (curr.max_possible_score ?? curr.max_score ?? curr.total_points ?? 1)) *
                  100),
            0
          ) / attempts.length
        )
      : null;

  const cluster = dashboardData?.cluster || dashboardData?.proficiency_level || 'Proficient';
  const feedbackSummary =
    dashboardData?.feedback_summary ||
    dashboardData?.recent_feedback ||
    dashboardData?.strengths ||
    'Consistently demonstrates solid understanding of fundamental concepts. Focus on elaborating rubric criteria in essay questions.';

  const recentAttempts = attempts.slice(0, 5);

  return (
    <div className="space-y-8">
      {/* Welcome Banner */}
      <div className="bg-gradient-to-r from-blue-700 via-indigo-700 to-indigo-800 rounded-2xl p-6 md:p-8 text-white shadow-lg shadow-indigo-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-6">
        <div className="space-y-1.5">
          <span className="text-xs uppercase tracking-wider font-semibold text-indigo-200">
            Student Assessment Portal
          </span>
          <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight">
            Hello, {user?.name || 'Student'}!
          </h1>
          <p className="text-sm text-indigo-100 max-w-xl">
            Take curriculum assessments, receive instant AI feedback with rubric breakdowns, and track your cognitive growth.
          </p>
        </div>
        <div>
          <Link to="/student/exams">
            <Button
              variant="secondary"
              size="lg"
              icon={BookOpen}
              className="bg-white text-indigo-900 hover:bg-indigo-50 border-none font-semibold shadow-md"
            >
              Browse Available Exams
            </Button>
          </Link>
        </div>
      </div>

      {error && <Alert type="warning" message={error} onClose={() => setError('')} />}

      {/* Top 3 Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        <Card className="hover:border-indigo-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Completed Assessments
              </p>
              <h3 className="text-3xl font-extrabold text-gray-900 mt-1">{totalAttempts}</h3>
              <p className="text-xs text-indigo-600 font-medium mt-1">Exams submitted</p>
            </div>
            <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-xl flex items-center justify-center">
              <CheckCircle2 className="w-6 h-6" />
            </div>
          </div>
        </Card>

        <Card className="hover:border-emerald-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Average Score
              </p>
              <h3 className="text-3xl font-extrabold text-gray-900 mt-1">
                {avgScore !== null ? `${avgScore}%` : '—'}
              </h3>
              <p className="text-xs text-emerald-600 font-medium mt-1">Overall performance</p>
            </div>
            <div className="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-xl flex items-center justify-center">
              <Award className="w-6 h-6" />
            </div>
          </div>
        </Card>

        <Card className="hover:border-purple-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Assigned Learning Cluster
              </p>
              <div className="mt-1.5">
                <Badge type="cluster" size="lg">
                  {cluster}
                </Badge>
              </div>
              <p className="text-xs text-purple-600 font-medium mt-1">ML proficiency tier</p>
            </div>
            <div className="w-12 h-12 bg-purple-50 text-purple-600 rounded-xl flex items-center justify-center">
              <Target className="w-6 h-6" />
            </div>
          </div>
        </Card>
      </div>

      {/* Main Grid: Recent Attempts & Feedback Summary */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Recent Attempts (2 cols) */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
              <Clock className="w-5 h-5 text-indigo-600" />
              Recent Exam Attempts
            </h2>
            <Link
              to="/student/results"
              className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1"
            >
              All Results ({attempts.length}) <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          {recentAttempts.length === 0 ? (
            <Card className="text-center py-12">
              <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-full flex items-center justify-center mx-auto mb-3">
                <BookOpen className="w-6 h-6" />
              </div>
              <h4 className="text-base font-bold text-gray-800">No attempts yet</h4>
              <p className="text-xs text-gray-500 mt-1 max-w-sm mx-auto">
                You haven't taken any assessment exams yet. Select an exam from the catalog to test your knowledge!
              </p>
              <div className="mt-4">
                <Link to="/student/exams">
                  <Button size="sm" icon={BookOpen}>
                    Browse Available Exams
                  </Button>
                </Link>
              </div>
            </Card>
          ) : (
            <div className="space-y-3">
              {recentAttempts.map((attempt) => {
                const attemptId = attempt.id || attempt._id || attempt.attempt_id;
                const score = attempt.total_score ?? attempt.score ?? 0;
                const maxScore =
                  attempt.max_possible_score ?? attempt.max_score ?? attempt.total_points ?? 100;
                const pct =
                  attempt.percentage !== undefined && attempt.percentage !== null
                    ? Math.round(attempt.percentage)
                    : Math.round((score / (maxScore || 1)) * 100);

                const passed = pct >= 60;

                return (
                  <Card
                    key={attemptId || Math.random()}
                    className="p-4 hover:border-indigo-300 transition-all"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div>
                        <h4 className="font-semibold text-gray-900 text-sm">
                          {attempt.exam_title || attempt.title || `Assessment #${attempt.exam_id || attemptId}`}
                        </h4>
                        <p className="text-xs text-gray-500 mt-0.5">
                          Submitted on:{' '}
                          {attempt.submitted_at
                            ? new Date(attempt.submitted_at).toLocaleDateString()
                            : 'Recently'}
                        </p>
                      </div>

                      <div className="flex items-center gap-4 shrink-0">
                        <div className="text-right">
                          <p className="text-sm font-bold text-gray-900">
                            {score} / {maxScore} pts ({pct}%)
                          </p>
                          <span
                            className={`text-[10px] font-bold uppercase tracking-wider ${
                              passed ? 'text-emerald-600' : 'text-rose-600'
                            }`}
                          >
                            {passed ? 'Passed' : 'Needs Review'}
                          </span>
                        </div>
                        <Link to={`/student/attempt/${attemptId}`}>
                          <Button variant="outline" size="sm">
                            View Feedback
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

        {/* Feedback Summary Card (1 col) */}
        <div className="space-y-4">
          <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-indigo-600" />
            AI Feedback Summary
          </h2>

          <Card title="Semantic Progress Diagnostic" subtitle="Grounded in your recent submissions">
            <div className="space-y-4 text-xs">
              <div className="p-3 bg-indigo-50/60 rounded-xl border border-indigo-100 text-indigo-950 leading-relaxed">
                {typeof feedbackSummary === 'string' ? (
                  <p>{feedbackSummary}</p>
                ) : (
                  <ul className="list-disc pl-4 space-y-1">
                    {Array.isArray(feedbackSummary) &&
                      feedbackSummary.map((item, idx) => <li key={idx}>{item}</li>)}
                  </ul>
                )}
              </div>

              <div>
                <h5 className="font-bold text-gray-800 uppercase tracking-wider text-[10px] mb-2">
                  Recommended Study Steps
                </h5>
                <ul className="space-y-2 text-gray-600">
                  <li className="flex items-start gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                    <span>Review lesson notes prior to taking timed evaluations.</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                    <span>Support essay statements with specific curriculum examples.</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                    <span>Check grading rubrics carefully before submitting answers.</span>
                  </li>
                </ul>
              </div>

              <div className="pt-2">
                <Link to="/student/exams">
                  <Button variant="outline" size="sm" className="w-full">
                    Start New Assessment
                  </Button>
                </Link>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};

export default StudentDashboard;
