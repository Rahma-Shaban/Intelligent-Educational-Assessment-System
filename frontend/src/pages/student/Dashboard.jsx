import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { getStudentDashboard, getMyAttempts } from '../../api/client';
import ProfessorPicker from '../../components/ProfessorPicker';
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
  ArrowLeft,
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
        setError('معلش، قدرنا نجيب جزء من البيانات بس.');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [user]);

  if (loading) {
    return <LoadingSpinner size="lg" message="جاري تحميل المنصة... " />;
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
    'بنلاحظ فهم قوي للمفاهيم الأساسية — ركّز على شرح إجاباتك بالتفصيل في أسئلة المقال.';

  const recentAttempts = attempts.slice(0, 5);

  return (
    <div className="space-y-8">
      {/* Welcome Banner */}
      <div className="relative overflow-hidden bg-gradient-to-bl from-teal-700 via-teal-800 to-cocoa-950 rounded-3xl p-6 md:p-8 text-white shadow-pop flex flex-col sm:flex-row sm:items-center sm:justify-between gap-6">
        <span className="code-chip-light absolute top-5 end-6 rotate-2 hidden md:inline-block">your_progress +1 🚀</span>
        <div className="absolute -bottom-16 -start-10 w-56 h-56 rounded-full bg-teal-500/15 blur-2xl" />
        <div className="space-y-1.5 relative z-10">
          <span className="text-xs font-bold text-gold-300">بوابة الطالب</span>
          <h1 className="font-display text-3xl md:text-4xl leading-snug">
            يلا بينا يا <span className="text-gold-300">{user?.name || 'صديقنا'}</span> 🚀
          </h1>
          <p className="text-sm text-teal-100 max-w-xl leading-relaxed">
            امتحن من منهجك، خد تقييم فوري من الذكاء الاصطناعي، وتابع تطور مستواك.
          </p>
        </div>
        <div className="relative z-10">
          <Link to="/student/exams">
            <Button
              variant="secondary"
              size="lg"
              icon={BookOpen}
              className="bg-gold-400 text-clay-950 hover:bg-gold-300 border-none font-bold"
            >
              شوف الامتحانات المتاحة
            </Button>
          </Link>
        </div>
      </div>

      {error && <Alert type="warning" message={error} onClose={() => setError('')} />}

      {/* Professor selection — persisted on the account, exams are scoped to it */}
      <ProfessorPicker />

      {/* Top 3 Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        <Card className="hover:border-teal-200 !border-t-4 !border-t-teal-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-bold text-cocoa-500">امتحانات سلّمتها</p>
              <h3 className="font-display text-3xl text-teal-700 mt-1">{totalAttempts}</h3>
              <p className="text-[11px] text-cocoa-500 font-semibold mt-1">محاولة مكتملة</p>
            </div>
            <div className="w-12 h-12 bg-teal-50 text-teal-700 rounded-2xl rounded-br-sm flex items-center justify-center">
              <CheckCircle2 className="w-6 h-6" />
            </div>
          </div>
        </Card>

        <Card className="hover:border-gold-200 !border-t-4 !border-t-gold-400">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-bold text-cocoa-500">متوسط درجاتك</p>
              <h3 className="font-display text-3xl text-gold-600 mt-1">
                {avgScore !== null ? `${avgScore}%` : '—'}
              </h3>
              <p className="text-[11px] text-cocoa-500 font-semibold mt-1">أداءك العام</p>
            </div>
            <div className="w-12 h-12 bg-gold-100 text-gold-600 rounded-2xl rounded-br-sm flex items-center justify-center">
              <Award className="w-6 h-6" />
            </div>
          </div>
        </Card>

        <Card className="hover:border-clay-200 !border-t-4 !border-t-clay-600">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-bold text-cocoa-500">مجموعتك التعليمية</p>
              <div className="mt-1.5">
                <Badge type="cluster" size="lg">
                  {cluster}
                </Badge>
              </div>
              <p className="text-[11px] text-cocoa-500 font-semibold mt-1">حسب تحليل الذكاء الاصطناعي</p>
            </div>
            <div className="w-12 h-12 bg-clay-100 text-clay-700 rounded-2xl rounded-br-sm flex items-center justify-center">
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
            <h2 className="text-lg font-extrabold text-ink flex items-center gap-2">
              <Clock className="w-5 h-5 text-clay-600" />
              آخر محاولاتك
            </h2>
            <Link
              to="/student/results"
              className="text-xs font-bold text-clay-700 hover:text-clay-600 flex items-center gap-1"
            >
              كل النتائج ({attempts.length}) <ArrowLeft className="w-3.5 h-3.5" />
            </Link>
          </div>

          {recentAttempts.length === 0 ? (
            <Card className="text-center py-12">
              <div className="w-14 h-14 bg-teal-50 text-teal-700 rounded-2xl rounded-br-md flex items-center justify-center mx-auto mb-3 -rotate-3 text-2xl">
                🦉
              </div>
              <h4 className="text-base font-bold text-ink">لسه مامتحنتش حاجة</h4>
              <p className="text-xs text-cocoa-500 mt-1 max-w-sm mx-auto leading-relaxed">
                اختار امتحان من القائمة واختبر معلوماتك — النتيجة والتحليل هيوصلك فوراً!
              </p>
              <div className="mt-4">
                <Link to="/student/exams">
                  <Button size="sm" icon={BookOpen} className="btn-cut">
                    شوف الامتحانات المتاحة
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
                    className="p-4 hover:border-gold-400 transition-all"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div>
                        <h4 className="font-bold text-ink text-sm" dir="auto">
                          {attempt.exam_title || attempt.title || `Assessment #${attempt.exam_id || attemptId}`}
                        </h4>
                        <p className="text-xs text-cocoa-500 mt-0.5">
                          اتسلّم في:{' '}
                          {attempt.submitted_at
                            ? new Date(attempt.submitted_at).toLocaleDateString('ar-EG')
                            : 'حديثاً'}
                        </p>
                      </div>

                      <div className="flex items-center gap-4 shrink-0">
                        <div className="text-left">
                          <p className="text-sm font-extrabold text-ink">
                            {score} / {maxScore} ({pct}%)
                          </p>
                          <span
                            className={`text-[10px] font-bold ${
                              passed ? 'text-teal-700' : 'text-rose-600'
                            }`}
                          >
                            {passed ? 'ناجح 🎉' : 'محتاج مراجعة'}
                          </span>
                        </div>
                        <Link to={`/student/attempt/${attemptId}`}>
                          <Button variant="outline" size="sm">
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

        {/* Feedback Summary Card (1 col) */}
        <div className="space-y-4">
          <h2 className="text-lg font-extrabold text-ink flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-clay-600" />
            تقييم الذكاء الاصطناعي
          </h2>

          <Card title="إقيوس بيقولك 💬" subtitle="بناءً على آخر محاولاتك">
            <div className="space-y-4 text-xs">
              <div className="p-3 bg-teal-50/70 rounded-2xl border-2 border-dashed border-teal-200 text-teal-900 leading-relaxed font-semibold">
                {typeof feedbackSummary === 'string' ? (
                  <p>{feedbackSummary}</p>
                ) : (
                  <ul className="list-disc ps-4 space-y-1">
                    {Array.isArray(feedbackSummary) &&
                      feedbackSummary.map((item, idx) => <li key={idx}>{item}</li>)}
                  </ul>
                )}
              </div>

              <div>
                <h5 className="font-bold text-cocoa-800 text-[12px] mb-2">
                  خطوات مقترحة للمذاكرة
                </h5>
                <ul className="space-y-2 text-cocoa-500">
                  <li className="flex items-start gap-2">
                    <CheckCircle2 className="w-4 h-4 text-teal-600 shrink-0 mt-0.5" />
                    <span>راجع ملاحظات الدرس قبل ما تبدأ الامتحان.</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <CheckCircle2 className="w-4 h-4 text-teal-600 shrink-0 mt-0.5" />
                    <span>ادعم إجاباتك بأمثلة من المنهج.</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <CheckCircle2 className="w-4 h-4 text-teal-600 shrink-0 mt-0.5" />
                    <span>اقرأ معايير التصحيح كويس قبل التسليم.</span>
                  </li>
                </ul>
              </div>

              <div className="pt-2">
                <Link to="/student/exams">
                  <Button variant="outline" size="sm" className="w-full">
                    ابدأ امتحان جديد 🚀
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
