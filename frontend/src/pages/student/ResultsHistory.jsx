import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { getMyAttempts } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  Award,
  CheckCircle2,
  Clock,
  ArrowRight,
  Search,
  BookOpen,
  Calendar,
  Layers,
} from 'lucide-react';

const ResultsHistory = () => {
  const [attempts, setAttempts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    const fetchAttempts = async () => {
      setLoading(true);
      setError('');
      try {
        const data = await getMyAttempts();
        const list = Array.isArray(data) ? data : data?.attempts || [];
        setAttempts(list);
      } catch (err) {
        console.error('Failed to load attempts history:', err);
        setError('Failed to retrieve assessment history.');
      } finally {
        setLoading(false);
      }
    };

    fetchAttempts();
  }, []);

  const filtered = attempts.filter((att) => {
    const title = (att.exam_title || att.title || `Attempt #${att.id}`).toLowerCase();
    return title.includes(searchQuery.toLowerCase());
  });

  if (loading) {
    return <LoadingSpinner size="lg" message="Loading your assessment attempts..." />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-extrabold text-gray-900 tracking-tight">
            My Assessment Results
          </h1>
          <p className="text-sm text-gray-600 mt-1">
            Review detailed feedback, scored rubrics, and model answers for all completed exams.
          </p>
        </div>
        <Link to="/student/exams">
          <Button variant="primary" size="md" icon={BookOpen}>
            Take New Exam
          </Button>
        </Link>
      </div>

      {error && <Alert type="error" message={error} onClose={() => setError('')} />}

      {/* Search Input */}
      {attempts.length > 0 && (
        <Card className="p-4">
          <div className="relative max-w-md">
            <Search className="w-4 h-4 text-gray-400 absolute left-3 top-3 pointer-events-none" />
            <input
              type="text"
              placeholder="Filter by exam title..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-600 focus:border-indigo-600"
            />
          </div>
        </Card>
      )}

      {/* Attempts List */}
      {filtered.length === 0 ? (
        <Card className="text-center py-16">
          <div className="w-14 h-14 bg-indigo-50 text-indigo-600 rounded-full flex items-center justify-center mx-auto mb-3">
            <Award className="w-7 h-7" />
          </div>
          <h3 className="text-lg font-bold text-gray-900">
            {attempts.length === 0 ? 'No Assessment Results Yet' : 'No Matching Results'}
          </h3>
          <p className="text-sm text-gray-500 mt-1 max-w-md mx-auto">
            {attempts.length === 0
              ? 'Complete an assessment exam to see your AI-graded scores and rubric breakdown here.'
              : 'Try clearing your search term.'}
          </p>
          {attempts.length === 0 && (
            <div className="mt-5">
              <Link to="/student/exams">
                <Button icon={BookOpen}>Browse Available Exams</Button>
              </Link>
            </div>
          )}
        </Card>
      ) : (
        <div className="space-y-4">
          {filtered.map((att) => {
            const attemptId = att.id || att._id || att.attempt_id;
            const score = att.total_score ?? att.score ?? 0;
            const maxScore = att.max_possible_score ?? att.max_score ?? att.total_points ?? 100;
            const pct =
              att.percentage !== undefined && att.percentage !== null
                ? Math.round(att.percentage)
                : Math.round((score / (maxScore || 1)) * 100);
            const passed = pct >= 60;

            const dateStr = att.submitted_at
              ? new Date(att.submitted_at).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : 'Recently';

            return (
              <Card
                key={attemptId || Math.random()}
                className="p-5 hover:border-indigo-300 transition-all shadow-sm"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-bold text-gray-900 text-base">
                        <Link
                          to={`/student/attempt/${attemptId}`}
                          className="hover:text-indigo-600 transition-colors"
                        >
                          {att.exam_title || att.title || `Assessment #${att.exam_id || attemptId}`}
                        </Link>
                      </h3>
                      <span
                        className={`text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${
                          passed
                            ? 'bg-emerald-100 text-emerald-800'
                            : 'bg-rose-100 text-rose-800'
                        }`}
                      >
                        {passed ? 'Passed' : 'Needs Review'}
                      </span>
                      {att.cluster && (
                        <Badge type="cluster" size="sm">
                          {att.cluster}
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 flex items-center gap-1.5">
                      <Calendar className="w-3.5 h-3.5" /> Submitted: {dateStr}
                    </p>
                  </div>

                  <div className="flex items-center gap-5 shrink-0">
                    <div className="text-right">
                      <p className="text-base font-extrabold text-gray-900">
                        {score} / {maxScore} pts
                      </p>
                      <p
                        className={`text-xs font-bold ${
                          passed ? 'text-emerald-600' : 'text-rose-600'
                        }`}
                      >
                        {pct}% Score
                      </p>
                    </div>

                    <Link to={`/student/attempt/${attemptId}`}>
                      <Button variant="outline" size="sm" icon={ArrowRight}>
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
  );
};

export default ResultsHistory;
