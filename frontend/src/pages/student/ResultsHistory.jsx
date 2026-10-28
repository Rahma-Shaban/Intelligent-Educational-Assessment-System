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
  ArrowLeft,
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
        setError('فشل تحميل سجل المحاولات.');
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
    return <LoadingSpinner size="lg" message="جاري تحميل نتائجك..." />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="relative">
          <span className="code-chip absolute -top-3 end-0 rotate-2 hidden md:inline-block">history.sort(score)</span>
          <h1 className="font-display text-3xl md:text-4xl text-ink">نتائجي 🏅</h1>
          <p className="text-sm text-cocoa-500 mt-1">
            راجع تقييمك ونماذج التصحيح والإجابات النموذجية لكل امتحان سلّمته.
          </p>
        </div>
        <Link to="/student/exams">
          <Button variant="primary" size="md" icon={BookOpen} className="btn-cut shrink-0">
            امتحن جديد
          </Button>
        </Link>
      </div>

      {error && <Alert type="error" message={error} onClose={() => setError('')} />}

      {/* Search Input */}
      {attempts.length > 0 && (
        <Card className="p-4">
          <div className="relative max-w-md">
            <Search className="w-4 h-4 text-cocoa-300 absolute start-3 top-3 pointer-events-none" />
            <input
              type="text"
              placeholder="دوّر باسم الامتحان..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full ps-10 pe-3 py-2 text-sm bg-white border-2 border-cocoa-300/60 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 outline-none transition"
            />
          </div>
        </Card>
      )}

      {/* Attempts List */}
      {filtered.length === 0 ? (
        <Card className="text-center py-16">
          <div className="w-14 h-14 bg-gold-100 text-gold-600 rounded-2xl rounded-br-md flex items-center justify-center mx-auto mb-3 -rotate-3 text-2xl">
            🏅
          </div>
          <h3 className="text-lg font-extrabold text-ink">
            {attempts.length === 0 ? 'لسه مفيش نتائج' : 'مفيش نتائج مطابقة'}
          </h3>
          <p className="text-sm text-cocoa-500 mt-1 max-w-md mx-auto">
            {attempts.length === 0
              ? 'امتحن نفسك في أي امتحان متاح وهتلاقي نتيجتك وتحليلك هنا فوراً.'
              : 'جرّب تمسح كلمة البحث.'}
          </p>
          {attempts.length === 0 && (
            <div className="mt-5">
              <Link to="/student/exams">
                <Button icon={BookOpen} className="btn-cut">شوف الامتحانات المتاحة</Button>
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
              ? new Date(att.submitted_at).toLocaleDateString('ar-EG', {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : 'حديثاً';

            return (
              <Card
                key={attemptId || Math.random()}
                className="p-5 hover:border-gold-400 transition-all"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-bold text-ink text-base" dir="auto">
                        <Link
                          to={`/student/attempt/${attemptId}`}
                          className="hover:text-clay-600 transition-colors"
                        >
                          {att.exam_title || att.title || `Assessment #${att.exam_id || attemptId}`}
                        </Link>
                      </h3>
                      <span
                        className={`sticker !text-[10px] !py-0.5 ${
                          passed ? 'text-teal-700' : 'text-rose-600'
                        }`}
                        style={{ borderWidth: 1.5 }}
                      >
                        {passed ? 'ناجح 🎉' : 'محتاج مراجعة'}
                      </span>
                      {att.is_practice && (
                        <Badge variant="info" size="sm">
                          تدريب
                        </Badge>
                      )}
                      {att.cluster && (
                        <Badge type="cluster" size="sm">
                          {att.cluster}
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-cocoa-500 flex items-center gap-1.5">
                      <Calendar className="w-3.5 h-3.5" /> اتسلّم: {dateStr}
                    </p>
                  </div>

                  <div className="flex items-center gap-5 shrink-0">
                    <div className="text-left">
                      <p className="text-base font-extrabold text-ink">
                        {score} / {maxScore}
                      </p>
                      <p
                        className={`text-xs font-bold ${
                          passed ? 'text-teal-700' : 'text-rose-600'
                        }`}
                      >
                        {pct}%
                      </p>
                    </div>

                    <Link to={`/student/attempt/${attemptId}`}>
                      <Button variant="outline" size="sm" icon={ArrowLeft}>
                        شوف التقييم
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
